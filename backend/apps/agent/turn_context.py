"""B1: one immutable, in-memory causal envelope; no ORM or domain snapshot.

``history_before`` is an exclusive local (created_at, id) boundary immediately
before the first inbound. It does not depend on processing status or Meta time.
Legacy text adapters have no message IDs and cannot fabricate provenance.
"""
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from apps.channels.events import ChannelEvent, event_from_message
from apps.channels.models import Message


@dataclass(frozen=True, slots=True)
class MessageCursor:
    created_at: datetime
    message_id: int | None


@dataclass(frozen=True, slots=True)
class TurnContext:
    organization_id: int
    conversation_id: int
    channel_account_id: int
    channel_type: str
    contact_id: int
    events: tuple[ChannelEvent, ...]
    anchor: MessageCursor | None
    history_before: MessageCursor | None
    clinic_now: datetime
    clinic_timezone: str

    @property
    def inbound_ids(self) -> tuple[int, ...]:
        return tuple(e.message_id for e in self.events if e.message_id is not None)

    @property
    def texts(self) -> tuple[str, ...]:
        return tuple(e.text for e in self.events)

    @property
    def burst_text(self) -> str:
        return '\n'.join(text for text in self.texts if text)

    @property
    def latest_text(self) -> str:
        return next((text for text in reversed(self.texts) if text), '')

    @property
    def media_kinds(self) -> tuple[str, ...]:
        return tuple(e.event_type or e.payload_type for e in self.events
                     if e.limited_content or e.uninterpretable)

    def assert_scope(self, conversation) -> None:
        if (self.organization_id, self.conversation_id, self.channel_account_id,
            self.contact_id) != (conversation.organization_id, conversation.pk,
                                conversation.channel_account_id, conversation.contact_id):
            raise ValueError('TurnContext scope does not match conversation')


def build_turn_context(conversation, messages, *, now=None) -> TurnContext:
    """Freeze the actual inbound members in persisted local order."""
    messages = tuple(messages)
    for message in messages:
        if (not message.pk or message.created_at is None
                or message.direction != Message.DIRECTION_IN
                or message.organization_id != conversation.organization_id
                or message.conversation_id != conversation.pk
                or message.channel_account_id != conversation.channel_account_id
                or message.contact_id not in (None, conversation.contact_id)):
            raise ValueError('TurnContext requires persisted inbounds from its scope')
    if len({m.pk for m in messages}) != len(messages):
        raise ValueError('TurnContext inbound members must be unique')
    events = tuple(event_from_message(m) for m in sorted(
        messages, key=lambda m: (m.created_at, m.pk)))
    return _context(conversation, events, now=now)


def _context(conversation, events, *, now=None) -> TurnContext:
    if (conversation.channel_account.organization_id != conversation.organization_id
            or conversation.contact.organization_id != conversation.organization_id):
        raise ValueError('TurnContext relationships must belong to its organization')
    now = now or timezone.now()
    try:
        clinic_zone = ZoneInfo(conversation.organization.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        clinic_zone = timezone.get_default_timezone()
    anchor = (MessageCursor(events[-1].created_at, events[-1].message_id)
              if events and events[-1].message_id is not None else None)
    history_before = (MessageCursor(events[0].created_at, events[0].message_id)
                      if anchor else None if events else MessageCursor(now, None))
    return TurnContext(
        organization_id=conversation.organization_id, conversation_id=conversation.pk,
        channel_account_id=conversation.channel_account_id,
        channel_type=conversation.channel_account.channel_type,
        contact_id=conversation.contact_id, events=events, anchor=anchor,
        history_before=history_before, clinic_now=now.astimezone(clinic_zone),
        clinic_timezone=str(clinic_zone),
    )


def context_from_inputs(conversation, *, turn_context=None, burst_messages=None,
                        triggered_by=None, burst=None, payload_types=None) -> TurnContext:
    """Compatibility boundary for known direct callers; real messages win.

    With no supplied input, the legacy direct planner call means the last local
    inbound. It never invents a burst from status, timing or matching body text.
    """
    if turn_context is not None:
        turn_context.assert_scope(conversation)
        return turn_context
    if burst_messages is not None:
        return build_turn_context(conversation, burst_messages)
    if triggered_by is not None:
        return build_turn_context(conversation, [triggered_by])
    if burst is not None or payload_types is not None:
        texts, kinds = tuple(burst or ()), tuple(payload_types or ())
        events = tuple(ChannelEvent(
            text=texts[i] if i < len(texts) else '',
            payload_type=kinds[i] if i < len(kinds) else 'text',
        ) for i in range(max(len(texts), len(kinds))))
        return _context(conversation, events)
    message = Message.objects.for_organization(conversation.organization_id).filter(
        conversation_id=conversation.pk, channel_account_id=conversation.channel_account_id,
        direction=Message.DIRECTION_IN,
    ).exclude(status=Message.STATUS_DISCARDED).order_by('-created_at', '-id').first()
    return build_turn_context(conversation, [message] if message else [])


def messages_for_turn(conversation, turn_context: TurnContext) -> list[Message]:
    """Scoped ORM adapter only for existing consumers requiring persisted FKs.

    Membership and order come from C1; this does not discover another burst.
    """
    turn_context.assert_scope(conversation)
    rows = Message.objects.for_organization(turn_context.organization_id).filter(
        conversation_id=turn_context.conversation_id,
        channel_account_id=turn_context.channel_account_id,
        direction=Message.DIRECTION_IN, pk__in=turn_context.inbound_ids,
    ).in_bulk()
    if len(rows) != len(turn_context.inbound_ids):
        raise ValueError('TurnContext member no longer available')
    for event in turn_context.events:
        if event.message_id is not None:
            row = rows[event.message_id]
            if (row.contact_id not in (None, turn_context.contact_id)
                    or event_from_message(row) != event):
                raise ValueError('TurnContext member evidence changed')
    return [rows[pk] for pk in turn_context.inbound_ids]
