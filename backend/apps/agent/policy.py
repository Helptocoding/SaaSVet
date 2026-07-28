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

from . import identity, matchers, tier0
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
    #    flujo; descarta cualquier pending_action.
    if matchers.is_emergency(burst_text):
        flow.pop('pending_action', None)
        conversation.save(update_fields=['flow'])
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

    # 7. Confirmación de un pending_action (ACTIVO en F2: las tools de
    #    escritura proponen; la afirmativa ejecuta el commit staged en el
    #    planner — invariante TC-SEC-03). En F1 quedaba dormant (read-only).
    if flow.get('pending_action'):
        verdict = _burst_confirmation(burst)
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

    # 8b. Reto de vinculación familiar en curso (UX-04, PR-17b): el mensaje es
    #     un factor del reto triple (mascota → 4 dígitos).
    family = flow.get('family_challenge')
    if family:
        return _advance_family_challenge(conversation, contact, text, family)

    # 8c. Tamiz de identidad en curso (UX-05): el mensaje responde "¿nuevo o
    #     ya registrado?", o aporta el nombre del titular. Determinista.
    triage = flow.get('identity_triage')
    if triage:
        return _advance_identity_triage(conversation, contact, burst_text,
                                        triage)

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

    # 12b. Número SIN registro que pide algo PERSONAL (agendar / sus citas /
    #      cancelar): nunca se asume que es nuevo — se pregunta, y si dice que
    #      ya es cliente el reto lo busca en la tabla y lo verifica para seguir
    #      atendiéndolo.
    #
    #      Vive aquí, en el router determinista, y no en el planner: antes esto
    #      solo reaccionaba si el MODELO llamaba una tool personal y ésta
    #      rebotaba con verification_required. Un modelo que se ponía a
    #      recolectar nombre/mascota/fecha en texto plano (piloto 2026-07-28)
    #      nunca disparaba nada — y terminó "agendando" una cita inexistente.
    if (contact.owner_id is None
            and not flow.get('identity_triage_done')
            and matchers.wants_personal_action(burst_text)):
        # Si el propio mensaje ya lo contesta ("soy nuevo, quiero cita"), no se
        # pregunta lo que el cliente acaba de decir (`tasa_repregunta`).
        verdict = matchers.classify_client_triage(burst_text)
        if verdict == 'new':
            flow['identity_triage_done'] = 'new'
            conversation.save(update_fields=['flow'])
            return PolicyDecision(kind=RUN_PLANNER, meta={'triage': 'new'})
        if verdict == 'returning':
            flow['identity_triage'] = {'stage': 'titular', 'asks': 1}
            conversation.save(update_fields=['flow'])
            return PolicyDecision(kind=REPLY, text=tier0.T0_TRIAGE_TITULAR,
                                  meta={'reason': 'identity_triage',
                                        'triage': 'returning'})
        return PolicyDecision(
            kind=REPLY, text=start_identity_triage(conversation),
            meta={'reason': 'identity_triage', 'triage': 'asked',
                  'privacy_notice': True})

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
# Tamiz de identidad (UX-05) — ¿cliente nuevo, o ya registrado?
# ---------------------------------------------------------------------------
# Decisión de producto: el sistema NUNCA asume que un número sin registro es un
# cliente nuevo. Pregunta; y si dice que ya es cliente, lo BUSCA en `Owner` y lo
# verifica con el reto de 3 factores para seguir atendiéndolo él mismo. Decir
# "ya vine antes" no escala a nadie — solo escala una verificación FALLIDA.

def start_identity_triage(conversation):
    """Siembra el tamiz y devuelve la pregunta.

    Público: el planner también lo usa cuando una tool personal rebota con
    `verification_required` sobre un número sin registro.
    """
    conversation.flow['identity_triage'] = {'stage': 'ask', 'asks': 1}
    conversation.save(update_fields=['flow'])
    return tier0.render_triage(
        conversation.organization,
        first_contact=not _has_outbound(conversation),
    )


def _advance_identity_triage(conversation, contact, text, triage):
    flow = conversation.flow
    if triage.get('stage') == 'titular':
        return _seed_family_challenge(conversation, text)

    verdict = matchers.classify_client_triage(text)

    if verdict == 'returning':
        triage['stage'] = 'titular'
        conversation.save(update_fields=['flow'])
        return PolicyDecision(kind=REPLY, text=tier0.T0_TRIAGE_TITULAR,
                              meta={'reason': 'identity_triage',
                                    'triage': 'returning',
                                    'privacy_notice': True})

    if verdict == 'new':
        flow.pop('identity_triage', None)
        flow['identity_triage_done'] = 'new'
        conversation.save(update_fields=['flow'])
        return PolicyDecision(kind=RUN_PLANNER, meta={'triage': 'new'})

    # 'unclear' → una re-pregunta explícita sin costo (patrón del reto UX-03).
    # A la segunda se cede al planner: mejor que dejar al cliente en un bucle.
    if triage.get('asks', 1) < 2:
        triage['asks'] = triage.get('asks', 1) + 1
        conversation.save(update_fields=['flow'])
        return PolicyDecision(kind=REPLY, text=tier0.T0_TRIAGE_RETRY,
                              meta={'reason': 'identity_triage',
                                    'triage': 'retry',
                                    'privacy_notice': True})
    flow.pop('identity_triage', None)
    flow['identity_triage_done'] = 'unclear'
    conversation.save(update_fields=['flow'])
    return PolicyDecision(kind=RUN_PLANNER, meta={'triage': 'unclear'})


