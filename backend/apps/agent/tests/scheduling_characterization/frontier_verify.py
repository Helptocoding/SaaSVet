"""Offline verification from raw physical witnesses, not declared PASS flags."""
import hashlib
from pathlib import Path

from .assessment import invariant_gate
from .evidence import Interval, timestamp, reconstruct
from .physical import lines, read
from .recipes import verify_recipe
from .runner import BASELINE


def require(condition, code):
    if not condition:
        raise ValueError(code)


def message(snapshot, pk):
    return next(m for m in snapshot['messages'] if m['id'] == pk)


def accepted(directory):
    return [o for o in lines(directory / 'offers.jsonl') if o['outcome'] == 'ACCEPTED_DURABLE']


def verify_coexistence(directory, receipt, report):
    require('coexistence.json' in receipt['artifacts'], 'COEXISTENCE_WITNESS_NOT_HASHED')
    proof = read(directory / 'coexistence.json')
    require(proof['snapshot'] in receipt['artifacts'], 'COEXISTENCE_CUT_NOT_HASHED')
    cut = read(directory / proof['snapshot'])
    members = [message(cut, pk) for pk in proof['member_ids']]
    require(len(members) >= 2 and len({m['conversation_id'] for m in members}) == len(members),
            'MULTIPLE_DISTINCT_CONVERSATIONS_NOT_OBSERVED')
    require(len({m['organization_id'] for m in members}) == 1, 'COEXISTENCE_NOT_SAME_ORG')
    require(all(m['turn_work_id'] is None and m['status'] == 'pending' and m['available_at']
                and timestamp(m['available_at']) <= cut['db_ns'] for m in members),
            'NATURAL_READY_EPISODES_DID_NOT_COEXIST')
    origins = {o['message_id']: o for o in accepted(directory)}
    require(set(origins) == set(proof['member_ids']) and all(
            origins[m['id']]['offered_db_ns_bounds'][1] <= timestamp(m['available_at'])
            for m in members), 'READY_WAS_NOT_NATURAL_COMMITTED_INGRESS')
    require(not cut['works'], 'WORK_ALREADY_ASSIGNED_AT_COEXISTENCE_CUT')
    require(all(e['claim_commit_ns_bounds'][0] > cut['db_ns'] for e in report['episodes']),
            'CLAIM_PRECEDES_READY_COEXISTENCE')


