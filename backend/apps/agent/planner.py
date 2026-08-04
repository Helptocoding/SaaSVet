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
import copy
import logging
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import (
    arbiter,
    confirmations,
    goals,
    guards,
    matchers,
    policy,
    prompts,
    tier0,
    tools,
)
from .executor import ToolExecutor
from .llm import LLMError, estimate_cost, get_llm_client
from .models import Conversation, HumanHandoff, LLMCall, TurnDecision
from .outbound import enqueue_outbound

logger = logging.getLogger('agent.events')

# 2 fallos de tool consecutivos → escalar (spec §2.5, E-08).
MAX_CONSECUTIVE_TOOL_FAILURES = 2


def handle_inbound(conversation, *, agent_settings=None, llm_client=None,
                   executor=None, triggered_by=None, burst=None,
                   payload_types=None):
    """Envoltorio de `_handle_inbound_inner` que deja el rastro append-only
    de la decisión del turno (R12, É-F4 Fase 1 §1.3).

    Único punto de escritura: las ~20 salidas de texto libre de
    `_handle_inbound_inner` desembocan TODAS aquí. El registro NUNCA puede
    tumbar el turno (mismo patrón que `_persist_llm_call`) — si
    `TurnDecision.objects.create` revienta, el turno responde igual y solo
    se pierde el rastro de ESE turno.
    """
    started = time.monotonic()
    result = _handle_inbound_inner(
        conversation, agent_settings=agent_settings, llm_client=llm_client,
        executor=executor, triggered_by=triggered_by, burst=burst,
        payload_types=payload_types,
    )
    # El árbitro corre AQUÍ, con el saliente ya encolado (É-F5 Fase 4, p56
    # §5-bis): clasifica qué le pasó al compromiso y el ejecutor aplica los
    # efectos SOBRE EL COMPROMISO. Ese turno ya ocurrió — el cliente ya leyó
    # el mensaje y nada de esto puede tocarlo.
    verdict = _settle_commitment(conversation, result, burst)
    _record_turn_decision(conversation, result, started, triggered_by,
                          verdict=verdict)
    return result


def _settle_commitment(conversation, result, burst):
    """Clasifica el desenlace del compromiso y aplica sus efectos.

    Nunca puede tumbar el turno: si algo revienta aquí, el cliente ya tiene su
    respuesta y lo único que se pierde es el rastro (mismo criterio que
    `_record_turn_decision`).
    """
    try:
        raw = [b for b in (burst or []) if b]
        burst_text = "\n".join(raw)
        commitment = (goals.get_open_goal(conversation)
                      or goals.get_identity_commitment(conversation))
        view = (arbiter.CommitmentView(commitment.name, commitment.return_to)
                if commitment is not None else None)
        facts = _observe_turn_facts(
            burst_text,
            goal_advanced=bool(result.get('goal_advanced')),
            other_goal_proposed=result.get('other_goal_proposed', ''),
        )
        verdict = arbiter.decide(facts, view)
        _apply_verdict(conversation, verdict,
                       supplanted_by=result.get('other_goal_proposed', ''))
        return verdict, facts
    except Exception:
        logger.exception("AGENT_ARBITER_FAILED")
        return None, None


def _observe_turn_facts(burst_text, *, goal_advanced, other_goal_proposed):
    """Los hechos del turno, YA calculados (p55 A3).

    Vive aquí y no en `arbiter.py` porque producir hechos exige llamar
    matchers, y el árbitro tiene que seguir siendo puro: su pureza es lo que
    permite recalcular veredictos sobre conversaciones históricas sin base de
    datos ni proveedor (p56 §5-bis). El gate A3 rechazó la primera versión,
    que los producía dentro del módulo.

    **Ninguno viene del modelo, y es estructural**: si un hecho lo generara el
    LLM, reproducir un veredicto exigiría volver a llamarlo y la propiedad de
    recálculo se perdería.
    """
    return arbiter.TurnFacts(
        proposes_other_commitment=bool(other_goal_proposed),
        client_declined=matchers.classify_confirmation(burst_text) == 'negative',
        interrupts=(matchers.looks_like_question(burst_text)
                    and not goal_advanced),
    )


