"""B4 Message outbox: short claims, logical admission, external evidence CAS.

Lock order: Conversation -> Message. No network call under either lock.
The admission COMMIT is the logical start: takeover afterwards cannot revoke
the attempt, even in the unavoidable gap between commit and the socket call.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Q
from django.db.models.functions import Now

from apps.channels.delivery import DELIVERY_RANK, apply_evidence
from apps.channels.models import Message
from apps.channels.providers import SendResult, get_provider, valid_provider_id
from .durable import db_now
from .models import Conversation, TurnWork

logger = logging.getLogger('agent.events')
SEND_MAX_ATTEMPTS = 5
SEND_BACKOFF_BASE = timedelta(seconds=30)
SEND_BACKOFF_CAP = timedelta(hours=1)
SEND_LEASE = timedelta(minutes=2)
SESSION_WINDOW = timedelta(hours=24)
MAX_BATCH = 100


def event(name, **fields):
    # IDs are log context, never metric labels. No body, token or wamid.
    data = {'event': 'AGENT_SEND_' + name.upper(), **fields}
    transaction.on_commit(lambda: logger.info(data['event'], extra=data))


@dataclass(frozen=True)
class SendClaim:
    message_id: int
    organization_id: int
    conversation_id: int
    channel_account_id: int
    token: uuid.UUID


def _rows(claim):
    return Message.objects.filter(pk=claim.message_id,
        organization_id=claim.organization_id, conversation_id=claim.conversation_id,
        channel_account_id=claim.channel_account_id, send_token=claim.token,
        direction=Message.DIRECTION_OUT)


def _scope(message, conv):
    return (conv is not None and conv.pk == message.conversation_id
        and conv.organization_id == message.organization_id
        and conv.channel_account_id == message.channel_account_id
        and conv.channel_account.organization_id == message.organization_id
        and conv.contact.organization_id == message.organization_id
        and message.contact_id in (None, conv.contact_id))


def _rejection(message, conv):
    if message.origin_epoch is None:
        return 'legacy_unverified'
    if not _scope(message, conv):
        return 'scope_invalid'
    if message.origin_epoch != conv.ownership_epoch:
        return 'ownership_invalidated'
    if conv.channel_account.status != 'active':
        return 'channel_inactive'
    if message.turn_work_id is not None and not TurnWork.objects.filter(
            pk=message.turn_work_id, organization_id=message.organization_id,
            conversation_id=conv.pk, ownership_epoch=message.origin_epoch,
            ).filter(Q(status=TurnWork.COMPLETED) |
                     Q(status=TurnWork.FAILED, messages__pk=message.pk,
                       messages__semantic_type=Message.SEMANTIC_PROCESSING_FAILURE)).exists():
        return 'turn_work_invalid'
    return ''


def _lock_conv(conv_id, org_id, *, skip_locked=False):
    return (Conversation.objects.select_for_update(of=('self',), skip_locked=skip_locked)
        .select_related('contact', 'channel_account')
        .filter(pk=conv_id, organization_id=org_id).first())


def _discard(message, reason):
    message.status, message.failure_reason = Message.STATUS_DISCARDED, reason
    message.save(update_fields=['status', 'failure_reason'])
    event('discarded', message_id=message.pk, outcome_code=reason)


def claim_message(message_id, *, organization_id, channel_account_id):
    """Claim exactly one eligible row; a locked conversation is skipped."""
    candidate = Message.objects.filter(pk=message_id, organization_id=organization_id,
        channel_account_id=channel_account_id, direction='out', status='pending'
    ).values('conversation_id').first()
    if candidate is None:
        event('claim_conflict')
        return None
    with transaction.atomic():
        conv = _lock_conv(candidate['conversation_id'], organization_id, skip_locked=True)
        if (conv is None and candidate['conversation_id'] is not None
                and Conversation.objects.filter(pk=candidate['conversation_id'],
                                                organization_id=organization_id).exists()):
            event('claim_conflict')
            return None
        message = (Message.objects.select_for_update(skip_locked=True)
            .filter(pk=message_id, organization_id=organization_id,
                    conversation_id=candidate['conversation_id'],
                    channel_account_id=channel_account_id, status='pending', direction='out')
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=Now())).first())
        if message is None:
            event('claim_conflict')
            return None
        reason = _rejection(message, conv)
        if reason:
            _discard(message, reason)
            return None
        now = db_now()
        if (message.external_message_id or message.provider_accepted_at or message.delivered_at
                or message.read_at or message.uncertain_at):
            # Contradictory legacy/admin state is not proof that dispatch is safe.
            message.status = 'uncertain'
            message.uncertain_at = message.uncertain_at or now
            message.failure_reason = 'pending_with_external_evidence'
            message.save(update_fields=['status', 'uncertain_at', 'failure_reason'])
            event('uncertain', message_id=message.pk, outcome_code=message.failure_reason)
            return None
        if conv.last_inbound_at is None or now - conv.last_inbound_at > SESSION_WINDOW:
            message.status = Message.STATUS_FAILED
            message.failure_reason = 'ventana de sesión de 24h cerrada'
            message.save(update_fields=['status', 'failure_reason'])
            event('failed', outcome_code='session_window_closed')
            return None
        if message.attempts >= SEND_MAX_ATTEMPTS:
            message.status, message.failure_reason = 'failed', 'attempts_exhausted'
            message.save(update_fields=['status', 'failure_reason'])
            return None
        message.status = Message.STATUS_SENDING
        message.send_token = uuid.uuid4()
        message.send_started_at = now
        message.send_lease_until = now + SEND_LEASE
        message.send_admitted_at = None
        message.attempts += 1
        message.next_attempt_at = None
        message.failure_reason = ''
        message.save(update_fields=['status', 'send_token', 'send_started_at',
            'send_lease_until', 'send_admitted_at', 'attempts', 'next_attempt_at', 'failure_reason'])
        event('claimed', message_id=message.pk, attempts=message.attempts,
              outbound_pending_age_seconds=max(0, (now - message.created_at).total_seconds()))
        return SendClaim(message.pk, organization_id, conv.pk, channel_account_id, message.send_token)


def admit_dispatch(claim):
    """One-use admission. A second invocation with the same token cannot send."""
    with transaction.atomic():
        conv = _lock_conv(claim.conversation_id, claim.organization_id)
        message = _rows(claim).select_for_update().filter(status='sending',
            send_admitted_at__isnull=True, send_lease_until__gt=Now()).first()
        if message is None:
            event('admission_conflict')
            return None
        reason = _rejection(message, conv)
        if reason:
            _discard(message, reason)
            return None
        now = db_now()
        if conv.last_inbound_at is None or now - conv.last_inbound_at > SESSION_WINDOW:
            message.status, message.failure_reason = 'failed', 'session_window_closed'
            message.save(update_fields=['status', 'failure_reason'])
            return None
        message.send_admitted_at = now
        message.save(update_fields=['send_admitted_at'])
        message.conversation = conv
        message.channel_account = conv.channel_account
        event('admitted', message_id=message.pk,
              dispatch_latency_seconds=(now - message.created_at).total_seconds())
        return message


def finalize_dispatch(claim, result):
    """Record admitted external reality even after epoch change/lease expiry.

