"""Durable media GET/upload jobs: short scoped locks, bounded external I/O."""
from dataclasses import dataclass
from datetime import timedelta
import logging
from uuid import uuid4

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.db.models.functions import Least, Now

from .media_storage import media_upload_path
from .media_clock import media_now
from .media_incidents import audit_purge_deadlines, dispatch_purge_alerts, incident_counts, observe_purge
from .media_revocations import revocation_record
from .media_transfer import MediaDownloadError, downloaded_media, scavenge_media_spools
from .models import MessageMedia

logger = logging.getLogger('agent.events')
MAX_ATTEMPTS = 5
LEASE = timedelta(seconds=180)
RETENTION = timedelta(days=180)


@dataclass(frozen=True)
class MediaClaim:
    pk: int
    organization_id: int
    token: object


def _event(name, media, code=''):
    emit = logger.error if name == 'MEDIA_OBJECT_INCONSISTENT' else logger.warning if name.endswith('_FAILED') else logger.info
    emit(name, extra=dict(event=name, media_public_id=str(media.public_id),
        organization_id=media.organization_id, message_id=media.message_id, outcome_code=code))


def _owned(claim):
    return MessageMedia.objects.for_organization(claim.organization_id).filter(
        pk=claim.pk, worker_token=claim.token)


def _mutate(claim, values):
    with transaction.atomic():
        row = _owned(claim).select_for_update().first()
        if row is None:
            return False
        if values.get('status') == 'ready' or values.get('file'):
            if revocation_record(row):
                return False
        for name, value in values.items():
            setattr(row, name, value)
        # Fields are server-owned transition results; constraints still apply.
        row.save(validate=False, update_fields=list(values))
        return True


def claim_media():
    # Background enumeration is the only unscoped scan. Every transition below
    # resolves and mutates the row with its explicit organization under a lock.
    due = Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=Now())
    eligible = ((Q(status__in=['pending', 'failed'], attempts__lt=MAX_ATTEMPTS) & due
                | Q(status='downloading', lease_until__lte=Now())) & Q(persisted_at__isnull=True)
                & (Q(expires_at__isnull=True) | Q(expires_at__gt=Now())))
    candidates = list(MessageMedia.objects.filter(eligible).order_by('created_at', 'pk')
                      .values('pk', 'organization_id')[:20])
    for candidate in candidates:
        with transaction.atomic():
            row = (MessageMedia.objects.for_organization(candidate['organization_id'])
                .select_for_update(skip_locked=True, of=('self',)).filter(eligible, pk=candidate['pk'])
                .select_related('message', 'channel_account').first())
            if row is None:
                continue
            record = revocation_record(row)
            if record:
                from datetime import datetime
                row.status, row.expired_at = 'expired', datetime.fromisoformat(record['revoked_at'])
                row.worker_token = row.lease_until = row.next_attempt_at = None
                row.attempts, row.error = MAX_ATTEMPTS, 'access_revoked'
                row.save(validate=False, update_fields=['status', 'expired_at', 'worker_token',
                    'lease_until', 'next_attempt_at', 'attempts', 'error'])
                continue
            if (row.message.organization_id != row.organization_id
                    or row.channel_account.organization_id != row.organization_id
                    or row.message.channel_account_id != row.channel_account_id or row.message.direction != 'in'):
                row.status, row.error, row.attempts = 'failed', 'scope_mismatch', MAX_ATTEMPTS
                row.worker_token = row.lease_until = None
                row.save(validate=False, update_fields=['status', 'error', 'attempts', 'worker_token', 'lease_until'])
                continue
            if row.attempts >= MAX_ATTEMPTS:
                row.status, row.error = 'failed', 'attempts_exhausted'
                row.worker_token = row.lease_until = None
                row.save(validate=False, update_fields=['status', 'error', 'worker_token', 'lease_until'])
                continue
            row.status, row.worker_token = 'downloading', uuid4()
            row.lease_until = media_now() + LEASE
            row.attempts += 1
            row.next_attempt_at, row.error = None, ''
            row.save(validate=False, update_fields=['status', 'worker_token', 'lease_until', 'attempts', 'next_attempt_at', 'error'])
            return MediaClaim(row.pk, row.organization_id, row.worker_token)
    return None