def _apply_verdict(conversation, verdict, *, supplanted_by=''):
    """Aplica al COMPROMISO lo que el veredicto dice que le pasó.

    **INVARIANTE (p56 §5-bis).** Los efectos tocan únicamente el estado
    persistente del compromiso, **nunca el mensaje ya emitido en ese turno**.
    Esto corre DESPUÉS de encolar el saliente: ese turno ya ocurrió y el
    cliente ya lo leyó. Un `SUPPLANT` no "reemplaza la respuesta"; anota que
    la promesa quedó suspendida para el turno siguiente.

    A6 de p55: cada veredicto lleva su propio contador y ninguno toca el de
    otro. Reetiquetar un desvío como fallo es lo que produjo el handoff de la
    conv 13.
    """
    if verdict.verdict in (arbiter.ANSWER, arbiter.CONTINUE):
        return
    goal = (goals.get_open_goal(conversation)
            or goals.get_identity_commitment(conversation))
    if goal is None:
        return
    if verdict.verdict == arbiter.DEVIATE:
        goals.deviate(goal, verdict.return_to)
    elif verdict.verdict == arbiter.SUPPLANT:
        goals.suspend(goal, supplanted_by=supplanted_by or 'otro compromiso')
    elif verdict.verdict == arbiter.ABORT:
        goals.abandon(goal, 'el cliente lo descartó')


def _record_turn_decision(conversation, result, started, triggered_by,
                          *, verdict=None):
    try:
        duration_ms = int((time.monotonic() - started) * 1000)
        because = _infer_because(result)
        turn_verdict, facts = verdict or (None, None)
        # `verdict` guarda el veredicto del ÁRBITRO (enum cerrado de cinco).
        # Hasta É-F5 Fase 4 guardaba el nombre interno de la salida del planner
        # —`planner_reply`, `escalate`…— porque no había árbitro; era deuda
        # declarada en el propio docstring del modelo. Ese desenlace operativo
        # no se pierde: baja a `facts_produced`, que es diagnóstico.
        produced = {'reason': result['reason']} if result.get('reason') else {}
        produced['salida'] = result.get('decision', '')
        TurnDecision.objects.create(
            organization=conversation.organization,
            conversation=conversation,
            verdict=(turn_verdict.verdict if turn_verdict
                     else result.get('decision', '')),
            because=because,
            active_commitment=(turn_verdict.commitment if turn_verdict else ''),
            return_to=(turn_verdict.return_to if turn_verdict else ''),
            supplanted_by=result.get('other_goal_proposed', ''),
            facts_consumed=({
                'propone_otro_compromiso': facts.proposes_other_commitment,
                'el_cliente_dijo_que_no': facts.client_declined,
                'interrumpe': facts.interrupts,
            } if facts else {}),
            facts_produced=produced,
            planner_used=result.get('llm_calls', 0) > 0,
            tools_called=result.get('tools', 0),
            duration_ms=duration_ms,
            triggered_by_message=triggered_by,
        )
    except Exception:
        logger.exception("AGENT_TURN_DECISION_RECORD_FAILED")


