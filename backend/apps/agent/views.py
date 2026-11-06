"""
agent/views.py — API de la bandeja `/api/inbox/` (É-F0 PR-6).

Permisos propios `agentinbox.*` (Q13): la bandeja expone transcripts (PII
conversacional) — no cuelga de appointment.*. `claim` cubre también cerrar
y liberar (gestión de estado); `config` (kill switch + horario + FAQ) es
solo de ADMIN.

Toda query org-scoped con for_organization; conversaciones por public_id
(ADR p18). Views delgadas: el único "estado" que mutan es el conversacional
(Conversation/Message del propio subsistema), nunca dominio.
"""
import logging
from uuid import UUID

from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, Exists, F, OuterRef, Prefetch, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, Substr
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.channels.models import Message
from apps.core.permissions import make_permission
from apps.core.sanitize import sanitize_text
from apps.core.validators import phone_digits
from apps.core.views import resolve_public_id
from apps.patients.services import lookup_owner_by_phone

from . import goals
from .models import AgentSettings, ContactIdentity, Conversation, HumanHandoff
from .serializers import (
    AgentSettingsSerializer,
    ConversationListSerializer,
    InboxReadSerializer,
    MessageSerializer,
    SendMessageSerializer,
    SessionSerializer,
    ThreadSerializer,
)

from .durable import invalidate_ownership

logger = logging.getLogger('agent.events')

# La bandeja carga como máximo este número de mensajes por transcript (los
# más recientes). Paginación real si alguna conversación lo rebasa (F1+).
TRANSCRIPT_CAP = 200


def _get_conversation(request, pk):
    return resolve_public_id(
        Conversation.objects.for_organization(request.user.organization)
        .select_related('contact', 'contact__owner', 'claimed_by'),
        pk,
    )


def _get_send_idempotency_key(request):
    """Lee X-Idempotency-Key (opcional) y lo normaliza al contrato DB."""
    key = (request.headers.get('X-Idempotency-Key') or '').strip()
    return key[:64] or None


def _replay_outbound_message(organization, idempotency_key):
    """Mensaje saliente original de la org para esta llave, o ``None``."""
    if not idempotency_key:
        return None
    return (
        Message.objects.for_organization(organization)
        .filter(
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_HUMAN,
            idempotency_key=idempotency_key,
        )
        .select_related('human_author', 'conversation', 'reply_to__human_author', 'media')
        .first()
    )


def _closed_send_response(request, conversation):
    """Respuesta estable al intentar escribir sobre una sesión cerrada."""
    current = (
        Conversation.objects.for_organization(request.user.organization)
        .filter(contact_id=conversation.contact_id,
                channel_account_id=conversation.channel_account_id)
        .exclude(state=Conversation.STATE_CLOSED)
        .order_by('-last_activity_at')
        .first()
    )
    return Response(
        {'error': 'Esta conversación está cerrada.',
         'code': 'session_closed',
         'current_conversation': (str(current.public_id) if current else None)},
        status=400,
    )


# RFC 8594. Tres meses y medio, mismo criterio que el `DELETE` de citas
# (ADR p57): tiempo para que un cliente desconocido aparezca en el log antes de
# cortar a 410. La bandeja ya no la llama — el sunset existe para los que no
# conocemos, no para el nuestro.
_CONVERSATIONS_SUNSET_DATE = 'Mon, 30 Nov 2026 23:59:59 GMT'
_deprecation_logger = logging.getLogger('core.deprecation')


@api_view(['GET'])
@permission_classes([make_permission('agentinbox.view')])
def list_conversations(request):
    """DEPRECADO — la bandeja agrupa por persona (`GET /api/inbox/threads/`).

    Devolvía una fila por EPISODIO, que es lo que hacía que un cliente con 19
    conversaciones apareciera 19 veces. El sucesor no es un renombre: agrupa por
    `(contacto, cuenta)` y publica el estado de la sesión vigente junto a la
    actividad del hilo completo.

    Sigue funcionando hasta el Sunset. El log mide si alguien la llama todavía:
    es el gate para cortarla a `410`, no un adorno.
    """
    org = request.user.organization
    queryset = (
        Conversation.objects.for_organization(org)
        .select_related('contact', 'contact__owner', 'claimed_by')
        .prefetch_related(
            Prefetch(
                'messages',
                queryset=Message.objects.order_by('-created_at', '-id')[:1],
                to_attr='latest_messages',
            ),
            # Escalada abierta: la bandeja necesita distinguir una urgencia
            # clínica de una duda de horarios (É-F3 W0-4).
            Prefetch(
                'handoffs',
                queryset=HumanHandoff.objects.for_organization(org)
                .filter(resolved_at__isnull=True)
                .order_by('-created_at')[:1],
                to_attr='open_handoffs',
            ),
        )
        # Las urgentes primero, siempre: una convulsión no puede quedar debajo
        # de una conversación más reciente sobre precios.
        .annotate(_urgent=Exists(
            HumanHandoff.objects.for_organization(org).filter(
                conversation=OuterRef('pk'),
                resolved_at__isnull=True,
                priority=HumanHandoff.PRIORITY_URGENT,
            )
        ))
        .order_by('-_urgent', '-last_activity_at')
    )
    state = request.query_params.get('state')
    if state:
        valid_states = {choice for choice, _ in Conversation.STATE_CHOICES}
        if state not in valid_states:
            return Response({'error': 'Estado inválido'}, status=400)
        queryset = queryset.filter(state=state)
    else:
        # Default de bandeja: lo operable (las cerradas se piden explícito).
        queryset = queryset.exclude(state=Conversation.STATE_CLOSED)

    response = Response(
        ConversationListSerializer(queryset[:100], many=True).data
    )
    return _deprecated_conversations(response, request)


def _deprecated_conversations(response, request):
    """Cabeceras RFC 8594 + log de adopción del listado por conversación."""
    successor = '/api/inbox/threads/'
    response['Deprecation'] = 'true'
    response['Sunset'] = _CONVERSATIONS_SUNSET_DATE
    response['Link'] = f'<{successor}>; rel="successor-version"'
    _deprecation_logger.warning(
        "DEPRECATED_ENDPOINT_HIT",
        extra={
            "event": "DEPRECATED_ENDPOINT_HIT",
            "endpoint": request.path,
            "method": request.method,
            "user_id": getattr(request.user, 'pk', None),
            "org_id": getattr(request.user, 'organization_id', None),
            "successor": f"GET {successor}",
            "sunset": _CONVERSATIONS_SUNSET_DATE,
        },
    )
    return response


