"""Isolated D29 live adapter and finite pipeline probe.

Only the explicit series command emits sustained load. The finite probe uses
two ordinary inputs and cannot produce a level acceptance or calibration rate.
Scenario adapters are checked before DB allocation; no ordinary fallback can
pretend to execute an unimplemented fault boundary.
"""
import argparse
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import time
import tarfile
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from .assessment import assess
from .controller import digest
from .evidence import NS, ClockMap, Episode, Interval, queue_counts, reconstruct, timestamp
from .recipes import verify_recipe
from .replay import schedule
from .runner import BASELINE, Recorder, bootstrap, network_denied, require_empty_database, source_manifest, write_json

MODULE = 'apps.agent.tests.scheduling_characterization.execution'
DIRECT_LOAD_CASES = ('R1-01', 'R1-02', 'R1-03', 'R1-04', 'R1-05', 'R1-06', 'R2-01', 'R2-02', 'R2-09')


def verify_sources():
    """Compare all tracked baseline Python sources to the archive, in memory."""
    backend = Path(__file__).resolve().parents[4]
    root = backend.parent
    archive = subprocess.check_output(['rtk', 'proxy', 'git', 'archive', '--format=tar', BASELINE, 'backend'],
                                      cwd=os.environ.get('D29_ARCHIVE_REPOSITORY', str(root)))
    changed = []
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        for member in files.getmembers():
            if member.isfile() and member.name.endswith('.py'):
                target = root / member.name
                expected = hashlib.sha256(files.extractfile(member).read()).hexdigest()
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                    changed.append(member.name)
    if changed:
        raise RuntimeError('Baseline Python sources differ from archived baseline')
    return True


def append(path, value):
    with Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, separators=(',', ':')) + '\n')
        stream.flush()


def read_lines(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines()] if Path(path).exists() else []