def verify_geometry(directory, receipt, report, journals):
    require(all(name in receipt['artifacts'] for name in ('geometry.json', 'emissions.jsonl',
            'balanced-control-calendar.json', 'unequal-calendar.json')), 'GEOMETRY_WITNESS_NOT_HASHED')
    geometry = read(directory / 'geometry.json')
    calendars = [read(directory / (p + '-calendar.json')) for p in ('balanced-control', 'unequal')]
    normalized = [[(s['offset_ns'], s['end_offset_ns']) for s in c['slots']] for c in calendars]
    require(normalized[0] == normalized[1] and len(normalized[0]) >= 6,
            'GLOBAL_CALENDAR_NOT_COMMON')
    emissions = lines(directory / 'emissions.jsonl')
    ledger = {o['attempt']: o for o in accepted(directory)}
    orgs = receipt['organization_ids']
    counts = []
    for calendar in calendars:
        measured = [e for e in emissions if e['phase'] == calendar['phase']]
        require(len(measured) == len(calendar['slots']), 'FINITE_GLOBAL_SLOT_MISSING')
        require(len({e['slot_index'] for e in measured}) == len(measured), 'DUPLICATE_GLOBAL_SLOT')
        starts = set()
        by_org = {}
        conversation_ids = set()
        for slot, emission in zip(calendar['slots'], sorted(measured, key=lambda e: e['slot_index'])):
            require(emission['slot_index'] == slot['index'], 'GLOBAL_SLOT_ID_MISMATCH')
            require(emission['organization_id'] == orgs[slot['organization_index']], 'OFFER_TENANT_MISMATCH')
            require(emission['due_monotonic_ns'] <= emission['started_monotonic_ns']
                    < emission['end_monotonic_ns'], 'GENERATOR_MISSED_COMMON_SLOT')
            starts.add(emission['due_monotonic_ns'] - slot['offset_ns'])
            original = ledger.get(emission['attempt'])
            require(original is not None and all(original[k] == emission[k] for k in
                    ('message_id', 'organization_id', 'outcome', 'offered_db_ns_bounds')),
                    'EMISSION_NOT_RECONCILED_WITH_DURABLE_INGRESS')
            by_org[emission['organization_id']] = by_org.get(emission['organization_id'], 0) + 1
            ep = next(e for e in report['episodes'] if emission['message_id'] in e['member_ids'])
            require(len(ep['member_ids']) == 1, 'GEOMETRY_DEMAND_COALESCED')
            conversation_ids.add(ep['conversation_id'])
        require(len(starts) == 1, 'GLOBAL_CALENDAR_START_CHANGED')
        require(len(conversation_ids) == len(measured), 'GEOMETRY_CONVERSATIONS_NOT_DISTINCT')
        counts.append([by_org.get(orgs[i], 0) for i in
                       (geometry['control_org_indexes'] if calendar['phase'] == 'balanced-control'
                        else geometry['subject_org_indexes'])])
    require(counts[0][0] == counts[0][1] > 0 and counts[1][0] == 2 * counts[1][1] > 0
            and sum(counts[0]) == sum(counts[1]), 'ACTUAL_2_TO_1_COMPARISON_MISSING')
    cut = read(directory / geometry['pre_subject_snapshot'])
    require(geometry['pre_subject_snapshot'] in receipt['artifacts'], 'GEOMETRY_CUT_NOT_HASHED')
    require(not any(m['direction'] == 'in' and m['turn_work_id'] is None for m in cut['messages']),
            'CONTROL_QUEUE_CONTAMINATES_SUBJECT')
    planners = [j for j in journals if j[0]['worker'] in ('planner_1', 'planner_2')]
    require(len(planners) == 2 and len({j[0]['os_pid'] for j in planners}) == 2 and
            max(j[0]['monotonic_ns'] for j in planners) < min(j[-1]['monotonic_ns'] for j in planners)
            and all(any(r['event'] == 'poll_start' for r in j) for j in planners),
            'REAL_CONCURRENT_PLANNERS_NOT_OBSERVED')
    require(geometry['finite_fixture_not_confirmed_base'] is True and geometry['measured_rates'] is None,
            'FINITE_CONTROL_PROMOTED_TO_CONFIRMED_BASE')