# Mapeo GRUESO decision→Because (Fase 1, sin árbitro todavía — ver docstring
# de `TurnDecision`). `reason`/`handoff_reason` son las únicas señales que
# sobreviven hasta este envoltorio; las ~22 salidas internas no se tocan.
_ESCALATE_BECAUSE = {
    HumanHandoff.REASON_EMERGENCY: TurnDecision.Because.SAFEGUARD,
    HumanHandoff.REASON_POLICY: TurnDecision.Because.SAFEGUARD,
    HumanHandoff.REASON_EXPLICIT: TurnDecision.Because.HUMAN_REQUESTED,
    HumanHandoff.REASON_BUDGET: TurnDecision.Because.BUDGET_EXCEEDED,
    HumanHandoff.REASON_TOOL_FAILURE: TurnDecision.Because.SYSTEM_ERROR,
    HumanHandoff.REASON_IDENTITY: TurnDecision.Because.VERIFICATION_REQUIRED,
    HumanHandoff.REASON_LOW_CONFIDENCE: TurnDecision.Because.VERIFICATION_REQUIRED,
}
_REPLY_BECAUSE = {
    'deviation': TurnDecision.Because.CLIENT_QUESTIONED,
    'confirm_defer': TurnDecision.Because.CLIENT_DEFERRED,
    'blocked': TurnDecision.Because.SAFEGUARD,
    'human_active': TurnDecision.Because.SAFEGUARD,
    'handoff_pending': TurnDecision.Because.SAFEGUARD,
    'handoff_ack': TurnDecision.Because.SAFEGUARD,
    'disabled': TurnDecision.Because.SAFEGUARD,
    'media': TurnDecision.Because.OUT_OF_SCOPE,
    'bot_question': TurnDecision.Because.OUT_OF_SCOPE,
    'out_payment': TurnDecision.Because.OUT_OF_SCOPE,
    'identity_triage': TurnDecision.Because.CLIENT_ANSWERED,
}
_DIRECT_BECAUSE = {
    'silent': TurnDecision.Because.SAFEGUARD,
    'close': TurnDecision.Because.SAFEGUARD,
    'guard_blocked': TurnDecision.Because.SAFEGUARD,
    'goal_stalled': TurnDecision.Because.GOAL_STALLED,
    'tool_budget_exhausted': TurnDecision.Because.BUDGET_EXCEEDED,
    'identity_challenge': TurnDecision.Because.VERIFICATION_REQUIRED,
    'identity_triage': TurnDecision.Because.VERIFICATION_REQUIRED,
    'family_restricted': TurnDecision.Because.VERIFICATION_REQUIRED,
    'committed': TurnDecision.Because.CLIENT_CONFIRMED,
    'confirm_expired': TurnDecision.Because.CLIENT_DEFERRED,
    'commit_unknown': TurnDecision.Because.SYSTEM_ERROR,
    'commit_slot_taken': TurnDecision.Because.SYSTEM_ERROR,
    'commit_past_date': TurnDecision.Because.SYSTEM_ERROR,
    'commit_invalid': TurnDecision.Because.SYSTEM_ERROR,
}


def _infer_because(result):
    decision = result.get('decision', '')
    if decision == 'escalate':
        return _ESCALATE_BECAUSE.get(
            result.get('handoff_reason', ''), TurnDecision.Because.SYSTEM_ERROR)
    if decision == 'reply':
        return _REPLY_BECAUSE.get(
            result.get('reason'), TurnDecision.Because.PLANNER_HANDLED)
    return _DIRECT_BECAUSE.get(decision, TurnDecision.Because.PLANNER_HANDLED)


def _handle_inbound_inner(conversation, *, agent_settings=None, llm_client=None,
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
        text = decision.text
        # UX-01: el aviso just-in-time va ANTES de la primera recolección de
        # datos personales. El tamiz de identidad se resuelve en el router y
        # sale por aquí — sin este prefijo, un cliente nuevo daba su nombre sin
        # haberlo recibido (el camino viejo, por el planner, sí lo emitía).
        if decision.meta.get('privacy_notice'):
            text = _privacy_prefix(conversation) + text
        enqueue_outbound(conversation, text, author='system')
        return {'decision': 'reply', 'llm_calls': 0, 'tools': 0,
                'reason': decision.meta.get('reason')}

    if decision.kind == policy.CLOSE:
        enqueue_outbound(conversation, decision.text, author='system')
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
            enqueue_outbound(conversation, decision.text, author='system')
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
                        triggered_by,
                        burst_text='\n'.join(texts) if texts else (text or ''))