def _seed_family_challenge(conversation, titular_name):
    """Dice ser cliente y aporta el nombre del titular: se busca en `Owner` y
    arranca el reto (mascota → últimos 4 dígitos). Es el MISMO estado que
    siembra la tool `link_family_member`, pero sin depender del LLM."""
    titular = (titular_name or '').strip()
    candidates = identity.find_link_candidates(
        conversation.organization, titular)
    flow = conversation.flow
    flow.pop('identity_triage', None)
    flow['identity_triage_done'] = 'returning'

    # Si el cliente YA nombró a la mascota antes en la conversación ("cita para
    # Luna"), ese factor está aportado: volver a pedirlo es la repregunta más
    # torpe posible. No debilita el reto — el dato lo dio él, sin que el
    # sistema enumerara nada (G4), y de hecho antes de saber que se le pediría.
    stage, survivors = 'pet', candidates
    if candidates:
        named = [o for o in candidates
                 if identity.owner_has_pet(o, _inbound_history(conversation))]
        if len(named) == 1:
            stage, survivors = 'digits', named

    # Se siembra AUNQUE no haya candidatos: comportamiento uniforme, sin
    # oráculo de existencia (G4) — falla al final como cualquier dato malo.
    flow['family_challenge'] = {
        'stage': stage,
        'candidate_ids': [o.pk for o in survivors],
        'titular': titular,
        'fails': 0,
    }
    conversation.save(update_fields=['flow'])
    text = tier0.T0_TRIAGE_DIGITS if stage == 'digits' else tier0.T0_TRIAGE_PET
    return PolicyDecision(kind=REPLY, text=text,
                          meta={'reason': 'identity_triage',
                                'triage': f'family_seeded_{stage}',
                                'privacy_notice': True})


def _inbound_history(conversation, limit=12):
    """Texto de los entrantes recientes — para saber qué datos ya aportó el
    cliente por su cuenta y no volver a pedírselos."""
    from apps.channels.models import Message
    bodies = (
        Message.objects.for_organization(conversation.organization)
        .filter(conversation=conversation, direction=Message.DIRECTION_IN)
        .order_by('-created_at', '-id')
        .values_list('body', flat=True)[:limit]
    )
    return '\n'.join(b for b in bodies if b)


# ---------------------------------------------------------------------------
# Reto de vinculación familiar (UX-04, PR-17b) — 3 factores, acceso RESTRINGIDO
# ---------------------------------------------------------------------------

def _advance_family_challenge(conversation, contact, text, family):
    """Avanza el reto triple. mascota (narrow de candidatos) → 4 dígitos (pin a
    uno). 3/3 ok → vínculo secundario. 2 fallos reales → handoff instrumentado.
    El sistema VERIFICA lo aportado; jamás revela qué dato falló (G4/E-06)."""
    from apps.patients.models import Owner
    stage = family.get('stage', 'pet')
    owners = list(
        Owner.objects.for_organization(conversation.organization)
        .filter(pk__in=family.get('candidate_ids', []))
    )

    if stage == 'pet':
        survivors = [o.pk for o in owners if identity.owner_has_pet(o, text)]
        if survivors:
            family['candidate_ids'] = survivors
            family['stage'] = 'digits'
            conversation.save(update_fields=['flow'])
            return PolicyDecision(
                kind=REPLY, meta={'family': 'digits'},
                text="Gracias 🙂 Por último: ¿los últimos 4 dígitos del "
                     "teléfono que el titular tiene registrado con nosotros?")
        return _family_fail(conversation, family, 'failed_other')

    # stage == 'digits'
    matches = [o for o in owners if identity.owner_digits_match(o, text)]
    if len(matches) == 1:
        identity.link_family(contact, matches[0])
        conversation.flow.pop('family_challenge', None)
        conversation.save(update_fields=['flow'])
        _log_family(conversation, 'AGENT_FAMILY_LINK_LINKED', 'linked')
        return PolicyDecision(kind=RUN_PLANNER,
                              meta={'verified': True, 'family_linked': True})
    # 0 → dígitos incorrectos; >1 → homónimos indistinguibles (ambiguo).
    return _family_fail(conversation, family,
                        'failed_digits' if not matches else 'failed_ambiguous')


def _family_fail(conversation, family, reason_detail):
    family['fails'] = family.get('fails', 0) + 1
    if family['fails'] >= 2:
        conversation.flow.pop('family_challenge', None)
        conversation.save(update_fields=['flow'])
        _log_family(conversation, 'AGENT_FAMILY_LINK_FAILED', reason_detail)
        return PolicyDecision(
            kind=ESCALATE,
            text="No pude validar esos datos. Te comunico con el equipo para "
                 "ayudarte con gusto 🙂",
            handoff_reason=HumanHandoff.REASON_IDENTITY,
            meta={'handoff_detail': f'family:{reason_detail}'})
    conversation.save(update_fields=['flow'])
    return PolicyDecision(
        kind=REPLY, meta={'family': 'retry'},
        text="Mmm, ese dato no me coincide. ¿Puedes revisarlo? 🙂")


def _log_family(conversation, event, reason_detail=''):
    logger.info(event, extra={
        'event': event,
        'organization_id': conversation.organization_id,
        'conversation_id': conversation.pk,
        'reason_detail': reason_detail,
    })


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
    conversation.flow.pop('pending_action', None)
    # El acuse al cliente que insiste se rearma con cada escalada nueva.
    conversation.flow.pop('handoff_ack_sent', None)
    conversation.state = Conversation.STATE_HANDOFF_PENDING
    conversation.save(update_fields=['state', 'flow'])

    # El objetivo en curso pasa a manos del humano: queda cerrado como
    # `handoff`, no como abandonado (W2 — importa para el embudo).
    from . import goals
    from .models import ConversationGoal
    goals.close_open_goal(
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
