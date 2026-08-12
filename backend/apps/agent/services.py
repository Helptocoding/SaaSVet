"""
agent/services.py — Servicios del núcleo conversacional (É-F0).

PR-4: ingesta de mensajes entrantes — normalización telefónica (Q5),
resolución de identidad de contacto (spec §2.3, regla G4) y conversación
abierta. El webhook (`channels.views`) es transporte puro: verifica firma,
parsea y delega aquí. Nada de LLM en F0.

Regla de tenancy: la organización nace del ChannelAccount receptor (R1) y
de ahí NUNCA se re-deriva; todo acceso a modelos tenant-scoped va con
`for_organization()`.
"""
import copy
import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.channels.models import Message
from apps.patients.services import lookup_owner_by_phone

from .models import ContactIdentity, Conversation

logger = logging.getLogger('agent.events')

# Debounce real por ventana silenciosa (É-F3 W1-4).
#
# El delay fijo anterior (+3 s) NO era un debounce: cada mensaje tenía su
# propio vencimiento, así que solo agrupaba ráfagas de copiar-pegar, nunca a
# una persona escribiendo. "Hola" / "quiero una cita" / "para mañana" salían
# como tres turnos y tres respuestas.
#
# Ahora cada entrante EMPUJA el vencimiento de todos los pendientes de su
# conversación: el turno arranca cuando el cliente lleva QUIET_WINDOW callado.
# Sin timers ni jobs — una columna y un UPDATE. MAX_WAIT evita que alguien que
# escribe sin parar se quede sin respuesta.
QUIET_WINDOW = timedelta(seconds=8)
MAX_WAIT = timedelta(seconds=25)
# Alias histórico (el runbook y los tests lo nombran).
INBOUND_AVAILABLE_DELAY = QUIET_WINDOW


def normalize_wa_id(wa_id: str) -> str:
    """Últimos 10 dígitos de un wa_id mexicano (decisión Q5 — México-only;
    el dominio NO migra a E.164).

    Formatos aceptados (tras quedarnos solo con dígitos):
      - ``521`` + 10 dígitos (13) → últimos 10  (móvil MX con '1' histórico)
      - ``52`` + 10 dígitos (12)  → últimos 10
      - 10 dígitos                → tal cual
    Cualquier otro formato → ``''`` (no normalizable: la identidad queda
    ``unknown`` y el alta de cliente por chat se bloquea — escalada E-10).
    """
    digits = ''.join(ch for ch in (wa_id or '') if ch.isdigit())
    if len(digits) == 13 and digits.startswith('521'):
        return digits[-10:]
    if len(digits) == 12 and digits.startswith('52'):
        return digits[-10:]
    if len(digits) == 10:
        return digits
    return ''


def wa_id_to_sendable(wa_id):
    """Convierte el wa_id ENTRANTE al número que Meta acepta para ENVIAR.

    WhatsApp entrega los móviles mexicanos con un '1' legacy tras el código
    de país (``521XXXXXXXXXX``), pero la API de envío rechaza ese formato
    (error 131030 "not in allowed list") — hay que mandar a ``52XXXXXXXXXX``
    (sin el '1'). Meta responde el mapeo: input ``52...`` → wa_id ``521...``.

    México-only (decisión Q5): para 10 dígitos se antepone ``52``; otros
    formatos se devuelven tal cual (defensivo — no reescribir números que
    no reconocemos)."""
    digits = ''.join(ch for ch in (wa_id or '') if ch.isdigit())
    if len(digits) == 13 and digits.startswith('521'):
        return '52' + digits[3:]
    if len(digits) == 10:
        return '52' + digits
    return digits