class Provider:
    """Synthetic wire with independent durable admissions and cost witnesses."""
    def __init__(self, directory, role, job):
        self.directory, self.role, self.job = directory, role, job
        self.calls = defaultdict(int)
        self.serial = 0
        self.meta_message = None

    def request(self, session, method, url, **kwargs):
        import requests
        from django.db import connection
        from django.test import Client
        from apps.agent import durable
        from apps.agent.models import LLMCall
        from apps.agent.turn_changes import current_changes
        from apps.agent.tests.b9a_harness import answer, response, tool
        host = urlsplit(url).hostname
        if host not in ('llm.b9a.invalid', 'meta.b9a.invalid', 'b9a.internal.test'):
            raise AssertionError('External destination outside contained fixture')
        if connection.in_atomic_block:
            raise AssertionError('HTTP under transaction')
        changes = current_changes()
        witness = changes.witness if changes is not None else None
        if host == 'b9a.internal.test':
            time.sleep(.1)
            target = urlsplit(url)
            path = target.path + ('?' + target.query if target.query else '')
            headers = {'HTTP_' + k.upper().replace('-', '_'): v for k, v in kwargs.get('headers', {}).items()}
            client = Client()
            if kwargs.get('json') is not None:
                reply = client.generic(method.upper(), path, json.dumps(kwargs['json']), content_type='application/json', **headers)
            else:
                reply = getattr(client, method.lower())(path, kwargs.get('params') or {}, **headers)
            result = requests.Response()
            result.status_code, result._content = reply.status_code, reply.content
            result.headers.update(dict(reply.headers))
            return result
        event = dict(boundary='llm' if host == 'llm.b9a.invalid' else 'meta',
                     in_atomic=False, external_destination=False, db_ns=timestamp(durable.db_now().isoformat()))
        if host == 'llm.b9a.invalid':
            if witness is None:
                raise AssertionError('LLM without ownership witness')
            call = LLMCall.objects.filter(turn_work_id=witness.turn_work_id,
                organization_id=witness.organization_id, admission_lease_token=witness.lease_token,
                admission_epoch=witness.ownership_epoch, admitted_at__isnull=False, recorded_at__isnull=True).first()
            active = durable.active_org_work(witness.organization_id)
            event.update(organization_id=witness.organization_id, turn_work_id=witness.turn_work_id,
                         epoch=witness.ownership_epoch, lease_fingerprint=hashlib.sha256(witness.lease_token.bytes).hexdigest(),
                         admission_verified=call is not None, active_org_work=active.count(),
                         matching_active_work=active.filter(pk=witness.turn_work_id, lease_token=witness.lease_token).exists())
            if not event['admission_verified'] or event['active_org_work'] != 1 or not event['matching_active_work']:
                raise AssertionError('LLM without exclusive admitted claim')
            self.calls[witness.turn_work_id] += 1
            event['call_number'] = self.calls[witness.turn_work_id]
            delay = .5
        else:
            row = self.meta_message
            if row is None:
                raise AssertionError('Meta without sender admission observation')
            row.refresh_from_db()
            event.update(organization_id=row.organization_id, message_id=row.pk,
                         admission_verified=row.send_admitted_at is not None)
            delay = .2
        affected = event['organization_id'] == self.job['organization_ids'][0]
        if affected and self.job['case_id'] == 'R2-01' and event['boundary'] == 'llm':
            delay *= self.job['slow_multiplier']
        if affected and self.job['case_id'] == 'R2-09' and event['boundary'] == 'meta' and self.job['variant'] == 'slow_meta':
            delay *= self.job['slow_multiplier']
        start = time.perf_counter_ns()
        append(self.directory / (self.role + '-wire.jsonl'), dict(event, event='dispatch', monotonic_ns=start))
        if affected and self.job['case_id'] == 'R2-02' and event['boundary'] == 'llm':
            marker = self.directory / 'llm-block-acquired'
            try:
                with marker.open('x') as stream:
                    stream.write(self.role)
            except FileExistsError:
                pass
            else:
                append(self.directory / (self.role + '-events.jsonl'), dict(event='llm_admitted', run_id=self.job['run_id'],
                    organization_index=0, db_ns=event['db_ns'], observed=True, source='INDEPENDENT_DB_WITNESS'))
                append(self.directory / (self.role + '-events.jsonl'), dict(event='block_begin', run_id=self.job['run_id'],
                    organization_index=0, db_ns=timestamp(durable.db_now().isoformat()), observed=True, source='CONTAINED_PROVIDER'))
                time.sleep(self.job['blocked_llm_hold_seconds'])
                append(self.directory / (self.role + '-events.jsonl'), dict(event='block_release', run_id=self.job['run_id'],
                    organization_index=0, db_ns=timestamp(durable.db_now().isoformat()), observed=True, source='CONTAINED_PROVIDER'))
        time.sleep(delay)
        result_kind = 'UNCERTAIN' if affected and self.job['case_id'] == 'R2-09' and self.job['variant'] == 'uncertain_meta' else 'ACCEPTED'
        append(self.directory / (self.role + '-wire.jsonl'), dict(event, event='result', result=result_kind,
               monotonic_ns=time.perf_counter_ns(), elapsed_ns=time.perf_counter_ns() - start))
        if result_kind == 'UNCERTAIN':
            raise requests.Timeout('Synthetic uncertain Meta result')
        if host == 'llm.b9a.invalid':
            return response(tool('get_service_catalog') if self.calls[witness.turn_work_id] == 1 else answer())
        self.serial += 1
        return response({'messages': [{'id': f'wamid.d29.controller.{os.getpid()}.{self.serial}'}]})


