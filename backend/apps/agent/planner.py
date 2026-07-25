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

from . import confirmations, goals, guards, policy, prompts, tier0, tools
from .executor import ToolExecutor
from .llm import LLMError, estimate_cost, get_llm_client
from .models import Conversation, HumanHandoff, LLMCall
from .outbound import enqueue_outbound

logger = logging.getLogger('agent.events')

# 2 fallos de tool consecutivos → escalar (spec §2.5, E-08).
MAX_CONSECUTIVE_TOOL_FAILURES = 2


def handle_inbound(conversation, *, agent_settings=None, llm_client=None,
                   executor=None, triggered_by=None, burst=None,
                   payload_types=None):
    """Procesa el turno de la conversación. Devuelve un dict de telemetría
    {decision, llm_calls, tools} para el worker/tests.

    `burst` = cuerpos de TODOS los entrantes drenados en este turno, en orden
    (el worker los agrupa). El Policy Engine evalúa la ráfaga completa para
    urgencia/humano/opt-out/confirmación; el modelo ya veía todos los mensajes
    en el historial.
    """
    from .models import AgentSettings
    if agent_settings is None:
        agent_settings = AgentSettings.objects.filter(
            organization=conversation.organization,
        ).first()

    raw_burst = list(burst) if burst is not None else []
    texts = [b for b in raw_burst if b]
    text = texts[-1] if texts else (
        '' if raw_burst else _last_inbound_text(conversation))
    if not raw_burst:
        raw_burst = [text] if text else []
    decision = policy.evaluate(conversation, text, burst=raw_burst,
                               payload_types=payload_types,
                               agent_settings=agent_settings)

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
            detail=decision.meta.get('handoff_detail', ''),
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
    base_messages = prompts.assemble_messages(conversation)
    # Hilo del turno: las llamadas del propio modelo y sus resultados (W1-3).
    # Antes solo viajaba el ÚLTIMO resultado, como bloque de sistema, y el
    # modelo no veía que ya había llamado a la herramienta.
    turn_messages = []
    tool_facts = []          # lo que las tools devolvieron ESTE turno (G1)
    correction = None        # instrucción correctiva del guard (un intento)
    goal_touched = False     # ¿se avanzó en el objetivo en curso? (W2)
    llm_calls = 0
    tool_calls = 0
    consecutive_failures = 0
    max_tools = getattr(settings, 'AGENT_MAX_TOOLS_PER_TURN', 5)

    for step in range(max_tools + 2):
        messages = base_messages + turn_messages
        if correction:
            messages = messages + [{
                'role': 'system',
                'content': f"Tu borrador anterior no se envió. {correction}",
            }]
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
            enqueue_outbound(conversation, tier0.T0_TECH_PROBLEM,
                             author='agent')
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
            text = result.text or _fallback_text()
            violations = guards.check_output(text, tool_facts=tool_facts)
            # Un solo reintento con instrucción correctiva: el modelo suele
            # obedecer a la segunda y el cliente no nota nada.
            if violations and correction is None:
                correction = guards.correction_message(violations)
                _log_guard(conversation, violations, action='retry')
                continue
            if guards.has_hard(violations):
                # Persistió una regla dura: ese texto NO sale al cliente.
                _log_guard(conversation, violations, action='blocked')
                policy.escalate_to_human(
                    conversation, reason_code=HumanHandoff.REASON_POLICY,
                    detail=guards.summarize(violations),
                )
                enqueue_outbound(conversation, tier0.T0_GUARD_BLOCKED,
                                 author='agent')
                return {'decision': 'guard_blocked', 'llm_calls': llm_calls,
                        'tools': tool_calls,
                        'reason': guards.summarize(violations)}
            if _settle_goal(conversation, goal_touched=goal_touched,
                            other_tool_used=bool(tool_calls)):
                # Estancamiento semántico: 3 turnos sin llenar un solo dato.
                # Sustituye al presupuesto contable como disparador — "no
                # avanzamos" es una señal real; "gastaste N llamadas" no.
                policy.escalate_to_human(
                    conversation,
                    reason_code=HumanHandoff.REASON_LOW_CONFIDENCE,
                    detail='goal_stalled',
                )
                enqueue_outbound(conversation, tier0.T0_GOAL_STALLED,
                                 author='agent')
                return {'decision': 'goal_stalled', 'llm_calls': llm_calls,
                        'tools': tool_calls}
            if violations:
                _log_guard(conversation, violations, action='sent')
            enqueue_outbound(
                conversation,
                _after_hours_prefix(conversation, agent_settings) + text,
                author='agent')
            return {'decision': 'planner_reply', 'llm_calls': llm_calls,
                    'tools': tool_calls}

        # tool_call
        tool_calls += 1
        if result.tool_name in goals.TOOL_GOALS:
            goal_touched = True
        # El stub de tests no emite id: se sintetiza para poder correlacionar.
        result.tool_call_id = result.tool_call_id or f'call_{step}'
        turn_messages.append(prompts.tool_call_message(result))
        outcome = tools.run_tool(
            result.tool_name, result.tool_args,
            conversation=conversation, executor=executor,
            triggered_by=triggered_by,
        )

        # Tier-2: la tool PROPUSO (ya stageó el pending). Enviamos el
        # parafraseo y cerramos el turno — el "sí" del cliente lo ejecuta
        # (policy §7 → _commit_pending). NO se re-alimenta al LLM.
        if outcome.needs_confirmation:
            # El alta de un cliente nuevo recolecta datos personales: el aviso
            # de privacidad va ANTES de persistirlos (just-in-time, spec §4).
            prefix = (
                _privacy_prefix(conversation)
                if result.tool_name == 'register_new_client_and_pet' else ''
            )
            enqueue_outbound(conversation, prefix + outcome.confirmation_text,
                             author='agent')
            return {'decision': 'awaiting_confirmation',
                    'llm_calls': llm_calls, 'tools': tool_calls}

        # La tool emitió una pregunta directa (p.ej. arranque del reto
        # familiar) → se envía y se cierra el turno, sin realimentar al LLM.
        if outcome.ok and outcome.reply_text:
            enqueue_outbound(conversation, outcome.reply_text, author='agent')
            return {'decision': 'awaiting_reply',
                    'llm_calls': llm_calls, 'tools': tool_calls}

        if not outcome.ok:
            # Acceso restringido del familiar (PR-17b): no es un fallo de
            # sistema — se explica y se ofrece una persona (sin escalar en bucle).
            if outcome.client_error == 'family_restricted':
                enqueue_outbound(
                    conversation,
                    "Por seguridad, cancelar o mover una cita solo lo puede "
                    "hacer el titular o nuestro equipo. ¿Te comunico con una "
                    "persona? 🙂",
                    author='agent')
                return {'decision': 'family_restricted',
                        'llm_calls': llm_calls, 'tools': tool_calls}
            if outcome.client_error == 'verification_required':
                # Número YA registrado (phone_match) → reto de identidad para
                # confirmar que es el titular. Número NO registrado → no tiene
                # mascota que confirmar: ofrecer alta en vez de rebotar a humano.
                if conversation.contact.owner_id is None:
                    enqueue_outbound(
                        conversation,
                        _privacy_prefix(conversation) + tier0.T0_NEW_CLIENT,
                        author='agent')
                    return {'decision': 'offer_new_client',
                            'llm_calls': llm_calls, 'tools': tool_calls}
                challenge = policy.start_identity_challenge(conversation)
                enqueue_outbound(conversation,
                                 _privacy_prefix(conversation) + challenge,
                                 author='agent')
                return {'decision': 'identity_challenge',
                        'llm_calls': llm_calls, 'tools': tool_calls}

            # Errores SUAVES (faltan datos, fecha inválida, hueco tomado…):
            # NO son fallos de sistema. Se realimentan al LLM con una guía para
            # que PREGUNTE o AJUSTE — jamás rebotan a un humano. Solo un
            # 'tool_failure' real (HTTP 5xx/transporte) escala.
            if outcome.client_error != 'tool_failure':
                consecutive_failures = 0
                payload = {
                    'error': outcome.client_error,
                    'detalle': outcome.detail,
                    'guia': _soft_error_hint(outcome.client_error),
                }
                if outcome.data:
                    # Estado del objetivo (W2): qué ya tengo, qué falta y qué
                    # hay que confirmar. El modelo redacta la pregunta.
                    payload['objetivo'] = outcome.data
                turn_messages.append(
                    prompts.tool_result_message(result, payload))
                continue

            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_TOOL_FAILURES:
                policy.escalate_to_human(
                    conversation, reason_code=HumanHandoff.REASON_TOOL_FAILURE,
                )
                enqueue_outbound(conversation, tier0.T0_TECH_PROBLEM,
                                 author='agent')
                return {'decision': 'escalate', 'llm_calls': llm_calls,
                        'tools': tool_calls, 'reason': 'tool_failure'}
            turn_messages.append(prompts.tool_result_message(result, {
                'error': 'tool_failure',
                'guia': _soft_error_hint('tool_failure'),
            }))
            continue

        consecutive_failures = 0
        if outcome.data is not None:
            tool_facts.append({'tool': result.tool_name,
                               'resultado': outcome.data})
        turn_messages.append(prompts.tool_result_message(
            result, {'resultado': outcome.data}))

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
        if outcome.client_error == 'past_date':
            enqueue_outbound(
                conversation,
                "Esa fecha ya pasó 😅 ¿Para qué día lo dejamos?",
                author='agent',
            )
            return {'decision': 'commit_past_date', 'llm_calls': 0, 'tools': 1}
        if outcome.client_error == 'invalid_data':
            # El dominio rechazó por otra razón (dato faltante, valor
            # inválido). No es un fallo de sistema: se pide el dato, no se
            # rebota a un humano ni se miente diciendo que se ocupó el horario.
            enqueue_outbound(
                conversation,
                "No pude guardarlo con esos datos 🙈 ¿Me confirmas el día y la "
                "hora que quieres?",
                author='agent',
            )
            logger.warning("AGENT_COMMIT_REJECTED", extra={
                "event": "AGENT_COMMIT_REJECTED",
                "organization_id": conversation.organization_id,
                "conversation_id": conversation.pk,
                "tool": pending['tool'],
                "detail": outcome.detail[:160],
            })
            return {'decision': 'commit_invalid', 'llm_calls': 0, 'tools': 1}
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

    # El objetivo se cumplió: se cierra aquí, en el único punto donde consta
    # que el dominio aceptó la escritura (W2).
    from .models import ConversationGoal
    goals.close_open_goal(
        conversation, ConversationGoal.STATUS_COMPLETED, pending['tool'])

    enqueue_outbound(conversation,
                     _success_message(pending['tool'], outcome, conversation, executor),
                     author='agent')
    return {'decision': 'committed', 'llm_calls': 0, 'tools': 1,
            'tool': pending['tool']}


