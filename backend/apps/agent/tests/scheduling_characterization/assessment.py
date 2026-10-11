"""Independent acceptance gates for D29 receipts, not product/release authority.

The executor supplies raw observations; a plan cannot supply passing booleans.
Synthetic replay can accredit these gates but never accredit a real load level.
"""
from collections import Counter, defaultdict
from copy import deepcopy

from .evidence import NS, Interval, backlog_disposition, transactions


def disposition(report, gates, *, faults=False, synthetic=False):
    """Keep every adverse finding; never average a failure into a success."""
    labels = set()
    if gates['invariants']['violations']:
        labels.add('INVARIANT_FAILURE')
    if any(v.startswith(('RECOVERY_MEMBERSHIP', 'RECOVERY_BUDGET', 'STALE_WITNESS')) for v in gates['scenario']['violations']):
        labels.add('INVARIANT_FAILURE')
    if any(gates[k]['violations'] for k in ('demand', 'preparation', 'windows', 'scenario')):
        labels.add('INVALID_RUN')
    if report['summary'].get('OBSERVED_EXCESS', 0):
        labels.add('OBSERVED_INCOMPATIBLE_WITH_TARGET')
    if 'OBSERVED_BACKLOG_GROWTH' in gates['windows']['backlog'].values():
        labels.add('OBSERVED_BACKLOG_GROWTH')
    unresolved = any(report['summary'].get(k, 0) for k in (
        'PENDING_CENSORED', 'NOT_YET_READY', 'INDETERMINATE', 'INVALID_EVIDENCE'))
    if (report['issues'] or report['uncertain_transactions'] or unresolved
            or any(g['missing'] for g in gates.values())
            or 'INDETERMINATE' in gates['windows']['backlog'].values()):
        labels.add('INDETERMINATE')
    if not labels:
        labels.add('FAULT_OBSERVATION_COMPLETE_COVERAGE_PENDING' if faults else 'OBSERVED_COMPATIBLE')
    if synthetic:
        # Preserve the evaluated finding, but label its provenance unmistakably.
        return {'model_dispositions': sorted(labels), 'dispositions': ['SYNTHETIC_REPLAY_NOT_LOAD_ACCEPTANCE']}
    return {'dispositions': sorted(labels)}


def demand_gate(plan, report, offers, scheduled, organizations, offer_span):
    """Reconcile the schedule, attempts, committed inbounds and READY episodes.

    No arbitrary tolerance is added. An attempt must begin in its declared
    pacing slot; every slot before the half-open end must have an attempt.
    Coalescing/never-READY demand is reported, never sold as offered episodes.
    """
    missing, violations = [], []
    by_slot = defaultdict(list)
    for attempt in offers:
        if attempt.get('phase') == 'BACKLOG':
            continue
        slot = attempt.get('schedule_id')
        if slot is None:
            missing.append('OFFER_WITHOUT_SCHEDULE')
        by_slot[slot].append(attempt)
    expected = Counter()
    actual = Counter()
    for slot in scheduled:
        expected[slot['organization_index']] += 1
        attempts = by_slot.pop(slot['id'], [])
        if len(attempts) != 1:
            violations.append('MISSING_OR_DUPLICATE_SCHEDULE_SLOT:' + slot['id'])
            continue
        attempt = attempts[0]
        org = organizations[slot['organization_index']]
        if attempt.get('organization_id') != org:
            violations.append('OFFER_TENANT_MISMATCH:' + slot['id'])
        started = attempt.get('started_monotonic_ns')
        if started is None:
            missing.append('OFFER_TIME_UNKNOWN:' + slot['id'])
        elif not slot['due_monotonic_ns'] <= started < slot['end_monotonic_ns']:
            violations.append('GENERATOR_MISSED_PACING_SLOT:' + slot['id'])
        if attempt.get('outcome') != 'ACCEPTED_DURABLE':
            violations.append('OFFER_NOT_ACCEPTED_DURABLE:' + slot['id'])
        else:
            actual[slot['organization_index']] += 1
    if by_slot:
        violations.append('UNPLANNED_OFFERS')
    accepted = {o['message_id'] for o in offers if o.get('outcome') == 'ACCEPTED_DURABLE'}
    members = [m for e in report['episodes'] for m in e['member_ids']]
    if set(members) != accepted or len(members) != len(set(members)):
        missing.append('POPULATION_NOT_CONSERVED')
    if report['population']['unresolved_offers'] or report['issues']:
        missing.append('POPULATION_OR_CAPTURE_UNRESOLVED')
    if not plan.get('boundary_case'):
        # Sustained ordinary offers are supposed to create separate episodes.
        # Deliberate corrections/duplicates are checked by the boundary recipe.
        if len(report['episodes']) != len(accepted):
            violations.append('COALESCED_DEMAND_NOT_DECLARED_READY_EPISODE_LOAD')
        lo, hi = offer_span
        for e in report['episodes']:
            ready = e['ready_ns_bounds']
            backlog = any(o.get('phase') == 'BACKLOG' and o.get('message_id') in e['member_ids'] for o in offers)
            if not backlog and (ready[0] is None or ready[1] is None):
                missing.append('READY_DEMAND_ORIGIN_UNKNOWN:' + e['episode_id'])
    return dict(missing=sorted(set(missing)), violations=sorted(set(violations)),
                planned_attempts_by_org_index=dict(expected), accepted_attempts_by_org_index=dict(actual),
                ready_episodes_by_org=report['organization_counts'],
                ready_in_offer_window=sum(e['ready_ns_bounds'][0] is not None
                    and offer_span[0] <= e['ready_ns_bounds'][0] < offer_span[1] for e in report['episodes']),
                ready_after_offer_window=sum(e['ready_ns_bounds'][0] is not None
                    and e['ready_ns_bounds'][0] >= offer_span[1] for e in report['episodes']))