def worker(directory, role, job):
    bootstrap()
    import requests
    from django.core.management import call_command
    from django.db import connection
    from django.test import override_settings
    from apps.agent import sender
    from apps.agent.tests.b9a_harness import SETTINGS
    provider = Provider(directory, role, job)
    original_admit = sender.admit_dispatch
    def admit(claim):
        row = original_admit(claim)
        provider.meta_message = row
        return row
    settings = dict(SETTINGS, AGENT_SAFETY_AUTOMATION_ENABLED=True)
    with Recorder(directory, job['run_id']).capture(role), override_settings(**settings), \
            patch.object(requests.Session, 'request', lambda session, method, url, **kw: provider.request(session, method, url, **kw)), \
            patch.object(sender, 'admit_dispatch', admit):
        # Ready after containment and capture are active.
        (directory / (role + '.ready')).write_text('ready\n', encoding='utf-8')
        while not (directory / 'stop').exists():
            call_command('run_agent_worker', once=True, mode='sender' if role == 'sender' else 'planner',
                         batch=1, poll=1, stdout=io.StringIO())
            time.sleep(1)


@contextmanager
def participants(directory, job):
    processes, streams = [], []
    write_json(directory / 'participant-plan.json', job)
    try:
        for role in ('planner_1', 'planner_2', 'sender'):
            stream = (directory / (role + '.log')).open('x', encoding='utf-8')
            streams.append(stream)
            process = subprocess.Popen(['rtk', 'proxy', sys.executable, '-X', 'utf8', '-m', MODULE, 'worker',
                '--output', str(directory), '--role', role, '--job', str(directory / 'participant-plan.json')],
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'),
                stdout=stream, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            processes.append(process)
        deadline = time.monotonic() + 45
        while not all((directory / (role + '.ready')).exists() for role in ('planner_1', 'planner_2', 'sender')):
            if time.monotonic() >= deadline or any(p.poll() is not None for p in processes):
                raise RuntimeError('Participants failed preparation')
            time.sleep(.05)
        yield processes
    finally:
        (directory / 'stop').touch()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
        for stream in streams:
            stream.close()


def health(processes):
    if any(p.poll() is not None for p in processes):
        raise RuntimeError('Participant exited before declared stop')


def offer(recorder, fixture, slot, schedule_slot=None, phase='ORDINARY'):
    started = time.perf_counter_ns()
    row = recorder.offer(fixture[1], slot=slot)
    # Existing Recorder ledger stays untouched; additional schedule ledger is
    # independent and includes all accepted/failed attempts and their timing.
    result = dict(recorder.offers[-1], started_monotonic_ns=started,
                  finished_monotonic_ns=time.perf_counter_ns(), phase=phase,
                  schedule_id=schedule_slot['id'] if schedule_slot else None)
    recorder.offers[-1].update(result)
    append(recorder.directory / 'schedule-offers.jsonl', result)
    return row


def wait_claim(row, processes, limit=165):
    deadline = time.monotonic() + limit
    while True:
        health(processes)
        row.refresh_from_db()
        if row.turn_work_id:
            return row.turn_work_id
        if time.monotonic() >= deadline:
            return None
        time.sleep(.05)


def read_capture(directory):
    from apps.agent.claim_diagnostic_report import read_journal
    return [read_journal(directory / (role + '.jsonl')) for role in ('ingress', 'planner_1', 'planner_2', 'sender')]


def queued_samples(report, offsets, intervals):
    eps = [Episode(e['organization_id'], e['conversation_id'], 1, members=e['member_ids'],
                   ready=Interval(*e['ready_ns_bounds']),
                   claim=Interval(*e['claim_commit_ns_bounds']) if e['claim_commit_ns_bounds'] else None)
           for e in report['episodes']]
    samples = []
    for offset, interval in zip(offsets, intervals):
        counts = queue_counts(eps, interval)
        per_org = {str(o): counts.get(int(o), [0, 0]) for o in report['organization_counts']}
        per_org['global'] = [sum(c[i] for c in per_org.values()) for i in (0, 1)]
        samples.append(dict(offset_seconds=offset, counts=per_org, correlated_clock=True,
                            db_ns_bounds=interval.json()))
    return samples


def execute_job(directory, job, *, finite=False):
    """Run a fresh isolated job; each calibration episode waits its real claim."""
    bootstrap()
    require_empty_database()
    verify_sources()
    if not finite and job['case_id'] not in DIRECT_LOAD_CASES:
        raise RuntimeError('This scenario needs its boundary injection adapter; ordinary fallback is forbidden')
    directory.mkdir(parents=True, exist_ok=False)
    source_manifest(directory)
    write_json(directory / 'sealed-job.json', job)
    from apps.agent.tests.test_b9a_e2e import seed_domain
    from apps.agent import durable
    fixtures = [seed_domain('D29C-' + job['run_id'] + '-' + str(i)) for i in range(job['organization_count'])]
    job = dict(job, organization_ids=[f[0].pk for f in fixtures])
    recorder = Recorder(directory, job['run_id'])
    slots, offsets, mono_cuts = [], [], []
    events = []
    with network_denied(), recorder.capture('ingress'):
      if not finite and job['case_id'] == 'R1-06':
        for org, rate in enumerate(job['offered_rates_per_minute']):
            needed = math.ceil(rate * 2)
            if needed > job['conversations_per_org']:
                raise ValueError('Backlog needs distinct conversations; seal a new plan with sufficient fixture size')
            for slot in range(needed):
                row = offer(recorder, fixtures[org], slot, phase='BACKLOG')
                if row is None:
                    raise RuntimeError('Backlog ingress unresolved')
        from .runner import wait_ready
        for row in __import__('apps.channels.models', fromlist=['Message']).Message.objects.filter(direction='in'):
            wait_ready(row)
        recorder.snapshot('backlog_ready_before_workers')
      with participants(directory, job) as processes:
        first = recorder.snapshot('initial')
        start = time.perf_counter_ns()
        if finite or job['phase'] == 'CALIBRATE':
            count = 1 if finite else job['calibration_episodes_per_org']
            for n in range(count):
                for f in fixtures:
                    row = offer(recorder, f, n % job['conversations_per_org'])
                    if row is None or wait_claim(row, processes) is None:
                        raise RuntimeError('Calibration/probe input unresolved; no reference can be derived')
            # Claims alone are not a service witness. Wait for this finite
            # population to finish and for sender disposition to be visible.
            # A finite R2-02 probe must observe the declared real provider hold
            # before stopping participants. This changes no lease/load policy.
            followup = 45 + (job['blocked_llm_hold_seconds'] if finite and job['case_id'] == 'R2-02' else 0)
            end = time.monotonic() + followup
            while True:
                snap = recorder.snapshot('finite_followup')
                if snap['works'] and all(w['status'] == 'COMPLETED' for w in snap['works']):
                    from apps.channels.models import Message
                    resolved = Message.objects.filter(direction='out', provider_accepted_at__isnull=False).count()
                    # The finite negative sender probe must retain uncertainty;
                    # it is a terminal observation, never provider acceptance.
                    if finite and job['case_id'] == 'R2-09' and job['variant'] == 'uncertain_meta':
                        resolved += Message.objects.filter(direction='out', status='uncertain',
                            organization_id=job['organization_ids'][0]).count()
                    if resolved == count * len(fixtures):
                        break
                health(processes)
                if time.monotonic() >= end:
                    raise RuntimeError('Finite service/sender did not resolve')
                time.sleep(.1)
        else:
            slots = schedule(job, start)
            offsets = list(range(0, job['offer_seconds'] + 1, 120))
            if offsets[-1] != job['offer_seconds']:
                offsets.append(job['offer_seconds'])
            mono_cuts = [start + offset * NS for offset in offsets]
            write_json(directory / 'schedule.json', slots)
            for n, slot in enumerate(slots):
                while time.perf_counter_ns() < slot['due_monotonic_ns']:
                    health(processes)
                    time.sleep(min(.05, (slot['due_monotonic_ns'] - time.perf_counter_ns()) / NS))
                offer(recorder, fixtures[slot['organization_index']], n % job['conversations_per_org'], slot)
            offer_end = start + job['offer_seconds'] * NS
            while time.perf_counter_ns() < offer_end:
                health(processes)
                time.sleep(.05)
            recorder.snapshot('offer_end')
            follow_end = time.monotonic() + job['followup_seconds']
            while time.monotonic() < follow_end:
                health(processes)
                snap = recorder.snapshot('followup')
                if not [m for m in snap['messages'] if m['turn_work_id'] is None and m['status'] == 'pending']:
                    break
                time.sleep(.25)
        final = recorder.snapshot('final')
    journals = read_capture(directory)
    report = reconstruct(journals, recorder.offers, final['messages'], Interval(final['db_ns'], final['db_ns']), run_id=job['run_id'])
    dispatches = [e for role in ('planner_1', 'planner_2', 'sender')
                  for e in read_lines(directory / (role + '-wire.jsonl')) if e['event'] == 'dispatch']
    from .assessment import invariant_gate
    invariant = invariant_gate(report, journals, final['messages'], final['works'], dispatches, job['organization_ids'])
    preparation = dict(fresh_database=True, participants_ready_before_offer=True, source_integrity=verify_sources(),
                       capture_all_participants=not report['issues'], durable_database=True, contained_provider=True)
    if finite:
        result = dict(report, job_sha256=job['job_sha256'], source_kind='ISOLATED_LIVE',
                      dispositions=['FINITE_PIPELINE_PROBE_NOT_LEVEL_ACCEPTANCE'], benchmark=False,
                      checks=dict(inputs=len(recorder.offers) == job['organization_count'],
                          cohort_complete=not report['issues'], within_observed=report['summary']['OBSERVED_WITHIN_TARGET'] == len(fixtures),
                          independent_wire_invariants=not invariant['missing'] and not invariant['violations'],
                          participants_exited_normally=all(p.returncode == 0 for p in processes)),
                      invariants=invariant, calibration_reference_by_org_index=None)
    elif job['phase'] == 'CALIBRATE':
        refs = []
        for org in job['organization_ids']:
            episodes = [e for e in report['episodes'] if e['organization_id'] == org]
            duration = max(e['claim_commit_ns_bounds'][1] for e in episodes) - min(e['ready_ns_bounds'][0] for e in episodes)
            refs.append(60 * NS * len(episodes) / duration if duration > 0 else None)
        valid = (not report['issues'] and not invariant['missing'] and not invariant['violations']
                 and report['summary']['OBSERVED_WITHIN_TARGET'] == len(fixtures) * job['calibration_episodes_per_org'])
        result = dict(report, job_sha256=job['job_sha256'], source_kind='ISOLATED_LIVE', invariants=invariant,
                      dispositions=['CALIBRATION_REFERENCE_OBSERVED'] if valid else ['INDETERMINATE'],
                      calibration_reference_by_org_index=refs if valid else None)
    else:
        clock = ClockMap(next(j for j in journals if j[0]['worker'] == 'ingress'))
        if clock.offset is None:
            raise RuntimeError('Offer/window clock not calibrated')
        intervals = [Interval(t + clock.offset.lo, t + clock.offset.hi) for t in mono_cuts]
        queues = queued_samples(report, offsets, intervals)
        # Required boundaries are derived from observations. Missing advanced
        # cases remain INDETERMINATE instead of being inferred from case IDs.
        from .scenario_observations import observations
        events = observations(job, report, journals, dispatches, read_lines, directory, final)
        result = assess(job, report, offers=recorder.offers, scheduled=slots, organizations=job['organization_ids'],
                        offer_span=(intervals[0].lo, intervals[-1].hi), queue_samples=queues,
                        journals=journals, census=final['messages'], works=final['works'], wire=dispatches,
                        preparation=preparation, recipe=verify_recipe(job, events))
        result.update(job_sha256=job['job_sha256'], scenario_events=events, queue_samples=queues,
                      rates_note='Nominal input pacing and actual READY episodes are reported separately; natural deadlines unchanged.')
    write_json(directory / 'job-result.json', result)
    return result


class LiveBackend:
    synthetic = False

    def __init__(self, template, output):
        if not template.startswith('test_'):
            raise ValueError('Explicit test_* schema template required')
        self.template, self.output = template, Path(output)

    def preflight(self, plan):
        unsupported = sorted(set(plan['cases']) - set(DIRECT_LOAD_CASES))
        if unsupported:
            raise ValueError('Live injection adapters required before this series: ' + ', '.join(unsupported))
        verify_sources()

    def execute(self, job):
        import psycopg
        from psycopg import sql
        config = json.loads(os.environ.get('B3_TEST_DATABASE', '{}'))
        if config.get('HOST') not in ('127.0.0.1', 'localhost') or config.get('NAME') != self.template:
            raise ValueError('Explicit local schema template configuration required')
        if job['case_id'] not in DIRECT_LOAD_CASES:
            raise RuntimeError('Scenario injection adapter not accredited; no silent ordinary fallback')
        name = 'test_d29_' + hashlib.sha256(job['run_id'].encode()).hexdigest()[:24]
        directory = self.output / (job['run_id'] + '-live')
        with psycopg.connect(dbname='postgres', user=config['USER'], password=config['PASSWORD'],
                            host=config['HOST'], port=config['PORT'], autocommit=True) as admin:
            # Never drop/reuse a pre-existing database. Only this successfully
            # created fresh database belongs to this job and may be removed.
            admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(name), sql.Identifier(self.template)))
            try:
                isolated = dict(config, NAME=name)
                path = self.output / (job['run_id'] + '-executor.json')
                write_json(path, job)
                with (self.output / (job['run_id'] + '-executor.log')).open('x', encoding='utf-8') as stream:
                    process = subprocess.run(['rtk', 'proxy', sys.executable, '-X', 'utf8', '-m', MODULE, 'job',
                        '--job', str(path), '--output', str(directory), '--execute-load'],
                        env=dict(os.environ, B3_TEST_DATABASE=json.dumps(isolated), PYTHONDONTWRITEBYTECODE='1'),
                        stdout=stream, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if process.returncode != 0:
                    raise RuntimeError('Isolated job failed; inspect executor log')
                return json.loads((directory / 'job-result.json').read_text(encoding='utf-8'))
            finally:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                write_json(self.output / (job['run_id'] + '-database-cleanup.json'), {'created_database': name, 'removed': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('worker', 'job', 'finite-probe'))
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--role', choices=('planner_1', 'planner_2', 'sender'))
    parser.add_argument('--execute-load', action='store_true')
    args = parser.parse_args()
    job = json.loads(args.job.read_text(encoding='utf-8'))
    if args.command == 'worker':
        if args.role is None:
            parser.error('worker requires --role')
        worker(args.output, args.role, job)
        return
    unsigned = dict(job)
    seal = unsigned.pop('job_sha256', None)
    if seal != digest(unsigned) or job.get('baseline') != BASELINE or job.get('bound_seconds') != 120:
        parser.error('Invalid or modified sealed job')
    from .controller import source_hashes
    if job.get('source_hashes') != source_hashes():
        parser.error('Job sources changed after sealing')
    if args.command == 'job' and not args.execute_load:
        parser.error('job requires --execute-load; finite-probe cannot accept a level')
    result = execute_job(args.output, job, finite=args.command == 'finite-probe')
    print(json.dumps({'dispositions': result['dispositions'], 'checks': result.get('checks')}))
    if args.command == 'finite-probe' and not all(result['checks'].values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
