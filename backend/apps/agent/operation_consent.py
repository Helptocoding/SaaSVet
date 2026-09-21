"""B7B bounded consent adapter. AUTHORIZED never calls a business tool."""
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from apps.channels.models import Message
from apps.channels.providers import valid_provider_id
from . import durable, operations
from .durable import db_now
from .operation_proposals import (RECEIPT_KEY, POLICY_VERSION, enabled, observe,
    proposal_token, render_proposal, is_proposal_emitted, EmissionEvidence)


@dataclass(frozen=True)
class Evaluation:
    decision: str
    reason: str
    operation_id: int | None = None
    duplicate: bool = False


@dataclass(frozen=True)
class AuthorizationEvidence:
    operation_key: UUID
    parameters_digest: str
    proposal_message_id: int
    proposal_provider_message_id: str
    proposal_emission_evidence: EmissionEvidence
    response_message_id: int
    response_turn_id: int
    actor_contact_id: int
    authorization_mode: str
    binding_revision: int
    identity_revision: int
    ownership_epoch: int
    decision: str
    decision_at: datetime

    def __post_init__(self):
        if (not isinstance(self.operation_key, UUID)
                or not re.fullmatch('[0-9a-f]{64}', self.parameters_digest)
                or not valid_provider_id(self.proposal_provider_message_id)
                or not isinstance(self.proposal_emission_evidence, EmissionEvidence)
                or self.decision not in ('ACCEPT', 'REJECT')
                or self.authorization_mode != 'EXPLICIT_CONFIRMATION'
                or not self.decision_at or self.decision_at.tzinfo is None
                or any(type(x) is not int or x <= 0 for x in (self.proposal_message_id,
                    self.response_message_id, self.response_turn_id, self.actor_contact_id))):
            raise ValueError('Incomplete causal authorization evidence')


def normalize(text):
    # Preserve emoji, digits, extra content and punctuation inside the answer.
    text = ''.join(c for c in unicodedata.normalize('NFD', text.casefold())
                   if unicodedata.category(c) != 'Mn')
    return ' '.join(text.strip().rstrip('.!').split())


def classify(text, operation=None):
    value = normalize(text)
    if '?' in value or '¿' in value:
        return Evaluation('IRRELEVANT', 'question')
    correction = (re.search(r'\b(pero|mejor|otra|otro|cambia|cambiar)\b', value)
                  or (re.match(r'^(si|no|confirmo|confirmar)\b', value)
                      and re.search(r'\bpara\b', value)))
    if correction and value != 'no mejor no':
        return Evaluation('AMBIGUOUS', 'correction')
    if re.search(r'\b(si (hay|todavia|aun)|siempre que|con tal|menos de)\b', value):
        return Evaluation('AMBIGUOUS', 'conditional')
    if re.search(r'\b(y|tambien)\b', value):
        return Evaluation('AMBIGUOUS', 'multiple_intents')
    if value in {'no', 'no mejor no', 'no quiero cancelarla', 'olvida la propuesta',
                 'no estoy de acuerdo', 'no 👍', 'no estoy de acuerdo 👍'}:
        return Evaluation('REJECT', 'explicit_rejection')
    if operation and value == 'confirmar ' + proposal_token(operation).lower():
        return Evaluation('ACCEPT', 'exact_token')
    if value in {'si confirmo', 'confirmo esa cita', 'si cancelala', 'si'}:
        if value == 'si cancelala' and operation and operation.operation_kind != 'CANCEL_APPOINTMENT':
            return Evaluation('AMBIGUOUS', 'action_mismatch')
        if (value == 'confirmo esa cita' and operation
                and operation.operation_kind not in ('CREATE_APPOINTMENT', 'RESCHEDULE_APPOINTMENT')):
            return Evaluation('AMBIGUOUS', 'action_mismatch')
        return Evaluation('ACCEPT', 'explicit_text')
    if not value or value in {'aja', 'bueno', 'esta bien', 'como veas', '👍', 'ok', 'perfecto'}:
        return Evaluation('AMBIGUOUS', 'unclear')
    if value.startswith(('si ', 'confirm', 'no ')):
        return Evaluation('AMBIGUOUS', 'extra_content')
    return Evaluation('IRRELEVANT', 'other_message')