def _success_message(tool, outcome, conversation, executor):
    """Mensaje de éxito enriquecido (UX-09/UX-11): al agendar se añade
    dirección/indicaciones; al cancelar se ofrece reagendar con horarios
    concretos (retención)."""
    if tool == 'cancel_appointment':
        fecha, horas = tools.suggest_retention_slots(conversation, executor)
        if fecha and horas:
            return (f"Listo, cancelé tu cita. Si quieres te reagendo — tengo "
                    f"lugar el {fecha}: {' o '.join(horas)}. ¿Te acomoda "
                    f"alguno? 🙂")
        return _commit_success_text(tool, outcome)

    base = _commit_success_text(tool, outcome)
    if tool in ('create_appointment', 'register_new_client_and_pet'):
        base += _post_scheduling_info(conversation)
    return base


def _post_scheduling_info(conversation):
    """UX-09: sufijo con dirección/indicaciones de la clínica. Fuente única =
    Organization (ADR p53); faq_facts es fallback. '' si no hay datos — nunca
    se inventa (G1)."""
    from . import clinic_context
    from .models import AgentSettings
    org = conversation.organization
    org_facts = clinic_context.clinic_facts(org)
    settings_obj = AgentSettings.objects.filter(organization=org).first()
    legacy = (settings_obj.faq_facts or {}) if settings_obj else {}

    address = (org_facts.get('dirección')
               or legacy.get('direccion') or legacy.get('dirección'))
    hints = (org_facts.get('indicaciones') or legacy.get('indicaciones')
             or legacy.get('como_llegar') or legacy.get('cómo_llegar'))
    maps = org_facts.get('mapa')
    parts = []
    if address:
        parts.append(f"📍 {address}")
    if maps:
        parts.append(str(maps))
    if hints:
        parts.append(str(hints))
    return ("\n\n" + "\n".join(parts)) if parts else ""


