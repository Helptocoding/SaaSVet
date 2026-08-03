"""
agent/policy.py — Policy Engine determinista (É-F1 PR-11).

Corre ANTES del planner (spec §3 router + §11.2 pre-planner) en el orden
EXACTO de la spec. Decide, sin LLM, qué hacer con cada mensaje entrante:
responder una plantilla tier-0, escalar a humano, ejecutar/descartar una
confirmación pendiente, o ceder al planner (RUN_PLANNER, que PR-12 llena).

Ninguna decisión de autorización, tenant o identidad depende de la salida
del modelo — el LLM propone, el sistema dispone (plan v1.1, principio 2).

`evaluate()` es PURA (sin efectos de red/LLM); sí puede mutar estado
conversacional determinista (verificación implícita, arranque/avance del
reto de identidad, opt-out) — todo testeable sin proveedor.
"""
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from . import goals, identity, matchers, tier0
from .models import Conversation, HumanHandoff

logger = logging.getLogger('agent.events')

# Tipos de decisión que consume el worker (PR-12).
REPLY = 'reply'              # enviar `text` (plantilla), no invocar LLM
ESCALATE = 'escalate'        # crear handoff (+ opcional `text`)
RUN_PLANNER = 'run_planner'  # nada aplicó → el planner decide (PR-12)
SILENT = 'silent'            # no responder (humano activo / bloqueado)
CLOSE = 'close'              # cerrar la conversación tras `text`


@dataclass
class PolicyDecision:
    kind: str
    text: str = ''
    handoff_reason: str = ''
    handoff_priority: str = HumanHandoff.PRIORITY_NORMAL
    meta: dict = field(default_factory=dict)


def _budget_exhausted(conversation):
    cap = getattr(settings, 'AGENT_MAX_LLM_TURNS_PER_CONVERSATION', 15)
    return conversation.total_llm_calls >= cap


def _agent_settings(conversation):
    from .models import AgentSettings
    return AgentSettings.objects.filter(
        organization=conversation.organization,
    ).first()


