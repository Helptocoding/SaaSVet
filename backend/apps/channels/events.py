"""B1 channel projection. Only the reserved, validated projection is runtime data.

The body is stored once in Message.body. ``body_source`` records whether it is
text, a caption or a visible title; IDs never come from the title. No binary
content is fetched or interpreted here. Missing legacy metadata stays unknown.
"""
from dataclasses import dataclass, replace
from datetime import datetime


EVENT_METADATA_KEY = '_channel_event'
EVENT_METADATA_VERSION = 1
MEDIA_TYPES = frozenset({'audio', 'image', 'document', 'video', 'sticker'})
LIMITED_TYPES = MEDIA_TYPES | {'location', 'other'}


@dataclass(frozen=True, slots=True)
class ChannelEvent:
    text: str = ''
    payload_type: str = 'other'
    event_type: str | None = None
    body_source: str | None = None
    interaction_type: str | None = None
    reply_to_id: str | None = None
    action_id: str | None = None
    media_reference_id: str | None = None
    media_mime_type: str | None = None
    message_id: int | None = None
    external_message_id: str | None = None
    created_at: datetime | None = None

    @property
    def original_text(self) -> str | None:
        return self.text if self.body_source == 'text' else None

    @property
    def normalized_text(self) -> None:
        # The current channel contract does not store a second text form.
        return None

    @property
    def caption(self) -> str | None:
        return self.text if self.body_source == 'caption' else None

    @property
    def action_title(self) -> str | None:
        return self.text if self.body_source == 'title' else None

    @property
    def limited_content(self) -> bool:
        return (self.event_type or self.payload_type) in LIMITED_TYPES

    @property
    def binary_understood(self) -> bool:
        return False

    @property
    def uninterpretable(self) -> bool:
        return not self.text.strip() and self.payload_type != 'text'

    def projection(self) -> dict:
        """Persist provenance, never a second copy of text/caption/title."""
        return {
            'version': EVENT_METADATA_VERSION,
            'event_type': self.event_type,
            'body_source': self.body_source,
            'interaction_type': self.interaction_type,
            'reply_to_id': self.reply_to_id,
            'action_id': self.action_id,
            'media_reference_id': self.media_reference_id,
            'media_mime_type': self.media_mime_type,
        }


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _string(value) -> str:
    return value if isinstance(value, str) else ''


def normalize_whatsapp_event(msg: dict) -> ChannelEvent:
    """Project supplied text and explicit provider identifiers, without I/O."""
    msg = _mapping(msg)
    kind = _string(msg.get('type')) or 'unknown'
    text, source, interaction, action_id = '', 'none', None, None
    payload_type = kind if kind in {'text', 'audio', 'image', 'document',
                                   'location', 'sticker', 'video'} else 'other'
    media = _mapping(msg.get(kind)) if kind in MEDIA_TYPES else {}
    if kind == 'text':
        text = _string(_mapping(msg.get('text')).get('body'))
        source = 'text'
    elif kind in MEDIA_TYPES and isinstance(media.get('caption'), str):
        text, source = media['caption'], 'caption'
    elif kind == 'interactive':
        interactive = _mapping(msg.get('interactive'))
        interaction = _string(interactive.get('type')) or None
        if interaction is None:
            # A supplied object is evidence of its kind, never of a missing ID.
            interaction = next((k for k in ('button_reply', 'list_reply')
                                if isinstance(interactive.get(k), dict)), None)
        if interaction in ('button_reply', 'list_reply'):
            reply = _mapping(interactive.get(interaction))
            text, source = _string(reply.get('title')), 'title'
            action_id = _string(reply.get('id')) or None
            # Existing model choices remain compatible; projection keeps kind.
            payload_type = 'button_reply'
    elif kind == 'button':
        button = _mapping(msg.get('button'))
        text, source = _string(button.get('text')), 'title'
        action_id = _string(button.get('payload')) or None
        payload_type = 'button_reply'
    return ChannelEvent(
        text=text, payload_type=payload_type, event_type=kind,
        body_source=source, interaction_type=interaction,
        reply_to_id=_string(_mapping(msg.get('context')).get('id')) or None,
        action_id=action_id,
        media_reference_id=_string(media.get('id')) or None,
        media_mime_type=_string(media.get('mime_type')) or None,
        external_message_id=_string(msg.get('id')) or None,
    )


def event_from_message(message) -> ChannelEvent:
    """Read scalar persisted data; arbitrary/raw legacy JSON is diagnostic only."""
    legacy = ChannelEvent(
        text=message.body, payload_type=message.payload_type,
        message_id=message.pk, external_message_id=message.external_message_id,
        created_at=message.created_at,
    )
    projection = _mapping(message.raw_metadata).get(EVENT_METADATA_KEY)
    if not _valid_projection(projection, message.payload_type):
        return legacy
    return replace(legacy, **{k: v for k, v in projection.items() if k != 'version'})


def _valid_projection(value, payload_type: str) -> bool:
    if not isinstance(value, dict) or type(value.get('version')) is not int:
        return False
    if value['version'] != EVENT_METADATA_VERSION:
        return False
    fields = {'event_type', 'body_source', 'interaction_type', 'reply_to_id',
              'action_id', 'media_reference_id', 'media_mime_type'}
    if set(value) != fields | {'version'}:
        return False
    if any(v is not None and not isinstance(v, str)
           for k, v in value.items() if k != 'version'):
        return False
    kind, source = value['event_type'], value['body_source']
    if not kind or source not in {'text', 'caption', 'title', 'none'}:
        return False
    expected = kind if kind in {'text', 'audio', 'image', 'document',
                               'location', 'sticker', 'video'} else 'other'
    if kind in {'interactive', 'button'} and source == 'title':
        expected = 'button_reply'
    if payload_type != expected and not (kind == 'video' and payload_type == 'other'):
        return False
    if source == 'text' and kind != 'text':
        return False
    if source == 'caption' and kind not in MEDIA_TYPES:
        return False
    if source == 'title' and kind not in {'interactive', 'button'}:
        return False
    if value['interaction_type'] is not None and kind != 'interactive':
        return False
    if source == 'title' and kind == 'interactive' and value['interaction_type'] not in {
            'button_reply', 'list_reply'}:
        return False
    if value['action_id'] is not None and source != 'title':
        return False
    if any(value[k] is not None for k in ('media_reference_id', 'media_mime_type')):
        if kind not in MEDIA_TYPES:
            return False
    return True