def _commit_success_text(tool, outcome):
    cuando = (outcome.data or {}).get('cuando', '')
    if tool == 'register_new_client_and_pet':
        return (f"¡Listo! ✅ Te registré y quedó agendada tu cita para el "
                f"{cuando}. Te esperamos 🐾")
    if tool == 'create_appointment':
        return f"¡Listo! ✅ Quedó agendada para el {cuando}. Te esperamos 🐾"
    if tool == 'reschedule_appointment':
        return f"¡Listo! Tu cita quedó reprogramada para el {cuando} ✅"
    if tool == 'cancel_appointment':
        return ("Listo, cancelé tu cita. Si quieres agendar otra, con gusto te "
                "ayudo 🙂")
    return "¡Listo! ✅"


def _soft_error_hint(client_error):
    """Guía para el LLM cuando una tool devuelve un error 'suave' → que
    PREGUNTE o AJUSTE en vez de rebotar a un humano."""
    return {
        'need_data': 'Faltan datos para agendar. Pregúntale al cliente lo que '
                     'falte (fecha y HORA concreta, y el motivo) antes de usar '
                     'la herramienta de nuevo.',
        'need_date': 'Falta el día. Pregúntale al cliente para qué fecha quiere.',
        'bad_date': 'No entendí la fecha. Pídesela al cliente en concreto '
                    '(por ejemplo "el viernes" o una fecha).',
        'past_date': 'Esa fecha ya pasó. Ofrécele una fecha futura.',
        'slot_taken': 'Ese horario se acaba de ocupar. Ofrécele otro horario.',
        'no_vet': 'La clínica no tiene veterinarios activos para agendar. '
                  'Discúlpate y ofrece pasar con una persona.',
        'unknown_handle': 'No ubico esa cita o mascota. Pídele al cliente que '
                          'te dé más detalle (nombre de la mascota o del día).',
        'not_cancelable': 'Esa cita ya no se puede cancelar por aquí. Ofrece '
                          'pasar con una persona.',
        'not_reschedulable': 'Esa cita ya no se puede mover por aquí. Ofrece '
                             'pasar con una persona.',
        'already_a_client': 'Este número ya está registrado. Trátalo como '
                            'cliente existente.',
        'ambiguous_identity': 'Hay varios registros con este número. Ofrece '
                              'pasar con una persona para validar.',
        'invalid_data': 'El sistema rechazó esos datos. Revisa lo que falta o '
                        'está mal (mira el detalle) y pregúntaselo al cliente '
                        'con naturalidad.',
        'invalid_slot': 'Alguno de los datos no es válido (mira `rechazado`). '
                        'Pídeselo de nuevo al cliente, sin tecnicismos.',
        'confirm_slot': 'Hay un dato que entendiste con poca seguridad (mira '
                        '`por_confirmar`). Confírmalo con el cliente antes de '
                        'seguir; no lo des por bueno.',
        'out_of_horizon': 'Esa fecha está demasiado lejos (solo agendamos '
                          'hasta 60 días). Ofrécele una más cercana.',
        'tool_failure': 'Hubo un problema técnico consultando el sistema. Si '
                        'vuelve a fallar, ofrece pasar con una persona.',
    }.get(client_error, 'No se pudo completar. Pregúntale al cliente o '
          'reformula lo que necesitas.')


