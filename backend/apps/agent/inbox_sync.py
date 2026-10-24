"""PERF-03: scoped, signed cursors over disposable projection fingerprints.

Only hashes, IDs and server watermarks enter cache, never bodies, names or phones.
Snapshots are immutable so concurrent tabs/replayed cursors do not consume changes.
Comparing membership also catches late commits, removals and time-derived fields;
an updated_at high watermark alone cannot safely account for those events.
"""
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from django.core import signing
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import BooleanField, Case, F, Q, TextField, Value, When
from django.db.models.functions import Cast, JSONObject, MD5, Now, Substr
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException

from .serializers import MessageSerializer

CURSOR_TTL = 600
SALT = 'inbox.sync.v1'


class InvalidSyncCursor(APIException):
    status_code = 400
    default_detail = 'La vista cambió. Vuelve a cargarla para sincronizar.'
    default_code = 'invalid_sync_cursor'


def digest(value):
    raw = json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True,
                     ensure_ascii=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def scope_for(request, resource, filters):
    return digest([request.user.organization_id, request.user.pk, resource, filters])


def _cache_key(token):
    return 'inbox-sync:v1:' + digest(token)


def previous_snapshot(request, scope):
    if 'since' not in request.query_params:
        return None
    token = request.query_params['since']
    if not token or len(token) > 2048:
        raise InvalidSyncCursor()
    try:
        claims = signing.loads(token, salt=SALT, max_age=CURSOR_TTL)
        if claims['s'] != scope or claims['v'] != 1:
            raise InvalidSyncCursor()
        state = cache.get(_cache_key(token))
        if (not isinstance(state, dict) or not isinstance(state.get('rows'), dict)
                or claims['w'] != state['watermarks']):
            raise InvalidSyncCursor()
    except InvalidSyncCursor:
        raise
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise InvalidSyncCursor() from None
    except Exception:
        # Cache is never authority. An outage requests an ordinary full recovery.
        raise InvalidSyncCursor() from None
    return state


def issue_cursor(request, scope, state, previous):
    if previous == state:
        return request.query_params['since']
    token = signing.dumps({'v': 1, 's': scope, 'n': uuid4().hex,
                           'w': state['watermarks']}, salt=SALT, compress=True)
    try:
        key = _cache_key(token)
        cache.set(key, state, timeout=CURSOR_TTL)
        # LocMemCache.set has no success return value; Redis can fail open too.
        # Verify reconstruction state exists instead of interpreting that return.
        if cache.get(key) != state:
            return None
    except Exception:
        return None
    return token


def watermark(rows):
    # Timestamp is persisted updated_at, never the browser clock/created_at alone.
    return max(([row.updated_at.isoformat(), row.pk] for row in rows), default=None)


def thread_key(row):
    return f"{row['contact_public_id']}:{row['channel_account_public_id']}"


def list_sync(request, payload, heads, scope, previous):
    rows = payload['results']
    fingerprints = {thread_key(row): digest(row) for row in rows}
    order = list(fingerprints)
    state = {'rows': fingerprints, 'order': order, 'watermarks': watermark(heads)}
    token = issue_cursor(request, scope, state, previous)
    if previous is None:
        return dict(payload, mode='full', sync_cursor=token)
    if token is None:
        raise InvalidSyncCursor()
    delta = {key: value for key, value in payload.items() if key != 'results'}
    delta.update(mode='delta', sync_cursor=token,
        upserts=[row for row in rows if previous['rows'].get(thread_key(row)) != fingerprints[thread_key(row)]],
        removals=[key for key in previous['rows'] if key not in fingerprints])
    if order != previous['order']:
        delta['order'] = order
    return delta


def stamped_messages(queryset):
    # Compute with the very SELECT that reads a message, so an intervening write
    # cannot be acknowledged by a stamp newer than the body sent to this reader.
    fields = ['updated_at', 'id', 'created_at', 'conversation_id', 'direction',
        'author_type', 'payload_type', 'status', 'failure_reason', 'idempotency_key',
        'external_message_id', 'send_started_at', 'send_admitted_at', 'provider_accepted_at',
        'delivered_at', 'read_at', 'uncertain_at', 'supersedes_message_id',
        'human_author__first_name', 'human_author__last_name', 'human_author__username',
        'human_author__public_id', 'conversation__public_id', 'reply_to_id',
        'reply_to__organization_id', 'reply_to__contact_id', 'reply_to__channel_account_id',
        'reply_to__author_type', 'reply_to__payload_type', 'reply_to__status',
        'reply_to__human_author__organization_id', 'reply_to__human_author__first_name',
        'reply_to__human_author__last_name', 'reply_to__human_author__username',
        'media__public_id', 'media__organization_id', 'media__channel_account_id',
        'media__status', 'media__updated_at', 'media__mime_type', 'media__file_size',
        'media__filename', 'media__expires_at', 'media__duration_ms', 'media__width', 'media__height']
    return queryset.annotate(_inbox_sync_stamp=MD5(Cast(JSONObject(
        **{f'v{index}': F(field) for index, field in enumerate(fields)},
        body=MD5('body'), reply_excerpt=MD5(Substr('reply_to__body', 1, 80)),
        media_expired=Case(When(media__expires_at__lte=Now(), then=Value(True)),
            default=Value(False), output_field=BooleanField())), TextField())))


