"""Bounded provider downloads into a dedicated, short-lived private spool."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import quote, urlparse

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files import File

from .media_policy import MAX_BYTES, MIME_TYPES, normalize_mime, normalize_sha256, positive_int
from .providers import MetaWhatsAppProvider, ProviderError

SPOOL_DIRECTORY = 'saaslyvet-inbox-media-spool'
SPOOL_MAX_AGE_SECONDS = 3600


class MediaDownloadError(Exception):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def spool_root():
    root = Path(settings.INBOX_MEDIA_SPOOL_ROOT or Path(tempfile.gettempdir()) / SPOOL_DIRECTORY)
    if root.name != SPOOL_DIRECTORY or root.is_symlink():
        raise ImproperlyConfigured('A dedicated private media spool directory is required')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root.resolve()


def scavenge_media_spools(now=None):
    """Only old UUID-named spool files, never recursive/general filesystem cleanup."""
    root = spool_root()
    cutoff = (time.time() if now is None else now) - SPOOL_MAX_AGE_SECONDS
    count = size = 0
    for path in root.iterdir():
        if not re.fullmatch(r'wa-[a-z0-9_]+\.spool', path.name) or path.is_symlink():
            continue
        if path.resolve().parent != root or not path.is_file():
            continue
        try:
            stat = path.stat()
            if stat.st_mtime < cutoff:
                path.unlink()
                count += 1
                size += stat.st_size
        except FileNotFoundError:
            pass  # Another scavenger already removed this orphan.
    return dict(removed=count, bytes=size)


def _check_status(response, *, binary=False):
    if 200 <= response.status_code < 300:
        return
    code = response.status_code
    if binary and code in (404, 410):
        raise MediaDownloadError('provider_url_expired', retryable=True)
    raise MediaDownloadError(f'provider_http_{code}', retryable=code == 429 or code >= 500)


def _download_url(value):
    if not isinstance(value, str):
        raise MediaDownloadError('invalid_download_url')
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or '').lower()
        valid = (parsed.scheme == 'https' and not parsed.username and not parsed.password
            and parsed.port in (None, 443) and not parsed.fragment
            and (host == 'lookaside.fbsbx.com' or host.endswith('.fbcdn.net')))
    except ValueError:
        valid = False
    if not valid:
        raise MediaDownloadError('invalid_download_url')
    return value


@contextmanager
def downloaded_media(media):
    """Fresh URL each attempt; bounded bytes/time; no redirect or URL persistence."""
    if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}', media.provider_media_id):
        raise MediaDownloadError('invalid_provider_media_id')
    kind = media.message.payload_type
    if kind not in MAX_BYTES:
        raise MediaDownloadError('unsupported_media_type')
    try:
        token = MetaWhatsAppProvider(media.channel_account)._access_token()
    except ProviderError:
        raise MediaDownloadError('credentials_missing', retryable=True) from None
    headers = {'Authorization': f'Bearer {token}'}
    started = time.monotonic()
    metadata_response = binary_response = spool = None
    path = None
    try:
        base = settings.WHATSAPP_API_BASE_URL.rstrip('/')
        metadata_response = requests.get(f'{base}/{quote(media.provider_media_id, safe="")}',
            params={'phone_number_id': media.channel_account.external_account_id},
            headers=headers, timeout=(5, 10), allow_redirects=False)
        _check_status(metadata_response)
        try:
            metadata = metadata_response.json()
        except ValueError:
            raise MediaDownloadError('invalid_provider_metadata', retryable=True) from None
        if not isinstance(metadata, dict):
            raise MediaDownloadError('invalid_provider_metadata', retryable=True)
        url = _download_url(metadata.get('url'))
        mime = normalize_mime(metadata.get('mime_type')) or normalize_mime(media.mime_type)
        if mime not in MIME_TYPES[kind]:
            raise MediaDownloadError('unsupported_mime_type')
        if media.mime_type and normalize_mime(media.mime_type) != mime:
            raise MediaDownloadError('mime_mismatch')
        limit = MAX_BYTES[kind]
        advertised = positive_int(metadata.get('file_size'))
        if advertised is not None and advertised > limit:
            raise MediaDownloadError('media_too_large')
        expected = [value for value in (media.expected_sha256, normalize_sha256(metadata.get('sha256'))) if value]
        if len(set(expected)) > 1:
            raise MediaDownloadError('checksum_mismatch')
        binary_response = requests.get(url, headers=headers, stream=True, timeout=(5, 5), allow_redirects=False)
        _check_status(binary_response, binary=True)
        wire_mime = normalize_mime(binary_response.headers.get('Content-Type'))
        if wire_mime and wire_mime not in (mime, 'application/octet-stream'):
            raise MediaDownloadError('mime_mismatch')
        length = binary_response.headers.get('Content-Length', '')
        if str(length).isdigit() and int(length) > limit:
            raise MediaDownloadError('media_too_large')
        spool = tempfile.NamedTemporaryFile(mode='w+b', prefix='wa-', suffix='.spool', dir=spool_root(), delete=False)
        path = Path(spool.name)
        digest, size = hashlib.sha256(), 0
        for chunk in binary_response.iter_content(chunk_size=64 * 1024):
            if time.monotonic() - started > 60:
                raise MediaDownloadError('download_deadline', retryable=True)
            if not chunk:
                continue
            size += len(chunk)
            if size > limit:
                raise MediaDownloadError('media_too_large')
            digest.update(chunk)
            spool.write(chunk)
        if size == 0:
            raise MediaDownloadError('empty_media', retryable=True)
        if advertised is not None and size != advertised:
            raise MediaDownloadError('size_mismatch', retryable=True)
        actual = digest.hexdigest()
        if any(value != actual for value in expected):
            raise MediaDownloadError('checksum_mismatch')
        spool.seek(0)
        content = File(spool, name='media.bin')
        content.content_type = mime
        yield content, dict(mime_type=mime, file_size=size, sha256=actual)
    except requests.RequestException:
        raise MediaDownloadError('provider_transport', retryable=True) from None
    finally:
        for response in (binary_response, metadata_response):
            if response is not None:
                response.close()
        if spool is not None:
            spool.close()
        if path is not None:
            path.unlink(missing_ok=True)