def _fail(claim, error):
    row = _owned(claim).first()
    if row is None:
        return
    _mutate(claim, dict(status='failed', error=error.code,
        attempts=row.attempts if error.retryable else MAX_ATTEMPTS,
        next_attempt_at=media_now() + timedelta(seconds=min(3600, 15 * 2**row.attempts)) if error.retryable else None,
        worker_token=None, lease_until=None))
    _event('MEDIA_DOWNLOAD_FAILED', row, error.code)


def process_media_claim(claim):
    if connection.in_atomic_block:
        raise RuntimeError('Media HTTP must run outside a database transaction')
    row = _owned(claim).select_related('message', 'channel_account').first()
    if row is None:
        return False
    if revocation_record(row):
        return False
    storage = row.file.storage
    key = None
    try:
        if row.file.name:
            # A previous worker may have died after upload. Purge its known key
            # before replacing the durable pointer with this claim's unique key.
            storage.delete(row.file.name)
            if not _mutate(claim, dict(file='')):
                return False
        with downloaded_media(row) as (content, metadata):
            key = media_upload_path(row, '')
            if not _mutate(claim, dict(file=key, lease_until=media_now() + LEASE)):
                return False
            stored = storage.save(key, content)
            if stored != key:
                storage.delete(stored)
                raise MediaDownloadError('storage_key_mismatch')
            now = media_now()
            completed = _mutate(claim, dict(**metadata, status='ready', file=key, persisted_at=now,
                expires_at=now + RETENTION, expired_at=None, error='', next_attempt_at=None,
                worker_token=None, lease_until=None, last_checked_at=now))
            if not completed:
                storage.delete(key)
                return False
        _event('MEDIA_DOWNLOAD_READY', row)
        return True
    except MediaDownloadError as error:
        _fail(claim, error)
    except Exception:
        # Exception strings can contain signed URLs, tokens or filenames.
        _fail(claim, MediaDownloadError('media_io_failed', retryable=True))
    return False


def download_pending_media(batch=1):
    if not settings.INBOX_MEDIA_ENABLED:
        return 0
    if connection.in_atomic_block:
        raise RuntimeError('Media jobs must run outside a database transaction')
    ready = 0
    for _ in range(max(0, min(int(batch), 2))):
        claim = claim_media()
        if claim is None:
            break
        ready += int(process_media_claim(claim))
    return ready


def expire_media(batch=100, *, stats=None):
    """Deny at the deadline even if physical deletion needs a later retry."""
    if not settings.INBOX_MEDIA_ENABLED:
        return 0
    if connection.in_atomic_block:
        raise RuntimeError('Media purges must run outside a database transaction')
    expired = Q(expires_at__lte=Now(), status__in=['ready', 'failed']) | Q(status='expired')
    abandoned = Q(status='failed', attempts__gte=MAX_ATTEMPTS, persisted_at__isnull=True) & ~Q(file='')
    due = Q(lease_until__isnull=True) | Q(lease_until__lte=Now())
    retry_due = Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=Now())
    candidates = list(MessageMedia.objects.filter(expired | abandoned).filter(due, retry_due)
        .exclude(status='expired', file='').annotate(_purge_due=Least('expires_at', 'expired_at'))
        .order_by('_purge_due', 'pk').values('pk', 'organization_id')[:batch])
    completed = 0
    for candidate in candidates:
        with transaction.atomic():
            row = (MessageMedia.objects.for_organization(candidate['organization_id'])
                .select_for_update(skip_locked=True).filter(expired | abandoned).filter(due, retry_due,
                    pk=candidate['pk']).first())
            if row is None:
                continue
            now = media_now()
            if row.expires_at is not None and row.expires_at <= now:
                row.status, row.expired_at = 'expired', row.expired_at or row.expires_at
            row.worker_token, row.lease_until = uuid4(), now + LEASE
            row.save(validate=False, update_fields=['status', 'expired_at', 'worker_token', 'lease_until'])
            claim = MediaClaim(row.pk, row.organization_id, row.worker_token)
            key = row.file.name
        if stats is not None:
            stats['attempted'] += 1
        observe_purge(row)
        try:
            if key:
                row.file.storage.delete(key)
                if row.file.storage.exists(key):
                    raise OSError('Media still present after purge')
            if _mutate(claim, dict(file='', worker_token=None, lease_until=None, next_attempt_at=None,
                    purge_verified_at=media_now(), error='')):
                _event('MEDIA_OBJECT_PURGED', row)
                completed += 1
        except Exception:
            if _mutate(claim, dict(worker_token=None, lease_until=None,
                    next_attempt_at=media_now() + timedelta(hours=23), error='purge_failed')):
                observe_purge(row, failed=True)
                if stats is not None:
                    stats['failed'] += 1
                _event('MEDIA_PURGE_FAILED', row, 'purge_failed')
    return completed