def verify_forecasts(directory, receipt, report, journals):
    require('forecast-sequence.json' in receipt['artifacts'], 'FORECAST_SEQUENCE_NOT_HASHED')
    sequence = read(directory / 'forecast-sequence.json')
    waiter_id = sequence['waiter_message_id']
    origin = timestamp(sequence['waiter_original_deadline'])
    waiter_episode = next(e for e in report['episodes'] if waiter_id in e['member_ids'])
    require(waiter_episode['ready_ns_bounds'] == [origin, origin], 'WAITER_ORIGIN_RESET_OR_UNCERTAIN')
    poll_ids = []
    proofs = []
    raw_rows = [r for j in journals for r in j]
    for filename in sequence['forecasts']:
        require(filename in receipt['artifacts'], 'FORECAST_WITNESS_NOT_HASHED')
        proof = read(directory / filename)
        require(proof['pre_query_snapshot'] in receipt['artifacts']
                and proof['actual_poll_result'] in receipt['artifacts'], 'CAUSAL_POLL_WITNESS_NOT_HASHED')
        pre = read(directory / proof['pre_query_snapshot'])
        result = read(directory / proof['actual_poll_result'])
        waiter = message(pre, waiter_id)
        future = message(pre, proof['future_message_id'])
        due = timestamp(future['available_at'])
        require(proof['source_kind'] == 'PHYSICAL_POSTGRESQL' and proof['forecast_due_ns'] == due,
                'FORECAST_NOT_FROM_REAL_DEADLINE')
        require(due - proof['native_forecast_horizon_ns'] <= pre['db_ns'] <= result['before_db_ns']
                <= result['after_db_ns'] < due and proof['native_forecast_horizon_ns'] == 1_000_000_000,
                'PRE_QUERY_WITNESS_OUTSIDE_NATIVE_FORECAST_WINDOW')
        require(waiter['turn_work_id'] is None and waiter['status'] == 'pending'
                and timestamp(waiter['available_at']) == origin <= pre['db_ns']
                and future['turn_work_id'] is None and future['status'] == 'pending'
                and waiter['organization_id'] != future['organization_id'],
                'READY_WAITER_AND_FUTURE_PEER_NOT_COEXISTING')
        require(all(w['status'] == 'COMPLETED' for w in pre['works']), 'ORG_AUTHORITY_BUSY_DURING_FORECAST')
        prior_waiter = [w for w in pre['works'] if w['organization_id'] == waiter['organization_id']]
        prior_peer = [w for w in pre['works'] if w['organization_id'] == future['organization_id']]
        require(prior_waiter and not prior_peer, 'REAL_LAST_CLAIM_ORDER_NOT_PRESENT')
        selections = [r for r in result['trace'] if r['event'] == 'selection_result']
        polls = [r for r in result['trace'] if r['event'] == 'poll_start']
        require(len(polls) == 1 and len(selections) == 1 and not selections[0]['conversation_ids']
                and result['processed'] == 0 and not any(r['event'] == 'claim_result' for r in result['trace']),
                'ACTUAL_SELECTION_YIELD_NOT_OBSERVED')
        require(all(r in raw_rows for r in result['trace']), 'POLL_RESULT_NOT_IN_ORIGINAL_JOURNAL')
        require(all(r['os_pid'] == result['os_pid'] for r in result['trace']), 'POLL_PROCESS_MISMATCH')
        # Held participants must have no actual poll at either forecast cut.
        # Validate their journals, not just the fixture's declared boolean.
        held = [j for j in journals if j[0]['worker'] in ('planner_2', 'sender')]
        selection = selections[0]['monotonic_ns']
        require(all(not any(r['event'] == 'poll_start' and r['monotonic_ns'] <= selection
                            for r in j) for j in held), 'FORECAST_PREDICATE_MUTATED_BY_OTHER_POLL')
        clocks = [timestamp(r['db_timestamp']) for r in raw_rows if r['event'] == 'db_clock']
        require(result['before_db_ns'] in clocks and result['after_db_ns'] in clocks,
                'POLL_CLOCK_NOT_IN_CAPTURE')
        poll_ids.append((result['os_pid'], polls[0]['poll_id']))
        proofs.append(proof)
    require(len(set(poll_ids)) == 2, 'FUTURE_ELIGIBILITY_NOT_REOBSERVED_ON_DISTINCT_POLL')
    miss = read(directory / sequence['miss'])
    ingress = next(o for o in accepted(directory) if o['attempt'] == miss['ingress_attempt'])
    miss_cut = read(directory / miss['snapshot'])
    require(sequence['miss'] in receipt['artifacts'] and miss['snapshot'] in receipt['artifacts'],
            'FORECAST_MISS_WITNESS_NOT_HASHED')
    future = message(miss_cut, proofs[0]['future_message_id'])
    require(ingress['offered_db_ns_bounds'][0] >= read(directory / proofs[0]['actual_poll_result'])['after_db_ns']
            and ingress['offered_db_ns_bounds'][1] < proofs[0]['forecast_due_ns'] <= miss_cut['db_ns']
            < timestamp(future['available_at']) == proofs[1]['forecast_due_ns'],
            'FORECAST_MISS_NOT_COMMITTED_PRE_READY_CORRECTION')
    require(miss['claim_miss'] is False and future['turn_work_id'] is None,
            'FORECAST_MISS_CONFUSED_WITH_CLAIM_MISS')
    require(timestamp(message(miss_cut, waiter_id)['available_at']) == origin
            and message(miss_cut, waiter_id)['turn_work_id'] is None, 'WAITER_ORIGIN_LOST_AT_MISS')
    eligible = read(directory / sequence['next_eligibility_snapshot'])
    require(timestamp(message(eligible, proofs[1]['future_message_id'])['available_at']) <= eligible['db_ns']
            and message(eligible, waiter_id)['turn_work_id'] is None
            and timestamp(message(eligible, waiter_id)['available_at']) == origin,
            'NEXT_NATURAL_ELIGIBILITY_NOT_OBSERVED')
    peer = read(directory / sequence['peer_claim'])
    peer_episode = next(e for e in report['episodes'] if proofs[1]['future_message_id'] in e['member_ids'])
    require(peer['processed'] == 1 and eligible['db_ns'] <= peer['before_db_ns']
            <= peer_episode['claim_commit_ns_bounds'][0] <= peer_episode['claim_commit_ns_bounds'][1]
            <= peer['after_db_ns'], 'NEXT_PEER_CLAIM_NOT_OBSERVED')
    final = read(directory / sequence['final_snapshot'])
    require(timestamp(message(final, waiter_id)['available_at']) == origin
            and waiter_episode['claim_commit_ns_bounds'][0] > eligible['db_ns'],
            'WAITER_AGE_OR_NEXT_COMMITTED_CLAIM_NOT_PRESERVED')
    result = read(directory / sequence['waiter_claim'])
    require(result['processed'] == 1 and result['before_db_ns'] <= waiter_episode['claim_commit_ns_bounds'][0]
            <= waiter_episode['claim_commit_ns_bounds'][1] <= result['after_db_ns'],
            'WAITER_CLAIM_NOT_CORRELATED_TO_ACTUAL_POLL')


