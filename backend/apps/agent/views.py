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

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.channels.models import Message
from apps.core.permissions import make_permission
from apps.core.sanitize import sanitize_text
from apps.core.views import resolve_public_id

from .models import AgentSettings, Conversation
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
        )
        .order_by('-last_activity_at')
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
        .select_related('human_author')
        .order_by('-created_at', '-id')[:TRANSCRIPT_CAP]
    )[::-1]  # cap por los más recientes, entregados en orden cronológico
    return Response({
        'conversation': ConversationListSerializer(conversation).data,
        'messages': MessageSerializer(messages, many=True).data,
    })


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
    conversation = _get_conversation(request, pk)
    if (
        conversation.claimed_by_id is not None
        and conversation.claimed_by_id != request.user.pk
    ):
        return Response({
            'code': 'already_claimed',
            'message': 'Otra persona ya está atendiendo esta conversación.',
        }, status=409)

    conversation.claimed_by = request.user
    conversation.claimed_at = timezone.now()
    conversation.state = Conversation.STATE_HUMAN_ACTIVE
    conversation.save(update_fields=['claimed_by', 'claimed_at', 'state'])
    return Response(ConversationListSerializer(conversation).data)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.claim')])
def close_conversation(request, pk):
    conversation = _get_conversation(request, pk)
    if conversation.state != Conversation.STATE_CLOSED:
        conversation.state = Conversation.STATE_CLOSED
        conversation.closed_at = timezone.now()
        conversation.save(update_fields=['state', 'closed_at'])
    return Response(ConversationListSerializer(conversation).data)


@api_view(['POST'])
@permission_classes([make_permission('agentinbox.claim')])
def release_conversation(request, pk):
    """Devuelve la conversación al agente/cola (state=active, sin claim)."""
    conversation = _get_conversation(request, pk)
    if conversation.state == Conversation.STATE_CLOSED:
        return Response(
            {'error': 'La conversación está cerrada.'}, status=400,
        )
    conversation.state = Conversation.STATE_ACTIVE
    conversation.claimed_by = None
    conversation.claimed_at = None
    conversation.save(update_fields=['state', 'claimed_by', 'claimed_at'])
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
