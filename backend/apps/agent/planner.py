"""
agent/planner.py — Orquestación del turno (É-F1 PR-12).

Conecta Policy Engine → (LLM planner) → Tool Executor → salida. El worker
llama `handle_inbound` por cada conversación con entrantes drenados; en F0
el worker auto-saludaba, ahora (enabled=True) corre este pipeline.

Flujo:
  policy.evaluate → REPLY/ESCALATE/CLOSE/SILENT se resuelven sin LLM.
  RUN_PLANNER → bucle acotado: LLM propone texto o tool; las tools se
  ejecutan por el executor (loopback+RBAC reales) y su resultado (DATOS,
  G6) vuelve al modelo; termina en texto. Cada llamada persiste LLMCall
  (tokens/costo/latencia) e incrementa el presupuesto (R11).

Seguridad: el LLM nunca autoriza — el Policy Engine decidió ANTES si se
invoca; el executor + run_tool revalidan tier/verificación/ownership.
"""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import confirmations, policy, prompts, tier0, tools
from .executor import ToolExecutor
from .llm import LLMError, estimate_cost, get_llm_client
from .models import Conversation, HumanHandoff, LLMCall
from .outbound import enqueue_outbound

logger = logging.getLogger('agent.events')

# 2 fallos de tool consecutivos → escalar (spec §2.5, E-08).
MAX_CONSECUTIVE_TOOL_FAILURES = 2


def handle_inbound(conversation, *, agent_settings=None, llm_client=None,
                   executor=None, triggered_by=None):
    """Procesa el último entrante de la conversación. Devuelve un dict de
    telemetría {decision, llm_calls, tools} para el worker/tests."""
    from .models import AgentSettings
    if agent_settings is None:
        agent_settings = AgentSettings.objects.filter(
            organization=conversation.organization,
        ).first()

    text = _last_inbound_text(conversation)
    decision = policy.evaluate(conversation, text, agent_settings=agent_settings)

    if decision.kind == policy.SILENT:
        return {'decision': 'silent', 'llm_calls': 0, 'tools': 0}

    if decision.kind == policy.REPLY:
        enqueue_outbound(conversation, decision.text, author='agent')
        return {'decision': 'reply', 'llm_calls': 0, 'tools': 0,
                'reason': decision.meta.get('reason')}

    if decision.kind == policy.CLOSE:
        enqueue_outbound(conversation, decision.text, author='agent')
        conversation.state = Conversation.STATE_CLOSED
        conversation.closed_at = timezone.now()
        conversation.save(update_fields=['state', 'closed_at'])
        return {'decision': 'close', 'llm_calls': 0, 'tools': 0}

    if decision.kind == policy.ESCALATE:
        policy.escalate_to_human(
            conversation, reason_code=decision.handoff_reason,
            priority=decision.handoff_priority,
        )
        if decision.text:
            enqueue_outbound(conversation, decision.text, author='agent')
        return {'decision': 'escalate', 'llm_calls': 0, 'tools': 0,
                'handoff_reason': decision.handoff_reason}

    # RUN_PLANNER
    if executor is None:
        executor = ToolExecutor(conversation, agent_settings.agent_user)

    # Afirmativa a una acción propuesta (tier-2): ejecuta EXACTAMENTE lo
    # parafraseado, sin volver a pasar por el LLM (invariante TC-SEC-03).
    if (decision.meta.get('confirm') == 'affirmative'
            and confirmations.get_pending(conversation)):
        return _commit_pending(conversation, executor, triggered_by=triggered_by)

    if llm_client is None:
        llm_client = get_llm_client('planner')
    return _run_planner(conversation, agent_settings, llm_client, executor,
                        triggered_by)