This grants no conversational authority: token/scope/admission still required.
No retry if takeover or recovery already invalidated eligibility.
"""
    if not isinstance(result, SendResult):
        result = SendResult('uncertain', code='invalid_transport_result')
    if result.kind == 'accepted' and not valid_provider_id(result.provider_id):
        result = SendResult('uncertain', code='acceptance_id_missing')
    with transaction.atomic():
        conv = _lock_conv(claim.conversation_id, claim.organization_id)
        message = _rows(claim).select_for_update().filter(
            send_admitted_at__isnull=False,
            status__in=('sending', 'uncertain', 'sent', 'delivered', 'read')).first()
        if message is None or not _scope(message, conv):
            event('finalize_conflict')
            return False
        now = db_now()
        if result.kind == 'accepted':
            fields = apply_evidence(message, 'sent', now, provider_id=result.provider_id)
            if fields:
                message.save(update_fields=fields)
                event('accepted', message_id=message.pk,
                    provider_acceptance_latency_seconds=(now - message.send_admitted_at).total_seconds())
            return bool(fields)
        if message.status in DELIVERY_RANK:
            return False  # a webhook already proved acceptance
        if result.kind == 'known_rejected':
            safe_retry = (result.retryable and result.code == 'meta_130429' and message.status == 'sending'
                and message.send_lease_until > now and message.attempts < SEND_MAX_ATTEMPTS
                and not _rejection(message, conv))
            message.status = 'pending' if safe_retry else 'failed'
            message.failure_reason = result.code[:200]
            fields = ['status', 'failure_reason']
            if safe_retry:
                message.next_attempt_at = now + min(
                    SEND_BACKOFF_BASE * (2 ** (message.attempts - 1)), SEND_BACKOFF_CAP)
                fields.append('next_attempt_at')
            message.save(update_fields=fields)
            event('retry_scheduled' if safe_retry else 'failed', message_id=message.pk,
                  outcome_code=result.code)
        else:
            message.status = 'uncertain'
            message.uncertain_at = message.uncertain_at or now
            message.failure_reason = (result.code or 'unclassified_result')[:200]
            fields = ['status', 'uncertain_at', 'failure_reason']
            if valid_provider_id(result.provider_id) and not message.external_message_id:
                message.external_message_id = result.provider_id
                fields.append('external_message_id')
            message.save(update_fields=fields)
            event('uncertain', message_id=message.pk, outcome_code=message.failure_reason)
        return True


def dispatch_claim(claim, provider_factory=get_provider):
    if connection.in_atomic_block:
        raise RuntimeError('Sender HTTP must run outside a database transaction')
    message = admit_dispatch(claim)
    if message is None:
        return False
    from .services import wa_id_to_sendable
    try:
        result = provider_factory(message.channel_account).send_text(
            wa_id_to_sendable(message.conversation.contact.external_id), message.body)
    except Exception as exc:
        # Legacy retryable exceptions (and unknown adapter failures) prove nothing.
        result = SendResult('uncertain', code=f'adapter_{type(exc).__name__}')
    # DB errors propagate. The durable SENDING is recovered as UNCERTAIN,
    # never another HTTP. A process kill/BaseException has the same recovery.
    finalize_dispatch(claim, result)
    return True


def recover_expired(batch=20):
    recovered = 0
    candidates = list(Message.objects.filter(direction='out', status='sending',
        send_lease_until__lte=Now()).values('pk', 'organization_id', 'conversation_id')[:batch])
    for candidate in candidates:
        with transaction.atomic():
            conv = _lock_conv(candidate['conversation_id'], candidate['organization_id'])
            message = Message.objects.select_for_update().filter(pk=candidate['pk'],
                organization_id=candidate['organization_id'],
                conversation_id=candidate['conversation_id'], status='sending',
                send_lease_until__lte=Now()).first()
            if message is None:
                continue
            if not _scope(message, conv):
                event('recovery_scope_rejected', message_id=message.pk)
                continue
            now = db_now()
            message.status, message.uncertain_at = 'uncertain', now
            message.failure_reason = ('lease_expired_after_admission' if message.send_admitted_at
                                      else 'lease_expired_before_admission')
            message.save(update_fields=['status', 'uncertain_at', 'failure_reason'])
            event('expired', message_id=message.pk, outcome_code=message.failure_reason,
                  sending_age_seconds=(now - message.send_started_at).total_seconds())
            recovered += 1
    return recovered


def send_pending_outbound(batch=20, provider_factory=get_provider, now=None):
    """Bounded global polling; all individual claims carry tenant/account scope.