def window_gate(plan, report, queue_samples, organizations):
    missing, violations = [], []
    duration = plan['offer_seconds']
    offsets = list(range(0, duration + 1, 120))
    if offsets[-1] != duration:
        offsets.append(duration)
    if [q.get('offset_seconds') for q in queue_samples] != offsets:
        missing.append('QUEUE_CUTS_NOT_COMPLETE_OR_ALIGNED')
    backlog = {}
    for org in [str(o) for o in organizations] + ['global']:
        counts = [q.get('counts', {}).get(org) for q in queue_samples]
        if not counts or any(c is None for c in counts):
            missing.append('QUEUE_SCOPE_MISSING:' + org)
            backlog[org] = 'INDETERMINATE'
            continue
        if any(not isinstance(c, list) or len(c) != 2 or not 0 <= c[0] <= c[1] for c in counts):
            violations.append('INVALID_QUEUE_INTERVAL:' + org)
            backlog[org] = 'INDETERMINATE'
            continue
        full = [b['offset_seconds'] - a['offset_seconds'] == 120 for a, b in zip(queue_samples, queue_samples[1:])]
        backlog[org] = backlog_disposition(counts, full)
    if any(q.get('correlated_clock') is not True for q in queue_samples):
        missing.append('QUEUE_CLOCK_CORRELATION_NOT_ACCREDITED')
    return dict(missing=sorted(set(missing)), violations=violations, backlog=backlog)


