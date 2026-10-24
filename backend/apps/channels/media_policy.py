"""Transport metadata and bounded file policy; no binary interpretation by AI."""
import base64
import re

MEDIA_TYPES = frozenset(('image', 'audio', 'video', 'document', 'sticker'))
MIME_TYPES = {
    'image': {'image/jpeg', 'image/png', 'image/webp', 'image/gif'},
    'sticker': {'image/webp'},
    'audio': {'audio/aac', 'audio/amr', 'audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/opus', 'application/ogg', 'audio/wav'},
    'video': {'video/mp4', 'video/3gpp', 'video/3gp'},
    'document': {'application/pdf', 'text/plain', 'application/msword', 'application/vnd.ms-excel',
        'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation'},
}
MAX_BYTES = {'image': 5 * 1024**2, 'sticker': 500 * 1024, 'audio': 16 * 1024**2,
             'video': 16 * 1024**2, 'document': 25 * 1024**2}


def normalize_sha256(value):
    if not isinstance(value, str):
        return ''
    if re.fullmatch(r'[0-9a-fA-F]{64}', value):
        return value.lower()
    try:
        decoded = base64.b64decode(value, validate=True)
        return decoded.hex() if len(decoded) == 32 else ''
    except (ValueError, TypeError):
        return ''


def normalize_mime(value):
    return value.split(';', 1)[0].strip().lower()[:100] if isinstance(value, str) else ''


def positive_int(value, maximum=9223372036854775807):
    return value if type(value) is int and 0 <= value <= maximum else None


def extract_media_metadata(msg):
    from .media_storage import safe_filename
    kind = msg.get('type')
    value = msg.get(kind) if isinstance(kind, str) and kind in MEDIA_TYPES else None
    if not isinstance(value, dict) or not isinstance(value.get('id'), str):
        return None
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value['id']):
        return None
    return dict(provider_media_id=value['id'], mime_type=normalize_mime(value.get('mime_type')),
        filename=safe_filename(value.get('filename')) if value.get('filename') else '',
        expected_sha256=normalize_sha256(value.get('sha256')), file_size=positive_int(value.get('file_size')),
        duration_ms=positive_int(value.get('duration_ms'), 2147483647),
        width=positive_int(value.get('width'), 2147483647),
        height=positive_int(value.get('height'), 2147483647))