def _run_planner(conversation, agent_settings, llm_client, executor,
                 triggered_by):
    tool_specs = tools.as_openai_tools()
    extra_data = None
    llm_calls = 0
    tool_calls = 0
    consecutive_failures = 0
    max_tools = getattr(settings, 'AGENT_MAX_TOOLS_PER_TURN', 5)

    for _ in range(max_tools + 1):
        messages = prompts.assemble_messages(conversation, extra_data=extra_data)
        try:
            result = llm_client.complete(
                system=prompts.SYSTEM_PROMPT, messages=messages,
                tools=tool_specs,
            )
        except LLMError as exc:
            _persist_llm_error(conversation, llm_client, exc)
            # Fallo del modelo: degradar a humano (no dejar al cliente mudo).
            policy.escalate_to_human(
                conversation, reason_code=HumanHandoff.REASON_TOOL_FAILURE,
                detail='llm_error',
            )
            enqueue_outbound(conversation, tier0.T0_BUDGET, author='agent')
            return {'decision': 'escalate', 'llm_calls': llm_calls,
                    'tools': tool_calls, 'reason': 'llm_error'}

        llm_calls += 1
        # La telemetría (costo/tokens) JAMÁS debe tumbar la respuesta al
        # cliente: si falla el registro, se loguea y el turno continúa.
        try:
            _persist_llm_call(conversation, llm_client, result)
        except Exception:
            logger.exception("AGENT_LLMCALL_PERSIST_FAILED")
        _bump_budget(conversation)

        if result.kind == 'text':
            enqueue_outbound(conversation, result.text or _fallback_text(),
                             author='agent')
            return {'decision': 'planner_reply', 'llm_calls': llm_calls,
                    'tools': tool_calls}

        # tool_call
        tool_calls += 1
        outcome = tools.run_tool(
            result.tool_name, result.tool_args,
            conversation=conversation, executor=executor,
            triggered_by=triggered_by,
        )

        # Tier-2: la tool PROPUSO (ya stageó el pending). Enviamos el
        # parafraseo y cerramos el turno — el "sí" del cliente lo ejecuta
        # (policy §7 → _commit_pending). NO se re-alimenta al LLM.
        if outcome.needs_confirmation:
            enqueue_outbound(conversation, outcome.confirmation_text,
                             author='agent')
            return {'decision': 'awaiting_confirmation',
                    'llm_calls': llm_calls, 'tools': tool_calls}

        if not outcome.ok:
            if outcome.client_error == 'verification_required':
                text = policy.start_identity_challenge(conversation)
                enqueue_outbound(conversation, text, author='agent')
                return {'decision': 'identity_challenge',
                        'llm_calls': llm_calls, 'tools': tool_calls}
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_TOOL_FAILURES:
                policy.escalate_to_human(
                    conversation, reason_code=HumanHandoff.REASON_TOOL_FAILURE,
                )
                enqueue_outbound(
                    conversation,
                    "Disculpa, tuve un problema para consultar eso. Te "
                    "comunico con una persona del equipo 🙏",
                    author='agent',
                )
                return {'decision': 'escalate', 'llm_calls': llm_calls,
                        'tools': tool_calls, 'reason': 'tool_failure'}
            # Un fallo: reintenta el turno con el error como dato.
            extra_data = {'tool': result.tool_name, 'error': outcome.client_error}
            continue

        consecutive_failures = 0
        extra_data = {'tool': result.tool_name, 'result': outcome.data}

    # Agotó el presupuesto de tools del turno sin respuesta final.
    enqueue_outbound(conversation, _fallback_text(), author='agent')
    return {'decision': 'tool_budget_exhausted', 'llm_calls': llm_calls,
            'tools': tool_calls}