@api_view(['GET', 'POST'])
@permission_classes([make_permission('agentinbox.config')])
def whatsapp_token_view(request):
    """Gestiona el access token de WhatsApp de la org (ADMIN, agentinbox.config).

    GET  → estado {configured, last4, channel} — NUNCA devuelve el token.
    POST {token} → cifra y guarda en el/los ChannelAccount(s) de WhatsApp de la
    org. Write-only: el token no se registra en logs ni se devuelve. Permite
    rotar el token temporal de Meta desde la UI sin tocar .env.prod ni reiniciar
    (el provider lee DB-first, con fallback a env)."""
    from apps.channels.models import ChannelAccount
    org = request.user.organization
    channels = (ChannelAccount.objects.for_organization(org)
                .filter(channel_type=ChannelAccount.CHANNEL_WHATSAPP))

    if request.method == 'POST':
        token = (request.data.get('token') or '').strip()
        if not token:
            return Response(
                {'code': 'validation_error',
                 'errors': {'token': ['El token es requerido.']}},
                status=400)
        if not channels.exists():
            return Response(
                {'code': 'not_found',
                 'message': 'La organización no tiene un canal de WhatsApp.'},
                status=404)
        updated = 0
        for channel in channels:
            channel.set_access_token(token)
            channel.save(update_fields=[
                'access_token_encrypted', 'access_token_last4'])
            updated += 1
        logger.info("WHATSAPP_TOKEN_SET", extra={
            "event": "WHATSAPP_TOKEN_SET",
            "organization_id": org.id, "actor_id": request.user.id,
            "channels": updated,
        })

    primary = channels.first()
    return Response({
        'configured': bool(primary and primary.has_db_token),
        'last4': (primary.access_token_last4 if primary else ''),
        'channel': (primary.external_account_id if primary else None),
    })


@api_view(['GET'])
@permission_classes([make_permission('agentinbox.view')])
def metrics_view(request):
    """Métricas de NEGOCIO del piloto F2 (spec §8): GET /api/inbox/metrics/
    ?from=&to= (YYYY-MM-DD, días locales de la org). Default: últimos 30 días.
    Read-only sobre ToolExecution/Conversation/HumanHandoff (nunca analytics)."""
    from datetime import datetime, timedelta

    from .metrics import compute_business_metrics

    org = request.user.organization
    now = timezone.now()

    def _day_bound(value, fallback):
        if not value:
            return fallback
        try:
            day = datetime.strptime(value[:10], '%Y-%m-%d').date()
        except ValueError:
            return fallback
        return timezone.make_aware(datetime.combine(day, datetime.min.time()))

    date_from = _day_bound(request.query_params.get('from'),
                           now - timedelta(days=30))
    # `to` es inclusivo por día → el límite superior es el inicio del día siguiente.
    to_param = request.query_params.get('to')
    if to_param:
        date_to = _day_bound(to_param, now) + timedelta(days=1)
    else:
        date_to = now
    # Cap defensivo del rango (consistente con el contrato de analytics: 365d).
    if (date_to - date_from) > timedelta(days=366):
        date_from = date_to - timedelta(days=366)

    return Response(compute_business_metrics(org, date_from, date_to))


@api_view(['GET'])
@permission_classes([make_permission('agentinbox.view')])
def conversation_messages(request, pk):
    """DEPRECADO — el transcript del HILO (`threads/<c>/<a>/messages/`).

    Devuelve un solo episodio, y la bandeja dejó de pedirlos por separado: leer
    a una persona a trozos era justo el problema.

    Y no solo está sin consumidores: filtra distinto que el sucesor. Excluye los
    salientes `discarded` pero **no los `failed`** —los que el proveedor nunca
    entregó porque la ventana de 24 h estaba cerrada— así que le mostraría a
    recepción mensajes que el cliente jamás recibió. Se deprecó en vez de
    arreglarlo: el sucesor ya filtra bien con `operational_messages`, y mantener dos
    lecturas del mismo transcript que no coinciden es peor que tener una.
    """
    from apps.channels.selectors import operational_messages

    conversation = _get_conversation(request, pk)
    org = request.user.organization
    messages = list(
        operational_messages(
            Message.objects.for_organization(org)
            .filter(conversation=conversation)
        )
        .select_related('human_author', 'conversation', 'reply_to__human_author', 'media')
        .order_by('-created_at', '-id')[:TRANSCRIPT_CAP]
    )[::-1]  # cap por los más recientes, entregados en orden cronológico
    return _deprecated_conversations(Response({
        'conversation': ConversationListSerializer(conversation).data,
        'messages': MessageSerializer(messages, many=True).data,
        # FLUJO-C: el caso de identidad, si lo hay. `None` en la inmensa
        # mayoría de conversaciones — la bandeja solo lo pinta cuando existe.
        'identity_case': _identity_case_payload(conversation),
        # Por qué llegó este caso a una persona. Los de identidad ya se
        # explican arriba, con sus acciones; esto cubre TODO lo demás, que
        # hasta aquí llegaba a la bandeja sin decir nada.
        'handoff': _handoff_payload(conversation),
    }), request)


def _handoff_payload(conversation):
    """Por qué esta conversación está esperando a una persona.

    El dato existía desde siempre (`reason_code` + `reason_detail`) y se
    quedaba en la base: la API publicaba solo el código grueso y la bandeja no
    pintaba ninguno de los dos. El resultado práctico era que recepción veía
    «Esperando» y tenía que leer el transcript entero para deducir qué pasó —
    o preguntarle al cliente algo que el sistema ya sabía.

    `reason_code` clasifica (`low_confidence`); `reason_detail` es el que
    informa (`goal_stalled`). Y ninguno de los dos dice qué quería el cliente,
    así que va también el compromiso en juego con sus datos: lo que ya había
    dado y lo que faltaba. Esa es la diferencia entre «el bot se atascó» y «se
    atascó pidiendo la mascota, ya tenía día y hora».
    """
    handoff = (conversation.handoffs
               .filter(resolved_at__isnull=True)
               .order_by('-priority', '-id').first())
    if handoff is None:
        return None
    goal = goals.last_task_goal(conversation)
    return {
        'reason': handoff.reason_code,
        'detail': handoff.reason_detail,
        'priority': handoff.priority,
        'opened_at': handoff.created_at,
        'state': 'ACKNOWLEDGED' if handoff.acknowledged_at else 'QUEUED',
        'notification_status': handoff.notification_status,
        'acknowledged_at': handoff.acknowledged_at,
        'acknowledged_by': str(handoff.acknowledged_by.public_id) if handoff.acknowledged_by_id else None,
        'safety_signals': handoff.safety_signals,
        'source_turn': handoff.source_turn_id,
        'guidance_status': handoff.guidance_message.status if handoff.guidance_message_id else None,
        'open_cases': [{'id': h.pk, 'reason': h.reason_code, 'priority': h.priority,
                        'opened_at': h.created_at,
                        'state': 'ACKNOWLEDGED' if h.acknowledged_at else 'QUEUED'}
                       for h in conversation.handoffs.filter(resolved_at__isnull=True).order_by('id')],
        'goal': goals.describe(goal) if goal is not None else None,
    }


