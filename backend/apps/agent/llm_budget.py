"""B9 operational admission, not billing. No network while locks are held."""
import json
import logging
from uuid import uuid4

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from . import durable
from .llm import DEFAULT_MAX_TOKENS, LLMError, valid_token_count
from .models import LLMCall, TurnWork
from .turn_changes import current_changes

logger = logging.getLogger('agent.events')
PURPOSES = ('planner', 'operation_authorizer', 'operation_verifier')
MAX_INPUT_BYTES = 65536


class BudgetRejected(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _event(name, purpose):
    logger.info(name, extra={'event': name, 'purpose': purpose})


def admit(witness, *, admission_id, purpose, max_tokens, model_id,
          prompt_version, retry_of=None):
    """Commit one slot exactly once. A replay grants no new provider dispatch.

    durable=True rejects nesting in application transactions. Django's TestCase
    outer wrapper is test-only; real durability is tested with committed fixtures.
    """
    if purpose not in PURPOSES or type(max_tokens) is not int or not 0 < max_tokens <= DEFAULT_MAX_TOKENS:
        raise BudgetRejected('llm_budget_invalid_request')
    with transaction.atomic(durable=True):
        _, work = durable.lock_witness(witness)
        durable.check_turn_deadline(witness)
        existing = LLMCall.objects.filter(admission_id=admission_id).first()
        if existing is not None:
            if (existing.organization_id != witness.organization_id or
                    existing.turn_work_id != witness.turn_work_id or
                    existing.purpose != purpose or existing.reserved_output_tokens != max_tokens or
                    existing.admission_lease_token != witness.lease_token):
                raise BudgetRejected('llm_admission_scope_mismatch')
            return existing, False
        if work.llm_calls_admitted is None or work.llm_output_tokens_reserved is None:
            raise BudgetRejected('llm_budget_legacy_unknown')
        if (work.llm_calls_admitted >= work.llm_call_limit or
                work.llm_output_tokens_reserved + max_tokens > work.llm_output_token_limit):
            _event('llm_budget_exhausted', purpose)
            raise BudgetRejected('llm_budget_exhausted')
        if retry_of is not None and not LLMCall.objects.filter(pk=retry_of,
                organization_id=witness.organization_id, turn_work=work,
                purpose=purpose).exists():
            raise BudgetRejected('llm_retry_scope_mismatch')
        call = LLMCall.objects.create(
            organization_id=witness.organization_id, conversation_id=witness.conversation_id,
            turn_work=work, admission_id=admission_id, admitted_at=timezone.now(),
            admission_lease_token=witness.lease_token, admission_epoch=witness.ownership_epoch,
            purpose=purpose, reserved_output_tokens=max_tokens,
            provider='openai_compatible', model_id=str(model_id)[:64],
            prompt_version=prompt_version, retry_of_id=retry_of)
        TurnWork.objects.filter(pk=work.pk, organization_id=witness.organization_id).update(
            llm_calls_admitted=F('llm_calls_admitted') + 1,
            llm_output_tokens_reserved=F('llm_output_tokens_reserved') + max_tokens)
        transaction.on_commit(lambda: _event('llm_budget_admitted', purpose))
    return call, True


def record(call, *, result=None, error=None):
    """Record observation once, even after loss of witness; never return quota.

    The internal scoped call row is authority to record provider evidence, not to
    publish conversation output or perform domain work. No arbitrary error text.
    """
    usage = vars(result) if result is not None else (getattr(error, 'usage', None) or {})
    values = dict(input_tokens=valid_token_count(usage.get('input_tokens')),
                  output_tokens=valid_token_count(usage.get('output_tokens')),
                  recorded_at=timezone.now(),
                  error='provider_error' if error is not None else '')
    # No new commercial pricing policy; unknown cost remains NULL.
    latency = valid_token_count(usage.get('latency_ms'))
    values['latency_ms'] = latency
    if result is not None:
        reason = result.finish_reason
        values['finish_reason'] = reason if reason in (
            'stop', 'length', 'tool_calls', 'function_call', 'content_filter') else ''
    with transaction.atomic(durable=call.admission_id is not None):
        changed = LLMCall.objects.filter(pk=call.pk, organization_id=call.organization_id,
            conversation_id=call.conversation_id, turn_work_id=call.turn_work_id,
            admission_id=call.admission_id, recorded_at__isnull=True).update(**values)
    if changed:
        _event('llm_usage_recorded' if all(values[k] is not None for k in
            ('input_tokens', 'output_tokens')) else 'llm_usage_unavailable', call.purpose)


def complete(conversation, client, *, purpose, prompt_version, retry_of=None, **kwargs):
    """Single accounting boundary for the three agent call sites and evals."""
    max_tokens = kwargs.setdefault('max_tokens', DEFAULT_MAX_TOKENS)
    payload = {key: kwargs.get(key) for key in ('system', 'messages', 'tools')}
    if len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > MAX_INPUT_BYTES:
        raise BudgetRejected('llm_input_limit')
    changes = current_changes()
    if changes is not None:
        changes.scope(conversation)
        try:
            call, fresh = admit(changes.witness, admission_id=uuid4(), purpose=purpose,
                max_tokens=max_tokens, model_id=getattr(client, 'model', ''),
                prompt_version=prompt_version, retry_of=retry_of)
        except BudgetRejected:
            _event('llm_budget_rejected', purpose)
            raise
        if not fresh:
            raise BudgetRejected('llm_admission_already_observed')
    else:
        # Historical helper/eval path: no TurnWork, no claim of beta admission.
        call = LLMCall.objects.create(organization_id=conversation.organization_id,
            conversation=conversation, provider='openai_compatible',
            model_id=str(getattr(client, 'model', ''))[:64], purpose=purpose,
            prompt_version=prompt_version, retry_of_id=retry_of)
    try:
        result = client.complete(**kwargs)
    except LLMError as exc:
        record(call, error=exc)
        exc.llm_call_id = call.pk
        raise
    record(call, result=result)
    result.llm_call_id = call.pk
    return result


def inspect_turn(*, organization_id, turn_work_id):
    """Read-only, explicit tenant authority; never loads prompt/response content."""
    work = TurnWork.objects.get(pk=turn_work_id, organization_id=organization_id)
    calls = list(LLMCall.objects.filter(organization_id=organization_id, turn_work=work)
        .order_by('id').values('id', 'admission_id', 'purpose', 'model_id', 'retry_of_id',
            'admitted_at', 'recorded_at', 'reserved_output_tokens', 'input_tokens',
            'output_tokens', 'cost_estimate', 'error'))
    admissions = [c for c in calls if c['admission_id'] is not None]
    return {'turn_work_id': work.pk, 'call_limit': work.llm_call_limit,
        'output_token_limit': work.llm_output_token_limit,
        'calls_admitted': work.llm_calls_admitted,
        'output_tokens_reserved': work.llm_output_tokens_reserved,
        'calls_remaining': (None if work.llm_calls_admitted is None else
                            work.llm_call_limit - work.llm_calls_admitted),
        'calls': calls,
        'evidence_matches_counters': (None if work.llm_calls_admitted is None or
            work.llm_output_tokens_reserved is None else
            len(admissions) == work.llm_calls_admitted and
            sum(c['reserved_output_tokens'] for c in admissions) == work.llm_output_tokens_reserved),
        'usage_unavailable': sum(c['input_tokens'] is None or c['output_tokens'] is None for c in calls),
        'unobserved_admissions': sum(c['recorded_at'] is None for c in calls)}