def reconcile_ready_media(batch=100):
    """Missing before expiry is an inconsistency, never a fabricated expiration."""
    if not settings.INBOX_MEDIA_ENABLED:
        return 0
    if connection.in_atomic_block:
        raise RuntimeError('Media reconciliation must run outside a database transaction')
    checked = 0
    due = Q(last_checked_at__isnull=True) | Q(last_checked_at__lte=media_now() - timedelta(days=1))
    free = Q(lease_until__isnull=True) | Q(lease_until__lte=Now())
    candidates = list(MessageMedia.objects.filter(due, free, status='ready', expires_at__gt=Now())
        .order_by('last_checked_at', 'pk').values('pk', 'organization_id')[:batch])
    for candidate in candidates:
        with transaction.atomic():
            row = (MessageMedia.objects.for_organization(candidate['organization_id']).select_for_update(skip_locked=True)
                .filter(due, free, pk=candidate['pk'], status='ready', expires_at__gt=Now()).first())
            if row is None:
                continue
            row.worker_token, row.lease_until = uuid4(), media_now() + LEASE
            row.last_checked_at = media_now()
            row.save(validate=False, update_fields=['worker_token', 'lease_until', 'last_checked_at'])
            claim = MediaClaim(row.pk, row.organization_id, row.worker_token)
        try:
            missing = not row.file.name or not row.file.storage.exists(row.file.name)
            values = dict(worker_token=None, lease_until=None)
            if missing:
                values.update(status='failed', error='object_missing', attempts=MAX_ATTEMPTS)
                _event('MEDIA_OBJECT_INCONSISTENT', row, 'object_missing')
            _mutate(claim, values)
            checked += 1
        except Exception:
            _mutate(claim, dict(worker_token=None, lease_until=None, error='reconcile_failed'))
            _event('MEDIA_RECONCILE_FAILED', row, 'reconcile_failed')
    return checked


def maintain_media(batch=100, *, alerts_only=False):
    if not settings.INBOX_MEDIA_ENABLED:
        return dict(enabled=False, purged=0, checked=0, attempted=0, failed=0, overdue=0,
            alerts=dict(accepted=0, pending_configuration=True), **incident_counts(), spools=dict(removed=0, bytes=0))
    stats = dict(attempted=0, failed=0)
    overdue = audit_purge_deadlines(batch)
    purged = 0 if alerts_only else expire_media(batch, stats=stats)
    # Evaluate time thresholds even if all purge attempts failed or have backoff.
    audit_purge_deadlines(batch)
    return dict(enabled=True, purged=purged, checked=0 if alerts_only else reconcile_ready_media(batch),
        **stats, overdue=overdue, **incident_counts(), alerts=dispatch_purge_alerts(batch),
        spools=dict(removed=0, bytes=0) if alerts_only else scavenge_media_spools())