def _run_planner(conversation, agent_settings, llm_client, executor,
                 triggered_by, *, burst_text=''):
    tool_specs = tools.as_openai_tools()
    base_messages = prompts.assemble_messages(conversation,
                                              burst_text=burst_text)
    # Hilo del turno: las llamadas del propio modelo y sus resultados (W1-3).
    # Antes solo viajaba el ÚLTIMO resultado, como bloque de sistema, y el
    # modelo no veía que ya había llamado a la herramienta.
    turn_messages = []
    tool_facts = []          # lo que las tools devolvieron ESTE turno (G1)
    correction = None        # instrucción correctiva del guard (un intento)
    # ¿Este turno descubrió que hay que identificar a alguien? Si sí, el aviso
    # de privacidad encabeza la respuesta (LFPDPPP just-in-time). Lo pone el
    # sistema porque es un literal legal, no algo que el modelo redacte.
    needs_privacy_notice = False
    # W2 — tres señales distintas, antes colapsadas en una sola (`goal_touched`)
    # que solo decía "se llamó una tool de objetivo". Un modelo atascado la
    # llama en CADA vuelta, así que el estancamiento nunca se detectaba.
    goal_attempted = False   # se llamó una tool de objetivo
    goal_progressed = False  # …y de verdad llenó algo
    other_goal_proposed = ''  # el modelo llamó la tool de OTRO compromiso
    other_tool_used = False  # se usó una tool ajena al objetivo (interrupción)
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
                             author='system')
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
            # …y los de CONDUCTA (É-F4 Fase 4). Los léxicos juzgan lo que se
            # dijo; estos, cómo se está comportando el sistema — que es donde
            # estaban los fallos más caros de la auditoría y ninguno era una
            # palabra prohibida. Nacen en SOFT: observan y corrigen, no
            # escalan.
            violations += guards.check_behaviour(
                text,
                asked=_asked_counters(conversation),
                anchored_facts=prompts.anchored_identity_facts(conversation),
                tool_ran=tool_calls > 0,
            )
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
                                 author='system')
                return {'decision': 'guard_blocked', 'llm_calls': llm_calls,
                        'tools': tool_calls,
                        'reason': guards.summarize(violations)}
            if _settle_goal(conversation, goal_progressed=goal_progressed,
                            goal_attempted=goal_attempted,
                            other_tool_used=other_tool_used,
                            client_asked=matchers.looks_like_question(
                                burst_text)):
                # Estancamiento semántico: 3 turnos sin llenar un solo dato.
                # Sustituye al presupuesto contable como disparador — "no
                # avanzamos" es una señal real; "gastaste N llamadas" no.
                policy.escalate_to_human(
                    conversation,
                    reason_code=HumanHandoff.REASON_LOW_CONFIDENCE,
                    detail='goal_stalled',
                )
                enqueue_outbound(conversation, tier0.T0_GOAL_STALLED,
                                 author='system')
                return {'decision': 'goal_stalled', 'llm_calls': llm_calls,
                        'tools': tool_calls}
            if violations:
                _log_guard(conversation, violations, action='sent')
            # ÚNICO texto que el modelo redactó de verdad → voz propia del
            # agente (R11, Fase 2 §2.1). Todo lo demás sale como 'system'.
            #
            # El aviso de privacidad va DELANTE si en este turno el sistema
            # descubrió que necesita identificar a alguien (É-F5 Fase 2).
            # Antes lo anteponía el paso 12b del router, que se retiró; sin
            # esto, pedir nombre, mascota o dígitos —que ES recolección de
            # datos personales— dejaba de ir precedido del aviso (LFPDPPP,
            # spec §4 just-in-time).
            #
            # Lo pone el sistema, no el modelo, y a propósito: es un literal
            # legal. `_privacy_prefix` ya es idempotente por contacto, así que
            # no se repite aunque la verificación se pida varias veces.
            enqueue_outbound(
                conversation,
                (_privacy_prefix(conversation) if needs_privacy_notice else '')
                + _after_hours_prefix(conversation, agent_settings,
                                      burst_text=burst_text) + text,
                author='agent')
            return {'decision': 'planner_reply', 'llm_calls': llm_calls,
                    'tools': tool_calls,
                    'goal_advanced': goal_progressed,
                    'other_goal_proposed': other_goal_proposed}

        # tool_call
        tool_calls += 1
        is_goal_tool = result.tool_name in goals.TOOL_GOALS
        if is_goal_tool:
            goal_attempted = True
            # ¿El modelo llamó una herramienta de un compromiso DISTINTO al que
            # está en curso? Es el hecho que hacía falta para que el veredicto
            # `suplantar` fuera alcanzable: el cliente cambió de tema a algo
            # que el sistema sí sabe hacer (É-F5 Fase 4).
            propuesto = goals.TOOL_GOALS[result.tool_name]
            en_curso = goals.get_open_goal(conversation)
            if en_curso is not None and en_curso.name != propuesto:
                other_goal_proposed = propuesto
        else:
            other_tool_used = True
        # El stub de tests no emite id: se sintetiza para poder correlacionar.
        result.tool_call_id = result.tool_call_id or f'call_{step}'
        turn_messages.append(prompts.tool_call_message(result))
        # Foto de lo propuesto ANTES de la llamada. Desde ADR p55 §4 las tools
        # no cierran turnos: PROPONEN un compromiso persistiéndolo, y el
        # planner detecta la propuesta comparando. Un `pending` puede
        # preexistir (policy paso 7 con veredicto 'unclear' cae al planner sin
        # descartarlo), así que se compara el contenido, no la presencia.
        proposals_before = _open_proposals(conversation)
        outcome = tools.run_tool(
            result.tool_name, result.tool_args,
            conversation=conversation, executor=executor,
            triggered_by=triggered_by,
        )

        # ¿AVANZÓ el objetivo, o solo se tocó? Llamar la herramienta con los
        # mismos datos de siempre no es progreso: es el bucle.
        if is_goal_tool:
            if outcome.ok:
                goal_progressed = True
            elif isinstance(outcome.data, dict) and outcome.data.get('capturado'):
                goal_progressed = True

        proposed = _new_proposal(proposals_before, conversation)

        # Tier-2: la tool PROPUSO (ya stageó el pending). Enviamos el
        # parafraseo y cerramos el turno — el "sí" del cliente lo ejecuta
        # (policy §7 → _commit_pending). NO se re-alimenta al LLM.
        #
        # Que el turno termine aquí lo decide el PLANNER al ver la propuesta,
        # no una bandera que la tool trae encima (ADR p55 §4). La barrera es
        # la misma de siempre: se ejecutan los args STAGED, jamás
        # regenerados (TC-SEC-03).
        if proposed == 'confirmation':
            # El alta de un cliente nuevo recolecta datos personales: el aviso
            # de privacidad va ANTES de persistirlos (just-in-time, spec §4).
            prefix = (
                _privacy_prefix(conversation)
                if result.tool_name == 'register_new_client_and_pet' else ''
            )
            # Excepción deliberada a la regla de autoría: el parafraseo tier-2
            # es plantilla, pero lo PROPUSO el modelo con su llamada a
            # herramienta y el cliente le contesta a él. Se conserva como voz
            # del agente — la confirmación tier-2 no se toca (§11 del plan).
            paraphrase = (confirmations.get_pending(conversation) or {}).get(
                'paraphrase', '')
            enqueue_outbound(conversation, prefix + paraphrase, author='agent')
            return {'decision': 'awaiting_confirmation',
                    'llm_calls': llm_calls, 'tools': tool_calls}

        # Aquí una tool podía PROPONER un reto de identidad: el planner emitía
        # la plantilla del primer factor y cerraba el turno sin realimentar al
        # LLM. Retirado en É-F5 Fase 2 junto con `link_family_member`, su único
        # productor — el docstring de aquella tool lo decía sin querer: «el
        # resto del reto lo conduce el Policy Engine, sin LLM». Ese conductor
        # ya no existe, así que la tool sembraba un reto que nadie avanzaba.
        # Su función la cumple `identify_client` en una sola llamada, y quien
        # pregunta lo que falta es el modelo.

        if not outcome.ok:
            # Acceso restringido del familiar (PR-17b): no es un fallo de
            # sistema — se explica y se ofrece una persona (sin escalar en bucle).
            if outcome.client_error == 'family_restricted':
                enqueue_outbound(
                    conversation,
                    "Por seguridad, cancelar o mover una cita solo lo puede "
                    "hacer el titular o nuestro equipo. ¿Te comunico con una "
                    "persona? 🙂",
                    author='system')
                return {'decision': 'family_restricted',
                        'llm_calls': llm_calls, 'tools': tool_calls}
            # Errores SUAVES (faltan datos, fecha inválida, hueco tomado…):
            # NO son fallos de sistema. Se realimentan al LLM con una guía para
            # que PREGUNTE o AJUSTE — jamás rebotan a un humano. Solo un
            # 'tool_failure' real (HTTP 5xx/transporte) escala.
            if outcome.client_error != 'tool_failure':
                consecutive_failures = 0
                if outcome.client_error == 'verification_required':
                    # El sistema acaba de decidir que necesita identificar a
                    # quien escribe: lo que el modelo pida a continuación son
                    # datos personales, así que el aviso encabeza la respuesta.
                    needs_privacy_notice = True
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
                                 author='system')
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
    enqueue_outbound(conversation, _fallback_text(), author='system')
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
            author='system',
        )
        return {'decision': 'confirm_expired', 'llm_calls': 0, 'tools': 0}

    handler = tools.COMMIT_HANDLERS.get(pending['tool'])
    if handler is None:  # defensivo: pending corrupto
        confirmations.clear_pending(conversation)
        enqueue_outbound(conversation, _fallback_text(), author='system')
        return {'decision': 'commit_unknown', 'llm_calls': 0, 'tools': 0}

    outcome = handler(conversation, executor, pending['args'],
                      triggered_by=triggered_by)
    confirmations.clear_pending(conversation)

    if not outcome.ok:
        if outcome.client_error == 'slot_taken':
            enqueue_outbound(
                conversation,
                "Uy, justo se ocupó ese horario 😅 ¿Buscamos otra opción?",
                author='system',
            )
            return {'decision': 'commit_slot_taken', 'llm_calls': 0,
                    'tools': 1}
        if outcome.client_error == 'past_date':
            enqueue_outbound(
                conversation,
                "Esa fecha ya pasó 😅 ¿Para qué día lo dejamos?",
                author='system',
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
                author='system',
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
            author='system',
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
                     author='system')
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
        # É-F5 Fase 2: la verificación deja de ser una rama que TERMINA el
        # turno con una plantilla y pasa a ser un error suave como los demás.
        # Antes, este código secuestraba el turno: el router sembraba un reto,
        # emitía su plantilla y el modelo no volvía a ver la conversación
        # hasta que el reto se resolviera o muriera. Ahora el modelo se entera
        # de que falta verificar y lo pide él, conversando.
        #
        # La barrera NO se toca: `run_tool` sigue revalidando y la llamada
        # rebota sin ejecutar nada. Lo que cambia es quién redacta la
        # respuesta, no quién autoriza.
        'verification_required': 'Todavía no sabes con certeza quién te '
                                 'escribe, y eso hace falta para tocar datos '
                                 'personales. Pídele lo que falte —su nombre, '
                                 'el de su mascota o los últimos 4 dígitos del '
                                 'teléfono registrado— y di para qué es. '
                                 'Cuando te lo diga, llama a la herramienta de '
                                 'identificación.',
        # C7 · ya se pidió dos veces y no funcionó. El sistema deja de pedir
        # igual y le dice al modelo que cambie de estrategia — repetir la
        # misma pregunta es lo que hizo que el cliente de la conv 12 se fuera.
        'change_approach': 'Ya le pediste ese dato dos veces y no ha '
                           'funcionado: NO se lo vuelvas a preguntar igual. '
                           'Cambia de estrategia — ofrécele opciones '
                           'concretas (consulta disponibilidad y propón dos o '
                           'tres horarios), o pregúntaselo de otra forma. Si '
                           'aun así no avanzan, ofrécele pasar con una '
                           'persona.',
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