def evaluate(conversation, text, *, burst=None, payload_types=None,
             agent_settings=None):
    """Pipeline pre-planner. Devuelve PolicyDecision.

    `text` = último entrante. `burst` = TODOS los entrantes drenados en este
    turno (el worker los agrupa). Los matchers de seguridad —urgencia, petición
    de humano, opt-out y confirmación— corren sobre la ráfaga COMPLETA: con
    "mi perro convulsiona" + "ayúdenme por favor" el detector solo veía el
    segundo mensaje y la urgencia se perdía. Los matchers de conveniencia
    (gracias, pagos) siguen mirando el último mensaje, que es su semántica.
    """
    if agent_settings is None:
        agent_settings = _agent_settings(conversation)
    contact = conversation.contact
    flow = conversation.flow
    raw_burst = list(burst) if burst is not None else [text]
    burst = [b for b in raw_burst if b]
    burst_text = '\n'.join(burst) if burst else (text or '')

    # 0. Kill switch / demo → buzón pasivo (T0-DISABLED, sin LLM).
    org = conversation.organization
    if agent_settings is None or not agent_settings.enabled or getattr(org, 'is_demo', False):
        return PolicyDecision(
            kind=REPLY,
            text=tier0.render_first_reply(agent_settings, org),
            meta={'reason': 'disabled'},
        )

    # 1. Contacto bloqueado → silencio (GB-10).
    if contact.is_blocked:
        return PolicyDecision(kind=SILENT, meta={'reason': 'blocked'})

    # 2. Humano ya atiende → el agente calla (spec §7.2, invariante duro).
    if conversation.state == Conversation.STATE_HUMAN_ACTIVE:
        return PolicyDecision(kind=SILENT, meta={'reason': 'human_active'})

    # 2b. Media sin texto (audio, foto, sticker, ubicación): no hay nada que
    #     leer. Antes esto llegaba al modelo como "[mensaje sin texto]" y
    #     producía una respuesta confusa gastando una llamada; la spec GB-1
    #     pedía plantilla. En México el audio es una fracción enorme del
    #     tráfico: esta rama se mide (`payload_type`) para decidir si toca
    #     transcripción (UX-14).
    if raw_burst and not any((b or '').strip() for b in raw_burst):
        return PolicyDecision(
            kind=REPLY, text=tier0.render_media_reply(payload_types),
            meta={'reason': 'media'},
        )

    # 3. URGENCIA (prioridad 1, R16) — antes que todo, incluso a mitad de
    #    flujo. Un `pending_action` en curso NO se descarta aquí: la
    #    urgencia SUPLANTA (no aborta, R4/R5) — `escalate_to_human` lo
    #    suspende, nunca lo destruye (Fase 1 §1.1).
    if matchers.is_emergency(burst_text):
        return PolicyDecision(
            kind=ESCALATE,
            text=tier0.render_emergency(agent_settings, org),
            handoff_reason=HumanHandoff.REASON_EMERGENCY,
            handoff_priority=HumanHandoff.PRIORITY_URGENT,
        )

    # 4. Pide humano.
    if matchers.wants_human(burst_text):
        return PolicyDecision(
            kind=ESCALATE,
            text=tier0.T0_HANDOFF,
            handoff_reason=HumanHandoff.REASON_EXPLICIT,
        )

    # 5. Opt-out → baja de PROACTIVOS + despedida + cierre.
    #    No bloquea al contacto: la spec (INT-04) dice que si el cliente
    #    vuelve a escribir se le atiende normal. Con `is_blocked` quedaba
    #    silenciado para siempre — un "stop" en un mal día lo dejaba
    #    inalcanzable.
    if any(matchers.wants_optout(part) for part in burst):
        contact.proactive_opt_out = True
        contact.save(update_fields=['proactive_opt_out'])
        return PolicyDecision(
            kind=CLOSE,
            text="Listo, no volveré a escribirte por aquí. Si cambias de "
                 "opinión, escríbenos cuando quieras 🐾",
            meta={'reason': 'optout'},
        )

    # 6. "¿Eres una persona?" — responde SIN descartar pending (INT-06).
    if matchers.is_bot_question(text):
        return PolicyDecision(kind=REPLY, text=tier0.T0_BOTQ,
                              meta={'reason': 'bot_question'})

    # 6b. Ya hay una escalada esperando: le prometimos una persona, así que el
    #     agente no sigue conversando como si nada. Un acuse UNA vez y luego
    #     silencio — antes seguía respondiendo con el modelo, contradiciendo
    #     la promesa; el silencio total tampoco vale (el cliente insiste sin
    #     saber si lo leyeron).
    if conversation.state == Conversation.STATE_HANDOFF_PENDING:
        if flow.get('handoff_ack_sent'):
            return PolicyDecision(kind=SILENT,
                                  meta={'reason': 'handoff_pending'})
        flow['handoff_ack_sent'] = True
        conversation.save(update_fields=['flow'])
        return PolicyDecision(kind=REPLY, text=tier0.T0_HANDOFF_WAITING,
                              meta={'reason': 'handoff_ack'})

    # 6c. Compromiso de identidad SUSPENDIDO (R5/R8): si no hay ninguno al
    #     frente pero sí uno suspendido, se retoma antes de que los pasos
    #     normales (8/8b/8c) lo procesen — con su etapa y sus candidatos
    #     intactos. Es lo que resuelve el `4586` tardío de la conv 13: antes
    #     el reto se destruía al escalar y el dato correcto caía al vacío.
    if goals.get_identity_commitment(conversation) is None:
        suspended = goals.get_suspended_goal(conversation)
        if suspended is not None and suspended.name in goals.IDENTITY_GOALS:
            goals.resume(suspended)

    # 7. Confirmación de un pending_action (ACTIVO en F2: las tools de
    #    escritura proponen; la afirmativa ejecuta el commit staged en el
    #    planner — invariante TC-SEC-03). En F1 quedaba dormant (read-only).
    if flow.get('pending_action'):
        verdict = _burst_confirmation(burst)
        if verdict == 'defer':
            # El cliente pidió tiempo y le contestamos «aquí queda pendiente —
            # me dices». Eso es una PROMESA de esperar, así que se registra
            # para que el recordatorio automático no la contradiga una hora
            # después (ADR p56 §7 / C13: los mensajes que el sistema INICIA
            # también tienen que cumplir un propósito). Es un hecho de
            # CONTROL —el veredicto de una confirmación—, no de situación:
            # `nudge_abandoned_flows` puede leerlo sin violar el invariante 1.
            flow['deferred_at'] = timezone.now().isoformat()
            conversation.save(update_fields=['flow'])
            return PolicyDecision(kind=REPLY, text=tier0.T0_DEFER,
                                  meta={'reason': 'confirm_defer'})
        if verdict == 'negative':
            flow.pop('pending_action', None)
            conversation.save(update_fields=['flow'])
            # sigue el pipeline con el pending descartado
        elif verdict == 'affirmative':
            return PolicyDecision(kind=RUN_PLANNER,
                                  meta={'confirm': 'affirmative'})
        # 'unclear' → cae al planner para clasificar (etapa 2, UX-02)

    # 8/8b/8c. RETIRADOS (É-F5 Fase 2, ADR p56 §4).
    #
    #   Aquí vivían los tres retos de identidad —titular, familia, tamiz— y
    #   con ellos ~370 líneas que decidían QUÉ FRASE tocaba en cada etapa. El
    #   router intervenía antes de que hubiera conversación: la del piloto que
    #   abrió É-F5 se resolvió con CERO llamadas al modelo, y sus cinco
    #   respuestas eran constantes de `tier0.py`.
    #
    #   Criterio que los retira (C5): **preempción solo donde la contención es
    #   imposible**. La barrera de datos personales nunca fue este router —
    #   es `_verification_ok` dentro de `run_tool`, que se evalúa por debajo
    #   del modelo. Un planner conversando libremente sobre identidad NO puede
    #   ejecutar una tool personal: la llamada rebota sin tocar nada. Preempción
    #   y contención cumplían lo mismo; solo la primera costaba humanidad.
    #
    #   El compromiso de identidad SIGUE existiendo (qué falta, el porqué de
    #   cada factor, dónde iba) — lo que desaparece es la máquina que decidía
    #   la frase. Se publica al modelo como estado y él conduce.

    # 9. Verificación IMPLÍCITA pasiva: si nombra su mascota, sube el nivel
    #    (no cambia la decisión, habilita las tools personales del turno).
    if contact.verification_level == contact.VERIFICATION_PHONE_MATCH:
        identity.try_verify_by_pet_name(contact, burst_text)

    # 10. Presupuesto agotado (R11, E-09).
    if _budget_exhausted(conversation):
        return PolicyDecision(
            kind=ESCALATE, text=tier0.T0_BUDGET,
            handoff_reason=HumanHandoff.REASON_BUDGET,
        )

    # 10b. Saludo pelón en el primer turno → bienvenida institucional, sin
    #      LLM. La plantilla estaba escrita y aprobada por el PO pero solo
    #      corría con el agente APAGADO: con el agente encendido la primera
    #      impresión la improvisaba el modelo.
    if matchers.is_bare_greeting(text) and not _has_outbound(conversation):
        return PolicyDecision(
            kind=REPLY,
            text=tier0.render_first_reply(agent_settings, org),
            meta={'reason': 'greeting'},
        )

    # 11. Agradecimiento trivial → cierre cordial sin LLM.
    if matchers.is_thanks(text):
        return PolicyDecision(kind=REPLY, text=tier0.T0_THANKS,
                              meta={'reason': 'thanks'})

    # 12. Fuera de alcance — pagos (matcher; consejo médico/queja los
    #     clasifica el planner, spec §3).
    if _mentions_payment(text):
        return PolicyDecision(kind=REPLY, text=tier0.T0_OUT_PAYMENT,
                              meta={'reason': 'out_payment'})

    # 12b. RETIRADO (É-F5 Fase 2).
    #
    #      El tamiz de identidad interceptaba a todo número sin registro que
    #      pidiera algo personal, ANTES de que el modelo viera el mensaje. Nació
    #      para tapar un fallo real (piloto 2026-07-28: un modelo recolectando
    #      datos en texto plano "agendó" una cita inexistente), pero la cura
    #      correcta de aquello no era preemptar: es que la escritura pase por
    #      una herramienta y la herramienta revalide — que es lo que ya ocurre.
    #
    #      Su coste quedó documentado en la conversación que abrió É-F5: el
    #      cliente escribió "ya he ido, mi nombre es Ana" y el tamiz le
    #      preguntó por ese mismo nombre medio segundo después, porque
    #      `classify_client_triage` solo buscaba lemas de tamiz y nada en el
    #      router extraía un dato.

    # 13. Nada aplicó → el planner decide (lecturas INT-10..14).
    return PolicyDecision(kind=RUN_PLANNER)