def invariant_gate(report, journals, census, works, wire, organizations):
    """Verify causal membership and durable admission witnesses, not snapshots alone.

    N=1 at dispatch has an independent DB count and matching work/token witness.
    Lock order/CAS remain unchanged-source requirements, not fabricated probes.
    """
    missing, violations = [], []
    orgs = set(organizations)
    rows = {m['id']: m for m in census}
    work_rows = {w['id']: w for w in works}
    for ep in report['episodes']:
        if ep['organization_id'] not in orgs:
            violations.append('EPISODE_OUTSIDE_DECLARED_TENANTS')
        for mid in ep['member_ids']:
            row = rows.get(mid)
            if row is None:
                missing.append('MEMBER_MISSING_FROM_CENSUS')
            elif (row['organization_id'], row['conversation_id']) != (ep['organization_id'], ep['conversation_id']):
                violations.append('CROSS_TENANT_MEMBERSHIP')
            elif ep['turn_work_id'] and row.get('turn_work_id') != ep['turn_work_id']:
                violations.append('MEMBERSHIP_REASSIGNED_AFTER_CLAIM')
        if ep['turn_work_id']:
            w = work_rows.get(ep['turn_work_id'])
            if w is None:
                missing.append('CLAIM_WORK_MISSING')
            elif (w['organization_id'], w['conversation_id']) != (ep['organization_id'], ep['conversation_id']):
                violations.append('WORK_SCOPE_MISMATCH')
    try:
        effects, unresolved = transactions(journals)
    except (ValueError, KeyError):
        effects, unresolved = [], [True]
    if unresolved:
        missing.append('INVARIANT_TRANSACTION_UNRESOLVED')
    claims = defaultdict(list)
    for tx in effects:
        for event in tx['rows']:
            if event['event'] == 'claim_bound':
                claims[event['turn_work_id']].append((tx['commit'], event))
    for event in wire:
        if event.get('organization_id') not in orgs:
            violations.append('WIRE_SCOPE_MISMATCH')
        if event.get('external_destination') is not False:
            violations.append('UNCONTAINED_DESTINATION')
        if event.get('in_atomic') is not False:
            violations.append('HTTP_UNDER_TRANSACTION')
        if event.get('admission_verified') is not True:
            missing.append('DURABLE_WIRE_ADMISSION_NOT_WITNESSED')
        if event.get('boundary') == 'llm':
            if event.get('active_org_work') != 1 or event.get('matching_active_work') is not True:
                violations.append('N1_OR_OWNERSHIP_AT_DISPATCH')
            bound = next((c for c in claims.get(event.get('turn_work_id'), [])
                          if c[1].get('epoch') == event.get('epoch')
                          and c[1].get('lease_fingerprint') == event.get('lease_fingerprint')), None)
            if bound is None or event.get('db_ns') is None or bound[0].hi is None or bound[0].hi > event['db_ns']:
                missing.append('DISPATCH_BEFORE_RESOLVED_OUTER_COMMIT')
    claimed = {e['turn_work_id'] for e in report['episodes'] if e['turn_work_id']}
    if claimed - {e.get('turn_work_id') for e in wire if e.get('boundary') == 'llm'}:
        missing.append('CLAIMED_WORK_WITHOUT_SERVICE_WITNESS')
    if not wire:
        missing.append('SERVICE_COST_NOT_OBSERVED')
    return dict(missing=sorted(set(missing)), violations=sorted(set(violations)),
                witnesses=len(wire), checked=['tenant_membership', 'immutable_membership', 'outer_commit',
                                             'durable_admission', 'N1_at_dispatch', 'no_HTTP_in_transaction',
                                             'contained_destinations'])


def assess(plan, report, *, offers, scheduled, organizations, offer_span,
           queue_samples, journals, census, works, wire, preparation, recipe,
           synthetic=False):
    gates = {
        'demand': demand_gate(plan, report, offers, scheduled, organizations, offer_span),
        'windows': window_gate(plan, report, queue_samples, organizations),
        'invariants': invariant_gate(report, journals, census, works, wire, organizations),
        'preparation': {'missing': [], 'violations': []},
        'scenario': recipe,
    }
    if not synthetic and any(e.get('source') == 'REPLAY' for e in report.get('scenario_events', [])):
        gates['scenario']['missing'].append('REPLAY_CANNOT_ACCREDIT_LIVE_SCENARIO')
    required = ('fresh_database', 'participants_ready_before_offer', 'source_integrity',
                'capture_all_participants', 'durable_database', 'contained_provider')
    gates['preparation']['missing'] = [k for k in required if preparation.get(k) is not True]
    if preparation.get('source_integrity') is False:
        gates['preparation']['violations'].append('BASELINE_SOURCE_CHANGED')
    result = deepcopy(report)
    result.update(schema='saaslyvet-d29-level-v2', gates=gates, case_id=plan['case_id'],
                  source_kind='SYNTHETIC_REPLAY' if synthetic else 'ISOLATED_LIVE',
                  contract_accepted=False, sustainable_envelope=None,
                  **disposition(report, gates, faults=plan['case_id'].startswith('R2-'), synthetic=synthetic))
    return result
