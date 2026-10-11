"""Finite evaluation controls and future burst/backlog infrastructure.

No rates, CONFIRMED_BASE producer, adaptive controller or production imports
at module import. Processes execute the unchanged baseline with contained READ.
"""
import io
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from .evidence import NS, timestamp
from .execution import append
from .physical import BoundaryUnavailable, Session, contained, db_peer, lines, read, wait_db
from .runner import bootstrap, network_denied, write_json

MODULE = 'apps.agent.tests.scheduling_characterization.frontiers'
ROLES = ('planner_1', 'planner_2', 'sender')
# Existing release-poll interval, used only as a finite fixture calendar.
RELEASE_POLL_NS = NS


def publish(path, value):
    """Publish a complete gate/result atomically; no partial JSON barrier."""
    if path.exists():
        raise FileExistsError(str(path))
    pending = path.with_name(path.name + '.writing-' + uuid4().hex)
    try:
        write_json(pending, value)
        pending.rename(path)
    finally:
        pending.unlink(missing_ok=True)


def wait_file(session, path, timeout=45):
    end = time.monotonic() + timeout
    last_error = None
    while True:
        try:
            return read(path)
        except (FileNotFoundError, PermissionError, json.JSONDecodeError) as exc:
            # Windows may briefly deny a just-renamed gate during scanning.
            # Only transport readiness is retried, never a poll or DB result.
            last_error = type(exc).__name__
        if any(p.poll() is not None for p, _, _ in session.children):
            raise BoundaryUnavailable('A controlled participant exited')
        if time.monotonic() >= end:
            raise BoundaryUnavailable('Unreadable physical control boundary: ' + path.name + ' / ' + last_error)
        time.sleep(.01)


def forecast_witness(peer):
    """Independent READ ONLY cut, narrowly scoped to the native predicate.

    Open the connection before entering the horizon. Query the real state
    inside it; do not reuse an earlier snapshot or execute a later replay.
    """
    from psycopg.rows import dict_row
    with peer.transaction(), peer.cursor(row_factory=dict_row) as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        cursor.execute('SELECT clock_timestamp() AS at, pg_backend_pid() AS pid')
        clock = cursor.fetchone()
        cursor.execute('SELECT id, organization_id, conversation_id, direction, status, '
                       'semantic_type, available_at, turn_work_id FROM channels_message ORDER BY id')
        messages = cursor.fetchall()
        cursor.execute('SELECT id, organization_id, conversation_id, status, claimed_at '
                       'FROM agent_turnwork ORDER BY id')
        works = cursor.fetchall()
    return json.loads(json.dumps(dict(db_ns=timestamp(clock['at'].isoformat()),
        backend_pid=clock['pid'], messages=messages, works=works,
        observation_kind='INDEPENDENT_MINIMAL_PRE_SELECTION_WITNESS'), default=str))