def _has_outbound(conversation):
    from apps.channels.models import Message
    return Message.objects.for_organization(conversation.organization).filter(
        conversation=conversation, direction=Message.DIRECTION_OUT,
    ).exists()


def _burst_confirmation(burst):
    """Primer veredicto decisivo de la ráfaga.

    "sí" seguido de "gracias" es una afirmativa, no un agradecimiento: sin
    esto el último mensaje ganaba y la acción confirmada no se ejecutaba.
    'unclear' solo si NINGÚN mensaje de la ráfaga decide.
    """
    for part in burst:
        verdict = matchers.classify_confirmation(part)
        if verdict != 'unclear':
            return verdict
    return 'unclear'


_PAYMENT_LEMMAS = (
    'te puedo pagar por aqui', 'te pago por aqui', 'pagar por whatsapp',
    'transferencia', 'tu clabe', 'numero de tarjeta', 'deposito', 'te deposito',
    'pago en linea', 'link de pago', 'me pasas tu cuenta',
)


def _mentions_payment(text):
    n = matchers.normalize(text)
    return any(lemma in n for lemma in _PAYMENT_LEMMAS)
# ---------------------------------------------------------------------------
# FSM de identidad — RETIRADA (É-F5 Fase 2, ADR p56)
# ---------------------------------------------------------------------------
# Aquí vivían 11 funciones y ~370 líneas que conducían los tres retos de
# identidad decidiendo, etapa por etapa, qué frase le tocaba al cliente:
# start_identity_challenge, _is_interruption, _check_interruption,
# _advance_challenge, _clear_challenge, start_identity_triage,
# _advance_identity_triage, _seed_family_challenge, _inbound_history,
# _advance_family_challenge, _family_fail.
#
# Lo que se conserva vive en otras capas y no se ha tocado:
#   - la BARRERA: `_verification_ok` dentro de `run_tool` (tools.py).
#   - el DICTAMEN: `identity.try_verify_by_*` / `link_family`, que cotean
#     contra la base — el modelo aporta el candidato, el código decide.
#   - el COMPROMISO: qué falta, el `why` de cada factor y dónde iba
#     (`goals.py`), ahora publicado al modelo como estado en vez de consumido
#     por una máquina de estados.
#
# Quien conduce la conversación es el planner. Ver ADR p56 §4 (preempción vs.
# contención) y el plan É-F5 §4.1.




