"""Three physical finite frontiers; dependent preparations remain PENDING.

Does not invoke Controller, level, calibration, replay, rate search or E.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .evidence import Interval, reconstruct, timestamp
from .frontier_infrastructure import (ROLES, emit_phase, observe_drain, participant,
                                      participants, poll, preparation, prepare_backlog)
from .physical import BoundaryUnavailable, Session, lines, read, wait_db
from .recipes import RECIPES
from .runner import BASELINE, bootstrap, network_denied, require_empty_database, source_manifest, wait_ready, write_json
from .execution import verify_sources

CASES = ('R1-01', 'R1-03', 'R1-04')


def r101(s):
    with participants(s, 'loop'):
        rows, cut, name = prepare_backlog(s, [(0, i) for i in range(3)])
        s.event('multiple_conversations', [name, 'offers.jsonl'],
                member_ids=[r.pk for r in rows], ready_coexistence_db_ns=cut['db_ns'])
        write_json(s.directory / 'coexistence.json', dict(snapshot=name,
                   member_ids=[r.pk for r in rows], participants_released=False))
        (s.directory / 'release').touch()
        observe_drain(s, rows, 'multiconversation-drain')


def r103(s):
    # Each phase has precisely two active orgs. The drained control orgs have
    # no unassigned input during the unequal phase and cannot enter selection.
    with participants(s, 'loop'):
        (s.directory / 'release').touch()
        balanced = [(i % 2, i // 2) for i in range(6)]
        rows = emit_phase(s, 'balanced-control', balanced)
        observe_drain(s, rows, 'balanced-control-drain')
        cut, filename = s.snap('before-unequal-offer')
        next_slot = {2: 0, 3: 0}
        unequal = []
        for org in (2, 2, 3, 2, 2, 3):
            unequal.append((org, next_slot[org]))
            next_slot[org] += 1
        later = emit_phase(s, 'unequal', unequal)
        observe_drain(s, later, 'unequal-drain')
        write_json(s.directory / 'geometry.json',
                   dict(control_org_indexes=[0, 1], subject_org_indexes=[2, 3],
                        pre_subject_snapshot=filename, finite_fixture_not_confirmed_base=True,
                        global_calendar='COMMON_NORMALIZED_RELEASE_POLL_SLOTS',
                        measured_rates=None))
        s.event('concurrent_planners', ['planner_1.jsonl', 'planner_2.jsonl'], source='JOURNAL')
        s.event('same_global_2_to_1', ['geometry.json', 'emissions.jsonl',
                'balanced-control-calendar.json', 'unequal-calendar.json'], org=2)


def forecast_poll(s, future, serial, label, *, supersede=False):
    """Pre-query witness + actual baseline query result, never a later replay.

    Only this controlled poll is released. No other participant can mutate the
    predicate. The actual poll bracket must fit inside the existing E4 horizon.
    """
    future.refresh_from_db()
    deadline = future.available_at
    result, result_file = poll(s, 'planner_1', serial, label,
        forecast_peer_message=future.pk, pre_query_label=label, supersede_after_yield=supersede)
    snapshot = result['pre_query_snapshot']
    before = read(s.directory / snapshot)
    proof = dict(source_kind='PHYSICAL_POSTGRESQL', pre_query_snapshot=snapshot,
                 actual_poll_result=result_file, future_message_id=future.pk,
                 forecast_due_ns=timestamp(deadline.isoformat()), forecast_due_at=deadline.isoformat(),
                 native_forecast_horizon_ns=1_000_000_000,
                 observation='SELECTION_YIELD', claim_miss=False,
                 other_participants_held=True)
    filename = label + '-causal.json'
    write_json(s.directory / filename, proof)
    # Fail physically outside the horizon; no synthetic query/clock fallback.
    due = proof['forecast_due_ns']
    if not (due - proof['native_forecast_horizon_ns'] <= before['db_ns']
            <= result['before_db_ns'] <= result['after_db_ns'] < due):
        raise BoundaryUnavailable('Actual selector poll did not fit the natural forecast window')
    selections = [r for r in result['trace'] if r['event'] == 'selection_result']
    if result['processed'] != 0 or not selections or any(r['conversation_ids'] for r in selections):
        raise BoundaryUnavailable('Baseline selector did not physically yield')
    if any(r['event'] == 'claim_result' for r in result['trace']):
        raise BoundaryUnavailable('Selection yield was confused with a claim attempt')
    return proof, filename


def r104(s):
    with participants(s, 'commands'):
        history = s.offer(0, 9)
        wait_ready(history)
        result, history_file = poll(s, 'planner_1', 0, 'actual-prior-service')
        if result['processed'] != 1:
            raise BoundaryUnavailable('Prior org service was not actually observed')
        waiter = s.offer(0, 0)
        wait_ready(waiter)
        waiter.refresh_from_db()
        origin = waiter.available_at.isoformat()
        _, ready_file = s.snap('waiter-natural-ready')
        s.event('ready_waiter', [ready_file, 'offers.jsonl'])
        future = s.offer(1, 0)
        first, first_file = forecast_poll(s, future, 1, 'forecast-one', supersede=True)
        s.event('future_eligibility', [first_file], observed_boundary='SELECTION_YIELD')
        # Ordinary ingestion changes only the not-yet-READY peer deadline.
        # The waiter is a different conversation and retains its origin.
        from apps.channels.models import Message
        actual = read(s.directory / first['actual_poll_result'])
        correction = Message.objects.get(pk=actual['superseding_input_id'])
        s.recorder.offers = lines(s.directory / 'offers.jsonl')
        s.recorder.serial = max(o['attempt'] for o in s.recorder.offers)
        future.refresh_from_db(); correction.refresh_from_db()
        ingress = s.recorder.offers[-1]
        if (ingress['offered_db_ns_bounds'][1] >= first['forecast_due_ns'] or
                timestamp(future.available_at.isoformat()) <= first['forecast_due_ns']):
            raise BoundaryUnavailable('Ordinary pre-READY correction missed its real deadline')
        wait_db(first['forecast_due_at'])
        missed, miss_file = s.snap('forecast-deadline-not-materialized')
        write_json(s.directory / 'forecast-miss.json',
                   dict(source_kind='PHYSICAL_POSTGRESQL', forecast=first_file,
                        ingress_attempt=ingress['attempt'], snapshot=miss_file,
                        kind='FORECAST_DEADLINE_SUPERSEDED_BY_COMMITTED_INGRESS',
                        claim_miss=False, waiter_message_id=waiter.pk,
                        waiter_original_deadline=origin))
        s.event('forecast_miss', ['forecast-miss.json', 'offers.jsonl', miss_file],
                observed_boundary='FORECAST_DEADLINE_SUPERSEDED', claim_miss=False)
        second, second_file = forecast_poll(s, future, 2, 'forecast-two')
        s.event('future_eligibility_again', [second_file], observed_boundary='SELECTION_YIELD')
        wait_ready(future)
        _, eligible_file = s.snap('peer-natural-eligibility-after-yields')
        result, peer_file = poll(s, 'planner_1', 3, 'peer-now-eligible')
        if result['processed'] != 1:
            raise BoundaryUnavailable('Peer did not reach real service at its natural eligibility')
        result, waiter_file = poll(s, 'planner_1', 4, 'waiter-next-opportunity')
        if result['processed'] != 1:
            raise BoundaryUnavailable('Original waiter was not physically claimed')
        waiter.refresh_from_db()
        if waiter.available_at.isoformat() != origin or waiter.turn_work_id is None:
            raise AssertionError('Waiter origin reset or claim missing')
        for serial in range(3):
            poll(s, 'sender', serial, 'contained-sender-disposition')
        _, final_file = s.snap('waiter-original-age-at-committed-claim')
        write_json(s.directory / 'forecast-sequence.json',
                   dict(history_message_id=history.pk, waiter_message_id=waiter.pk,
                        future_message_ids=[future.pk, correction.pk], waiter_original_deadline=origin,
                        prior_service=history_file, waiter_ready_snapshot=ready_file,
                        forecasts=[first_file, second_file], miss='forecast-miss.json',
                        next_eligibility_snapshot=eligible_file, peer_claim=peer_file,
                        waiter_claim=waiter_file, final_snapshot=final_file,
                        fixture_controls='REAL_PROCESS_POLL_GATES_NO_SELECTOR_OR_CLOCK_PATCH'))


def execute(directory, case, run_id):
    if case not in CASES:
        raise ValueError('Only the three authorized physical frontiers may execute')
    bootstrap(); require_empty_database(); verify_sources()
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    source_manifest(directory)
    s = Session(directory, case, RECIPES[case].variants[0], run_id)
    error = None
    try:
        with network_denied(), s.recorder.capture('driver'):
            s.seed(1 if case == 'R1-01' else 4 if case == 'R1-03' else 2)
            seed, _ = s.snap('seed-domain-state')
            write_json(directory / 'seed-domain-state.json', seed)
            {'R1-01': r101, 'R1-03': r103, 'R1-04': r104}[case](s)
            final, final_name = s.snap('final')
    except Exception as exc:
        error = dict(kind='PHYSICAL_BOUNDARY_NOT_OBSERVED' if isinstance(exc, BoundaryUnavailable)
                     else 'IMPLEMENTATION_OR_INVARIANT_FAILURE',
                     exception_class=type(exc).__name__, message=str(exc))
    finally:
        s.cleanup()
    from apps.agent.claim_diagnostic_report import read_journal
    if error is None:
        journals = [read_journal(directory / (role + '.jsonl')) for role in ('driver',) + ROLES]
        report = reconstruct(journals, lines(directory / 'offers.jsonl'), final['messages'],
                             Interval(final['db_ns'], final['db_ns']), run_id=run_id)
        write_json(directory / 'cohort.json', report)
    artifacts = {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in directory.rglob('*') if p.is_file()}
    prerequisites = [] if case == 'R1-01' else [dict(name='CONFIRMED_BASE', status='PENDING',
        applies_to='COMPLETE_CHARACTERIZATION_CASE_NOT_FINITE_FRONTIER')]
    receipt = dict(schema='d29-remaining-frontier-v1', case_id=case, variant=s.variant,
                   run_id=run_id, baseline=BASELINE, source_kind='PHYSICAL_POSTGRESQL',
                   organization_count=len(s.fixtures), organization_ids=[f[0].pk for f in s.fixtures],
                   events=s.events, artifacts=artifacts,
                   final_snapshot=final_name if error is None else None, error=error,
                   physical_frontier=dict(scope='FINITE_BOUNDARY_ONLY'),
                   load_condition=dict(status='NOT_ACCREDITED', rates=None),
                   prerequisites=prerequisites, evidence_synthetic=[],
                   evidence_physical=list(artifacts), characterization=False, benchmark=False,
                   level_acceptance=False, sustainable_envelope=None,
                   global_state='CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY')
    write_json(directory / 'receipt.json', receipt)
    from .frontier_verify import verify
    result = verify(directory)
    write_json(directory / 'verification.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('run', 'participant', 'verify', 'prepare'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--case', choices=CASES + ('R1-05', 'R1-06'))
    p.add_argument('--run-id'); p.add_argument('--role', choices=ROLES)
    p.add_argument('--mode', choices=('loop', 'commands'))
    a = p.parse_args()
    if a.command == 'participant':
        participant(a.output, a.case, a.run_id, a.role, a.mode); return
    if a.command == 'prepare':
        result = preparation(a.case)
        a.output.mkdir(parents=True, exist_ok=False)
        write_json(a.output / 'preparation.json', result)
    elif a.command == 'verify':
        from .frontier_verify import verify
        result = verify(a.output)
    else:
        result = execute(a.output, a.case, a.run_id)
    print(json.dumps(result))
    if result.get('status') not in ('PHYSICALLY_ACCREDITED', 'PENDING'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
