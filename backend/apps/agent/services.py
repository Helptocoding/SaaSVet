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

from .durable import invalidate_ownership, db_now
from .models import TurnWork

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
    verificación persistido). **Eso NO significa empezar de cero**: desde F2 el
    contexto que ve el modelo es el del CONTACTO, no el del episodio
    (`prompts._history_queryset`). La sesión sigue siendo por episodio porque de
    ella cuelgan métricas, presupuesto, claim, hand-off y compromisos.

    **La creación se serializa sobre el contacto** (plan de continuidad, F2): el
    `select_for_update` de una conversación no protege la AUSENCIA de fila, así
    que dos webhooks simultáneos del mismo número podían crear dos sesiones. Se
    bloquea `ContactIdentity`, que siempre existe. Mismo patrón que ya usaba
    `resolve_contact_identity` contra su unique.
    """
    org = channel_account.organization
    with transaction.atomic():
        ContactIdentity.objects.select_for_update().get(pk=contact.pk)
        open_convs = list(
            Conversation.objects
            .for_organization(org)
            .filter(contact=contact, channel_account=channel_account)
            .exclude(state=Conversation.STATE_CLOSED)
            .order_by('-created_at')
        )
        conv = open_convs[0] if open_convs else None
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
    if len(open_convs) > 1:
        # The creation mutex is released before any Conversation lock. Final
        # turn publication locks Conversation before updating ContactIdentity.
        with transaction.atomic():
            current = list(Conversation.objects.select_for_update().filter(
                pk__in=[c.pk for c in open_convs], organization=org
            ).exclude(state=Conversation.STATE_CLOSED).order_by('pk'))
            if current:
                conv = _resolve_duplicate_sessions(current)
        if not current:
            return get_or_create_open_conversation(contact, channel_account)
    return conv


# Qué sesión sobrevive si hay más de una abierta. **No es «la más reciente»**:
# eso podía cerrar una que una persona está atendiendo y dejar viva una `active`
# más nueva, sacándole la conversación de las manos.
_SESSION_PRECEDENCE = {
    Conversation.STATE_HUMAN_ACTIVE: 3,
    Conversation.STATE_HANDOFF_PENDING: 2,
    Conversation.STATE_ACTIVE: 1,
}


def _resolve_duplicate_sessions(open_convs):
    """Deja una sola sesión abierta y cierra el resto. Devuelve la superviviente.

    El estado heredado existe: la carrera que este código cierra pudo crear dos
    filas antes de arreglarse. Se resuelve por PRECEDENCIA y, a igualdad, por
    recencia.
    """
    if len(open_convs) == 1:
        return open_convs[0]

    ranked = sorted(
        open_convs,
        key=lambda c: (_SESSION_PRECEDENCE.get(c.state, 0), c.created_at),
        reverse=True,
    )
    survivor, duplicates = ranked[0], ranked[1:]
    human = [c for c in open_convs
             if c.state in (Conversation.STATE_HUMAN_ACTIVE,
                            Conversation.STATE_HANDOFF_PENDING)]
    if len(human) > 1:
        # Dos personas operando: elegir por reloj no es una decisión de script.
        logger.error("AGENT_DUPLICATE_HUMAN_SESSIONS", extra={
            "event": "AGENT_DUPLICATE_HUMAN_SESSIONS",
            "organization_id": survivor.organization_id,
            "conversations": [c.pk for c in human],
        })
        return survivor

    now = timezone.now()
    for duplicate in sorted(duplicates, key=lambda c: c.pk):
        duplicate = Conversation.objects.select_for_update().get(pk=duplicate.pk)
        invalidate_ownership(duplicate, reason='duplicate_session')
        duplicate.state = Conversation.STATE_CLOSED
        duplicate.closed_at = now
        duplicate.close_reason = Conversation.CLOSE_DUPLICATE
        duplicate.save(update_fields=['state', 'closed_at', 'close_reason'])
        logger.warning("AGENT_DUPLICATE_SESSION_CLOSED", extra={
            "event": "AGENT_DUPLICATE_SESSION_CLOSED",
            "organization_id": duplicate.organization_id,
            "conversation_id": duplicate.pk,
            "survivor_id": survivor.pk,
        })
    return survivor


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
        contact=contact,          # F2 · el mensaje es de la PERSONA, no del hilo
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
        while True:
            with transaction.atomic():
                conversation = Conversation.objects.select_for_update().get(
                    pk=conversation.pk, organization_id=org.pk)
                if conversation.state != Conversation.STATE_CLOSED:
                    message.conversation = conversation
                    message.save()
                    conversation.last_inbound_at = now
                    conversation.last_activity_at = now
                    conversation.save(update_fields=['last_inbound_at', 'last_activity_at'])
                    if message.status == Message.STATUS_PENDING:
                        _extend_quiet_window(conversation, now)
                    break
            # A reset/close won the lock. Resolve a new episode without holding
            # the old Conversation lock while acquiring the creation mutex.
            conversation = get_or_create_open_conversation(contact, channel_account)
    except (ValidationError, IntegrityError):
        return None  # carrera de reintentos: otro request ya lo insertó

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
        status=Message.STATUS_PENDING, turn_work__isnull=True,
    )
    oldest = pending.aggregate(first=Min('created_at'))['first'] or now
    target = min(now + QUIET_WINDOW, oldest + MAX_WAIT)
    if target < now:
        target = now
    pending.update(available_at=target)


# Orden forward-only de los acuses de entrega del proveedor.
def record_status_update(channel_account, wamid, provider_status, error_detail=''):
    """Account/org scoped evidence; delegate all transitions to B4 delivery."""
    from apps.channels.status import record_status
    return record_status(channel_account, wamid, provider_status)


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
        if TurnWork.objects.filter(conversation=convo, status=TurnWork.PROCESSING,
                                   lease_expires_at__gt=db_now()).exists():
            raise TurnInProgress()

        handoff_id = (
            HumanHandoff.objects.for_organization(convo.organization).filter(
                conversation=convo, resolved_at__isnull=True,
            ).order_by('-id').values_list('pk', flat=True).first()
        )
        suspension = copy.deepcopy(convo.flow.get('suspended')) or None
        witness = {
            'suspension_id': (suspension or {}).get('suspension_id'),
            'state': convo.state,
            'claimed_by_id': convo.claimed_by_id,
            'ownership_epoch': convo.ownership_epoch,
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
        if TurnWork.objects.filter(conversation=convo, status=TurnWork.PROCESSING,
                                   lease_expires_at__gt=db_now()).exists():
            raise ReleaseConflict(CONFLICT_TURN)

        current_handoff = (
            HumanHandoff.objects.for_organization(convo.organization).filter(
                conversation=convo, resolved_at__isnull=True,
            ).order_by('-id').values_list('pk', flat=True).first()
        )
        current = {
            'suspension_id': (convo.flow.get('suspended') or {}).get('suspension_id'),
            'state': convo.state,
            'claimed_by_id': convo.claimed_by_id,
            'ownership_epoch': convo.ownership_epoch,
            'handoff_id': current_handoff,
        }
        for field, conflict in (
            ('suspension_id', CONFLICT_SUSPENSION),
            ('state', CONFLICT_STATE),
            ('claimed_by_id', CONFLICT_CLAIM),
            ('ownership_epoch', CONFLICT_TURN),
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

        invalidate_ownership(convo, reason='release')
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
            handoff = HumanHandoff.objects.for_organization(
                convo.organization).filter(
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


# ===========================================================================
# FLUJO-C — verificación humana de identidad (Item 2, F4 — ADR p57 §5.5)
#
# La única ruta por la que un contacto NO verificado puede terminar operando
# sobre un `Owner` existente, y toda ella pasa por una persona.
#
# **Verificar (3) y autorizar (4) son actos distintos y separados**, no un
# endpoint con un booleano: el primero registra un juicio humano, el segundo
# ejecuta una consecuencia. Separarlos es lo que permite auditar el juicio
# aunque nadie llegue a autorizar, y lo que impide que un solo clic haga las
# dos cosas sin dejar constancia de la primera.
#
# **Liberar no autoriza**: si el staff libera sin verificar, el release
# restaura la intención vencida, el cliente reconfirma, el commit vuelve a
# fallar con `owner_exists` y el caso se abre de nuevo. Es lo correcto.
# ===========================================================================
class IdentityCaseError(Exception):
    """Base de los rechazos de FLUJO-C. Cada uno lleva su `code` de contrato."""

    code = 'identity_case_error'
    message = 'No se pudo completar la verificación de identidad.'


class NoOpenIdentityCase(IdentityCaseError):
    code = 'no_identity_case'
    message = 'Esta conversación no tiene un caso de identidad abierto.'


class VerificationRequired(IdentityCaseError):
    code = 'verification_required'
    message = ('Hace falta registrar una verificación aprobada de este mismo '
               'caso y candidato antes de autorizar.')


class OwnerChanged(IdentityCaseError):
    code = 'owner_changed'
    message = 'El cliente candidato ya no existe en esta clínica.'


class AlreadyLinked(IdentityCaseError):
    code = 'already_linked'
    message = 'Este contacto ya quedó vinculado a un cliente.'


#: `reason_detail` de los hand-offs que FLUJO-C sabe resolver.
IDENTITY_CASE_DETAILS = ('owner_exists', 'owner_ambiguous')


def open_identity_case(conversation):
    """El `HumanHandoff` de identidad ABIERTO de esta conversación, o `None`.

    Se resuelve desde la conversación, nunca por un id del body: aceptar un
    hand-off del request permitiría auditar contra un caso ajeno.
    """
    from .models import HumanHandoff

    return (
        HumanHandoff.objects.for_organization(conversation.organization).filter(
            conversation=conversation,
            resolved_at__isnull=True,
            reason_code=HumanHandoff.REASON_IDENTITY,
            reason_detail__in=IDENTITY_CASE_DETAILS,
        ).order_by('-id').first()
    )


def resolve_owner_candidate(conversation, owner_public_id):
    """El `Owner` candidato, resuelto SOLO dentro de la org de la conversación.

    Nunca desde un id del request sin re-scopear, y nunca por PK entero: el
    identificador público es el único que viaja del cliente al servidor (ADR
    p18). Fuera de la organización, no existe.
    """
    from apps.patients.models import Owner

    if not owner_public_id:
        return None
    try:
        return Owner.objects.for_organization(
            conversation.organization).filter(
                public_id=owner_public_id, is_generic=False).first()
    except (ValidationError, ValueError, TypeError):
        return None      # UUID mal formado: no existe, y no se filtra el motivo


def record_identity_verification(conversation, *, owner_public_id, decision,
                                 evidence_kind, evidence_note, actor):
    """Paso 3/3' — registra el juicio humano. **NO vincula nada.**

    Verificar no autoriza: este registro no toca `ContactIdentity`, no toca el
    `Owner` y no resuelve el caso. Solo deja constancia, append-only, de que
    una persona identificada afirmó haber comprobado algo.

    El sistema **no juzga la evidencia**. `evidence_kind` es una etiqueta de
    auditoría; ninguna de sus opciones se basa en el teléfono, porque el
    teléfono ya se sabe que coincide —es lo que creó el caso— y usarlo como
    prueba sería circular.

    Un rechazo posterior invalida una aprobación previa del mismo
    `(contact, owner_candidate)`: la autorización lee siempre **el último**.
    """
    from .models import ContactIdentityVerification

    handoff = open_identity_case(conversation)
    if handoff is None:
        raise NoOpenIdentityCase()
    owner = resolve_owner_candidate(conversation, owner_public_id)
    if owner is None:
        raise OwnerChanged()

    record = ContactIdentityVerification(
        organization=conversation.organization,
        contact=conversation.contact,
        owner_candidate=owner,
        conversation=conversation,
        handoff=handoff,
        decision=decision,
        evidence_kind=evidence_kind,
        evidence_note=evidence_note,
        actor=actor,
    )
    record.save()      # OrganizationalModel.save() → full_clean() → clean()
    logger.info("AGENT_IDENTITY_VERIFICATION_RECORDED", extra={
        'event': 'AGENT_IDENTITY_VERIFICATION_RECORDED',
        'organization_id': conversation.organization_id,
        'conversation_id': conversation.pk,
        'handoff_id': handoff.pk,
        'decision': decision,
        'evidence_kind': evidence_kind,   # la NOTA no se loguea (PII)
    })
    return record


def authorize_identity_link(conversation, *, owner_public_id, actor):
    """Paso 4 — vincula el contacto al `Owner`. Exige verificación vigente.

    Las cuatro precondiciones se comprueban en el MISMO `atomic()`, con
    `select_for_update()` sobre `ContactIdentity` **y** sobre el `HumanHandoff`
    (§5.5.2). Comprobarlas fuera sería un TOCTOU: dos personas autorizando a la
    vez, o un rechazo que entra entre la lectura y la escritura.

    1. Hay un caso de identidad **abierto** en esta conversación.
    2. El **último** registro de `(contact, owner_candidate)` es `approved`, y
       es de ESTE hand-off y de ESTA conversación. Frescura acotada por el
       caso, no por reloj: evita inventar un TTL arbitrario y evita que una
       aprobación de hace tres meses habilite una acción de hoy.
    3. El candidato sigue existiendo en la organización.
    4. El contacto no está ya vinculado.

    Resolver el caso es parte del mismo commit: autorizar cierra el trabajo.
    """
    from . import identity
    from .models import ContactIdentity, ContactIdentityVerification, HumanHandoff

    with transaction.atomic():
        contact = (ContactIdentity.objects.select_for_update()
                   .get(pk=conversation.contact_id))

        case = open_identity_case(conversation)
        if case is None:
            raise NoOpenIdentityCase()
        handoff = (HumanHandoff.objects.select_for_update()
                   .filter(pk=case.pk, resolved_at__isnull=True).first())
        if handoff is None:
            raise NoOpenIdentityCase()

        owner = resolve_owner_candidate(conversation, owner_public_id)
        if owner is None:
            raise OwnerChanged()

        if contact.owner_id is not None:
            raise AlreadyLinked()

        latest = (
            ContactIdentityVerification.objects
            .for_organization(conversation.organization)
            .filter(contact=contact, owner_candidate=owner)
            .order_by('-id').first()
        )
        if (latest is None
                or latest.decision != ContactIdentityVerification.DECISION_APPROVED
                or latest.handoff_id != handoff.pk
                or latest.conversation_id != conversation.pk):
            raise VerificationRequired()

        identity.link_staff_verified(contact, owner)

        handoff.resolved_at = timezone.now()
        handoff.resolution = HumanHandoff.RESOLUTION_HANDLED
        fields = ['resolved_at', 'resolution']
        if handoff.claimed_by_id is None:
            handoff.claimed_by = actor
            handoff.claimed_at = timezone.now()
            fields += ['claimed_by', 'claimed_at']
        handoff.save(update_fields=fields)

    logger.info("AGENT_IDENTITY_LINK_AUTHORIZED", extra={
        'event': 'AGENT_IDENTITY_LINK_AUTHORIZED',
        'organization_id': conversation.organization_id,
        'conversation_id': conversation.pk,
        'handoff_id': handoff.pk,
        'owner_public_id': str(owner.public_id),
    })
    return contact


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