# ---------------------------------------------------------------------------
# Transiciones FSM + cierre por inactividad (spec §7.2, §2.8)
# ---------------------------------------------------------------------------

def escalate_to_human(conversation, *, reason_code, priority='normal',
                      detail=''):
    """Crea el HumanHandoff y pasa la conversación a HANDOFF_PENDING.
    Idempotente por conversación: no duplica handoffs abiertos."""
    existing = HumanHandoff.objects.filter(
        conversation=conversation, resolved_at__isnull=True,
    ).first()
    created = existing is None
    if created:
        HumanHandoff.objects.create(
            organization=conversation.organization,
            conversation=conversation,
            reason_code=reason_code,
            reason_detail=detail[:200],
            priority=priority,
        )
    escalated_now = created
    if (not created and priority == HumanHandoff.PRIORITY_URGENT
            and existing.priority != HumanHandoff.PRIORITY_URGENT):
        # La conversación ya estaba en cola por algo menor y ahora aparece una
        # urgencia: sube de prioridad y avisa (antes se quedaba en 'normal').
        existing.priority = HumanHandoff.PRIORITY_URGENT
        existing.reason_code = reason_code
        existing.save(update_fields=['priority', 'reason_code'])
        escalated_now = True
    flow = conversation.flow
    if flow.get('pending_action'):
        # SUSPENDE, no destruye (R4/R5): una urgencia SUPLANTA el
        # pending_action, no lo aborta — se ofrece de vuelta al retomar.
        #
        # Sigue viviendo en `flow` y no en el modelo de compromisos: la
        # confirmación tier-2 queda EXPLÍCITAMENTE fuera del alcance de la
        # Fase 3 (§11 del plan — es lo mejor implementado del sistema y el
        # patrón a imitar). Unificarla es trabajo de otro sprint, con su
        # propia entrada en el ADR.
        flow['suspended'] = {
            'kind': 'pending_action', 'state': flow['pending_action']}
        flow.pop('pending_action', None)
    # El acuse al cliente que insiste se rearma con cada escalada nueva.
    flow.pop('handoff_ack_sent', None)
    conversation.state = Conversation.STATE_HANDOFF_PENDING
    conversation.save(update_fields=['state', 'flow'])

    # La TAREA en curso pasa a manos del humano: queda cerrada como `handoff`,
    # no como abandonada (W2 — importa para el embudo). Incluye la que un reto
    # de identidad hubiera suspendido: si la conversación se va con una
    # persona, la tarea se va con ella.
    #
    # Los compromisos de IDENTIDAD no se tocan aquí: se apartan solos
    # (`park_identity`) para sobrevivir a la escalada — es lo que permite que
    # un dato correcto llegado tarde resuelva la verificación (conv 13).
    from .models import ConversationGoal
    goals.close_task_commitments(
        conversation, ConversationGoal.STATUS_HANDOFF, reason_code)

    # Una urgencia no puede quedarse esperando a que alguien tenga la bandeja
    # abierta (W0-4). El aviso nunca puede tumbar el turno: se traga todo.
    if escalated_now and priority == HumanHandoff.PRIORITY_URGENT:
        from . import alerts
        try:
            alerts.notify_urgent_handoff(
                conversation, reason_code=reason_code, detail=detail)
        except Exception:
            logger.exception("AGENT_URGENT_ALERT_FAILED")


