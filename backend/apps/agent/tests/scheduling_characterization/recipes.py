"""Executable scenario specifications and conservative transition witnesses.

Evidence events contain technical metadata only. A scheduled injection is not
its boundary: absence of the matching observed transition leaves it unproven.
"""
from dataclasses import dataclass

from .evidence import NS


@dataclass(frozen=True)
class Recipe:
    case_id: str
    variants: tuple
    prerequisites: tuple
    transitions: tuple
    natural_recovery: bool = False


RECIPES = {
    'R1-01': Recipe('R1-01', ('ordinary',), (), ('multiple_conversations',)),
    'R1-02': Recipe('R1-02', ('balanced',), (), ('concurrent_planners', 'balanced_offer')),
    'R1-03': Recipe('R1-03', ('unequal',), ('R1-02',), ('concurrent_planners', 'same_global_2_to_1')),
    'R1-04': Recipe('R1-04', ('forecasts',), (), ('ready_waiter', 'future_eligibility', 'forecast_miss', 'future_eligibility_again')),
    'R1-05': Recipe('R1-05', ('simultaneous', 'concentrated'), ('CONFIRMED_BASE',), ('burst_begin', 'burst_end', 'base_return', 'drain_cut')),
    'R1-06': Recipe('R1-06', ('backlog',), ('CONFIRMED_BASE',), ('captured_backlog', 'natural_ready', 'workers_start', 'drain_cut')),
    'R1-07': Recipe('R1-07', ('w1_w2', 'deadline_before', 'deadline_at', 'deadline_after', 'no_poll', 'legacy_null'), (),
                    ('first_ready', 'preclaim_correction', 'w1_commit', 'postclaim_input', 'w2_ready', 'duplicate', 'w2_commit')),
    'R2-01': Recipe('R2-01', ('slow',), ('CONFIRMED_BASE',), ('slow_service_begin', 'slow_service_end', 'peer_progress')),
    'R2-02': Recipe('R2-02', ('blocked',), ('CONFIRMED_BASE',), ('llm_admitted', 'block_begin', 'peer_progress', 'block_release')),
    'R2-03': Recipe('R2-03', ('precommit',), ('CONFIRMED_BASE',), ('prepared_membership', 'precommit_crash', 'rollback_resolved', 'next_new_claim')),
    'R2-04': Recipe('R2-04', ('postcommit',), ('CONFIRMED_BASE',), ('outer_commit', 'postcommit_crash', 'natural_expiry', 'same_work_reclaimed', 'old_witness_fenced'), True),
    'R2-05': Recipe('R2-05', ('retry', 'exhaustion'), ('CONFIRMED_BASE',), ('provider_error', 'retry_scheduled', 'natural_retry_due', 'same_work_retry', 'retry_terminal'), True),
    'R2-06': Recipe('R2-06', ('restart',), ('CONFIRMED_BASE',), ('pending_and_processing', 'workers_stop', 'workers_restart', 'history_preserved', 'recovery_terminal'), True),
    'R2-07': Recipe('R2-07', ('org_lock', 'message_lock', 'outer_rollback', 'savepoint_rollback', 'lost_ack'), ('CONFIRMED_BASE',), ()),
    'R2-08': Recipe('R2-08', ('safety_before', 'safety_after', 'takeover_before', 'takeover_after', 'w1_w2'), ('CONFIRMED_BASE',),
                    ('ordinary_population_captured', 'safety_or_takeover', 'epoch_advanced', 'old_witness_fenced', 'interruption_inventory')),
    'R2-09': Recipe('R2-09', ('slow_meta', 'uncertain_meta'), ('CONFIRMED_BASE',), ('sender_admitted', 'meta_dispatch', 'meta_result', 'ordinary_progress', 'no_blind_resend')),
    'R2-10': Recipe('R2-10', ('expired_consent', 'expired_authority', 'cross_tenant', 'closed_gate'), ('CONFIRMED_BASE',),
                    ('guard_input', 'guard_denied', 'no_domain_effect')),
}
LOCK_TRANSITIONS = {
    'org_lock': ('lock_acquired', 'first_proven_miss', 'lock_released', 'next_new_claim'),
    'message_lock': ('lock_acquired', 'transaction_wait_witness', 'lock_released', 'next_new_claim'),
    'outer_rollback': ('prepared_membership', 'outer_rollback', 'rollback_resolved', 'next_new_claim'),
    'savepoint_rollback': ('prepared_membership', 'savepoint_rollback', 'outer_resolved', 'next_new_claim'),
    'lost_ack': ('outer_commit_ack_error', 'independent_visibility', 'durable_witness_verified'),
}
DEADLINE_TRANSITIONS = {
    'deadline_before': ('accepted_before_deadline', 'first_ready', 'w1_commit'),
    'deadline_at': ('acceptance_interval_crosses_deadline', 'ready_interval_retained', 'w1_commit'),
    'deadline_after': ('first_ready', 'accepted_after_deadline', 'origin_not_reset', 'w1_commit'),
    'no_poll': ('deadline_elapsed_without_poll', 'first_poll_after_deadline', 'original_ready_retained', 'w1_commit'),
    'legacy_null': ('legacy_null_captured', 'legacy_origin_known_or_unknown_retained', 'w1_commit'),
}