def _identity_case_payload(conversation):
    """Proyección del caso de identidad abierto para la bandeja (§5.5).

    Muestra **qué pidió el cliente** —proyectado desde el staged, no el `flow`
    crudo— para que el staff no tenga que leer el transcript entero antes de
    decidir. Sin volcar el pendiente completo: lo que se necesita para juzgar,
    nada más.
    """
    from . import services

    handoff = services.open_identity_case(conversation)
    if handoff is None:
        return None

    staged = ((conversation.flow.get('suspended') or {}).get('state') or {})
    args = staged.get('args') or {}
    latest = (
        conversation.identity_verifications.order_by('-id')
        .select_related('actor', 'owner_candidate').first()
    )

    # El candidato solo existe cuando el teléfono resuelve a UN expediente
    # (`owner_exists`). Con `owner_ambiguous` es `None` a propósito: ofrecer uno
    # sería sugerir la elección que INV-C prohíbe, y el caso se resuelve
    # ordenando los expedientes, no eligiendo desde aquí.
    lookup = lookup_owner_by_phone(
        conversation.organization, conversation.contact.phone_normalized)
    candidate = lookup.owner

    return {
        'kind': handoff.reason_detail,          # owner_exists | owner_ambiguous
        'opened_at': handoff.created_at,
        'candidate': {
            'public_id': str(candidate.public_id),
            'name': candidate.name,
        } if candidate is not None else None,
        'requested': {
            'owner_name': args.get('owner_name', ''),
            'pet_name': args.get('pet_name', ''),
            'pet_species': args.get('pet_species', ''),
            'date': args.get('date', ''),
            'start_time': args.get('start_time', ''),
        } if staged.get('tool') == 'register_new_client_and_pet' else None,
        'last_verification': {
            'decision': latest.decision,
            'evidence_kind': latest.evidence_kind,
            'actor': latest.actor.get_full_name() or latest.actor.username,
            'created_at': latest.created_at,
            # Solo cuenta para autorizar si es de ESTE caso (§5.5.3).
            'applies_to_this_case': latest.handoff_id == handoff.pk,
        } if latest is not None else None,
    }


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.claim')])
def unlink_family(request, pk):
    """Revoca un vínculo familiar secundario (PR-17b): el número deja de tener
    acceso a los datos del titular. Solo aplica a vínculos family_challenge —
    nunca desvincula un phone_match/self_register legítimo."""
    from .models import ContactIdentity
    conversation = _get_conversation(request, pk)
    with transaction.atomic():
        locked = list(Conversation.objects.for_organization(request.user.organization)
                      .select_for_update().filter(contact_id=conversation.contact_id).order_by('pk'))
        conversation = next(c for c in locked if c.pk == conversation.pk)
        contact = conversation.contact
        if contact.linked_via != ContactIdentity.LINKED_FAMILY:
            return Response(
                {'error': 'Esta conversación no tiene un vínculo familiar.'},
                status=400,
            )
        for conv in locked:
            invalidate_ownership(conv, reason='identity_unlink')
        contact.owner = None
        contact.linked_via = ''
        contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        contact.verified_at = None
        contact.auto_rematch_blocked = True
        contact.save(update_fields=[
            'owner', 'linked_via', 'verification_level', 'verified_at', 'auto_rematch_blocked'])
        logger.info("AGENT_FAMILY_LINK_REVOKED", extra={
            "event": "AGENT_FAMILY_LINK_REVOKED",
            "organization_id": request.user.organization_id,
            "conversation_id": conversation.pk,
            "actor_id": request.user.id,
        })
        return Response(ConversationListSerializer(conversation).data)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.config')])
def reset_contact_identity(request, pk):
    """Resetea la identidad del contacto a `unknown` y cierra el hilo activo.

    A diferencia de `unlink_family` (solo revoca vínculos `family_challenge`),
    esta acción resetea CUALQUIER vínculo (`phone_match`, `confirmed_in_chat`,
    `self_register`, `staff_verified`) — pensada para soporte/QA cuando un
    número quedó ligado por error, o para reprobar el flujo de identidad
    desde cero con el mismo número real. Levanta `auto_rematch_blocked`, que
    bloquea CUALQUIER auto-enlace posterior por coincidencia de teléfono —
    tanto `services._rematch_owner` (mensaje entrante normal) como
    `tools.commit_register_new_client_and_pet` (alta de cliente nuevo que
    termina reutilizando este mismo Owner); sin la segunda cobertura, el reset
    era deshacible con un simple "quiero registrarme" en el mismo hilo. Solo
    ADMIN (`agentinbox.config`, el mismo permiso del kill switch y el token de
    WhatsApp — acción igual de sensible: desligar una identidad ya verificada
    es la mitad del vector que el diseño original evita).

    **Cómo se deshace, desde F4**: el reset ya no es irreversible salvo por el
    reto triple. `identity.link_staff_verified` —la vía auditada de FLUJO-C
    (ADR p57 §5.5)— limpia `auto_rematch_blocked` y vincula el contacto, pero
    solo después de que una persona con `agentinbox.identity_verify` registre
    una verificación aprobada con evidencia **externa al teléfono**. Es la
    única ruta legítima: sigue sin existir ningún camino automático que
    deshaga un reset."""
    from .models import ContactIdentity
    conversation = _get_conversation(request, pk)
    with transaction.atomic():
        locked = list(Conversation.objects.for_organization(request.user.organization)
                      .select_for_update().filter(contact_id=conversation.contact_id).order_by('pk'))
        conversation = next(c for c in locked if c.pk == conversation.pk)
        for conv in locked:
            invalidate_ownership(conv, reason='identity_reset')
        contact = conversation.contact
        previous_owner_id = contact.owner_id
        contact.owner = None
        contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        contact.verified_at = None
        contact.linked_via = ''
        contact.is_ambiguous = False
        contact.auto_rematch_blocked = True
        contact.save(update_fields=[
            'owner', 'verification_level', 'verified_at', 'linked_via',
            'is_ambiguous', 'auto_rematch_blocked'])

        now = timezone.now()
        open_conversations = Conversation.objects.for_organization(
            request.user.organization
        ).filter(contact=contact).exclude(state=Conversation.STATE_CLOSED)
        for conv in open_conversations:
            conv.state = Conversation.STATE_CLOSED
            conv.closed_at = now
            conv.close_reason = Conversation.CLOSE_IDENTITY_RESET
            conv.save(update_fields=['state', 'closed_at', 'close_reason'])

        logger.info("AGENT_CONTACT_IDENTITY_RESET", extra={
            "event": "AGENT_CONTACT_IDENTITY_RESET",
            "organization_id": request.user.organization_id,
            "contact_id": contact.pk,
            "previous_owner_id": previous_owner_id,
            "actor_id": request.user.id,
        })
        conversation.refresh_from_db()
        return Response(ConversationListSerializer(conversation).data)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.send')])