def resolve_contact_identity(channel_account, wa_id, profile_name=''):
    """``get_or_create`` de la identidad de contacto + match a Owner.

    El match corre SOLO al crear la identidad (spec §2.3):
      0 owners → ``unknown`` · 1 → ``phone_match`` · ≥2 → ``unknown`` +
      ``is_ambiguous`` (el sistema jamás "elige" — D1: Owner.phone no es
      unique por org; las intenciones personales escalan, E-05).

    **La comparación va normalizado ↔ normalizado** (E1 del inventario, INV-C,
    decisión §4.11). Antes comparaba el valor normalizado del ``wa_id`` contra
    ``Owner.phone`` EN CRUDO: un expediente guardado como ``"55 1234 5678"`` y
    otro como ``"5512345678"`` son la misma clave, pero la igualdad cruda solo
    encontraba el segundo — el lector veía **una** coincidencia donde INV-C
    dice **ambigua** y vinculaba el contacto a esa fila. Era una elección
    automática entre duplicados históricos, por una puerta que el inventario de
    escrituras no miraba.

    Que el nivel resultante sea ``phone_match`` (que no autoriza nada por sí
    solo) no lo hacía inocuo: ese vínculo es el punto de partida de la
    promoción a ``confirmed_in_chat``, y arrastraba el expediente equivocado.

    ``display_name`` (perfil de WhatsApp) se refresca en cada mensaje pero
    es dato NO confiable — solo display de bandeja, jamás verificación.
    """
    org = channel_account.organization
    contact = (
        ContactIdentity.objects
        .for_organization(org)
        .filter(channel_type=channel_account.channel_type, external_id=wa_id)
        .first()
    )
    if contact is not None:
        if profile_name and contact.display_name != profile_name[:128]:
            contact.display_name = profile_name[:128]
            contact.save(update_fields=['display_name'])
        _rematch_owner(contact)
        return contact

    phone = normalize_wa_id(wa_id)
    owner = None
    ambiguous = False
    level = ContactIdentity.VERIFICATION_UNKNOWN
    if phone:
        lookup = lookup_owner_by_phone(org, phone)
        if lookup.owner is not None:
            owner = lookup.owner
            level = ContactIdentity.VERIFICATION_PHONE_MATCH
        elif lookup.is_ambiguous:
            # Sin vínculo y sin subir de nivel: el dato se ordena primero.
            ambiguous = True

    contact = ContactIdentity(
        organization=org,
        channel_type=channel_account.channel_type,
        external_id=wa_id,
        phone_normalized=phone,
        owner=owner,
        verification_level=level,
        display_name=(profile_name or '')[:128],
        is_ambiguous=ambiguous,
    )
    try:
        with transaction.atomic():
            contact.save()
        logger.info("AGENT_CONTACT_CREATED", extra={
            "event": "AGENT_CONTACT_CREATED",
            "organization_id": org.pk,
            "contact_id": contact.pk,
            "verification_level": level,
            "ambiguous": ambiguous,
        })
    except (ValidationError, IntegrityError):
        # Carrera entre dos mensajes simultáneos del mismo contacto: gana
        # una fila (unique org+channel+external_id); reusar la ganadora.
        contact = ContactIdentity.objects.for_organization(org).get(
            channel_type=channel_account.channel_type, external_id=wa_id,
        )
    return contact


def _rematch_owner(contact):
    """Reintenta el match teléfono→Owner en contactos aún desconocidos.

    El match original corría SOLO al crear la identidad. Caso cotidiano: el
    cliente escribe antes de estar dado de alta, la clínica lo registra en
    mostrador, y al volver a escribir el sistema seguía diciendo que su número
    no está registrado — empujándolo a un alta duplicada. Solo aplica a
    contactos sin owner y sin verificación: nunca reasigna un vínculo hecho.

    Excepción: `auto_rematch_blocked` (levantado por `reset_contact_identity`)
    apaga este reintento — un reset de soporte/QA no debe deshacerse solo en
    el siguiente mensaje del mismo número. No es la única ruta de auto-enlace
    que respeta el flag — ver también
    `tools.commit_register_new_client_and_pet`.

    E2 del inventario (INV-C, decisión §4.11): resuelve sobre
    `Owner.phone_normalized`, no sobre `Owner.phone` crudo — mismo bypass que
    E1, y éste corre en CADA mensaje de un contacto aún `unknown`.

    Ante ambigüedad: `is_ambiguous=True`, **cero vínculo**, el nivel NO sube y
    `auto_rematch_blocked` **no se toca ni se limpia** — ese flag solo lo limpia
    una de las vías de promoción auditadas, y un lector no es ninguna de ellas.
    Un contacto ambiguo tampoco se «desambigua» solo: esta función vuelve a
    correr en mensajes posteriores y, si el dato quedó ordenado y hay un único
    candidato, entonces sí vincula. Que el conteo cambie es información del
    dominio, no una decisión del lector.
    """
    if contact.owner_id is not None or not contact.phone_normalized:
        return
    if contact.verification_level != ContactIdentity.VERIFICATION_UNKNOWN:
        return
    if contact.auto_rematch_blocked:
        return
    lookup = lookup_owner_by_phone(contact.organization, contact.phone_normalized)
    if lookup.owner is not None:
        contact.owner = lookup.owner
        contact.verification_level = ContactIdentity.VERIFICATION_PHONE_MATCH
        contact.is_ambiguous = False
        contact.save(update_fields=[
            'owner', 'verification_level', 'is_ambiguous'])
        logger.info("AGENT_CONTACT_REMATCHED", extra={
            "event": "AGENT_CONTACT_REMATCHED",
            "organization_id": contact.organization_id,
            "contact_id": contact.pk,
        })
    elif lookup.is_ambiguous and not contact.is_ambiguous:
        contact.is_ambiguous = True
        contact.save(update_fields=['is_ambiguous'])


