"""Independent deny ledger. Mount separately from DB backups; never roll it back.

Files are exclusive-create, fsynced, private tombstones. This is not a claim of
provider immutability: volume backup, integrity and custody need an ops drill.
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from .media_clock import media_now
from .media_storage import validate_key


class MediaAccessHeld(Exception):
    pass


def ledger_root(*, required=False):
    value = settings.INBOX_MEDIA_REVOCATION_ROOT
    if not value:
        if required or settings.MEDIA_BACKEND == 'b2':
            raise ImproperlyConfigured('Independent media revocation ledger required')
        return None  # Development only; early revocation still requires a ledger.
    root = Path(value)
    if not root.is_absolute() or root.name != 'inbox-media-revocations':
        raise ImproperlyConfigured('Invalid independent media ledger directory')
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ImproperlyConfigured('Media ledger symlinks are forbidden')
    if not root.is_dir() or (root / '.ready').read_text(encoding='ascii') != 'v1\n':
        raise ImproperlyConfigured('Media ledger not provisioned')
    return root


def identity(row):
    values = [row.organization_id, row.channel_account_id, row.provider_media_id or str(row.public_id)]
    return hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()


def read_record(path):
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ImproperlyConfigured('Invalid media revocation record')
    record = json.loads(path.read_text(encoding='utf-8'))
    stamp = datetime.fromisoformat(record['revoked_at'])
    if (record['schema'] != 1 or record['identity'] != path.stem or stamp.tzinfo is None
            or not isinstance(record['organization_id'], int)):
        raise ImproperlyConfigured('Invalid media revocation record')
    if record['object_key']:
        validate_key(record['object_key'])
        if not record['object_key'].startswith(f"inbox-media/{record['organization_id']}/"):
            raise ImproperlyConfigured('Invalid media revocation scope')
    return record


def revocation_record(row, *, allow_hold=False):
    if settings.INBOX_MEDIA_ACCESS_HOLD and not allow_hold:
        raise MediaAccessHeld('Media access is held for reconciliation')
    root = ledger_root()
    if root is None:
        return None
    path = root / (identity(row) + '.json')
    try:
        record = read_record(path)
    except FileNotFoundError:
        return None
    if record['organization_id'] != row.organization_id:
        raise ImproperlyConfigured('Invalid media revocation scope')
    return record


def provision_ledger():
    root = Path(settings.INBOX_MEDIA_REVOCATION_ROOT)
    if not root.is_absolute() or root.name != 'inbox-media-revocations':
        raise ImproperlyConfigured('Configure the independent ledger path first')
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ImproperlyConfigured('Media ledger symlinks are forbidden')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker = root / '.ready'
    if not marker.exists():
        with marker.open('x', encoding='ascii', newline='\n') as stream:
            stream.write('v1\n')
            stream.flush()
            os.fsync(stream.fileno())
    ledger_root(required=True)


def write_revocation(row, *, reason):
    """Must precede the DB transition. Failure leaves the operation unconfirmed."""
    root = ledger_root(required=True)
    key = identity(row)
    path = root / (key + '.json')
    record = dict(schema=1, identity=key, organization_id=row.organization_id,
        media_public_id=str(row.public_id), object_key=row.file.name or '',
        revoked_at=media_now().isoformat(), reason=reason)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        return read_record(path)
    # A torn write is intentionally a deny/error, never an implicit "not revoked".
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
        json.dump(record, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name != 'nt':
        descriptor = os.open(root, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return record


def revoke_media(*, organization_id, public_id, reason='arco'):
    from .models import MessageMedia
    if reason not in ('arco', 'restore_pending'):
        raise ValueError('Invalid revocation reason')
    with transaction.atomic():
        row = MessageMedia.objects.for_organization(organization_id).select_for_update().get(public_id=public_id)
        record = write_revocation(row, reason=reason)
        row.status, row.expired_at = 'expired', datetime.fromisoformat(record['revoked_at'])
        row.worker_token = row.lease_until = row.next_attempt_at = None
        row.error, row.attempts = 'access_revoked', 5
        # Original persistence/expiry are deliberately preserved.
        row.save(validate=False, update_fields=['status', 'expired_at', 'worker_token', 'lease_until',
            'next_attempt_at', 'error', 'attempts'])
    return row