def send_message(request, pk):
    conversation = _get_conversation(request, pk)

    # La resolución del recurso va primero (RBAC/tenant/404); después, el
    # replay debe ser estable aunque la sesión haya cambiado o se haya cerrado
    # desde el primer POST.
    org = request.user.organization
    idempotency_key = _get_send_idempotency_key(request)
    replay = _replay_outbound_message(org, idempotency_key)
    if replay is not None:
        return Response(MessageSerializer(replay).data, status=201)

    if conversation.state == Conversation.STATE_CLOSED:
        # Escribir sigue apuntando a la SESIÓN, no al hilo (§4): una sesión
        # cerrada no se reabre. Pero con la bandeja agrupada es fácil llegar
        # aquí desde un episodio viejo, así que la respuesta dice **cuál** es la
        # vigente en vez de dejar a recepción adivinando.
        return _closed_send_response(request, conversation)

    serializer = SendMessageSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    body = sanitize_text(serializer.validated_data['body'], max_length=4000)
    if not body:
        return Response({'error': 'Mensaje vacío.'}, status=400)

    now = timezone.now()
    try:
        with transaction.atomic():
            # Serializa send contra close/release/claim y hace indivisible el
            # outbox + takeover: nunca queda un mensaje humano sin dueño por
            # un fallo entre ambas escrituras.
            conversation = (
                Conversation.objects.for_organization(org)
                .select_for_update()
                .get(pk=conversation.pk)
            )
            if conversation.state == Conversation.STATE_CLOSED:
                return _closed_send_response(request, conversation)

            reply_to = None
            if 'reply_to_id' in serializer.validated_data:
                from apps.channels.replies import resolve_reply_target
                try:
                    reply_to = resolve_reply_target(organization_id=org.pk,
                        channel_account_id=conversation.channel_account_id,
                        contact_id=conversation.contact_id,
                        target_id=serializer.validated_data['reply_to_id'], lock=True)
                except ModelValidationError:
                    return Response({'code': 'invalid_reply_target',
                        'message': 'Elige un mensaje de este hilo para responder.'}, status=400)

            if conversation.state != Conversation.STATE_HUMAN_ACTIVE or conversation.claimed_by_id is None:
                invalidate_ownership(conversation, reason='human_reply')
            message = Message(
                origin_epoch=conversation.ownership_epoch,
                organization=org,
                channel_account=conversation.channel_account,
                conversation=conversation,
                contact_id=conversation.contact_id,   # F2
                direction=Message.DIRECTION_OUT,
                author_type=Message.AUTHOR_HUMAN,
                human_author=request.user,
                body=body,
                reply_to=reply_to,
                status=Message.STATUS_PENDING,
                idempotency_key=idempotency_key,
            )
            # full_clean() convierte un duplicado en ValidationError antes del
            # INSERT. Con llave se delega la carrera a la restricción DB para
            # que el perdedor reciba IntegrityError y recupere al ganador.
            message.save(validate=not bool(idempotency_key))

            # Responder ES tomar la conversación: el humano queda a cargo (el
            # worker F0 solo auto-saluda la primera vez; en F1 el planner
            # respeta HUMAN_ACTIVE y calla — spec §7.2).
            update_fields = ['last_activity_at']
            conversation.last_activity_at = now
            if conversation.state != Conversation.STATE_HUMAN_ACTIVE:
                conversation.state = Conversation.STATE_HUMAN_ACTIVE
                update_fields.append('state')
            if conversation.claimed_by_id is None:
                conversation.claimed_by = request.user
                conversation.claimed_at = now
                update_fields += ['claimed_by', 'claimed_at']
            conversation.save(update_fields=update_fields)
    except IntegrityError:
        # Debe ejecutarse FUERA del atomic roto. Solo una fila ganadora con la
        # misma llave convierte el error en replay; cualquier otro fallo de
        # integridad conserva su traceback y no se disfraza.
        replay = _replay_outbound_message(org, idempotency_key)
        if replay is not None:
            return Response(MessageSerializer(replay).data, status=201)
        raise

    # Takeover may have discarded the quoted agent outbound. Read its current
    # status and author in the same SELECT used for the response projection.
    message = (Message.objects.for_organization(org)
        .select_related('human_author', 'conversation', 'reply_to__human_author', 'media').get(pk=message.pk))
    return Response(MessageSerializer(message).data, status=201)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.send')])
def retry_message(request, pk, message_id):
    from .inbox_retry import retry_failed_message
    conversation = _get_conversation(request, pk)
    message = retry_failed_message(actor=request.user, conversation_id=conversation.pk,
                                   message_id=message_id,
                                   idempotency_key=_get_send_idempotency_key(request))
    message = (Message.objects.for_organization(request.user.organization)
        .select_related('human_author', 'conversation', 'reply_to__human_author', 'media').get(pk=message.pk))
    return Response(MessageSerializer(message).data)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.claim')])
