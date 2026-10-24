"""Servicios de lectura del Inbox: estado propio y conteos por episodio vigente."""
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.db.models import BigIntegerField, Count, F, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from rest_framework.exceptions import APIException, NotFound

from apps.channels.models import Message
from apps.channels.selectors import RECEIVED_IN_STATUSES, operational_messages

from .models import Conversation, InboxReadState


class InvalidReadMessage(APIException):
    status_code = 400
    default_code = 'invalid_read_message'
    default_detail = 'Solo se puede marcar un mensaje entrante visible del hilo.'


def _visible_inbound(user, conversation_ids):
    return operational_messages(Message.objects.for_organization(user.organization_id).filter(
        conversation_id__in=conversation_ids, direction=Message.DIRECTION_IN,
        contact_id=F('conversation__contact_id'),
        channel_account_id=F('conversation__channel_account_id'),
    ))


def _unread_inbound(user, conversation_ids):
    marker = InboxReadState.objects.for_organization(user.organization_id).filter(
        user=user, contact_id=OuterRef('contact_id'),
        channel_account_id=OuterRef('channel_account_id'),
    ).values('last_read_message_id')[:1]
    return _visible_inbound(user, conversation_ids).annotate(_read_id=Coalesce(
        Subquery(marker), Value(0), output_field=BigIntegerField(),
    )).filter(pk__gt=F('_read_id'))


def unread_counts(user, conversations):
    """Una consulta agregada para toda la página; nunca recorre episodios históricos."""
    current_ids = [row.pk for row in conversations if row.state != Conversation.STATE_CLOSED]
    if not current_ids:
        return {}
    counts = (_unread_inbound(user, current_ids).order_by().values('conversation_id')
        .annotate(total=Count('pk')).values_list('conversation_id', 'total'))
    return dict(counts)


def unread_total(user):
    """Total del caller sobre todas las cabeceras vigentes, sin materializarlas."""
    current_ids = (Conversation.objects.for_organization(user.organization_id)
                   .exclude(state=Conversation.STATE_CLOSED)
                   .order_by('contact_id', 'channel_account_id', '-last_activity_at', '-pk')
                   .distinct('contact_id', 'channel_account_id').values('pk'))
    return _unread_inbound(user, Subquery(current_ids)).count()


def thread_read_status(user, contact, account, current, page):
    """Marcador propio y destinos que realmente están incluidos en esta página."""
    marker = (InboxReadState.objects.for_organization(user.organization_id)
              .filter(user=user, contact=contact, channel_account=account)
              .values_list('last_read_message_id', flat=True).first())
    incoming = [message for message in page if current
                and message.conversation_id == current.pk
                and message.direction == Message.DIRECTION_IN
                and message.status in RECEIVED_IN_STATUSES]
    unread = [message for message in incoming if message.pk > (marker or 0)]
    return {
        'last_read_message_id': marker,
        'unread_count': (_visible_inbound(user, [current.pk]).filter(pk__gt=marker or 0).count()
                         if current else 0),
        'first_unread_message_id': unread[0].pk if unread else None,
        'latest_visible_inbound_id': max((message.pk for message in incoming), default=None),
    }


@transaction.atomic
def mark_thread_read(*, user, contact, account, message_id):
    """Upsert serializado: solo entrantes visibles del hilo y avance monótono por id."""
    org_id = user.organization_id
    if contact.organization_id != org_id or account.organization_id != org_id:
        raise NotFound('Hilo no encontrado.')
    scoped_messages = Message.objects.for_organization(org_id).filter(
        contact=contact, channel_account=account,
    )
    target = scoped_messages.filter(pk=message_id).first()
    if target is None:
        raise NotFound('Mensaje no encontrado.')
    if (target.direction != Message.DIRECTION_IN
            or not operational_messages(scoped_messages).filter(pk=target.pk).exists()):
        raise InvalidReadMessage()

    states = InboxReadState.objects.for_organization(org_id).filter(
        user=user, contact=contact, channel_account=account,
    )
    try:
        with transaction.atomic():
            state, _ = states.get_or_create(
                organization_id=org_id, user=user, contact=contact, channel_account=account,
                defaults={'last_read_message': target, 'created_by': user, 'updated_by': user},
            )
    except ValidationError as error:
        # OrganizationalModel.full_clean puede detectar la carrera antes del INSERT.
        # get_or_create ya recupera la variante IntegrityError de la misma carrera.
        if (set(error.error_dict) != {NON_FIELD_ERRORS}
                or any(item.code != 'unique_together' for item in error.error_dict[NON_FIELD_ERRORS])):
            raise
        state = states.get()
    state = states.select_for_update().get(pk=state.pk)
    if state.last_read_message_id is None or target.pk > state.last_read_message_id:
        state.last_read_message = target
        state.updated_by = user
        state.save(update_fields=['last_read_message', 'updated_at', 'updated_by'])
    return state
