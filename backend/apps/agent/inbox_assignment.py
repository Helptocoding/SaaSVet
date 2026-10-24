"""Explicit staff assignment; shares the Conversation lock and ownership fence."""
import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.permissions import user_has_permission_strict
from apps.users.models import User

from .durable import invalidate_ownership
from .models import Conversation

logger = logging.getLogger('agent.events')


def assignable_users(organization):
    # Same DB grants/wildcards as strict RBAC, without a query per employee or
    # the legacy role fallback. The POST independently revalidates the target.
    return User.objects.filter(
        organization=organization, is_active=True, is_service_account=False,
    ).exclude(role='ADMIN_SAAS').filter(
        Q(is_superuser=True) | Q(user_roles__role__permissions__code__in=(
            'agentinbox.send', 'agentinbox.*', '*.*',
        )),
    ).distinct().order_by('first_name', 'last_name', 'username', 'public_id')


def assign_conversation(conversation, actor, user_public_id):
    """Assign only an open, same-tenant conversation; no implied handoff ACK."""
    with transaction.atomic():
        convo = Conversation.objects.select_for_update().get(
            pk=conversation.pk, organization=actor.organization,
        )
        if convo.state == Conversation.STATE_CLOSED:
            raise ValidationError({'code': 'conversation_closed',
                'message': 'La conversación está cerrada.'})
        # The user lock also serializes an assignment with staff deactivation.
        target = User.objects.select_for_update().filter(
            public_id=user_public_id, organization=actor.organization,
        ).first()
        if target is None:
            raise NotFound('No se encontró la persona asignable.')
        if (not target.is_active or target.is_service_account
                or target.role == 'ADMIN_SAAS'
                or not user_has_permission_strict(target, 'agentinbox.send')):
            raise ValidationError({'code': 'invalid_assignee',
                'message': 'Elige una persona activa con permiso para responder.'})
        if convo.claimed_by_id == target.pk and convo.state == Conversation.STATE_HUMAN_ACTIVE:
            return convo

        previous = str(convo.claimed_by.public_id) if convo.claimed_by_id else None
        invalidate_ownership(convo, reason='staff_assignment')
        convo.claimed_by = target
        convo.claimed_at = timezone.now()
        convo.state = Conversation.STATE_HUMAN_ACTIVE
        convo.save(update_fields=['claimed_by', 'claimed_at', 'state'])
        event = {
            'organization_public_id': str(actor.organization.public_id),
            'conversation_public_id': str(convo.public_id),
            'actor_public_id': str(actor.public_id),
            'from_user_public_id': previous,
            'to_user_public_id': str(target.public_id),
            'assigned_at': convo.claimed_at.isoformat(),
        }
        transaction.on_commit(lambda: logger.info('INBOX_CONVERSATION_ASSIGNED', extra=event))
        return convo