@contextmanager
def participants(session, mode):
    if mode not in ('loop', 'commands'):
        raise ValueError('Explicit finite participant mode required')
    try:
        for role in ROLES:
            log = (session.directory / (role + '.log')).open('x', encoding='utf-8')
            command = ['rtk', 'proxy', sys.executable, '-B', '-X', 'utf8', '-m', MODULE,
                       'participant', '--output', str(session.directory), '--case', session.case,
                       '--run-id', session.run_id, '--role', role, '--mode', mode]
            p = subprocess.Popen(command, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                                 stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            session.children.append((p, log, role))
        for role in ROLES:
            wait_file(session, session.directory / (role + '-started.json'))
        yield
    finally:
        (session.directory / 'stop').touch(exist_ok=True)
        for p, _, role in session.children:
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                # Session.cleanup performs the actual PID/backend cleanup.
                continue
            write_json(session.directory / (role + '-exit.json'),
                       dict(exit_code=p.returncode, stopped_by_fixture=True))


def participant(directory, case, run_id, role, mode):
    bootstrap()
    from django.db import connection
    from django.core.management import call_command
    from apps.agent import durable, worker
    from apps.channels.models import ChannelAccount
    from apps.organizations.models import Organization
    session = Session(directory, case, 'finite', run_id)
    session.fixtures = [(o, ChannelAccount.objects.filter(organization=o).first())
                        for o in Organization.objects.order_by('id')]
    with network_denied(), session.recorder.capture(role), contained(session, role):
        connection.ensure_connection()
        publish(session.directory / (role + '-started.json'),
                   dict(os_pid=os.getpid(), backend_pid=connection.connection.info.backend_pid,
                        db_ns=timestamp(durable.db_now().isoformat()), role=role, mode=mode))
        serial = 0
        while not (session.directory / 'stop').exists():
            if mode == 'loop':
                if not (session.directory / 'release').exists():
                    time.sleep(.01)
                    continue
                call_command('run_agent_worker', once=True,
                             mode='sender' if role == 'sender' else 'planner',
                             batch=1, poll=1, stdout=io.StringIO())
                time.sleep(1)
            else:
                request = session.directory / f'{role}-command-{serial:03d}.json'
                if not request.exists():
                    time.sleep(.005)
                    continue
                command = wait_file(session, request)
                captured_before = len(lines(session.directory / (role + '.jsonl')))
                pre = None
                if command.get('forecast_peer_message') is not None:
                    if role != 'planner_1':
                        raise ValueError('Forecast fixture requires its sole controlled planner')
                    from apps.channels.models import Message
                    peer = Message.objects.get(pk=command['forecast_peer_message'])
                    # Enter the unchanged one-second horizon naturally. The
                    # independent query occurs BEFORE selection; defer disk
                    # publication to avoid moving selection past the deadline.
                    with db_peer() as witness_connection:
                        wait_db(peer.available_at - timedelta(seconds=.9))
                        pre = forecast_witness(witness_connection)
                before = timestamp(durable.db_now().isoformat())
                if role == 'sender':
                    call_command('run_agent_worker', once=True, mode='sender', batch=1,
                                 poll=1, stdout=io.StringIO())
                    processed = None
                else:
                    processed = worker.process_pending_conversations(batch=1)
                after = timestamp(durable.db_now().isoformat())
                rows = lines(session.directory / (role + '.jsonl'))[captured_before:]
                trace = [r for r in rows if r['event'] in
                         ('selection_start', 'selection_result', 'selection_end',
                          'poll_start', 'poll_end', 'claim_result')]
                corrected = None
                if command.get('supersede_after_yield'):
                    if processed != 0 or any(r['event'] == 'claim_result' or
                            (r['event'] == 'selection_result' and r['conversation_ids']) for r in trace):
                        raise BoundaryUnavailable('Forecast correction requires an actual selection yield')
                    # Ordinary ingress immediately after the real query, before
                    # receipt publication. Sole emitter during this gate; use
                    # the next global attempt and retain the original ledger.
                    prior = lines(session.directory / 'offers.jsonl')
                    session.recorder.serial = max(o['attempt'] for o in prior)
                    new = session.recorder.offer(peer.channel_account, slot=0,
                          key='wamid.d29.' + run_id + '.forecast-correction')
                    if new is None:
                        raise BoundaryUnavailable('Ordinary forecast correction did not commit')
                    corrected = new.pk
                pre_name = None
                if pre is not None:
                    pre_name = command['pre_query_label'] + '-independent-before-query.json'
                    write_json(session.directory / pre_name, pre)
                publish(session.directory / f'{role}-result-{serial:03d}.json',
                           dict(command=command, role=role, os_pid=os.getpid(),
                                before_db_ns=before, after_db_ns=after, processed=processed,
                                pre_query_snapshot=pre_name, superseding_input_id=corrected,
                                trace=trace))
                serial += 1


def poll(session, role, serial, stage, **control):
    name = f'{role}-command-{serial:03d}.json'
    publish(session.directory / name, dict(stage=stage, baseline_clock=True, **control))
    result = f'{role}-result-{serial:03d}.json'
    return wait_file(session, session.directory / result), result


def prepare_backlog(session, members):
    """Captured ordinary ingress while no planner is allowed to poll.

    members is an explicit finite (org index, distinct conversation slot) list.
    It is never called a rate-sized CONFIRMED_BASE backlog by this helper.
    """
    if not members or len(set(members)) != len(members):
        raise ValueError('Backlog fixture requires distinct conversations')
    if (session.directory / 'release').exists():
        raise ValueError('Backlog must precede participant release')
    if any(r['event'] == 'poll_start' for role in ROLES for r in
           lines(session.directory / (role + '.jsonl'))
           if (session.directory / (role + '.jsonl')).exists()):
        raise ValueError('Backlog cannot be prepared after a real worker poll')
    from .runner import wait_ready
    rows = [session.offer(org, slot) for org, slot in members]
    for row in rows:
        wait_ready(row)
    cut, filename = session.snap('ready-before-release')
    wanted = {r.pk for r in rows}
    selected = [m for m in cut['messages'] if m['id'] in wanted]
    if (len(selected) != len(rows) or any(m['turn_work_id'] is not None or
            m['available_at'] is None or timestamp(m['available_at']) > cut['db_ns']
            for m in selected)):
        raise BoundaryUnavailable('Full natural READY fixture did not coexist')
    return rows, cut, filename


def prepare_burst(session, variant, phases):
    """Seal supplied schedules only; no base production, sizing or execution.

    A future caller must derive these schedules from an accredited base and
    obtain execution authorization. This phase cannot supply either item.
    Simultaneous/concentrated names describe affected organizations, not an
    assertion that independently committed messages share an atomic instant.
    """
    if variant not in ('simultaneous', 'concentrated'):
        raise ValueError('Explicit burst variant required')
    if [p['phase'] for p in phases] != ['before-burst', 'burst', 'base-return']:
        raise ValueError('Burst needs ordered pre-burst, burst and return calendars')
    for phase in phases:
        schedule(phase['assignments'], phase['offsets_ns'], phase['ends_ns'])
    value = dict(preparation('R1-05'), variant=variant, supplied_phases=phases,
                 schedule_provenance='UNACCREDITED_CALLER_SUPPLIED',
                 affected_org_indexes=[0, 1] if variant == 'simultaneous' else [0],
                 confirmed_base=None)
    write_json(session.directory / ('burst-' + variant + '-preparation.json'), value)
    return value


def schedule(assignments, offsets_ns=None, ends_ns=None):
    if not assignments:
        raise ValueError('A finite phase needs declared conversation slots')
    if offsets_ns is None and ends_ns is None:
        offsets_ns = [i * RELEASE_POLL_NS for i in range(len(assignments))]
        ends_ns = [(i + 1) * RELEASE_POLL_NS for i in range(len(assignments))]
    if offsets_ns is None or ends_ns is None or len(offsets_ns) != len(assignments) or len(ends_ns) != len(assignments):
        raise ValueError('Complete explicit release windows required')
    if any(type(x) is not int or x < 0 for x in offsets_ns + ends_ns) or any(
            lo >= hi for lo, hi in zip(offsets_ns, ends_ns)) or offsets_ns != sorted(offsets_ns):
        raise ValueError('Nonnegative ordered release windows required')
    return [dict(index=i, offset_ns=lo, end_offset_ns=hi,
                 organization_index=org, conversation_slot=slot)
            for i, ((org, slot), lo, hi) in enumerate(zip(assignments, offsets_ns, ends_ns))]


def emit_phase(session, phase, assignments, *, stage_kind='FINITE_GEOMETRY',
               offsets_ns=None, ends_ns=None):
    """Execute and capture one explicit finite global calendar.

    The generic phase emitter is also infrastructure for future burst/return.
    No per-minute rate, base assertion or extrapolation is computed here.
    """
    from apps.agent import durable
    calendar = schedule(assignments, offsets_ns, ends_ns)
    write_json(session.directory / (phase + '-calendar.json'),
               dict(phase=phase, kind=stage_kind, slots=calendar, rates_per_minute=None))
    start = time.perf_counter_ns()
    append(session.directory / 'phases.jsonl', dict(phase=phase, boundary='BEGIN',
           db_ns=timestamp(durable.db_now().isoformat()), monotonic_ns=start,
           calendar=phase + '-calendar.json'))
    rows = []
    for slot in calendar:
        due = start + slot['offset_ns']
        while time.perf_counter_ns() < due:
            if any(p.poll() is not None for p, _, _ in session.children):
                raise BoundaryUnavailable('Participant exited during finite offer')
            time.sleep(min(.01, (due - time.perf_counter_ns()) / NS))
        began = time.perf_counter_ns()
        row = session.offer(slot['organization_index'], slot['conversation_slot'])
        rows.append(row)
        attempt = session.recorder.offers[-1]
        append(session.directory / 'emissions.jsonl', dict(attempt,
               phase=phase, slot_index=slot['index'], due_monotonic_ns=due,
               end_monotonic_ns=start + slot['end_offset_ns'],
               started_monotonic_ns=began, finished_monotonic_ns=time.perf_counter_ns()))
    append(session.directory / 'phases.jsonl', dict(phase=phase, boundary='OFFERS_END',
           db_ns=timestamp(durable.db_now().isoformat()), monotonic_ns=time.perf_counter_ns()))
    return rows


def reconcile_cut(offers, cut, member_ids):
    """Retain input population, age, READY queue and work obligations separately."""
    wanted = set(member_ids)
    ledger = [o for o in offers if o.get('message_id') in wanted]
    accepted = {o['message_id'] for o in ledger if o['outcome'] == 'ACCEPTED_DURABLE'}
    messages = [m for m in cut['messages'] if m['id'] in wanted]
    observed = {m['id'] for m in messages}
    work_ids = {m['turn_work_id'] for m in messages if m['turn_work_id'] is not None}
    works = {w['id']: w for w in cut['works'] if w['id'] in work_ids}
    orgs = {}
    for m in messages:
        org = orgs.setdefault(m['organization_id'], dict(accepted_inputs=0, ready_queue_ids=[],
            future_queue_ids=[], input_ready_age_ns={}, assigned_input_ids=[], work_obligations=[]))
        org['accepted_inputs'] += m['id'] in accepted
        due = timestamp(str(m['available_at'])) if m['available_at'] is not None else None
        org['input_ready_age_ns'][m['id']] = max(0, cut['db_ns'] - due) if due is not None else None
        if m['turn_work_id'] is None:
            org['ready_queue_ids' if due is not None and due <= cut['db_ns'] else 'future_queue_ids'].append(m['id'])
        else:
            org['assigned_input_ids'].append(m['id'])
            work = works.get(m['turn_work_id'])
            if work is None or work['status'] != 'COMPLETED':
                if m['turn_work_id'] not in org['work_obligations']:
                    org['work_obligations'].append(m['turn_work_id'])
    return dict(db_ns=cut['db_ns'], requested_member_ids=sorted(wanted),
                missing_accepted_ids=sorted(wanted - accepted), missing_snapshot_ids=sorted(wanted - observed),
                accepted_inputs=len(accepted), organizations=orgs,
                all_obligations_resolved=bool(wanted) and accepted == observed == wanted and len(works) == len(work_ids)
                and all(m['turn_work_id'] is not None for m in messages)
                and all(w['status'] == 'COMPLETED' for w in works.values()),
                age_scope='INPUT_READY_AGE_ONLY_EPISODE_AGE_REQUIRES_RECONSTRUCT', rates=None)


def phase_cut(session, phase, rows):
    cut = session.recorder.snapshot(phase)
    result = reconcile_cut(session.recorder.offers, cut, [r.pk for r in rows])
    append(session.directory / 'phase-reconciliation.jsonl', dict(result, phase=phase,
           raw_snapshot='snapshots.jsonl', raw_ledger='offers.jsonl'))
    return result


def start_prepared_backlog(session, rows):
    """Future execution helper, never invoked as R1-06 in this phase.

    prepare_backlog must already have completed with no worker process started.
    Workers start after the pre-start cut, remain held until all startup markers
    are captured, and then run the unchanged natural selector.
    """
    if session.children:
        raise ValueError('R1-06 requires workers initially not started')
    cut, filename = session.snap('backlog-before-worker-start')
    check = reconcile_cut(session.recorder.offers, cut, [r.pk for r in rows])
    if check['missing_accepted_ids'] or check['missing_snapshot_ids'] or any(
            len(o['ready_queue_ids']) != o['accepted_inputs'] for o in check['organizations'].values()):
        raise BoundaryUnavailable('Backlog must be fully READY before worker start')
    write_json(session.directory / 'backlog-pre-start.json', dict(check, snapshot=filename,
               workers_started=False, confirmed_base=None, complete_case_status='PENDING'))
    with participants(session, 'loop'):
        phase_cut(session, 'workers-initialized-before-release', rows)
        (session.directory / 'release').touch()
        return observe_drain(session, rows, 'backlog-after-start')


def observe_drain(session, rows, label, limit=120):
    """Retain every obligation and separate READY queue from work completion."""
    end = time.monotonic() + limit
    wanted = {r.pk for r in rows}
    while True:
        cut = session.recorder.snapshot(label)
        reconciliation = reconcile_cut(session.recorder.offers, cut, wanted)
        append(session.directory / 'phase-reconciliation.jsonl', dict(reconciliation,
               phase=label, raw_snapshot='snapshots.jsonl', raw_ledger='offers.jsonl'))
        messages = [m for m in cut['messages'] if m['id'] in wanted]
        works = [w for w in cut['works'] if w['id'] in {m['turn_work_id'] for m in messages}]
        append(session.directory / 'drain.jsonl', dict(stage=label, db_ns=cut['db_ns'],
               member_ids=sorted(wanted), ready_unassigned=[m['id'] for m in messages
               if m['turn_work_id'] is None and m['available_at'] is not None
               and timestamp(str(m['available_at'])) <= cut['db_ns']],
               future_unassigned=[m['id'] for m in messages if m['turn_work_id'] is None
               and m['available_at'] is not None and timestamp(str(m['available_at'])) > cut['db_ns']],
               assigned=[m['id'] for m in messages if m['turn_work_id'] is not None],
               nonterminal_work_ids=[w['id'] for w in works if w['status'] != 'COMPLETED']))
        if reconciliation['all_obligations_resolved']:
            return session.snap(label + '-resolved')
        if time.monotonic() >= end:
            raise BoundaryUnavailable('Finite followup retained unresolved obligations')
        if any(p.poll() is not None for p, _, _ in session.children):
            raise BoundaryUnavailable('Participant exited before drain observation')
        time.sleep(.1)


def preparation(case):
    if case not in ('R1-05', 'R1-06'):
        raise ValueError('Only the dependent preparations are declared here')
    return dict(case_id=case, status='PENDING', schema='d29-dependent-preparation-v1',
                infrastructure='IMPLEMENTED', source_kind='PREPARATION_ONLY',
                physical_frontier=dict(status='NOT_EXECUTED_AS_COMPLETE_SCENARIO'),
                load_condition=dict(status='NOT_ACCREDITED'),
                prerequisites=[dict(name='CONFIRMED_BASE', status='PENDING',
                                    producer='NOT_IMPLEMENTED_REQUIRES_CHARACTERIZATION')],
                evidence_synthetic=[], evidence_physical=[], characterization=False,
                benchmark=False, sustainable_envelope=None,
                helpers=['prepare_burst', 'emit_phase', 'phase_cut', 'reconcile_cut', 'observe_drain'] if case == 'R1-05'
                else ['prepare_backlog', 'start_prepared_backlog', 'phase_cut', 'reconcile_cut', 'observe_drain'],
                future_execution_authorized=False)
