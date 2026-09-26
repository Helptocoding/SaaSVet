"""B7B canonical proposals and causal channel receipts. No transport here."""
import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Now
from apps.channels.models import Message
from apps.channels.providers import valid_provider_id
from . import durable, operations

RECEIPT_KEY = '_b7b_receipt'
POLICY_VERSION = 1
ATTENDANCE_POLICY_VERSION = 2
logger = logging.getLogger('agent.events')


def enabled():
    return settings.AGENT_B7B_CONSENT_ENABLED


def observe(name):
    # Callers use a closed vocabulary, never user text/IDs as metric labels.
    transaction.on_commit(lambda: logger.info('AGENT_B7B_' + name.upper(),
        extra={'event': 'AGENT_B7B_' + name.upper(), 'count': 1, 'schema': 1}))


def proposal_token(operation):
    data = ':'.join(map(str, (operation.organization_id, operation.contact_id,
        operation.operation_key, operation.expires_at.isoformat())))
    # The random immutable UUID supplies entropy. No global signing-key rotation
    # can change the rendering of a historical proposal. This UX code is NOT
    # authentication; scope/permission/receipt validation remains mandatory.
    return hmac.new(operation.operation_key.bytes, data.encode(), hashlib.sha256).hexdigest()[:12].upper()


def render_proposal(operation):
    if attendance_contract(operation):
        return (operations.render(operation) + '\nPara declarar tu intención de asistir, '
            'responde citando este mensaje: SÍ CONFIRMO QUE ASISTIRÉ. También puedes responder '
            'CONFIRMAR ' + proposal_token(operation) + '. Para rechazarla responde NO. '
            'Tu declaración quedará registrada; la operación sigue pendiente de ejecución.')
    return (operations.render(operation) + '\n¿Confirmas esta propuesta exacta? '
        'Para aceptarla responde CONFIRMAR ' + proposal_token(operation)
        + '. Para rechazarla responde NO. La operación solo se realizará si siguen vigentes '
          'los permisos y las condiciones de esta propuesta.')


def attendance_contract(operation):
    """Only newly defined B8D cards can open this bounded contextual channel."""
    pre = operation.preconditions
    snapshot = pre.get('appointment_snapshot', {})
    return (operation.operation_kind == 'CONFIRM_ATTENDANCE'
        and operation.authorization_mode == 'CONTEXTUAL_DECLARATION'
        and pre.get('schema') == 3 and pre.get('attendance_contract') == 1
        and isinstance(snapshot, dict) and snapshot.get('schema') == 1
        and snapshot.get('status') == 'scheduled'
        and snapshot.get('appointment_id') == operation.appointment_id
        and snapshot.get('organization_id') == operation.organization_id
        and snapshot.get('pet_id') == operation.pet_id)


def authorization_mode_enabled(operation):
    return operation.authorization_mode == 'EXPLICIT_CONFIRMATION' or attendance_contract(operation)


def authorization_policy(operation):
    return ATTENDANCE_POLICY_VERSION if attendance_contract(operation) else POLICY_VERSION


def has_proposal_snapshot(operation):
    # B7A never emitted proposals. Old appointment definitions have no visible
    # original-vet snapshot; do not turn the renderer's fallback into a fact.
    if operation.authorization_mode == 'CONTEXTUAL_DECLARATION' and not attendance_contract(operation):
        return False
    if operation.operation_kind == 'REGISTER_PET':
        from .pet_execution import registration_contract
        return registration_contract(operation)
    return not operation.appointment_id or bool(
        operation.preconditions.get('labels', {}).get('original_veterinarian'))


def message_matches(operation, message):
    conv = operation.conversation
    return bool(has_proposal_snapshot(operation) and message and operation.proposal_message_id == message.pk
        and message.organization_id == operation.organization_id
        and message.conversation_id == operation.conversation_id
        and message.channel_account_id == conv.channel_account_id
        and message.contact_id == operation.contact_id == conv.contact_id
        and message.direction == 'out' and message.author_type == Message.AUTHOR_SYSTEM
        and message.semantic_type == Message.SEMANTIC_CONFIRMATION
        and message.operation_key == str(operation.operation_key)
        and message.origin_epoch == operation.ownership_epoch
        and message.turn_work_id is not None and message.is_active
        and message.body == render_proposal(operation))


@dataclass(frozen=True)
class EmissionEvidence:
    field: str
    observed_at: datetime


def emission_evidence(operation, message):
    if (not message_matches(operation, message)
            or message.status not in ('sent', 'delivered', 'read')
            or not valid_provider_id(message.external_message_id)
            or message.send_admitted_at is None or message.send_token is None):
        return None
    work = message.turn_work
    if (work.status != 'COMPLETED' or work.organization_id != operation.organization_id
            or work.conversation_id != operation.conversation_id
            or work.ownership_epoch != operation.ownership_epoch):
        return None
    stamps = [(getattr(message, field), field) for field in
              ('provider_accepted_at', 'delivered_at', 'read_at') if getattr(message, field)]
    if not stamps:
        return None
    stamp, field = min(stamps)
    if stamp < message.send_admitted_at:
        return None
    return EmissionEvidence(field, stamp)


def is_proposal_emitted(operation, message=None):
    # Read fresh delivery state; an ORM relation cached before dispatch is not evidence.
    if message is None:
        message = Message.objects.filter(pk=operation.proposal_message_id).first()
    return bool(emission_evidence(operation, message)
        and not Message.objects.filter(supersedes_message_id=message.pk).exists()
        and Message.objects.filter(organization_id=message.organization_id,
            channel_account_id=message.channel_account_id, direction='out',
            external_message_id=message.external_message_id).count() == 1)