def _receipt_evidence(operation, response):
    """No inference from final SENT or Message.created_at alone."""
    proposal = operation.proposal_message
    receipt = (response.raw_metadata or {}).get(RECEIPT_KEY, {})
    if not isinstance(receipt, dict) or receipt.get('version') != POLICY_VERSION:
        return None
    try:
        received = datetime.fromisoformat(receipt['received_at'])
        if not received.tzinfo:
            return None
        observed = receipt['observed']
        if not isinstance(observed, list):
            return None
        matches = [x for x in observed if isinstance(x, dict) and x.get('message_id') == proposal.pk]
        if len(matches) != 1 or matches[0].get('field') not in (
                'provider_accepted_at', 'delivered_at', 'read_at'):
            return None
        field = matches[0]['field']
        stamp = getattr(proposal, field)
        if not stamp or not stamp < received < operation.expires_at:
            return None
        return EmissionEvidence(field, stamp)
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def authorization_evidence(operation):
    """Value object from protected references; no duplicated transcript/digest."""
    response = operation.authorization_message
    if not response or operation.consent_state not in ('AUTHORIZED', 'REJECTED'):
        raise ValueError('No terminal consent evidence')
    if (response.organization_id != operation.organization_id
            or response.conversation_id != operation.conversation_id
            or response.contact_id != operation.contact_id
            or response.channel_account_id != operation.conversation.channel_account_id
            or response.direction != 'in' or response.author_type != Message.AUTHOR_CLIENT
            or not response.turn_work_id or response.turn_work.organization_id != operation.organization_id
            or response.turn_work.conversation_id != operation.conversation_id
            or operation.authorization_channel != 'whatsapp'
            or operation.authorization_policy_version != POLICY_VERSION):
        raise ValueError('Consent evidence scope mismatch')
    return AuthorizationEvidence(operation.operation_key, operation.parameters_digest,
        operation.proposal_message_id, operation.proposal_message.external_message_id,
        _receipt_evidence(operation, response), response.pk, response.turn_work_id,
        response.contact_id, operation.authorization_mode, operation.binding_revision,
        operation.identity_revision, operation.ownership_epoch,
        'ACCEPT' if operation.consent_state == 'AUTHORIZED' else 'REJECT', operation.consent_decided_at)


def execution_authorization_evidence(operation):
    """Recheck the protected B7B evidence, not just the historical state bit.

    Does not re-authorize, consult a model, renew TTL or require the old lease.
    The execution guard separately checks current authority and expiry.
    """
    from apps.channels.events import event_from_message
    evidence = authorization_evidence(operation)
    response = operation.authorization_message
    work = response.turn_work
    if (evidence.decision != 'ACCEPT' or operation.authorized_at != evidence.decision_at
            or not operation.created_at <= evidence.decision_at < operation.expires_at
            or not is_proposal_emitted(operation)
            or not response.is_active or response.status not in ('pending', 'processed')
            or not valid_provider_id(response.external_message_id)
            or operation.conversation.channel_account.channel_type != 'whatsapp'
            or work.ownership_epoch != evidence.ownership_epoch
            or work.anchor_message_id != response.pk or work.cursor_message_id != response.pk
            or work.anchor_created_at != response.created_at or work.cursor_created_at != response.created_at
            or Message.objects.filter(turn_work=work, direction='in').count() != 1):
        raise ValueError('Invalid execution authorization evidence')
    received = datetime.fromisoformat(response.raw_metadata[RECEIPT_KEY]['received_at'])
    if not evidence.proposal_emission_evidence.observed_at < received <= evidence.decision_at:
        raise ValueError('Consent decision is not causally subsequent')
    event = event_from_message(response)
    if event.body_source != 'text' or event.event_type != 'text':
        raise ValueError('Unsupported consent event')
    verdict = classify(event.text, operation)
    if verdict.decision != 'ACCEPT':
        raise ValueError('Response did not authorize the operation')
    if event.reply_to_id:
        matches = Message.objects.filter(organization_id=operation.organization_id,
            conversation_id=operation.conversation_id, channel_account_id=response.channel_account_id,
            contact_id=operation.contact_id, direction='out', external_message_id=event.reply_to_id)
        if (not valid_provider_id(event.reply_to_id) or matches.count() != 1
                or matches.first().pk != operation.proposal_message_id):
            raise ValueError('Consent reply does not identify the exact proposal')
    elif verdict.reason != 'exact_token':
        raise ValueError('Unreferenced consent requires the exact proposal token')
    return evidence