def claim_conversation(request, pk):
    """Reclama la conversación. **Serializado sobre la fila** (§5.6).

    Antes era un read-modify-write sin lock: dos personas podían reclamar «a la
    vez» y el release podía pisar un claim legítimo. Es la condición sin la
    cual el testigo del release no significa nada — no se puede comparar contra
    algo que otro camino escribe sin lock.
    """
    from django.db import transaction

    conversation = _get_conversation(request, pk)
    with transaction.atomic():
        convo = Conversation.objects.select_for_update().get(pk=conversation.pk)
        if (
            convo.claimed_by_id is not None
            and convo.claimed_by_id != request.user.pk
        ):
            return Response({
                'code': 'already_claimed',
                'message': 'Otra persona ya está atendiendo esta conversación.',
            }, status=409)

        if convo.claimed_by_id != request.user.pk or convo.state != Conversation.STATE_HUMAN_ACTIVE:
            invalidate_ownership(convo, reason='takeover')
        convo.claimed_by = request.user
        convo.claimed_at = timezone.now()
        convo.state = Conversation.STATE_HUMAN_ACTIVE
        convo.save(update_fields=['claimed_by', 'claimed_at', 'state'])
        from .safety_handoff import acknowledge
        acknowledge(convo, request.user)
    return Response(ConversationListSerializer(convo).data)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.claim')])
def close_conversation(request, pk):
    """Cierra la conversación. Serializado sobre la misma fila que claim/release."""
    from django.db import transaction

    conversation = _get_conversation(request, pk)
    with transaction.atomic():
        convo = Conversation.objects.select_for_update().get(pk=conversation.pk)
        if convo.state != Conversation.STATE_CLOSED:
            invalidate_ownership(convo, reason='staff_close')
            convo.state = Conversation.STATE_CLOSED
            convo.closed_at = timezone.now()
            convo.close_reason = Conversation.CLOSE_STAFF
            convo.save(update_fields=['state', 'closed_at', 'close_reason'])
    return Response(ConversationListSerializer(convo).data)


class AssignConversationInput(serializers.Serializer):
    user_public_id = serializers.UUIDField()

    def validate_user_public_id(self, value):
        if not isinstance(self.initial_data['user_public_id'], str):
            raise serializers.ValidationError('Usa el identificador público UUID.')
        return value


@api_view(['GET'])
@permission_classes([make_permission('agentinbox.claim')])
def assignable_users_view(request):
    from .inbox_assignment import assignable_users

    return Response([
        {'public_id': str(user.public_id), 'name': user.get_full_name().strip() or user.username}
        for user in assignable_users(request.user.organization)
    ])


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.claim')])
def assign_conversation_view(request, pk):
    from .inbox_assignment import assign_conversation

    conversation = _get_conversation(request, pk)
    data = AssignConversationInput(data=request.data)
    data.is_valid(raise_exception=True)
    convo = assign_conversation(conversation, request.user, data.validated_data['user_public_id'])
    return Response(ConversationListSerializer(convo).data)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.claim')])
def release_conversation(request, pk):
    """Devuelve la conversación al agente/cola y decide qué pasa con lo suspendido.

    La lógica vive en `services.release_conversation` (F3, ADR p57 §5.6): R1
    captura el testigo bajo lock, R2 pregunta al dominio fuera de toda
    transacción y R3 aplica el veredicto **solo** si el testigo sigue igual.
    Aquí queda el transporte: traducir sus desenlaces a HTTP.

    Fase 1 (R9 auditoría rigidez, §1.2): resuelve el `HumanHandoff` abierto y,
    si el contacto YA quedó verificado mientras el reto estaba apartado,
    abandona ese compromiso de identidad — re-interrogar a alguien ya validado
    no tiene sentido. Ambas cosas siguen ocurriendo, ahora dentro del commit de
    R3 y sobre el hand-off que R1 observó, no «el último abierto».
    """
    from . import services

    conversation = _get_conversation(request, pk)
    try:
        result = services.release_conversation(conversation, request.user)
    except services.ConversationClosed:
        return Response(
            {'error': 'La conversación está cerrada.'}, status=400,
        )
    except services.TurnInProgress:
        # Hay un turno en vuelo: el staff reintenta en segundos. No se pisa al
        # worker a mitad de una respuesta al cliente.
        return Response({
            'code': 'turn_in_progress',
            'message': 'El asistente está respondiendo justo ahora. '
                       'Vuelve a intentarlo en unos segundos.',
        }, status=409)
    except services.ReleaseConflict as conflict:
        # Dos vueltas y el mundo seguía moviéndose: lo decide una persona con
        # el caso recargado, no un bucle de reintentos.
        return Response({
            'code': 'release_conflict',
            'reason': conflict.reason,
            'message': 'La conversación cambió mientras la liberabas. '
                       'Recárgala y vuelve a decidir.',
        }, status=409)

    data = ConversationListSerializer(conversation).data
    data['release'] = result
    return Response(data)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.identity_verify')])
def verify_contact_identity(request, pk):
    """Paso 3/3' de FLUJO-C — registra el juicio humano. **No vincula nada.**

    Verificar y autorizar son **dos endpoints, no uno con un booleano**: el
    primero registra lo que una persona comprobó; el segundo ejecuta la
    consecuencia. Así queda auditado el juicio aunque nadie llegue a autorizar.

    La evidencia es **externa al teléfono**: el número ya se sabe que coincide
    —es lo que creó el caso—, así que usarlo como prueba sería circular. Por eso
    ninguna opción de `evidence_kind` se basa en él.
    """
    from . import services
    from .models import ContactIdentityVerification

    conversation = _get_conversation(request, pk)

    decision = (request.data.get('decision') or '').strip()
    valid_decisions = dict(ContactIdentityVerification.DECISION_CHOICES)
    if decision not in valid_decisions:
        return Response({
            'code': 'validation_error',
            'errors': {'decision': [
                f"Debe ser uno de: {', '.join(valid_decisions)}."]},
        }, status=400)

    evidence_kind = (request.data.get('evidence_kind') or '').strip()
    valid_kinds = dict(ContactIdentityVerification.EVIDENCE_CHOICES)
    if evidence_kind not in valid_kinds:
        return Response({
            'code': 'validation_error',
            'errors': {'evidence_kind': [
                f"Debe ser uno de: {', '.join(valid_kinds)}."]},
        }, status=400)

    note = sanitize_text(request.data.get('evidence_note') or '', max_length=280)

    try:
        record = services.record_identity_verification(
            conversation,
            owner_public_id=request.data.get('owner_public_id'),
            decision=decision,
            evidence_kind=evidence_kind,
            evidence_note=note,
            actor=request.user,
        )
    except services.IdentityCaseError as exc:
        return Response({'code': exc.code, 'message': exc.message}, status=409)

    return Response({
        'public_id': str(record.public_id),
        'decision': record.decision,
        'evidence_kind': record.evidence_kind,
        'created_at': record.created_at,
    }, status=201)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.identity_verify')])