def _commit_pending(conversation, executor, *, triggered_by=None):
    """Ejecuta el pending_action ya confirmado (spec §2.4). Corre el
    `commit_*` con los args STAGED (nunca re-generados por el LLM) → cumple
    TC-SEC-03: la afirmativa jamás amplía el alcance de lo parafraseado."""
    pending = confirmations.get_pending(conversation)

    # TTL vencido (spec §2.4): re-parafrasea y re-arma expiración; NO ejecuta.
    if confirmations.is_expired(pending):
        confirmations.stage_pending(
            conversation, tool=pending['tool'], args=pending['args'],
            paraphrase=pending['paraphrase'],
        )
        enqueue_outbound(
            conversation,
            confirmations.EXPIRED_REPARAPHRASE.format(
                paraphrase=pending['paraphrase']),
            author='agent',
        )
        return {'decision': 'confirm_expired', 'llm_calls': 0, 'tools': 0}

    handler = tools.COMMIT_HANDLERS.get(pending['tool'])
    if handler is None:  # defensivo: pending corrupto
        confirmations.clear_pending(conversation)
        enqueue_outbound(conversation, _fallback_text(), author='agent')
        return {'decision': 'commit_unknown', 'llm_calls': 0, 'tools': 0}

    outcome = handler(conversation, executor, pending['args'],
                      triggered_by=triggered_by)
    confirmations.clear_pending(conversation)

    if not outcome.ok:
        if outcome.client_error == 'slot_taken':
            enqueue_outbound(
                conversation,
                "Uy, justo se ocupó ese horario 😅 ¿Buscamos otra opción?",
                author='agent',
            )
            return {'decision': 'commit_slot_taken', 'llm_calls': 0,
                    'tools': 1}
        policy.escalate_to_human(
            conversation, reason_code=HumanHandoff.REASON_TOOL_FAILURE,
            detail='commit_failed',
        )
        enqueue_outbound(
            conversation,
            "Tuve un problema para completar eso. Te comunico con una persona "
            "del equipo 🙏",
            author='agent',
        )
        return {'decision': 'escalate', 'llm_calls': 0, 'tools': 1,
                'reason': 'commit_failed'}

    enqueue_outbound(conversation,
                     _commit_success_text(pending['tool'], outcome),
                     author='agent')
    return {'decision': 'committed', 'llm_calls': 0, 'tools': 1,
            'tool': pending['tool']}


def _commit_success_text(tool, outcome):
    cuando = (outcome.data or {}).get('cuando', '')
    if tool == 'create_appointment':
        return f"¡Listo! ✅ Quedó agendada para el {cuando}. Te esperamos 🐾"
    if tool == 'reschedule_appointment':
        return f"¡Listo! Tu cita quedó reprogramada para el {cuando} ✅"
    if tool == 'cancel_appointment':
        return ("Listo, cancelé tu cita. Si quieres agendar otra, con gusto te "
                "ayudo 🙂")
    return "¡Listo! ✅"


def _last_inbound_text(conversation):
    from apps.channels.models import Message
    message = (
        Message.objects.for_organization(conversation.organization)
        .filter(conversation=conversation, direction=Message.DIRECTION_IN)
        .order_by('-created_at', '-id')
        .first()
    )
    return message.body if message else ''


def _bump_budget(conversation):
    conversation.total_llm_calls += 1
    conversation.save(update_fields=['total_llm_calls'])


def _persist_llm_call(conversation, llm_client, result):
    LLMCall.objects.create(
        organization=conversation.organization,
        conversation=conversation,
        provider=getattr(settings, 'AGENT_LLM_BASE_URL', '')[:32],
        model_id=result.model_id or getattr(llm_client, 'model', ''),
        prompt_version=prompts.PROMPT_VERSION,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_estimate=estimate_cost(result.input_tokens, result.output_tokens),
        latency_ms=result.latency_ms,
        finish_reason=result.finish_reason,
    )


def _persist_llm_error(conversation, llm_client, exc):
    LLMCall.objects.create(
        organization=conversation.organization,
        conversation=conversation,
        model_id=getattr(llm_client, 'model', ''),
        prompt_version=prompts.PROMPT_VERSION,
        error=str(exc)[:200],
    )


def _fallback_text():
    return ("Perdón, no te entendí bien 😅 ¿Quieres agendar una cita, o tienes "
            "una duda de horarios o precios?")