def _persist_decision(operation, response, verdict, now):
    from .operation_model_contract import _lifecycle
    operation.consent_state = 'AUTHORIZED' if verdict.decision == 'ACCEPT' else 'REJECTED'
    operation.authorization_message = response
    operation.consent_decided_at = now
    operation.authorized_at = now if verdict.decision == 'ACCEPT' else None
    operation.authorization_channel = 'whatsapp'
    operation.authorization_policy_version = POLICY_VERSION
    authorization_evidence(operation)
    token = _lifecycle.set('decision')
    try:
        operation.save(update_fields=['consent_state', 'authorization_message', 'consent_decided_at',
            'authorized_at', 'authorization_channel', 'authorization_policy_version', 'updated_at'])
    finally:
        _lifecycle.reset(token)


def _between(proposal, response, conversation):
    # B1 history range used only to detect ambiguity, NEVER to find an older yes.
    return Message.objects.filter(organization_id=conversation.organization_id,
        conversation=conversation).exclude(status='discarded').exclude(pk__in=(proposal.pk, response.pk)).filter(
        Q(created_at__gt=proposal.created_at) | Q(created_at=proposal.created_at, pk__gt=proposal.pk)).filter(
        Q(created_at__lt=response.created_at) | Q(created_at=response.created_at, pk__lt=response.pk)).exists()


def evaluate_turn(witness):
    """One atomic terminal decision, current B3 scope, no LLM/HTTP/WRITE."""
    from .models import ConversationOperation, ContactIdentity, ConversationGoal, Conversation
    from . import safety, safety_handoff
    if not enabled():
        return Evaluation('STALE', 'disabled')
    with transaction.atomic():
        conv, work = durable.lock_witness(witness)
        durable.check_turn_deadline(witness)
        context = durable.context_for_work(witness)
        if conv.state != Conversation.STATE_ACTIVE or conv.claimed_by_id:
            observe('consent_takeover_blocked')
            return Evaluation('STALE', 'human_ownership')
        # B5 detector takes precedence even if its operational activation is off.
        if (safety.assess_context(conv, context).classification != safety.NO_SIGNAL
                or safety_handoff.pending_signal(conv)):
            return Evaluation('STALE', 'safety')
        conv.contact = ContactIdentity.all_objects.select_for_update().get(
            pk=conv.contact_id, organization_id=conv.organization_id)
        # Preserve B7A lock order, including when revalidate is called below.
        list(ConversationGoal.objects.select_for_update().filter(conversation=conv).order_by('pk'))
        ops = list(ConversationOperation.objects.select_for_update().filter(
            organization_id=conv.organization_id, conversation=conv).order_by('pk'))
        terminal = [op for op in ops if op.authorization_message_id in context.inbound_ids]
        if terminal:
            observe('consent_duplicate_ignored')
            op = terminal[0]
            return Evaluation('ACCEPT' if op.consent_state == 'AUTHORIZED' else 'REJECT',
                              'duplicate', op.pk, True)
        if durable.has_new_input(work):
            return Evaluation('STALE', 'new_input')
        if len(context.events) != 1:
            # A correction/condition in any member retires the pending scope.
            if any(classify(event.text).reason in ('correction', 'conditional') for event in context.events):
                operations.invalidate_pending(organization_id=conv.organization_id,
                    conversation_id=conv.pk, reason='consent_correction')
            observe('consent_ambiguous')
            return Evaluation('AMBIGUOUS', 'multiple_messages')
        from .turn_context import messages_for_turn
        response = messages_for_turn(conv, context)[0]
        event = context.events[0]
        if (response.contact_id != conv.contact_id or response.author_type != Message.AUTHOR_CLIENT
                or context.channel_type != 'whatsapp'
                or response.turn_work_id != work.pk or response.status != 'pending'
                or event.body_source != 'text' or event.event_type != 'text'
                or not valid_provider_id(response.external_message_id)):
            return Evaluation('STALE', 'response_scope')
        # Explicit provider reference always wins, including invalid references.
        referenced = None
        if event.reply_to_id:
            matches = Message.objects.filter(organization_id=conv.organization_id, conversation=conv,
                channel_account_id=conv.channel_account_id, contact_id=conv.contact_id,
                direction='out', external_message_id=event.reply_to_id)
            if not valid_provider_id(event.reply_to_id) or matches.count() != 1:
                return Evaluation('STALE', 'reply_scope')
            referenced = matches.get().pk
        candidates = []
        for op in ops:
            if referenced is not None and op.proposal_message_id != referenced:
                continue
            if op.consent_state == 'PENDING':
                op = operations.revalidate(op)
                if op.consent_state == 'PENDING' and op.expires_at <= db_now():
                    ConversationOperation.objects.filter(pk=op.pk).retire_pending('EXPIRED', 'ttl_elapsed')
                    op.refresh_from_db()
            if op.consent_state != 'PENDING':
                if op.consent_state == 'EXPIRED':
                    observe('consent_expired')
                elif op.invalidation_reason == 'identity_changed':
                    observe('consent_identity_blocked')
                elif op.invalidation_reason == 'permission_changed':
                    observe('consent_permission_blocked')
                continue
            if not is_proposal_emitted(op):
                observe('proposal_emission_uncertain' if op.proposal_message_id and
                        op.proposal_message.status == 'uncertain' else 'proposal_emission_pending')
                continue
            if not _receipt_evidence(op, response):
                continue
            candidates.append(op)
        if len(candidates) != 1:
            result = 'AMBIGUOUS' if len(candidates) > 1 else 'STALE'
            observe('consent_' + result.lower())
            return Evaluation(result, 'proposal_ambiguous' if candidates else 'proposal_ineligible')
        op = candidates[0]
        observe('proposal_emission_verified')
        verdict = classify(event.text, op)
        if verdict.reason in ('correction', 'conditional'):
            operations.invalidate_pending(organization_id=conv.organization_id,
                pk=op.pk, reason='consent_' + verdict.reason)
        if op.authorization_mode != 'EXPLICIT_CONFIRMATION':
            return Evaluation('AMBIGUOUS', 'contextual_mode_disabled', op.pk)
        if verdict.decision in ('ACCEPT', 'REJECT'):
            if referenced is None and (
                    (verdict.decision == 'REJECT' and _between(op.proposal_message, response, conv))
                    or (verdict.decision == 'ACCEPT' and verdict.reason != 'exact_token')):
                observe('consent_ambiguous')
                return Evaluation('AMBIGUOUS', 'explicit_reference_required', op.pk)
            now = db_now()
            if now >= op.expires_at:
                ConversationOperation.objects.filter(pk=op.pk).retire_pending('EXPIRED', 'ttl_elapsed')
                observe('consent_expired')
                return Evaluation('STALE', 'expired', op.pk)
            _persist_decision(op, response, verdict, now)
            durable.check_turn_deadline(witness)
            observe('consent_accepted' if verdict.decision == 'ACCEPT' else 'consent_rejected')
        else:
            observe('consent_ambiguous')
        return Evaluation(verdict.decision, verdict.reason, op.pk)


