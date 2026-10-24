"""WA-RETRY-01: requeue a known failure without creating another message.

The B4 sender remains the dispatch authority. Lock order: Conversation -> Message.
Never renew an epoch, erase external evidence, or requeue UNCERTAIN.
"""
import logging

from django.db import transaction
from rest_framework.exceptions import APIException, NotFound

from apps.channels.models import Message
from . import sender
from .models import Conversation

logger = logging.getLogger('agent.events')


class RetryRejected(APIException):
    status_code = 400

    def __init__(self, code, message, **payload):
        self.default_code = code
        self.error_payload = payload
        super().__init__(message, code=code)


def retry_failed_message(*, actor, conversation_id, message_id, idempotency_key=None):
    """D-7: another authorized staff member may retry; original authorship stays.

    Keep the previous claim until B4 replaces it with a fresh token. A stale
    finalizer cannot mutate PENDING, nor a new claim with a different token.
    """
    with transaction.atomic():
        conv = sender._lock_conv(conversation_id, actor.organization_id)
        if conv is None:
            raise NotFound()
        message = (Message.objects.for_organization(actor.organization_id)
                   .select_for_update(of=('self',)).select_related('human_author')
                   .filter(pk=message_id, conversation_id=conv.pk).first())
        if message is None or not sender._scope(message, conv):
            raise NotFound()

        context = dict(event='INBOX_MESSAGE_RETRY', organization_id=actor.organization_id,
                       conversation_id=conv.pk, message_id=message.pk, actor_id=actor.pk,
                       original_author_id=message.human_author_id,
                       original_author_type=message.author_type)

        def reject(code, detail, **payload):
            logger.info('INBOX_MESSAGE_RETRY', extra={**context, 'result': code})
            raise RetryRejected(code, detail, **payload)

        if message.direction != Message.DIRECTION_OUT or message.status != Message.STATUS_FAILED:
            reject('message_not_failed', 'Solo se puede reintentar un envío fallido conocido.')
        if (message.external_message_id or message.provider_accepted_at or message.delivered_at
                or message.read_at or message.uncertain_at):
            reject('external_evidence', 'El envío tiene evidencia externa y requiere revisión.')
        if idempotency_key and idempotency_key != message.idempotency_key:
            reject('idempotency_conflict', 'La clave no corresponde al mensaje original.')
        if conv.state == Conversation.STATE_CLOSED:
            reject('session_closed', 'La sesión está cerrada. Abre la sesión vigente.')
        reason = sender._rejection(message, conv)
        if reason:
            reject('retry_not_authorized', 'El envío ya no está autorizado en esta sesión.')
        now = sender.db_now()
        if conv.last_inbound_at is None or now - conv.last_inbound_at > sender.SESSION_WINDOW:
            reject('window_closed', 'La ventana de WhatsApp está cerrada.', suggestion='call')

        message.status = Message.STATUS_PENDING
        message.attempts = 0
        message.next_attempt_at = now
        message.failure_reason = ''
        message.updated_by = actor
        message.save(update_fields=['status', 'attempts', 'next_attempt_at', 'failure_reason',
                                   'updated_at', 'updated_by'])
        message.conversation = conv
        transaction.on_commit(lambda: logger.info('INBOX_MESSAGE_RETRY',
                              extra={**context, 'result': 'pending'}))
        return message