def hydrate_preview(current):
    if current is None:
        return
    from apps.channels.models import Message
    row = (Message.objects.for_organization(current.organization_id).filter(conversation=current)
        .annotate(preview=Substr('body', 1, 120)).order_by('-created_at', '-id')
        .values('pk', 'direction', 'payload_type', 'preview').first())
    # Reuse the serializer's existing latest_messages prefetch contract.
    current.latest_messages = [Message(pk=row['pk'], direction=row['direction'],
        payload_type=row['payload_type'], body=row['preview'])] if row else []


def sign_floor(scope, message):
    return signing.dumps({'s': scope, 'p': message.pk, 't': message.created_at.isoformat()},
                         salt=SALT+'.floor', compress=True) if message else None


def floor_message(queryset, requested, previous=None, scope=None):
    try:
        if requested is not None and not str(requested).isdigit():
            claims = signing.loads(requested, salt=SALT+'.floor')
            if claims['s'] != scope:
                raise ValueError
            return SimpleNamespace(pk=int(claims['p']), created_at=parse_datetime(claims['t']))
        floor_id = int(requested) if requested is not None else (previous or {}).get('floor')
        if floor_id is None:
            return None
        if floor_id <= 0 or floor_id > 9223372036854775807:
            raise ValueError
        if previous and floor_id == previous.get('floor') and previous.get('floor_at'):
            return SimpleNamespace(pk=floor_id, created_at=parse_datetime(previous['floor_at']))
        floor = queryset.filter(pk=floor_id).first()
        if floor is None:
            raise ValueError
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise InvalidSyncCursor() from None
    return floor


def from_floor(queryset, floor):
    return queryset.filter(Q(created_at__gt=floor.created_at)
        | Q(created_at=floor.created_at, pk__gte=floor.pk)) if floor else queryset


def changed_messages(queryset, previous, floor):
    # Lightweight stamps only for the range actually loaded by this reader.
    # Read all stamps in that range: late transactions/equal timestamps cannot
    # disappear behind a max(updated_at,id) cutoff. Bodies load only on change.
    stamps = list(from_floor(queryset, floor).order_by('created_at', 'id').values_list(
        'pk', 'updated_at', 'created_at', 'conversation_id', 'direction', 'status', '_inbox_sync_stamp'))
    fingerprints = {str(row[0]): row[6] for row in stamps}
    changed = [int(key) for key, value in fingerprints.items() if previous['rows'].get(key) != value]
    messages = list(queryset.filter(pk__in=changed).order_by('created_at', 'id'))
    page = [SimpleNamespace(pk=row[0], conversation_id=row[3], direction=row[4], status=row[5]) for row in stamps]
    watermarks = max(([row[1].isoformat(), row[0]] for row in stamps), default=None)
    extended = floor and (floor.pk != previous['floor'] or floor.created_at.isoformat() != previous['floor_at'])
    return {'messages': MessageSerializer(messages, many=True).data,
        'range_ids': [row[0] for row in stamps] if extended else None,
        'removals': [int(key) for key in previous['rows'] if key not in fingerprints],
        'rows': fingerprints, 'watermarks': watermarks, 'page': page,
        'floor': floor.pk if floor else (stamps[0][0] if stamps else None),
        'floor_at': floor.created_at.isoformat() if floor else (stamps[0][2].isoformat() if stamps else None)}


def transcript_sync(request, payload, page, scope, previous, changes=None):
    metadata = {key: value for key, value in payload.items() if key not in ('messages', 'next_before', 'reset_range', 'sync_floor')}
    state = {'rows': changes['rows'] if changes else {str(message.pk): message._inbox_sync_stamp for message in page},
        'floor': changes['floor'] if changes else (page[0].pk if page else None),
        'floor_at': changes['floor_at'] if changes else (page[0].created_at.isoformat() if page else None),
        'watermarks': changes['watermarks'] if changes else watermark(page),
        'metadata': digest(metadata)}
    token = issue_cursor(request, scope, state, previous)
    if previous is None:
        return dict(payload, mode='full', sync_cursor=token)
    if token is None:
        raise InvalidSyncCursor()
    delta = dict(mode='delta', sync_cursor=token, messages=changes['messages'],
        removals=changes['removals'], metadata=metadata if state['metadata'] != previous['metadata'] else {})
    if changes['range_ids'] is not None:
        delta['range_ids'] = changes['range_ids']
    return delta