def _settle_goal(conversation, *, goal_touched, other_tool_used):
    """Cierra el turno desde el punto de vista del objetivo (W2).

    Devuelve True si el objetivo se estancó y toca escalar. Un cliente que
    intercala una pregunta NO estanca nada: eso **pausa** el objetivo (se
    retoma solo, con lo ya capturado intacto) — es justo lo que la spec §2.7
    pedía y no se podía cumplir sin estado persistido.
    """
    goal = goals.get_open_goal(conversation)
    if goal is None or goal_touched:
        return False
    if other_tool_used:
        goals.pause(goal)
        return False
    return goals.bump_stall(goal)


def _after_hours_prefix(conversation, agent_settings):
    """INT-03: avisar UNA vez por conversación que estamos cerrados.

    El agente sigue atendiendo (el valor es 24/7), pero el cliente merece saber
    que el equipo humano responde al abrir. Antes esto solo existía en el
    saludo del buzón F0 — con el agente encendido no se decía nunca.
    """
    if agent_settings is None or conversation.flow.get('after_hours_notified'):
        return ''
    open_now = tier0.is_open_now(
        agent_settings.business_hours, conversation.organization.timezone)
    if open_now is not False:          # None = sin horario configurado
        return ''
    conversation.flow['after_hours_notified'] = True
    conversation.save(update_fields=['flow'])
    return tier0.T0_AFTER_HOURS_SUFFIX.strip() + "\n\n"


def _log_guard(conversation, violations, *, action):
    """Traza de un guard que disparó. Sin el texto (PII, regla R15)."""
    logger.warning("AGENT_OUTPUT_GUARD", extra={
        "event": "AGENT_OUTPUT_GUARD",
        "organization_id": conversation.organization_id,
        "conversation_id": conversation.pk,
        "violations": guards.summarize(violations),
        "action": action,
    })


def _privacy_prefix(conversation):
    """Aviso de privacidad just-in-time (spec §4 INT-00 / UX-01).

    Se emite UNA sola vez por contacto y siempre ANTES de la primera
    recolección o revelación de datos personales — no en el saludo (un link
    en el primer mensaje enfría la conversación y penaliza el rating de Meta).
    Estaba especificado y escrito (`tier0.render_privacy`) pero nunca se
    invocaba: el aviso no existía en producción. Devuelve '' si ya se emitió.
    """
    from .models import AgentSettings
    contact = conversation.contact
    if contact.privacy_notice_sent_at:
        return ''
    agent_settings = AgentSettings.objects.filter(
        organization=conversation.organization,
    ).first()
    contact.privacy_notice_sent_at = timezone.now()
    contact.save(update_fields=['privacy_notice_sent_at'])
    return tier0.render_privacy(agent_settings) + "\n\n"


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