def get_or_create_open_conversation(contact, channel_account):
    """Conversación no-cerrada más reciente del contacto, o una nueva.

    Spec §2.8: una conversación CLOSED no se reabre — un mensaje posterior
    abre un hilo NUEVO que hereda la ContactIdentity (y su nivel de
    verificación persistido).
    """
    org = channel_account.organization
    conv = (
        Conversation.objects
        .for_organization(org)
        .filter(contact=contact)
        .exclude(state=Conversation.STATE_CLOSED)
        .order_by('-created_at')
        .first()
    )
    if conv is None:
        conv = Conversation(
            organization=org,
            channel_account=channel_account,
            contact=contact,
        )
        conv.save()
        logger.info("AGENT_CONVERSATION_OPENED", extra={
            "event": "AGENT_CONVERSATION_OPENED",
            "organization_id": org.pk,
            "conversation_id": conv.pk,
        })
    return conv


def ingest_inbound_message(channel_account, *, wamid, wa_id, body='',
                           payload_type=Message.PAYLOAD_TEXT,
                           profile_name='', raw=None):
    """Persistir un entrante con dedup — el corazón del webhook (PR-4).

    Devuelve el ``Message`` creado, o ``None`` si el wamid ya se vio (R5:
    reintento del proveedor) o si perdimos la carrera contra otro request
    idéntico (el unique parcial de DB decide).

    Contacto bloqueado (GB-10): el mensaje SE persiste (auditable) pero con
    ``status='discarded'`` — el worker no lo procesa y no hay respuesta.
    """
    org = channel_account.organization
    if wamid and Message.objects.for_organization(org).filter(
        channel_account=channel_account,
        direction=Message.DIRECTION_IN,
        external_message_id=wamid,
    ).exists():
        return None

    contact = resolve_contact_identity(channel_account, wa_id, profile_name)
    conversation = get_or_create_open_conversation(contact, channel_account)

    now = timezone.now()
    message = Message(
        organization=org,
        channel_account=channel_account,
        conversation=conversation,
        direction=Message.DIRECTION_IN,
        author_type=Message.AUTHOR_CLIENT,
        payload_type=payload_type,
        body=body or '',
        external_message_id=wamid or None,
        raw_metadata=raw or {},
        status=(
            Message.STATUS_DISCARDED if contact.is_blocked
            else Message.STATUS_PENDING
        ),
        available_at=now + QUIET_WINDOW,
    )
    try:
        with transaction.atomic():
            message.save()
    except (ValidationError, IntegrityError):
        return None  # carrera de reintentos: otro request ya lo insertó

    conversation.last_inbound_at = now
    conversation.last_activity_at = now
    conversation.save(update_fields=['last_inbound_at', 'last_activity_at'])
    if message.status == Message.STATUS_PENDING:
        _extend_quiet_window(conversation, now)
    return message


def _extend_quiet_window(conversation, now):
    """Reinicia la ventana de silencio de TODOS los pendientes del hilo.

    Es el debounce: mientras el cliente siga escribiendo, el turno espera.
    El tope duro (`MAX_WAIT` desde el mensaje más viejo) garantiza respuesta
    aunque no pare de escribir.
    """
    from django.db.models import Min
    pending = Message.objects.for_organization(
        conversation.organization,
    ).filter(
        conversation=conversation,
        direction=Message.DIRECTION_IN,
        status=Message.STATUS_PENDING,
    )
    oldest = pending.aggregate(first=Min('created_at'))['first'] or now
    target = min(now + QUIET_WINDOW, oldest + MAX_WAIT)
    if target < now:
        target = now
    pending.update(available_at=target)