def capture_receipt(channel_account, external_contact_id):
    """First reception SELECT: MVCC sees only already committed B4 evidence.

    This runs BEFORE identity resolution or waiting on Conversation. An inbound
    concurrent with HTTP/SENT persistence cannot acquire evidence retroactively.
    The rows and statement timestamp are read by ONE SELECT. No provider clock,
    synthetic timestamp, untrusted raw key, transcript or delivery state copy.
    """
    if not enabled():
        return None
    from .models import ConversationOperation
    rows = list(ConversationOperation.objects.filter(
        organization_id=channel_account.organization_id,
        conversation__channel_account_id=channel_account.pk,
        contact__external_id=external_contact_id, consent_state='PENDING',
        proposal_message__isnull=False).select_related('proposal_message__turn_work', 'conversation')
        .annotate(received_at=Now()).order_by('pk')[:17])
    observed = []
    received_at = rows[0].received_at if rows else durable.db_now()
    if len(rows) <= 16:
        for operation in rows:
            evidence = emission_evidence(operation, operation.proposal_message)
            if (evidence and evidence.observed_at < received_at < operation.expires_at):
                observed.append({'message_id': operation.proposal_message_id,
                                 'field': evidence.field})
    return {'version': POLICY_VERSION, 'received_at': received_at.isoformat(),
            'observed': observed}


def publish_proposal(witness, operation, *, ordinal):
    """Only finalize_turn calls this, in its local publication transaction."""
    from .models import ConversationOperation
    from .operation_model_contract import _lifecycle
    if not enabled() or not transaction.get_connection().in_atomic_block:
        raise ValueError('B7B proposal requires enabled local publication')
    conv, work = durable.lock_witness(witness)
    if (operation.organization_id != conv.organization_id or operation.conversation_id != conv.pk
            or durable.has_new_input(work)):
        raise ValueError('Proposal scope/cursor mismatch')
    operation = operations.revalidate(operation)
    if operation.consent_state != 'PENDING' or not authorization_mode_enabled(operation):
        return None
    if not has_proposal_snapshot(operation):
        ConversationOperation.objects.filter(pk=operation.pk).retire_pending(
            'INVALIDATED', 'proposal_contract_changed')
        observe('consent_stale')
        return None
    if operation.proposal_message_id:
        return operation.proposal_message  # never another output on retry
    # Short-token collisions are explicitly rejected in the actor/conversation
    # scope, including historical proposals. No arbitrary winner or new UUID.
    peers = ConversationOperation.objects.filter(conversation=conv,
        organization_id=conv.organization_id, proposal_message__isnull=False).exclude(pk=operation.pk)
    if any(proposal_token(peer) == proposal_token(operation) for peer in peers):
        raise ValueError('Proposal token collision')
    message = Message.objects.create(organization_id=conv.organization_id,
        conversation=conv, channel_account_id=conv.channel_account_id, contact_id=conv.contact_id,
        direction='out', status='pending', author_type=Message.AUTHOR_SYSTEM,
        semantic_type=Message.SEMANTIC_CONFIRMATION, operation_key=str(operation.operation_key),
        turn_work=work, origin_epoch=witness.ownership_epoch, output_ordinal=ordinal,
        body=render_proposal(operation))
    operation.proposal_message = message
    token = _lifecycle.set('proposal')
    try:
        operation.save(update_fields=['proposal_message', 'updated_at'])
    finally:
        _lifecycle.reset(token)
    durable.check_turn_deadline(witness)
    observe('proposal_created')
    observe('proposal_emission_pending')
    return message


def dispatch_rejection(message, conv):
    """Called under B4 Conversation lock before claim AND HTTP admission."""
    from .models import ConversationOperation
    operation = ConversationOperation.objects.filter(organization_id=message.organization_id,
        conversation_id=conv.pk, proposal_message_id=message.pk).first()
    if operation is None:
        # Other historical confirmation outputs have no B7B authority.
        return 'proposal_unbound' if message.operation_key and enabled() else ''
    if not enabled():
        return 'consent_disabled'
    # B4 currently owns Message. revalidate takes identity/goal/operation after
    # Conversation; no identity writer takes Message, so no reversed lock edge.
    operation = operations.revalidate(operation)
    if operation.consent_state != 'PENDING' or not message_matches(operation, message):
        return 'proposal_stale'
    if Message.objects.filter(supersedes_message=message).exists():
        return 'proposal_superseded'
    if durable.has_new_input(message.turn_work):
        return 'proposal_new_input'
    return ''


def proposal_stage(operation):
    if not operation.proposal_message_id:
        return 'PREPARED'
    message = Message.objects.filter(pk=operation.proposal_message_id).first()
    if is_proposal_emitted(operation, message):
        return 'EMISSION_VERIFIED'
    return 'UNCERTAIN' if message and message.status == 'uncertain' else 'PERSISTED'


def observe_delivery(message):
    """B4 keeps state ownership; B7B emits only a bounded observation event."""
    from .models import ConversationOperation
    if message.semantic_type != Message.SEMANTIC_CONFIRMATION:
        return
    operation = ConversationOperation.objects.filter(organization_id=message.organization_id,
        conversation_id=message.conversation_id, proposal_message_id=message.pk).first()
    if operation is None:
        return
    if message.status == 'uncertain':
        observe('proposal_emission_uncertain')
    elif is_proposal_emitted(operation, message):
        observe('proposal_emission_verified')