def required_transitions(case_id, variant):
    recipe = RECIPES[case_id]
    if variant not in recipe.variants:
        raise ValueError('Undeclared scenario variant')
    if case_id == 'R2-07':
        return LOCK_TRANSITIONS[variant]
    if case_id == 'R1-07' and variant in DEADLINE_TRANSITIONS:
        return DEADLINE_TRANSITIONS[variant]
    if case_id == 'R2-08':
        prefix = ('ordinary_population_captured', 'ordinary_claim_committed') if variant.endswith('after') else ('ordinary_population_captured',)
        if variant == 'w1_w2':
            prefix += ('w1_processing_with_w2_ready',)
        return prefix + recipe.transitions[1:]
    return recipe.transitions


def verify_recipe(plan, events):
    """Require measured boundary, scope, order and natural expiry/retry origins."""
    required = required_transitions(plan['case_id'], plan.get('variant', RECIPES[plan['case_id']].variants[0]))
    missing, violations = [], []
    matching = []
    cursor = -1
    for boundary in required:
        found = next(((i, e) for i, e in enumerate(events) if i > cursor and e.get('event') == boundary
                      and e.get('run_id') == plan['run_id']), None)
        if not found:
            missing.append('SCENARIO_BOUNDARY_NOT_OBSERVED:' + boundary)
            continue
        cursor, event = found
        matching.append(event)
        if event.get('observed') is not True or event.get('db_ns') is None:
            missing.append('SCENARIO_BOUNDARY_UNACCREDITED:' + boundary)
        if event.get('organization_index') not in range(plan['organization_count']):
            violations.append('SCENARIO_SCOPE_MISMATCH:' + boundary)
        if event.get('source') not in ('JOURNAL', 'INDEPENDENT_DB_WITNESS', 'CONTAINED_PROVIDER', 'PROCESS_EXIT', 'REPLAY'):
            missing.append('SCENARIO_SOURCE_NOT_ACCREDITED:' + boundary)
    if any(b['db_ns'] < a['db_ns'] for a, b in zip(matching, matching[1:]) if a.get('db_ns') is not None and b.get('db_ns') is not None):
        violations.append('SCENARIO_BOUNDARIES_OUT_OF_ORDER')
    for event in matching:
        if event['event'] in ('natural_expiry', 'natural_retry_due'):
            if event.get('runtime_clock_or_deadline_changed') is not False:
                violations.append('RECOVERY_FRONTIER_ARTIFICIALLY_ADVANCED')
            if event.get('due_db_ns') is None or event.get('db_ns') is None or event['db_ns'] < event['due_db_ns']:
                missing.append('RECOVERY_DUE_NOT_REACHED')
        if event['event'] in ('same_work_reclaimed', 'same_work_retry', 'history_preserved'):
            if event.get('same_work_and_membership') is not True:
                violations.append('RECOVERY_MEMBERSHIP_OR_WORK_CHANGED')
            if event.get('budget_reset') is not False:
                violations.append('RECOVERY_BUDGET_RESET_OR_UNKNOWN')
        if event['event'] == 'old_witness_fenced' and event.get('effect_published') is not False:
            violations.append('STALE_WITNESS_PUBLISHED_OR_UNKNOWN')
    by_name = {e['event']: e for e in matching}
    for start, end, seconds in (('block_begin', 'block_release', plan.get('blocked_llm_hold_seconds', 120)),
                                ('burst_begin', 'burst_end', plan.get('burst_seconds', 120))):
        if start in by_name and end in by_name:
            a, b = by_name[start].get('db_ns'), by_name[end].get('db_ns')
            if a is None or b is None or b - a < seconds * NS:
                missing.append('DECLARED_HOLD_NOT_OBSERVED:' + start)
    if plan['case_id'] == 'R2-05' and plan.get('variant') == 'exhaustion':
        terminal = by_name.get('retry_terminal', {})
        if terminal.get('attempts_exhausted') is not True:
            missing.append('ATTEMPT_EXHAUSTION_NOT_OBSERVED')
    if plan['case_id'] == 'R2-09' and plan.get('variant') == 'uncertain_meta':
        if by_name.get('meta_result', {}).get('result') != 'UNCERTAIN':
            missing.append('UNCERTAIN_META_NOT_OBSERVED')
    return dict(missing=sorted(set(missing)), violations=sorted(set(violations)),
                required=list(required), observed=[e['event'] for e in matching],
                contract_coverage='PENDING' if plan['case_id'].startswith('R2-') else 'OBSERVATION_ONLY')
