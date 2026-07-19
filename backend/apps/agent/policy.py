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
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from . import identity, matchers, tier0
from .models import Conversation, HumanHandoff

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


def evaluate(conversation, text, *, agent_settings=None):
    """Pipeline pre-planner. Devuelve PolicyDecision. `text` = cuerpo del
    mensaje entrante ya persistido (los efectos de dominio no ocurren aquí)."""
    if agent_settings is None:
        agent_settings = _agent_settings(conversation)
    contact = conversation.contact
    flow = conversation.flow

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

    # 3. URGENCIA (prioridad 1, R16) — antes que todo, incluso a mitad de
    #    flujo; descarta cualquier pending_action.
    if matchers.is_emergency(text):
        flow.pop('pending_action', None)
        conversation.save(update_fields=['flow'])
        return PolicyDecision(
            kind=ESCALATE,
            text=tier0.render_emergency(agent_settings),
            handoff_reason=HumanHandoff.REASON_EMERGENCY,
            handoff_priority=HumanHandoff.PRIORITY_URGENT,
        )

    # 4. Pide humano.
    if matchers.wants_human(text):
        return PolicyDecision(
            kind=ESCALATE,
            text=tier0.T0_HANDOFF,
            handoff_reason=HumanHandoff.REASON_EXPLICIT,
        )

    # 5. Opt-out → baja + despedida + cierre.
    if matchers.wants_optout(text):
        contact.is_blocked = True  # F0/F1: opt-out cierra y silencia futuros
        contact.save(update_fields=['is_blocked'])
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

    # 7. Confirmación de un pending_action (ACTIVO en F2: las tools de
    #    escritura proponen; la afirmativa ejecuta el commit staged en el
    #    planner — invariante TC-SEC-03). En F1 quedaba dormant (read-only).
    if flow.get('pending_action'):
        verdict = matchers.classify_confirmation(text)
        if verdict == 'defer':
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

    # 8. Reto de identidad en curso (spec §2.3): el mensaje es la respuesta.
    challenge = flow.get('identity_challenge')
    if challenge:
        return _advance_challenge(conversation, contact, text, challenge)

    # 9. Verificación IMPLÍCITA pasiva: si nombra su mascota, sube el nivel
    #    (no cambia la decisión, habilita las tools personales del turno).
    if contact.verification_level == contact.VERIFICATION_PHONE_MATCH:
        identity.try_verify_by_pet_name(contact, text)

    # 10. Presupuesto agotado (R11, E-09).
    if _budget_exhausted(conversation):
        return PolicyDecision(
            kind=ESCALATE, text=tier0.T0_BUDGET,
            handoff_reason=HumanHandoff.REASON_BUDGET,
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

    # 13. Nada aplicó → el planner decide (lecturas INT-10..14).
    return PolicyDecision(kind=RUN_PLANNER)


_PAYMENT_LEMMAS = (
    'te puedo pagar por aqui', 'te pago por aqui', 'pagar por whatsapp',
    'transferencia', 'tu clabe', 'numero de tarjeta', 'deposito', 'te deposito',
    'pago en linea', 'link de pago', 'me pasas tu cuenta',
)


def _mentions_payment(text):
    n = matchers.normalize(text)
    return any(lemma in n for lemma in _PAYMENT_LEMMAS)


# ---------------------------------------------------------------------------
# Reto de identidad explícito (spec §2.3, UX-03)
# ---------------------------------------------------------------------------

def start_identity_challenge(conversation):
    """Inicia el reto (el planner lo llama cuando una tool personal devuelve
    verification_required). Devuelve el texto del reto."""
    conversation.flow['identity_challenge'] = {'stage': 'pet', 'fails': 0}
    conversation.save(update_fields=['flow'])
    return tier0.T0_CHALLENGE_PET


def _advance_challenge(conversation, contact, text, challenge):
    stage = challenge.get('stage', 'pet')
    fails = challenge.get('fails', 0)

    if stage == 'pet':
        if identity.try_verify_by_pet_answer(contact, text):
            return _clear_challenge(conversation, verified=True)
        # 1er no-match: repetición SIN contar como fallo (UX-03).
        if not challenge.get('retried'):
            challenge['retried'] = True
            conversation.save(update_fields=['flow'])
            return PolicyDecision(kind=REPLY, text=tier0.T0_CHALLENGE_RETRY,
                                  meta={'challenge': 'retry'})
        # 2º intento fallido de mascota → 2º factor (titular).
        challenge['stage'] = 'owner'
        conversation.save(update_fields=['flow'])
        return PolicyDecision(kind=REPLY, text=tier0.T0_CHALLENGE_OWNER,
                              meta={'challenge': 'owner'})

    if stage == 'owner':
        if identity.try_verify_by_owner_name(contact, text):
            return _clear_challenge(conversation, verified=True)
        fails += 1
        challenge['fails'] = fails
        conversation.save(update_fields=['flow'])
        # 2 fallos REALES → E-06 (sin revelar por qué falló).
        conversation.flow.pop('identity_challenge', None)
        conversation.save(update_fields=['flow'])
        return PolicyDecision(
            kind=ESCALATE, text=tier0.T0_CHALLENGE_FAILED,
            handoff_reason=HumanHandoff.REASON_IDENTITY,
        )

    return _clear_challenge(conversation, verified=False)


def _clear_challenge(conversation, verified):
    conversation.flow.pop('identity_challenge', None)
    conversation.save(update_fields=['flow'])
    if verified:
        # Verificado: cede al planner para atender la petición original.
        return PolicyDecision(kind=RUN_PLANNER, meta={'verified': True})
    return PolicyDecision(kind=RUN_PLANNER)


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
    if existing is None:
        HumanHandoff.objects.create(
            organization=conversation.organization,
            conversation=conversation,
            reason_code=reason_code,
            reason_detail=detail[:200],
            priority=priority,
        )
    conversation.flow.pop('pending_action', None)
    conversation.state = Conversation.STATE_HANDOFF_PENDING
    conversation.save(update_fields=['state', 'flow'])


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
        if conversation.contact.is_blocked:        # opt-out (GB-10)
            continue
        if flow.get('nudge_sent'):                 # una sola vez por conversación
            continue
        if not flow.get('pending_action'):         # solo un flujo a medias
            continue
        agent_settings = _agent_settings(conversation)
        if (agent_settings is None or not agent_settings.enabled
                or not agent_settings.nudge_enabled
                or getattr(conversation.organization, 'is_demo', False)):
            continue
        enqueue_outbound(conversation, NUDGE_TEXT, author='agent')
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