def authorize_identity_link(request, pk):
    """Paso 4 de FLUJO-C — vincula el contacto al `Owner` verificado.

    Exige una verificación **aprobada del mismo caso y del mismo candidato**
    (frescura acotada por el caso, no por reloj). Todo se deriva del servidor:
    la organización y el contacto salen de la conversación, el candidato se
    resuelve dentro de esa organización y el actor es `request.user` — si algo
    de eso viniera en el body, se ignora.
    """
    from . import services

    conversation = _get_conversation(request, pk)
    try:
        services.authorize_identity_link(
            conversation,
            owner_public_id=request.data.get('owner_public_id'),
            actor=request.user,
        )
    except services.IdentityCaseError as exc:
        return Response({'code': exc.code, 'message': exc.message}, status=409)

    conversation.refresh_from_db()
    return Response(ConversationListSerializer(conversation).data)


@api_view(['GET', 'PATCH'])
@permission_classes([make_permission('agentinbox.config')])
def agent_settings_view(request):
    settings_obj, _ = AgentSettings.objects.get_or_create(
        organization=request.user.organization,
    )
    if request.method == 'GET':
        return Response(AgentSettingsSerializer(settings_obj).data)

    serializer = AgentSettingsSerializer(
        settings_obj, data=request.data, partial=True,
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    logger.info("AGENT_SETTINGS_UPDATED", extra={
        "event": "AGENT_SETTINGS_UPDATED",
        "organization_id": request.user.organization_id,
        "actor_id": request.user.pk,
        "enabled": settings_obj.enabled,
    })
    return Response(serializer.data)


# ---------------------------------------------------------------------------
# Bandeja AGRUPADA por contacto (plan de continuidad, §4)
# ---------------------------------------------------------------------------
# La conversación sigue siendo el episodio; lo que cambia es que recepción ve
# una fila por PERSONA. En producción un contacto acumuló 19 conversaciones y
# la bandeja las pintaba como 19 filas distintas del mismo cliente.
#
# La clave es `(contact, channel_account)`, no solo el contacto: dos números de
# la misma clínica pueden ser dos flujos, y mezclarlos junta conversaciones que
# nadie tuvo juntas.

THREADS_PAGE_SIZE = 100
SESSIONS_PAGE = 20
# Página del transcript del hilo. Sustituye al tope duro de 200 por conversación:
# un hilo de años no se carga entero, se recorre hacia atrás con un cursor.
THREAD_MESSAGES_PAGE = 50


def _thread_row(conversation):
    """Proyecta una cabecera anotada, sin consultas adicionales por hilo."""
    contact = conversation.contact
    archived = conversation.state == Conversation.STATE_CLOSED
    return {
        'contact_public_id': contact.public_id,
        'channel_account_public_id': conversation.channel_account.public_id,
        'contact_display_name': contact.display_name,
        'contact_phone': contact.phone_normalized,
        'contact_verification': contact.verification_level,
        'linked_via': contact.linked_via,
        'owner_name': contact.owner.name if contact.owner_id else None,
        # Archivado: sin sesión vigente y, por tanto, sin acciones. Publicar el
        # `public_id` de una conversación cerrada invitaría a la bandeja a
        # ofrecer «responder» sobre algo que devuelve 400.
        'conversation_public_id': None if archived else conversation.public_id,
        # Entrada privada del serializer: la API publica solo el booleano.
        'processing_until': None if archived else conversation.processing_until,
        'state': None if archived else conversation.state,
        'claimed_by_name': (
            None if archived or conversation.claimed_by_id is None
            else (conversation.claimed_by.get_full_name()
                  or conversation.claimed_by.username)),
        'handoff_priority': conversation._inbox_handoff_priority,
        'handoff_reason': conversation._inbox_handoff_reason,
        'handoff_detail': conversation._inbox_handoff_detail,
        'last_activity_at': conversation._inbox_message_at,
        'last_message_preview': conversation._inbox_preview,
        'last_message_type': conversation._inbox_message_type,
        'last_message_filename': conversation._inbox_message_filename,
        'has_unanswered': conversation._inbox_direction == Message.DIRECTION_IN,
        'session_count': conversation._inbox_session_count,
    }


@api_view(['GET'])
@permission_classes([make_permission('agentinbox.view')])
def list_threads(request):
    """Bandeja agrupada: una fila por `(contacto, cuenta)`.

    `?archived=1` incluye los hilos sin sesión abierta. Por defecto no salen,
    igual que hoy no salen las conversaciones cerradas.
    """
    from apps.channels.selectors import operational_messages

    org = request.user.organization
    include_archived = request.query_params.get('archived') in ('1', 'true')
    try:
        offset = int(request.query_params.get('offset', 0))
        if not 0 <= offset <= 2147483647:
            raise ValueError
    except (TypeError, ValueError):
        return Response({'code': 'invalid_offset',
                         'error': 'El desplazamiento debe ser un entero no negativo.'}, status=400)

    # Normalize effective filters before binding the cursor to this query.
    unanswered = request.query_params.get('unanswered')
    urgent = request.query_params.get('urgent')
    claimed = request.query_params.get('claimed') or None
    if unanswered not in (None, '0', '1', 'false', 'true') or urgent not in (None, '0', '1', 'false', 'true'):
        return Response({'code': 'invalid_filter',
                         'error': 'Los filtros de atención y urgencia deben ser 0 o 1.'}, status=400)
    unanswered = None if unanswered is None else unanswered in ('1', 'true')
    urgent = urgent in ('1', 'true')
    if claimed:
        try:
            claimed = str(request.user.public_id if claimed == 'me' else UUID(claimed))
        except (ValueError, AttributeError):
            return Response({'code': 'invalid_filter',
                             'error': 'El responsable debe ser me o un identificador público válido.'}, status=400)

    query = (request.query_params.get('q') or '').strip()
    if len(query) < 2:
        query = ''

    from .inbox_sync import list_sync, previous_snapshot, scope_for
    sync_scope = scope_for(request, 'threads', {
        'archived': include_archived, 'offset': offset,
        'unanswered': unanswered, 'urgent': urgent, 'claimed': claimed, 'q': query,
    })
    previous = previous_snapshot(request, sync_scope)

    sessions = Conversation.objects.for_organization(org)
    eligible = sessions if include_archived else sessions.exclude(state=Conversation.STATE_CLOSED)
    # PostgreSQL elige solo una sesión por persona/cuenta: primero abierta,
    # luego por actividad. El historial se cuenta en SQL, nunca se materializa.
    head_ids = (eligible.annotate(
        _is_closed=Case(When(state=Conversation.STATE_CLOSED, then=Value(1)), default=Value(0)))
        .order_by('contact_id', 'channel_account_id', '_is_closed', '-last_activity_at', '-pk')
        .distinct('contact_id', 'channel_account_id').values('pk'))
    siblings = sessions.filter(contact_id=OuterRef('contact_id'),
                               channel_account_id=OuterRef('channel_account_id'))
    session_counts = (siblings.order_by().values('contact_id', 'channel_account_id')
                      .annotate(total=Count('pk')).values('total'))
    last_message = (operational_messages(
        Message.objects.for_organization(org).filter(
            contact_id=OuterRef('contact_id'), channel_account_id=OuterRef('channel_account_id')))
        .order_by('-created_at', '-id').annotate(preview=Substr('body', 1, 120),
            media_name=Case(When(media__organization_id=org.pk,
                media__channel_account_id=F('channel_account_id'), then=F('media__filename')), default=Value(None))))
    handoff = (HumanHandoff.objects.for_organization(org)
               .filter(conversation_id=OuterRef('pk'), resolved_at__isnull=True)
               .order_by('-priority', '-id'))

    # Conserva el orden previo: urgencia, actividad del mensaje y, en empate,
    # actividad de cualquier episodio del bucket (no solo la sesión vigente).
    epoch = timezone.make_aware(timezone.datetime(1970, 1, 1))
    conversations = (sessions.filter(pk__in=Subquery(head_ids))
        .select_related('contact', 'contact__owner', 'claimed_by', 'channel_account')
        .annotate(
            _inbox_session_count=Subquery(session_counts[:1]),
            _bucket_activity=Subquery(siblings.order_by('-last_activity_at').values('last_activity_at')[:1]),
            _inbox_message_at=Subquery(last_message.values('created_at')[:1]),
            _inbox_preview=Subquery(last_message.values('preview')[:1]),
            _inbox_message_type=Subquery(last_message.values('payload_type')[:1]),
            _inbox_message_filename=Subquery(last_message.values('media_name')[:1]),
            _inbox_direction=Subquery(last_message.values('direction')[:1]),
            _inbox_handoff_priority=Subquery(handoff.values('priority')[:1]),
            _inbox_handoff_reason=Subquery(handoff.values('reason_code')[:1]),
            _inbox_handoff_detail=Subquery(handoff.values('reason_detail')[:1]),
        ).annotate(
            _sort_urgent=Case(When(_inbox_handoff_priority=HumanHandoff.PRIORITY_URGENT,
                                   then=Value(1)), default=Value(0)),
            _sort_activity=Coalesce('_inbox_message_at', Value(epoch)),
        ).order_by('-_sort_urgent', '-_sort_activity', '-_bucket_activity',
                   'contact_id', 'channel_account_id'))
    # Filter after choosing each head; historical claims/handoffs must not
    # resurrect a closed episode or replace the current one in its bucket.
    if unanswered is True:
        conversations = conversations.filter(_inbox_direction=Message.DIRECTION_IN)
    elif unanswered is False:
        conversations = conversations.filter(_inbox_direction=Message.DIRECTION_OUT)
    if urgent:
        conversations = conversations.exclude(state=Conversation.STATE_CLOSED).filter(
            _inbox_handoff_priority=HumanHandoff.PRIORITY_URGENT)
    if claimed:
        conversations = conversations.exclude(state=Conversation.STATE_CLOSED).filter(
            claimed_by__public_id=claimed, claimed_by__organization_id=org.pk)
    if query:
        from .services import normalize_wa_id

        matches = (Q(contact__display_name__icontains=query)
                   | Q(contact__external_id__icontains=query)
                   | Q(contact__owner__name__icontains=query,
                       contact__owner__organization_id=org.pk))
        # Keep partial phone lookup: full E.164 normalization would reject a
        # fragment. Never add an empty/one-digit icontains that matches everyone.
        digits = phone_digits(query)
        if len(digits) >= 2:
            matches |= (Q(contact__phone_normalized__icontains=normalize_wa_id(digits) or digits)
                        | Q(contact__external_id__icontains=digits))
        conversations = conversations.filter(matches)
    # Una cabecera extra indica si hay otra página, sin COUNT ni historial en memoria.
    page = list(conversations[offset:offset + THREADS_PAGE_SIZE + 1])
    has_more = len(page) > THREADS_PAGE_SIZE
    from .inbox_read import unread_counts, unread_total

    heads = page[:THREADS_PAGE_SIZE]
    counts = unread_counts(request.user, heads)
    rows = [dict(_thread_row(head), unread_count=counts.get(head.pk, 0)) for head in heads]
    payload = {
        'results': ThreadSerializer(rows, many=True).data,
        'unread_total': unread_total(request.user),
        'has_more': has_more,
        'next_offset': offset + THREADS_PAGE_SIZE if has_more else None,
    }
    return Response(list_sync(request, payload, heads, sync_scope, previous))


def _resolve_thread(request, contact_pid, account_pid):
    """`(contact, channel_account)` del hilo, o 404. Siempre org-scoped."""
    from apps.channels.models import ChannelAccount

    org = request.user.organization
    contact = resolve_public_id(
        ContactIdentity.objects.for_organization(org).select_related('owner'),
        contact_pid,
    )
    account = resolve_public_id(
        ChannelAccount.objects.for_organization(org), account_pid,
    )
    return contact, account


@api_view(['GET'])
@permission_classes([make_permission('agentinbox.view')])
def thread_context_view(request, contact_pid, account_pid):
    from .inbox_context import ThreadContextSerializer, thread_context

    contact, account = _resolve_thread(request, contact_pid, account_pid)
    data = thread_context(organization=request.user.organization, contact=contact, account=account)
    return Response(ThreadContextSerializer(data).data)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.view')])
def thread_read(request, contact_pid, account_pid):
    """Marca solo la lectura del caller; no reclama ni modifica el episodio."""
    from .inbox_read import mark_thread_read, unread_counts, unread_total

    contact, account = _resolve_thread(request, contact_pid, account_pid)
    serializer = InboxReadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({'code': 'invalid_read_request', 'errors': serializer.errors}, status=400)
    state = mark_thread_read(
        user=request.user, contact=contact, account=account,
        message_id=serializer.validated_data['last_read_message_id'],
    )
    current = (Conversation.objects.for_organization(request.user.organization)
               .filter(contact=contact, channel_account=account)
               .exclude(state=Conversation.STATE_CLOSED)
               .order_by('-last_activity_at', '-pk').first())
    counts = unread_counts(request.user, [current] if current else [])
    return Response({
        'last_read_message_id': state.last_read_message_id,
        'unread_count': counts.get(current.pk, 0) if current else 0,
        'unread_total': unread_total(request.user),
    })


@api_view(['GET'])
@permission_classes([make_permission('agentinbox.view')])
def thread_sessions(request, contact_pid, account_pid):
    """Los episodios del hilo, del más reciente al más viejo. Paginado."""
    contact, account = _resolve_thread(request, contact_pid, account_pid)
    org = request.user.organization
    try:
        page = max(int(request.query_params.get('page', 1)), 1)
    except (TypeError, ValueError):
        page = 1
    offset = (page - 1) * SESSIONS_PAGE

    queryset = (
        Conversation.objects.for_organization(org)
        .filter(contact=contact, channel_account=account)
        .select_related('claimed_by')
        .order_by('-last_activity_at')
    )
    total = queryset.count()
    sessions = list(queryset[offset:offset + SESSIONS_PAGE])
    return Response({
        'count': total,
        'has_more': offset + len(sessions) < total,
        'results': SessionSerializer(sessions, many=True).data,
    })


@api_view(['GET'])
@permission_classes([make_permission('agentinbox.view')])
def thread_messages(request, contact_pid, account_pid):
    """Historial operacional paginado, reciente o centrado en un mensaje.

    `around` incluye el destino aunque esté oculto por estado, marcado como tal.
    Es lectura para recepción; no cambia la autoridad conversacional del agente.
    """
    from apps.channels.selectors import operational_messages

    contact, account = _resolve_thread(request, contact_pid, account_pid)
    org = request.user.organization

    scoped_messages = Message.objects.for_organization(org).filter(
        contact=contact, channel_account=account,
    ).select_related('human_author', 'conversation', 'reply_to__human_author', 'media')
    queryset = operational_messages(scoped_messages)

    from .inbox_sync import (InvalidSyncCursor, changed_messages, floor_message,
                             from_floor, hydrate_preview, previous_snapshot, scope_for, sign_floor,
                             stamped_messages, transcript_sync)
    queryset = stamped_messages(queryset)
    sync_scope = scope_for(request, 'messages', [str(contact.public_id), str(account.public_id)])
    previous = previous_snapshot(request, sync_scope)
    if previous is not None and ('before' in request.query_params or 'around' in request.query_params):
        raise InvalidSyncCursor()
    if 'floor' in request.query_params and ('before' in request.query_params or 'around' in request.query_params):
        raise InvalidSyncCursor()
    floor = floor_message(scoped_messages, request.query_params.get('floor'), previous, sync_scope)
    changes = None

    around_requested = 'around' in request.query_params
    if around_requested and 'before' in request.query_params:
        return Response({
            'code': 'invalid_cursor',
            'message': 'around y before son mutuamente excluyentes.',
        }, status=400)

    if previous is not None:
        changes = changed_messages(queryset, previous, floor)
        page = changes['page']
        messages = changes['messages']
        next_before = None
    elif around_requested:
        try:
            around = int(request.query_params['around'])
            if not 0 < around <= 9223372036854775807:
                raise ValueError
        except (TypeError, ValueError):
            return Response({
                'code': 'invalid_cursor', 'message': 'Cursor around inválido.',
            }, status=400)
        target = scoped_messages.filter(pk=around).first()
        if target is None:
            return Response({'code': 'not_found'}, status=404)

        # Una fila extra por lado detecta continuidad sin cargar todo el hilo.
        older = list(queryset.filter(
            Q(created_at__lt=target.created_at)
            | Q(created_at=target.created_at, pk__lt=target.pk),
        ).order_by('-created_at', '-id')[:26])
        newer = list(queryset.filter(
            Q(created_at__gt=target.created_at)
            | Q(created_at=target.created_at, pk__gt=target.pk),
        ).order_by('created_at', 'id')[:25])
        has_older, has_newer = len(older) > 25, len(newer) > 24
        page = older[:25][::-1] + [target] + newer[:24]
        messages = MessageSerializer(page, many=True).data
        target_hidden = not queryset.filter(pk=target.pk).exists()
        for message in messages:
            message['is_hidden'] = message['id'] == target.pk and target_hidden
        next_before = page[0].id if has_older else None
    else:
        before = request.query_params.get('before')
        if before:
            try:
                queryset = queryset.filter(id__lt=int(before))
            except (TypeError, ValueError):
                return Response({'error': 'Cursor inválido.'}, status=400)
        recent = from_floor(queryset, floor).order_by('-created_at', '-id')
        page = list(recent if floor else recent[:THREAD_MESSAGES_PAGE])
        messages = MessageSerializer(page[::-1], many=True).data
        next_before = page[-1].id if len(page) == THREAD_MESSAGES_PAGE else None

    # La sesión VIGENTE viaja con el transcript. La bandeja necesita las dos
    # cosas en el mismo sitio —el hilo para leer, la sesión para actuar— y
    # pedirlas por separado sería dos round-trips por cada clic en la lista.
    current = (
        Conversation.objects.for_organization(org)
        .filter(contact=contact, channel_account=account)
        .exclude(state=Conversation.STATE_CLOSED)
        .select_related('contact', 'contact__owner', 'claimed_by')
        .order_by('-last_activity_at')
        .first()
    )
    hydrate_preview(current)
    payload = {
        'contact_public_id': contact.public_id,
        'channel_account_public_id': account.public_id,
        'owner_name': contact.owner.name if contact.owner_id else None,
        'contact_display_name': contact.display_name,
        'contact_verification': contact.verification_level,
        # `null` = hilo archivado: se lee, no se actúa.
        'conversation': (ConversationListSerializer(current).data
                         if current else None),
        'identity_case': (_identity_case_payload(current)
                          if current else None),
        'handoff': _handoff_payload(current) if current else None,
        # Para pedir la página anterior: el id más viejo de ésta.
        'next_before': next_before,
        'messages': messages,
        'reset_range': floor is not None and previous is None,
    }
    from .inbox_read import thread_read_status

    payload.update(thread_read_status(
        request.user, contact, account, current, page if around_requested or changes else page[::-1],
    ))
    if changes is None:
        ordered = page if around_requested else page[::-1]
        payload['sync_floor'] = sign_floor(sync_scope, ordered[0] if ordered else None)
    if around_requested:
        payload.update(has_older=has_older, has_newer=has_newer)
    if around_requested or 'before' in request.query_params:
        return Response(payload)
    return Response(transcript_sync(request, payload, page if changes else page[::-1],
                                    sync_scope, previous, changes))