def _settle_goal(conversation, *, goal_progressed, goal_attempted,
                 other_tool_used, client_asked=False):
    """Cierra el turno desde el punto de vista del objetivo (W2).

    Devuelve True si el objetivo se estancó y toca escalar. Un cliente que
    intercala una pregunta NO estanca nada: eso **pausa** el objetivo (se
    retoma solo, con lo ya capturado intacto) — es justo lo que la spec §2.7
    pedía y no se podía cumplir sin estado persistido.

    El intento SIN progreso cuenta como estancamiento (corrección piloto conv
    12): antes bastaba con llamar la herramienta para que el turno se diera por
    productivo, así que un modelo repreguntando el mismo dato en bucle
    mantenía `stall_turns` en 0 indefinidamente — el detector era ciego
    justamente al caso que existe para cazar.

    **`client_asked` (C11 · ADR p56 §7).** Un turno en el que el cliente
    PREGUNTÓ no incrementa el estancamiento. Hasta aquí sí lo hacía: una
    pregunta no llena ningún slot, así que sumaba a `stall_turns`, y tres de
    esos mandaban al cliente con un humano diciéndole «creo que por aquí nos
    estamos enredando». **El sistema contaba la conversación del cliente como
    su propio atasco.** Es el mismo error que É-F4 Fase 0 corrigió para los
    retos de identidad (R1) sin aplicarlo aquí, y el corolario de R10 que la
    auditoría de rigidez dejó escrito y nadie implementó: *preguntar nunca
    puede acercar al cliente a una escalada*.

    Estancamiento pasa a significar lo que dice su nombre: **el sistema no está
    logrando avanzar** — el modelo llamando la misma herramienta con los mismos
    datos, vuelta tras vuelta— no *«el cliente no me dio lo que le pedí»*.

    Ojo con el alcance: `client_asked` es un hecho de **control** (es el mismo
    predicado que alimenta `TurnFacts.interrupts`, que el árbitro lee). Los
    turnos puramente sociales —una disculpa, una broma— son hechos de
    SITUACIÓN y **no** entran aquí: ninguna función de decisión puede leerlos
    (ADR p56, invariante 1).
    """
    goal = goals.get_open_goal(conversation)
    if goal is None or goal_progressed:
        return False
    if client_asked:
        return False
    if goal_attempted:
        return goals.bump_stall(goal)
    if other_tool_used:
        goals.pause(goal)
        return False
    return goals.bump_stall(goal)


