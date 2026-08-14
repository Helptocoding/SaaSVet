"""
agent/views.py — API de la bandeja `/api/inbox/` (É-F0 PR-6).

Permisos propios `agentinbox.*` (Q13): la bandeja expone transcripts (PII
conversacional) — no cuelga de appointment.*. `claim` cubre también cerrar
y liberar (gestión de estado); `config` (kill switch + horario + FAQ) es
ADMIN vía `*.*`.

Toda query org-scoped con for_organization; conversaciones por public_id
(ADR p18). Views delgadas: el único "estado" que mutan es el conversacional
(Conversation/Message del propio subsistema), nunca dominio.
"""
import logging

from django.db.models import Exists, OuterRef, Prefetch
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.channels.models import Message
from apps.core.permissions import make_permission
from apps.core.sanitize import sanitize_text
from apps.core.views import resolve_public_id
from apps.patients.services import lookup_owner_by_phone

from . import goals
from .models import AgentSettings, ContactIdentity, Conversation, HumanHandoff
from .serializers import (
    AgentSettingsSerializer,
    ConversationListSerializer,
    MessageSerializer,
    SendMessageSerializer,
)

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


@api_view(['GET'])
@permission_classes([make_permission('agentinbox.view')])
def list_conversations(request):
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

    return Response(
        ConversationListSerializer(queryset[:100], many=True).data
    )


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
    conversation = _get_conversation(request, pk)
    org = request.user.organization
    messages = list(
        Message.objects.for_organization(org)
        .filter(conversation=conversation)
        # Un saliente `discarded` nunca se envió (se descartó porque el cliente
        # siguió escribiendo, W1-4): mostrarlo haría que recepción leyera un
        # mensaje que el cliente jamás vio. Queda en DB para auditoría.
        .exclude(direction=Message.DIRECTION_OUT,
                 status=Message.STATUS_DISCARDED)
        .select_related('human_author')
        .order_by('-created_at', '-id')[:TRANSCRIPT_CAP]
    )[::-1]  # cap por los más recientes, entregados en orden cronológico
    return Response({
        'conversation': ConversationListSerializer(conversation).data,
        'messages': MessageSerializer(messages, many=True).data,
        # FLUJO-C: el caso de identidad, si lo hay. `None` en la inmensa
        # mayoría de conversaciones — la bandeja solo lo pinta cuando existe.
        'identity_case': _identity_case_payload(conversation),
        # Por qué llegó este caso a una persona. Los de identidad ya se
        # explican arriba, con sus acciones; esto cubre TODO lo demás, que
        # hasta aquí llegaba a la bandeja sin decir nada.
        'handoff': _handoff_payload(conversation),
    })


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
               .order_by('-id').first())
    if handoff is None:
        return None
    goal = goals.last_task_goal(conversation)
    return {
        'reason': handoff.reason_code,
        'detail': handoff.reason_detail,
        'priority': handoff.priority,
        'opened_at': handoff.created_at,
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
    contact = conversation.contact
    if contact.linked_via != ContactIdentity.LINKED_FAMILY:
        return Response(
            {'error': 'Esta conversación no tiene un vínculo familiar.'},
            status=400,
        )
    contact.owner = None
    contact.linked_via = ''
    contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
    contact.verified_at = None
    contact.save(update_fields=[
        'owner', 'linked_via', 'verification_level', 'verified_at'])
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
        conv.save(update_fields=['state', 'closed_at'])

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
    if conversation.state == Conversation.STATE_CLOSED:
        return Response(
            {'error': 'La conversación está cerrada.'}, status=400,
        )

    serializer = SendMessageSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    body = sanitize_text(serializer.validated_data['body'], max_length=4000)
    if not body:
        return Response({'error': 'Mensaje vacío.'}, status=400)

    org = request.user.organization
    now = timezone.now()
    message = Message(
        organization=org,
        channel_account=conversation.channel_account,
        conversation=conversation,
        direction=Message.DIRECTION_OUT,
        author_type=Message.AUTHOR_HUMAN,
        human_author=request.user,
        body=body,
        status=Message.STATUS_PENDING,
    )
    message.save()

    # Responder ES tomar la conversación: el humano queda a cargo (el
    # worker F0 solo auto-saluda la primera vez; en F1 el planner respeta
    # HUMAN_ACTIVE y calla — spec §7.2).
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

    return Response(MessageSerializer(message).data, status=201)


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

        convo.claimed_by = request.user
        convo.claimed_at = timezone.now()
        convo.state = Conversation.STATE_HUMAN_ACTIVE
        convo.save(update_fields=['claimed_by', 'claimed_at', 'state'])
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
            convo.state = Conversation.STATE_CLOSED
            convo.closed_at = timezone.now()
            convo.save(update_fields=['state', 'closed_at'])
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