# Orden forward-only de los acuses de entrega del proveedor.
_DELIVERY_RANK = {
    Message.STATUS_PENDING: 0,
    Message.STATUS_SENT: 1,
    Message.STATUS_DELIVERED: 2,
    Message.STATUS_READ: 3,
}
_PROVIDER_STATUS_MAP = {
    'sent': Message.STATUS_SENT,
    'delivered': Message.STATUS_DELIVERED,
    'read': Message.STATUS_READ,
}


def record_status_update(channel_account, wamid, provider_status,
                         error_detail=''):
    """Acuse de entrega de un SALIENTE (value.statuses[] del webhook).

    Forward-only: un acuse tardío 'sent' no degrada un 'read' ya aplicado.
    """
    if not wamid:
        return None
    org = channel_account.organization
    message = Message.objects.for_organization(org).filter(
        channel_account=channel_account,
        direction=Message.DIRECTION_OUT,
        external_message_id=wamid,
    ).first()
    if message is None:
        return None

    if provider_status == 'failed':
        message.status = Message.STATUS_FAILED
        message.failure_reason = (error_detail or 'proveedor: failed')[:200]
        message.save(update_fields=['status', 'failure_reason'])
        return message

    new_status = _PROVIDER_STATUS_MAP.get(provider_status)
    if new_status is None:
        return None
    if _DELIVERY_RANK.get(new_status, 0) <= _DELIVERY_RANK.get(message.status, 0):
        return message  # acuse viejo o repetido: no degradar
    message.status = new_status
    message.save(update_fields=['status'])
    return message


# ===========================================================================
# Servicio de release (Item 2, F3 — ADR p57 §2, §3.1, §5.6, §7)
#
# Liberar una conversación es aplicar un VEREDICTO sobre una propuesta que el
# cliente dejó a medias. Tres pasos, y el orden es el punto:
#
#   R1  tx corta: lock de la fila, se captura el TESTIGO y una copia de lo
#       suspendido. Se libera el lock.
#   R2  chequeo de dominio FUERA de toda transacción (una lectura HTTP, con
#       timeout): ¿el humano ya hizo el trabajo?
#   R3  tx corta: se re-lee el testigo y SOLO si coincide en los cinco campos
#       se aplica el veredicto junto con las mutaciones de release, en un
#       commit.
#
# Por qué R2 va fuera del lock: una llamada de red dentro de una transacción
# la mantiene abierta lo que tarde el otro extremo (invariante 7 del módulo).
# Y por qué hace falta el testigo: durante esa ventana el worker puede tomar
# el turno, otra persona puede reclamar la conversación o puede aparecer una
# suspensión nueva. Liberar, quitar el claim y resolver el hand-off **son**
# mutaciones: aplicarlas sobre un mundo que nadie verificó puede resolver el
# caso equivocado y dejar la intención perdida.
#
# Lo que este servicio NO hace, por decisión de producto:
#   · **No añade ningún TTL nuevo ni mensajes automáticos** (§9.4). La pérdida
#     silenciosa a ~24 h por `close_inactive_conversations` es preexistente y
#     sigue tal cual; convertirla en una baja con razón auditable
#     (`conversation_inactive`) es una mejora SEPARADA, fuera de F3.
#   · **No avisa al cliente cuando descarta** (§9.5): si el dominio prueba que
#     el objetivo ya quedó resuelto, se descarta en silencio. Un «ya lo había
#     hecho el equipo» no aporta nada y reabre una conversación cerrada.
#   · **No toca `deferred_at`** (D7): una promesa de esperar hecha al cliente
#     no la revoca un botón de staff.
# ===========================================================================
RELEASE_RESTORE = 'restore'
RELEASE_DISCARD = 'discard'

#: Motivos de `409 release_conflict`, uno por campo del testigo (§5.6).
CONFLICT_SUSPENSION = 'suspension_changed'
CONFLICT_STATE = 'state_changed'
CONFLICT_CLAIM = 'claim_changed'
CONFLICT_TURN = 'turn_in_progress'
CONFLICT_HANDOFF = 'handoff_changed'

#: Estados de cita que prueban que la creación propuesta ya ocurrió.
_LIVE_OR_DONE = ('scheduled', 'confirmed', 'in_progress', 'done')
_ACTIVE = ('scheduled', 'confirmed', 'in_progress')