def _asked_counters(conversation):
    """`{slot: veces_preguntado}` del compromiso de tarea en curso (R10)."""
    goal = goals.get_open_goal(conversation)
    return dict(goal.asked or {}) if goal is not None else {}


def _open_proposals(conversation):
    """Foto de los compromisos que una tool podría PROPONER en este turno.

    Dos formas de propuesta, ambas persistidas por la propia tool: el
    `pending_action` de tier-2 y un reto de identidad. Se fotografían para
    poder distinguir "lo propuso esta llamada" de "ya estaba" — sin eso haría
    falta que la tool lo dijera, que es la autoridad que ADR p55 §4 le quita.
    """
    commitment = goals.get_identity_commitment(conversation)
    return (
        copy.deepcopy(confirmations.get_pending(conversation)),
        commitment.pk if commitment is not None else None,
    )


def _new_proposal(before, conversation):
    """`'confirmation'` | `'identity'` | `None` — qué se propuso este turno."""
    pending_before, identity_before = before
    if confirmations.get_pending(conversation) not in (None, pending_before):
        return 'confirmation'
    commitment = goals.get_identity_commitment(conversation)
    if commitment is not None and commitment.pk != identity_before:
        return 'identity'
    return None


def _after_hours_prefix(conversation, agent_settings, *, burst_text=''):
    """INT-03: avisar UNA vez por conversación que estamos cerrados.

    El agente sigue atendiendo (el valor es 24/7), pero el cliente merece saber
    que el equipo humano responde al abrir. Antes esto solo existía en el
    saludo del buzón F0 — con el agente encendido no se decía nunca.

    **Con oportunidad** (Fase 2 §2.3): no se antepone cuando el cliente está
    reclamando o preguntando por la conversación misma. En la conv 13 el aviso
    cayó en medio de una queja por pérdida de contexto y **causó** el mensaje
    siguiente ("no te pedí ningún horario"). Un aviso correcto en el momento
    equivocado es ruido. Al suprimirlo NO se consume el flag: sigue disponible
    para un turno mejor.
    """
    if agent_settings is None or conversation.flow.get('after_hours_notified'):
        return ''
    if matchers.is_complaint_or_meta(burst_text):
        return ''
    from . import clinic_context
    org = conversation.organization
    open_now = tier0.is_open_now(
        clinic_context.effective_business_hours(org, agent_settings),
        org.timezone)
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