`now` retained for caller compatibility; authority uses the database clock.
"""
    if connection.in_atomic_block:
        raise RuntimeError('Sender must not be called inside a database transaction')
    batch = max(1, min(int(batch), MAX_BATCH))
    recover_expired(batch)
    candidates = list(Message.objects.filter(direction='out', status='pending')
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=Now()))
        .values('pk', 'organization_id', 'channel_account_id')[:batch])
    for candidate in candidates:
        claim = claim_message(candidate['pk'], organization_id=candidate['organization_id'],
                              channel_account_id=candidate['channel_account_id'])
        if claim:
            dispatch_claim(claim, provider_factory)
    return len(candidates)


def observe_outbound():
    """Bounded-cardinality operational snapshot, also exposed by a command."""
    from django.db.models import Count, Min
    now = db_now()
    rows = Message.objects.filter(direction='out').values('status').annotate(
        count=Count('pk'), oldest=Min('created_at'), started=Min('send_started_at'),
        uncertain=Min('uncertain_at'))
    snapshot = {}
    for row in rows:
        status = row['status']
        stamp = (row['uncertain'] if status == 'uncertain' else
                 row['started'] if status == 'sending' else row['oldest'])
        snapshot[status] = {'count': row['count'],
                           'age_seconds': max(0, (now - stamp).total_seconds()) if stamp else None}
    event('snapshot', outbound=snapshot)
    return snapshot


def reemit_uncertain(message_id, *, actor, reason, idempotency_key):
    """Explicit staff decision: new human Message, historical original intact.

    No HTTP here. Existing Inbox idempotency key and ownership rules apply.
    No semantic operation key/TurnWork copied: this is never business authority.
    """
    from apps.users.models import User
    from apps.core.permissions import user_has_permission
    from .durable import invalidate_ownership
    if (not isinstance(reason, str) or not reason.strip() or len(reason) > 200
            or not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 64):
        raise ValueError('Se requieren motivo y clave de idempotencia acotados')
    staff = User.objects.filter(pk=actor.pk, organization_id=actor.organization_id,
        is_active=True, is_service_account=False, role__in=('ADMIN', 'VET', 'ASSISTANT')).first()
    if staff is None:
        raise ValueError('Se requiere un operador activo')
    if not all(user_has_permission(staff, code) for code in ('agentinbox.send', 'agentinbox.claim')):
        raise ValueError('Se requieren permisos de envío y takeover')
    source = Message.objects.filter(pk=message_id, organization_id=staff.organization_id,
        direction='out').values('conversation_id').first()
    if source is None:
        raise ValueError('Mensaje fuera de alcance')
    with transaction.atomic():
        conv = _lock_conv(source['conversation_id'], staff.organization_id)
        original = Message.objects.get(pk=message_id,
            organization_id=staff.organization_id, direction='out')
        if not _scope(original, conv) or conv.state == Conversation.STATE_CLOSED:
            raise ValueError('Conversación no disponible')
        previous = Message.objects.filter(organization_id=staff.organization_id,
            idempotency_key=idempotency_key, direction='out', author_type=Message.AUTHOR_HUMAN).first()
        if previous:
            if previous.supersedes_message_id != original.pk:
                raise ValueError('Clave utilizada para otro mensaje')
            return previous
        if original.status != 'uncertain':
            raise ValueError('Solo se reemite incertidumbre de forma explícita')
        # Conversation serializes B4 status/reemission; preserve B3 lock order.
        invalidate_ownership(conv, reason='manual_reemission')
        conv.state = Conversation.STATE_HUMAN_ACTIVE
        conv.claimed_by, conv.claimed_at = staff, db_now()
        conv.save(update_fields=['state', 'claimed_by', 'claimed_at'])
        new = Message.objects.create(organization_id=staff.organization_id,
            channel_account_id=conv.channel_account_id, conversation=conv, contact_id=conv.contact_id,
            direction='out', author_type=Message.AUTHOR_HUMAN, human_author=staff,
            body=original.body, origin_epoch=conv.ownership_epoch, supersedes_message=original,
            idempotency_key=idempotency_key, raw_metadata={'b4_reemission_reason': reason.strip()})
        event('reemitted', message_id=new.pk, source_message_id=original.pk, actor_id=staff.pk)
        return new