def verify(directory):
    directory = Path(directory)
    errors = []
    r = None
    try:
        r = read(directory / 'receipt.json')
        require(r['schema'] == 'd29-remaining-frontier-v1' and r['baseline'] == BASELINE
                and r['source_kind'] == 'PHYSICAL_POSTGRESQL', 'WRONG_PHYSICAL_PROVENANCE')
        require(r['case_id'] in ('R1-01', 'R1-03', 'R1-04'), 'DEPENDENT_CASE_CANNOT_BE_ACCREDITED')
        require(r['error'] is None, 'PHYSICAL_EXECUTION_ERROR')
        require(r['characterization'] is False and r['benchmark'] is False
                and r['level_acceptance'] is False and r['sustainable_envelope'] is None
                and r['evidence_synthetic'] == [] and r['load_condition']['status'] == 'NOT_ACCREDITED',
                'FINITE_FRONTIER_PROMOTED_TO_LOAD_OR_REPLAY')
        require(r['global_state'] == 'CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY',
                'GLOBAL_STATE_CHANGED')
        require(r['load_condition'].get('rates') is None, 'FINITE_RATE_INVENTED')
        if r['case_id'] in ('R1-03', 'R1-04'):
            require(r['prerequisites'] == [dict(name='CONFIRMED_BASE', status='PENDING',
                    applies_to='COMPLETE_CHARACTERIZATION_CASE_NOT_FINITE_FRONTIER')],
                    'BASE_PREREQUISITE_REMOVED_OR_FABRICATED')
        for name, digest in r['artifacts'].items():
            path = directory / name
            require(not Path(name).is_absolute() and '..' not in Path(name).parts
                    and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                    'ARTIFACT_MISMATCH:' + name)
        required = ['cohort.json', 'participants-cleanup.json', 'seed-domain-state.json',
                    'offers.jsonl', 'source-manifest.json', r['final_snapshot']]
        required += [role + suffix for role in ('planner_1', 'planner_2', 'sender')
                     for suffix in ('.jsonl', '-started.json', '-exit.json')]
        required += ['driver.jsonl']
        require(all(name in r['artifacts'] for name in required), 'REQUIRED_PHYSICAL_ARTIFACT_MISSING')
        require(read(directory / 'participants-cleanup.json')['all_reaped'] is True, 'PARTICIPANT_LEAK')
        from apps.agent.claim_diagnostic_report import read_journal
        roles = ('driver', 'planner_1', 'planner_2', 'sender')
        journals = [read_journal(directory / (role + '.jsonl')) for role in roles]
        require(all(j[0]['worker'] == role for j, role in zip(journals, roles)), 'PARTICIPANT_ROLE_MISMATCH')
        require(all(read(directory / (role + '-exit.json'))['exit_code'] == 0 for role in roles[1:]),
                'PARTICIPANT_EXIT_NOT_RESOLVED')
        final = read(directory / r['final_snapshot'])
        require(final['works'] and all(w['status'] == 'COMPLETED' for w in final['works']),
                'FINAL_WORK_OBLIGATIONS_NOT_DRAINED')
        report = reconstruct(journals, lines(directory / 'offers.jsonl'), final['messages'],
                             Interval(final['db_ns'], final['db_ns']), run_id=r['run_id'])
        stored = read(directory / 'cohort.json')
        require(all(report[k] == stored[k] for k in ('episodes', 'summary', 'issues', 'uncertain_transactions')),
                'COHORT_NOT_REPRODUCIBLE_FROM_RAW_CAPTURE')
        require(not report['issues'] and not report['uncertain_transactions']
                and all(e['claim_commit_ns_bounds'] is not None for e in report['episodes']),
                'PHYSICAL_POPULATION_OR_COMMIT_UNRESOLVED')
        wire = [e for role in roles[1:] for e in lines(directory / (role + '-wire.jsonl')) if e['event'] == 'dispatch']
        gate = invariant_gate(report, journals, final['messages'], final['works'], wire, r['organization_ids'])
        require(not gate['missing'] and not gate['violations'], 'PHYSICAL_INVARIANTS:' + str(gate))
        require(final['domain_counts'] == read(directory / 'seed-domain-state.json')['domain_counts'],
                'UNEXPECTED_DOMAIN_WRITE')
        require(all(w['llm_calls_admitted'] == sum(c['turn_work_id'] == w['id'] for c in final['calls'])
                and w['llm_output_tokens_reserved'] == sum(c['reserved_output_tokens'] for c in final['calls']
                                                         if c['turn_work_id'] == w['id'])
                for w in final['works']), 'BUDGET_LEDGER_MISMATCH')
        recipe = verify_recipe(r, r['events'])
        require(not recipe['missing'] and not recipe['violations'], 'PHYSICAL_RECIPE_NOT_OBSERVED')
        require(all(e['source'] != 'REPLAY' and e.get('evidence')
                    and all(p in r['artifacts'] for p in e['evidence']) for e in r['events']),
                'EVENT_WITHOUT_PHYSICAL_WITNESS')
        if r['case_id'] == 'R1-01':
            verify_coexistence(directory, r, report)
        elif r['case_id'] == 'R1-03':
            verify_geometry(directory, r, report, journals)
        else:
            verify_forecasts(directory, r, report, journals)
    except (ValueError, KeyError, OSError, StopIteration, TypeError, IndexError) as exc:
        errors.append(str(exc) or type(exc).__name__)
    return dict(status='PHYSICALLY_ACCREDITED' if not errors else 'NOT_ACCREDITED',
                errors=errors, physical_frontier=dict(status='OBSERVED' if not errors else 'NOT_ACCREDITED',
                scope='FINITE_BOUNDARY_ONLY'), load_condition=dict(status='NOT_ACCREDITED'),
                prerequisites=r.get('prerequisites', []) if r else [], evidence_synthetic=[],
                source_kind='PHYSICAL_POSTGRESQL', level_acceptance=False, characterization=False,
                benchmark=False, sustainable_envelope=None,
                global_state='CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY')