class ReleaseConflict(Exception):
    """El mundo cambió entre R1 y R3. No se mutó nada."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class TurnInProgress(Exception):
    """Hay un turno del worker en vuelo: no se pisa (409, reintentable)."""


class ConversationClosed(Exception):
    """Una conversación cerrada no se libera."""


def release_conversation(conversation, actor):
    """Libera la conversación aplicando el veredicto sobre lo suspendido.

    Devuelve `{'verdict': 'restore'|'discard'|'none', 'reason': str}`. Lanza
    `TurnInProgress`, `ConversationClosed` o `ReleaseConflict`; ninguna de las
    tres muta nada.

    **Un solo reintento, no un bucle** (§5.6): si en dos vueltas el mundo sigue
    moviéndose, hay alguien más operando y la respuesta correcta es decírselo a
    quien pulsó el botón, no insistir hasta ganar.
    """
    last_reason = None
    for _attempt in (1, 2):
        witness, suspension = _capture_witness(conversation)
        verdict, reason = _domain_verdict(conversation, suspension)
        try:
            return _apply_release(conversation, witness, suspension,
                                  verdict, reason, actor)
        except ReleaseConflict as conflict:
            last_reason = conflict.reason
            logger.info("AGENT_RELEASE_CONFLICT", extra={
                'event': 'AGENT_RELEASE_CONFLICT',
                'organization_id': conversation.organization_id,
                'conversation_id': conversation.pk,
                'reason': conflict.reason,
            })
    raise ReleaseConflict(last_reason)


def _capture_witness(conversation):
    """R1 — bajo lock: valida, captura el testigo y copia lo suspendido."""
    from .models import HumanHandoff

    with transaction.atomic():
        convo = Conversation.objects.select_for_update().get(pk=conversation.pk)
        if convo.state == Conversation.STATE_CLOSED:
            raise ConversationClosed()
        # El worker pudo tomar el turno: no se le pisa a mitad de camino.
        if convo.processing_until and convo.processing_until > timezone.now():
            raise TurnInProgress()

        handoff_id = (
            HumanHandoff.objects.filter(
                conversation=convo, resolved_at__isnull=True,
            ).order_by('-id').values_list('pk', flat=True).first()
        )
        suspension = copy.deepcopy(convo.flow.get('suspended')) or None
        witness = {
            'suspension_id': (suspension or {}).get('suspension_id'),
            'state': convo.state,
            'claimed_by_id': convo.claimed_by_id,
            'processing_until': convo.processing_until,
            'handoff_id': handoff_id,
        }
    return witness, suspension


def _suspension_shape(suspension):
    """¿Se puede confiar en lo guardado? Devuelve `valid` | `legacy` | `invalid`.

    Un `suspended` malformado se consume **sin llamar al dominio y sin
    restaurar** (§7). Restaurarlo «para que el planner lo arregle» solo lo
    descarta DESPUÉS de que el cliente mande una afirmativa, y para entonces ya
    vio una propuesta que nadie va a cumplir.
    """
    from . import tools

    if not isinstance(suspension, dict):
        return 'invalid'
    if suspension.get('kind') != 'pending_action':
        return 'invalid'
    state = suspension.get('state')
    if not isinstance(state, dict) or not isinstance(state.get('args'), dict):
        return 'invalid'
    if not all(state.get(k) for k in ('tool', 'args', 'paraphrase')):
        return 'invalid'
    if state['tool'] not in tools.COMMIT_HANDLERS:
        return 'invalid'

    if not (suspension.get('suspension_id') and suspension.get('suspended_at')):
        # Legacy `{kind, state}` íntegro: se restaura igual. NUNCA se infiere
        # vigencia por la ausencia del sello — el dato es viejo, no inválido.
        return 'legacy'
    try:
        stamped = datetime.fromisoformat(suspension['suspended_at'])
    except (TypeError, ValueError):
        return 'invalid'
    if timezone.is_naive(stamped):
        stamped = stamped.replace(tzinfo=dt_timezone.utc)
    if stamped > timezone.now() + timedelta(minutes=5):
        return 'invalid'   # sello en el futuro: el dato no es de fiar
    return 'valid'


def _domain_verdict(conversation, suspension):
    """R2 — ¿el humano ya hizo el trabajo? Fuera de toda transacción.

    **Solo el match exacto descarta** (§7). Toda ambigüedad, error o timeout
    restaura: descartar de más deja al cliente esperando algo que nadie hará.
    """
    if suspension is None:
        return None, 'no_suspension'

    shape = _suspension_shape(suspension)
    if shape == 'invalid':
        return RELEASE_DISCARD, 'suspension_invalid'

    state = suspension['state']
    tool, args = state['tool'], state['args']

    # El alta NUNCA se descarta automáticamente (§3.1): sus controles son de
    # identidad, y sobre eso no hay lectura de agenda que pruebe nada.
    if tool == 'register_new_client_and_pet':
        return RELEASE_RESTORE, ('legacy' if shape == 'legacy' else 'not_resolved')

    executor = _release_executor(conversation)
    if executor is None:
        return RELEASE_RESTORE, 'no_executor'

    try:
        resolved, reason = _check_resolved(executor, tool, args)
    except Exception:            # noqa: BLE001 — el chequeo jamás tumba el release
        logger.exception("AGENT_RELEASE_DOMAIN_CHECK_FAILED")
        return RELEASE_RESTORE, 'domain_check_failed'
    if resolved is None:
        return RELEASE_DISCARD, reason      # 404: el recurso ya no existe
    if resolved:
        return RELEASE_DISCARD, reason
    return RELEASE_RESTORE, ('legacy' if shape == 'legacy' else reason)


def _release_executor(conversation):
    """`ToolExecutor` del usuario AGENT de la organización de la conversación.

    Nunca `request.user`: la lectura del chequeo debe tener exactamente el
    alcance del agente, no el de quien pulsó el botón en la bandeja.
    """
    from .executor import ToolExecutor
    from .models import AgentSettings

    settings_obj = AgentSettings.objects.filter(
        organization=conversation.organization).first()
    if settings_obj is None or settings_obj.agent_user_id is None:
        return None
    return ToolExecutor(conversation, settings_obj.agent_user)


def _check_resolved(executor, tool, args):
    """Una sola lectura HTTP por `public_id` (§3.1). `None` = 404."""
    if tool == 'create_appointment':
        pet_pid = args.get('pet_public_id')
        if not pet_pid:
            # Staged anterior a F2, sin identificador público: no se consulta
            # por PK (fallaría con ALLOW_LEGACY_ID_LOOKUP=False). Se restaura.
            return False, 'no_pet_public_id'
        status_code, data = executor.call(
            'GET', '/api/appointments/', tool_name='release_check',
            params={'date': args.get('date'), 'pet': pet_pid},
            args_redacted={'date': args.get('date')},
        )
        if status_code >= 400:
            return False, 'domain_check_failed'
        rows = data.get('results') if isinstance(data, dict) else data
        want = (args.get('start_time') or '')[:5]
        for row in rows or []:
            if ((row.get('start_time') or '')[:5] == want
                    and row.get('status') in _LIVE_OR_DONE):
                return True, 'already_created'
        return False, 'not_resolved'

    appt_pid = args.get('appointment_public_id')
    if not appt_pid:
        return False, 'no_appointment_public_id'
    status_code, appt = executor.call(
        'GET', f'/api/appointments/{appt_pid}/', tool_name='release_check',
        args_redacted={},
    )
    if status_code == 404:
        # Restaurar garantizaría un fallo posterior frente al cliente sobre una
        # cita que ya no existe.
        return None, 'unresolvable'
    if status_code >= 400:
        return False, 'domain_check_failed'

    if tool == 'cancel_appointment':
        if appt.get('status') in ('canceled', 'done'):
            return True, 'already_canceled'
        return False, 'not_resolved'

    if tool == 'reschedule_appointment':
        same = (appt.get('date') == args.get('date')
                and (appt.get('start_time') or '')[:5]
                == (args.get('start_time') or '')[:5])
        if same and appt.get('status') in _ACTIVE:
            return True, 'already_rescheduled'
        # Incluido el «tercer horario»: el humano la movió a otra parte. Se
        # restaura para que el cliente se entere, en vez de decidirlo un
        # heurístico a sus espaldas; la precondición de F2 resuelve el resto.
        return False, 'not_resolved'

    return False, 'unknown_tool'


def _apply_release(conversation, witness, suspension, verdict, reason, actor):
    """R3 — compare-and-set: o coincide el testigo entero, o no se muta nada."""
    from . import goals
    from .models import ConversationGoal, HumanHandoff

    with transaction.atomic():
        convo = Conversation.objects.select_for_update().get(pk=conversation.pk)

        current_handoff = (
            HumanHandoff.objects.filter(
                conversation=convo, resolved_at__isnull=True,
            ).order_by('-id').values_list('pk', flat=True).first()
        )
        current = {
            'suspension_id': (convo.flow.get('suspended') or {}).get('suspension_id'),
            'state': convo.state,
            'claimed_by_id': convo.claimed_by_id,
            'processing_until': convo.processing_until,
            'handoff_id': current_handoff,
        }
        for field, conflict in (
            ('suspension_id', CONFLICT_SUSPENSION),
            ('state', CONFLICT_STATE),
            ('claimed_by_id', CONFLICT_CLAIM),
            ('processing_until', CONFLICT_TURN),
            ('handoff_id', CONFLICT_HANDOFF),
        ):
            if current[field] != witness[field]:
                raise ReleaseConflict(conflict)

        flow = convo.flow
        if verdict == RELEASE_RESTORE:
            restored = copy.deepcopy(suspension['state'])
            # Restaurado VENCIDO (D1): el primer «sí» posterior cae SIEMPRE en
            # la rama de TTL vencido y re-parafrasea sin escribir. Ningún «sí»
            # viejo ejecuta nada por su cuenta.
            restored['expires_at'] = (
                timezone.now() - timedelta(seconds=1)).isoformat()
            flow['pending_action'] = restored
            # El nudge se rearma, pero una promesa de esperar hecha al cliente
            # no la revoca un botón de staff (D7).
            if not flow.get('deferred_at'):
                flow.pop('nudge_sent', None)
        flow.pop('suspended', None)

        convo.state = Conversation.STATE_ACTIVE
        convo.claimed_by = None
        convo.claimed_at = None
        convo.save(update_fields=['state', 'claimed_by', 'claimed_at', 'flow'])

        if convo.contact.verification_level in (
            ContactIdentity.VERIFICATION_CONFIRMED,
            ContactIdentity.VERIFICATION_STAFF,
        ):
            parked = ConversationGoal.objects.for_organization(
                convo.organization,
            ).filter(
                conversation=convo, name__in=goals.IDENTITY_GOALS,
                status=ConversationGoal.STATUS_SUSPENDED,
            ).first()
            if parked is not None:
                goals.close(parked, ConversationGoal.STATUS_ABANDONED,
                            'verificado por el equipo')

        # Se resuelve EL hand-off observado en R1, no «el último abierto»:
        # pueden no ser el mismo, y uno ya resuelto por otra persona no
        # autoriza a resolverlo de nuevo.
        if witness['handoff_id'] is not None:
            handoff = HumanHandoff.objects.filter(
                pk=witness['handoff_id'], resolved_at__isnull=True).first()
            if handoff is not None:
                handoff.resolved_at = timezone.now()
                handoff.resolution = HumanHandoff.RESOLUTION_RETURNED_TO_AGENT
                fields = ['resolved_at', 'resolution']
                if handoff.claimed_by_id is None:
                    handoff.claimed_by = actor
                    handoff.claimed_at = timezone.now()
                    fields += ['claimed_by', 'claimed_at']
                handoff.save(update_fields=fields)

    conversation.flow = convo.flow
    conversation.state = convo.state
    conversation.claimed_by_id = None
    conversation.claimed_at = None

    _log_release(convo, verdict, reason, suspension)
    return {'verdict': verdict or 'none', 'reason': reason}


def _log_release(convo, verdict, reason, suspension):
    """Auditoría del release. Sin PII: ids internos, veredicto y motivo."""
    if verdict is None:
        return
    if reason == 'suspension_invalid':
        event = 'AGENT_RELEASE_SUSPENSION_INVALID'
    elif reason == 'unresolvable':
        event = 'AGENT_RELEASE_PENDING_UNRESOLVABLE'
    elif verdict == RELEASE_DISCARD:
        event = 'AGENT_RELEASE_PENDING_DISCARDED'
    else:
        event = 'AGENT_RELEASE_PENDING_RESTORED'
    payload = {
        'event': event,
        'organization_id': convo.organization_id,
        'conversation_id': convo.pk,
        'reason': reason,
        'tool': ((suspension or {}).get('state') or {}).get('tool', ''),
    }
    if reason == 'legacy':
        payload['legacy'] = True
    logger.info(event, extra=payload)