def reply_text(result):
    if result.decision == 'ACCEPT':
        return 'Tu consentimiento quedó registrado para esa propuesta. La operación sigue pendiente de ejecución.'
    if result.decision == 'REJECT':
        return 'Propuesta rechazada. No se realizó ningún cambio.'
    if result.reason in ('correction', 'conditional'):
        return 'La propuesta anterior quedó invalidada. Necesito preparar una propuesta con los datos corregidos.'
    return ('No pude registrar un consentimiento inequívoco. Responde a la propuesta vigente '
            'con el código CONFIRMAR indicado, o cita ese mensaje para confirmar o rechazar.')


def retire_unresolved_corrections(changes):
    """After B6 flush: unknown corrections cannot leave old consent eligible.

    B6 alone supplies replacements. If it did not revise a binding, do not
    silently re-propose the old parameters as though the correction resolved.
    """
    if not enabled():
        return False
    from .models import ConversationOperation
    if not ConversationOperation.objects.filter(organization_id=changes.witness.organization_id,
            conversation_id=changes.witness.conversation_id).exists():
        return False
    context = durable.context_for_work(changes.witness)
    if not any(classify(event.text).reason == 'correction' for event in context.events):
        return False
    operations.invalidate_pending(organization_id=changes.witness.organization_id,
        conversation_id=changes.witness.conversation_id, reason='consent_correction')
    from .models import ConversationGoal
    return not any(goal.binding_revision != changes.binding_revisions.get(goal.pk)
        for goal in ConversationGoal.objects.filter(conversation_id=changes.witness.conversation_id,
            organization_id=changes.witness.organization_id, status__in=ConversationGoal.FOREGROUND_STATUSES))