NUDGE_IDLE = timedelta(minutes=60)   # silencio mínimo antes del recordatorio
NUDGE_WINDOW = timedelta(hours=24)   # ventana 24h de WhatsApp (fuera: plantillas F3)
NUDGE_TEXT = "¿Seguimos con tu cita? Aquí sigo para ayudarte 🐾"


def nudge_abandoned_flows(now=None):
    """UX-08: UN solo recordatorio por conversación cuando el cliente dejó a
    medias una propuesta de cita (hay `pending_action` sin responder). Nunca
    tras opt-out, nunca fuera de la ventana de 24 h, jamás dos veces. El worker
    lo corre en su pasada periódica. Devuelve cuántos nudges encoló."""
    from .outbound import enqueue_outbound
    now = now or timezone.now()
    candidates = (
        Conversation.objects.filter(
            state=Conversation.STATE_ACTIVE,
            last_inbound_at__lte=now - NUDGE_IDLE,
            last_inbound_at__gte=now - NUDGE_WINDOW,
        )
        .select_related('contact', 'organization')
    )
    count = 0
    for conversation in candidates:
        flow = conversation.flow or {}
        contact = conversation.contact
        if contact.is_blocked or contact.proactive_opt_out:
            continue
        if flow.get('nudge_sent'):                 # una sola vez por conversación
            continue
        if not flow.get('pending_action'):         # solo un flujo a medias
            continue
        if flow.get('deferred_at'):
            # El cliente dijo «déjame pensarlo» y le respondimos que aquí
            # quedaba pendiente. Insistir a los 60 minutos contradice esa
            # promesa — y no es un caso extremo, es el flujo normal del
            # producto: `T0_DEFER` conserva el `pending_action` a propósito,
            # así que hasta ahora TODO cliente que pedía tiempo recibía el
            # recordatorio igual.
            continue
        agent_settings = _agent_settings(conversation)
        if (agent_settings is None or not agent_settings.enabled
                or not agent_settings.nudge_enabled
                or getattr(conversation.organization, 'is_demo', False)):
            continue
        enqueue_outbound(conversation, NUDGE_TEXT, author='system')
        conversation.flow['nudge_sent'] = True
        conversation.save(update_fields=['flow'])
        count += 1
    return count


def close_inactive_conversations(idle_hours=24, now=None):
    """Cierra conversaciones sin actividad > idle_hours (spec §2.8). Corre en
    la pasada periódica del worker. Devuelve cuántas cerró."""
    from datetime import timedelta
    now = now or timezone.now()
    cutoff = now - timedelta(hours=idle_hours)
    stale = Conversation.objects.filter(
        last_activity_at__lt=cutoff,
    ).exclude(state=Conversation.STATE_CLOSED)
    count = 0
    for conversation in stale:
        conversation.state = Conversation.STATE_CLOSED
        conversation.closed_at = now
        conversation.save(update_fields=['state', 'closed_at'])
        count += 1
    return count
