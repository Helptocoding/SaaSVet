"""PROFILE-BETA-1 load witness on an isolated local PostgreSQL database.

Run with ``python -m apps.agent.tests.b9e_profile --scenario base --output PATH``.
This is a test-only process harness; the application runtime is unchanged.
"""
import argparse
import hashlib
import io
import json
import os
import site
import subprocess
import sys
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit


def setup():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    os.environ.update(DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='',
                      HEALTHCHECK_AGENT_WORKER_URL='', HEALTHCHECK_AGENT_SENDER_URL='')
    import django
    django.setup()
    from django.db import connection
    config = connection.settings_dict
    if (connection.vendor != 'postgresql' or not config['NAME'].startswith('test_')
            or config['HOST'] not in ('127.0.0.1', 'localhost')):
        raise RuntimeError('PROFILE-BETA-1 requires isolated local test PostgreSQL')
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid(), current_setting(%s), current_setting(%s)',
                       ['fsync', 'synchronous_commit'])
        pid, fsync, synchronous_commit = cursor.fetchone()
    if (fsync, synchronous_commit) != ('on', 'on'):
        raise RuntimeError('PostgreSQL durability settings are not enabled')
    return pid


def worker(role, scenario, stop_path):
    pid = setup()
    import requests
    from django.core.management import call_command
    from django.db import connection
    from django.test import Client, override_settings
    from apps.agent.turn_changes import current_changes
    from .b9a_harness import SETTINGS, answer, response, tool

    llm_count = defaultdict(int)
    wire_count = defaultdict(int)
    serial = 0
    blocked_once = False
    noisy_org_id = int(os.environ['B9E_NOISY_ORG_ID'])
    block_marker = stop_path.with_suffix('.blocked')
    measure_marker = stop_path.with_suffix('.measure')

    def request(session, method, url, **kwargs):
        nonlocal serial, blocked_once
        target = urlsplit(url)
        if target.hostname == 'b9a.internal.test':
            time.sleep(0.1)
            headers = {'HTTP_' + k.upper().replace('-', '_'): v
                       for k, v in kwargs.get('headers', {}).items()}
            path = target.path + ('?' + target.query if target.query else '')
            client = Client()
            if kwargs.get('json') is not None:
                reply = client.generic(method.upper(), path, json.dumps(kwargs['json']),
                                       content_type='application/json', **headers)
            else:
                reply = getattr(client, method.lower())(path, kwargs.get('params') or {}, **headers)
            result = requests.Response()
            result.status_code, result._content = reply.status_code, reply.content
            result.headers.update(dict(reply.headers))
            wire_count['domain_http'] += 1
            return result
        if target.hostname == 'llm.b9a.invalid':
            if connection.in_atomic_block:
                raise AssertionError('LLM HTTP under transaction')
            changes = current_changes()
            if changes is None:
                raise AssertionError('LLM HTTP without TurnWork context')
            work_id = changes.witness.turn_work_id
            llm_count[work_id] += 1
            wire_count['llm'] += 1
            if (scenario == 'blocked_llm' and measure_marker.exists()
                    and changes.witness.organization_id == noisy_org_id
                    and not blocked_once):
                blocked_once = True
                try:
                    descriptor = os.open(block_marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                except FileExistsError:
                    pass
                else:
                    os.close(descriptor)
                    time.sleep(10)
                    raise requests.Timeout('PROFILE-BETA-1 controlled 10 s timeout')
            time.sleep(0.5)
            return response(tool('get_service_catalog') if llm_count[work_id] == 1 else answer())
        if target.hostname == 'meta.b9a.invalid':
            if connection.in_atomic_block:
                raise AssertionError('Meta HTTP under transaction')
            wire_count['meta'] += 1
            time.sleep(2 if scenario == 'meta_slow' else 0.2)
            serial += 1
            return response({'messages': [{'id': f'wamid.b9e.{os.getpid()}.{serial}'}]})
        raise AssertionError('PROFILE-BETA-1 forbids external network destinations')

    settings = dict(SETTINGS, AGENT_SAFETY_AUTOMATION_ENABLED=True)
    print('B9E_READY ' + json.dumps({'pid': os.getpid(), 'backend_pid': pid,
                                    'role': role, 'scenario': scenario}), flush=True)
    with override_settings(**settings), patch.object(requests.Session, 'request', request):
        while not stop_path.exists():
            call_command('run_agent_worker', once=True,
                         mode='sender' if role == 'sender' else 'planner',
                         batch=1, poll=1, stdout=io.StringIO())
            time.sleep(1)
    print('B9E_RESULT ' + json.dumps({'pid': os.getpid(), 'backend_pid': pid,
                                     'role': role, 'wire': dict(wire_count),
                                     'llm_calls_per_work': dict(llm_count)}), flush=True)


def percentile(values, quantile):
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * quantile + 0.999999))] if values else None


def observe(label, start, end, org_ids, samples, events, processes):
    from django.db.models import Count
    from apps.agent.models import TurnWork
    from apps.channels.models import Message
    from django.utils import timezone

    inbounds = list(Message.objects.filter(direction='in', organization_id__in=org_ids,
                    created_at__gte=start, created_at__lt=end).select_related('turn_work'))
    outbounds = list(Message.objects.filter(direction='out', organization_id__in=org_ids,
                     created_at__gte=start, created_at__lt=end))
    healthy = set(org_ids[:2])
    claim = []
    safety = []
    missing_claim = []
    for msg in inbounds:
        if msg.organization_id not in healthy:
            continue
        if msg.turn_work_id and msg.turn_work.claimed_at:
            claim.append((msg.turn_work.claimed_at - msg.created_at).total_seconds())
        elif msg.semantic_type != Message.SEMANTIC_SAFETY_GUIDANCE:
            missing_claim.append(msg.pk)
    dispatch = []
    missing_dispatch = []
    for msg in outbounds:
        if msg.send_admitted_at:
            value = (msg.send_admitted_at - msg.created_at).total_seconds()
            dispatch.append(value)
            if msg.semantic_type == Message.SEMANTIC_SAFETY_GUIDANCE:
                safety.append(value)
        else:
            missing_dispatch.append(msg.pk)
    final = {
        'scenario': label, 'window_utc': [start.isoformat(), end.isoformat()],
        'postgresql_process_ids': processes,
        'inbound_count': len(inbounds), 'outbound_count': len(outbounds),
        'healthy_claim': {'count': len(claim), 'p95_seconds': percentile(claim, .95),
                          'max_seconds': max(claim, default=None), 'missing': len(missing_claim)},
        'safety_dispatch': {'count': len(safety), 'p95_seconds': percentile(safety, .95),
                            'max_seconds': max(safety, default=None)},
        'outbox_dispatch': {'count': len(dispatch), 'p95_seconds': percentile(dispatch, .95),
                            'max_seconds': max(dispatch, default=None), 'missing': len(missing_dispatch)},
        'queue_samples': samples,
        'generator_events': events,
        'turnwork_status': list(TurnWork.objects.filter(organization_id__in=org_ids)
                                .values('status').annotate(count=Count('pk'))),
        'outbound_status': list(Message.objects.filter(direction='out', organization_id__in=org_ids)
                                .values('status').annotate(count=Count('pk'))),
    }
    max_active = max((row['count'] for item in samples for row in item['active_work']), default=0)
    final['max_active_per_org_observed'] = max_active
    final['max_pending_inbound_observed'] = max((x['pending_inbound'] for x in samples), default=0)
    final['max_outbound_attempts'] = max((msg.attempts for msg in outbounds), default=0)
    if label in ('base', 'blocked_llm'):
        gates = {
            'healthy_claim_p95_le_10': bool(claim) and not missing_claim and percentile(claim, .95) <= 10,
            'safety_dispatch_p95_le_5': bool(safety) and percentile(safety, .95) <= 5,
        }
        if label == 'base':
            gates['outbox_dispatch_p95_le_5'] = (bool(dispatch) and not missing_dispatch
                                                  and percentile(dispatch, .95) <= 5)
    elif label == 'meta_slow':
        gates = {
            'durable_outbound_state': bool(outbounds) and all(msg.status in
                ('pending', 'sending', 'sent', 'delivered', 'read', 'uncertain', 'failed', 'discarded')
                for msg in outbounds),
            'bounded_concurrency': max_active <= 1,
            'no_blind_retry': all(msg.attempts <= 1 for msg in outbounds),
        }
    elif label == 'duplicate':
        gates = {'duplicate_webhook_deduplicated': events['duplicates'] > 0 and not events['errors']}
    else:
        gates = {'safety_admitted_under_saturation': bool(safety) and not missing_dispatch,
                 'bounded_concurrency': max_active <= 1,
                 'saturation_observed': final['max_pending_inbound_observed'] > 0}
    final['gates'] = gates
    final['technical_pass'] = all(gates.values()) and not events['errors']
    return final


def orchestrate(scenario, output, smoke=False):
    setup()
    from django.db import connection
    from django.test import override_settings
    from django.utils import timezone
    from apps.agent.models import TurnWork
    from apps.channels.models import Message
    from .b9a_harness import ApplicationHarness, SETTINGS
    from .test_b9a_e2e import seed_domain

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise RuntimeError('Refusing to overwrite an acceptance receipt')
    suffix = hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:8]
    fixtures = [seed_domain('B9E-' + suffix + '-' + str(i)) for i in range(3)]
    org_ids = [row[0].pk for row in fixtures]
    channels = [row[1] for row in fixtures]
    harnesses = [ApplicationHarness(channel) for channel in channels]
    stop_path = output.with_suffix('.stop')
    if any(path.exists() for path in (stop_path, stop_path.with_suffix('.measure'),
                                      stop_path.with_suffix('.blocked'))):
        raise RuntimeError('Stale profile marker at ' + str(stop_path))
    process_info = []
    processes = []
    child_logs = []
    events = {'sent': [0, 0, 0], 'safety': 0, 'duplicates': 0, 'errors': []}
    samples = []
    try:
        for role in ('planner-1', 'planner-2', 'sender'):
            log = output.with_name(output.stem + '-' + role + '.log')
            handle = log.open('w', encoding='utf-8')
            child_logs.append(handle)
            proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable),
                '-X', 'utf8', '-m', 'apps.agent.tests.b9e_profile',
                '--role', role, '--scenario', scenario, '--stop', str(stop_path)],
                cwd=Path(__file__).resolve().parents[3], env=dict(os.environ,
                PYTHONIOENCODING='utf-8', DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='',
                B9E_NOISY_ORG_ID=str(org_ids[2]),
                PYTHONPATH=os.pathsep.join(site.getsitepackages())),
                stdout=handle, stderr=subprocess.STDOUT)
            processes.append(proc)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready = []
            for role in ('planner-1', 'planner-2', 'sender'):
                log = output.with_name(output.stem + '-' + role + '.log')
                for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
                    if line.startswith('B9E_READY '):
                        ready.append(json.loads(line.split(' ', 1)[1]))
                        break
            if len(ready) == 3:
                process_info = ready
                break
            if any(proc.poll() is not None for proc in processes):
                raise RuntimeError('Worker exited before READY')
            time.sleep(.25)
        if len(process_info) != 3:
            raise RuntimeError('Workers did not become ready')
        warmup = 2 if smoke else 30
        measure = 10 if smoke else 300
        origin = time.monotonic()
        origin_utc = timezone.now()
        next_due = [origin, origin, origin]
        last_sample = -1
        with override_settings(**dict(SETTINGS, AGENT_SAFETY_AUTOMATION_ENABLED=True)):
            while True:
                elapsed = time.monotonic() - origin
                if elapsed >= warmup + measure:
                    break
                if elapsed >= warmup and not stop_path.with_suffix('.measure').exists():
                    stop_path.with_suffix('.measure').touch()
                second = int(elapsed)
                for i in range(3):
                    interval = 10 if i < 2 else 1
                    if time.monotonic() < next_due[i]:
                        continue
                    serial = events['sent'][i]
                    is_safety = i < 2 and (scenario == 'saturation' or serial % 3 == 0)
                    body = ('Mi perro está convulsionando ahora' if is_safety else
                            '¿Qué servicios ofrecen?')
                    wa_id = (f'5215500{i}{serial:06d}' if i == 2 or is_safety
                             else '5215512345678')
                    key = f'wamid.b9e.{suffix}.{i}.{serial}'
                    try:
                        msg = harnesses[i].inbound(body, wa_id=wa_id, key=key)
                        if msg is None:
                            raise AssertionError('Signed webhook did not persist inbound')
                        events['sent'][i] += 1
                        if is_safety:
                            events['safety'] += 1
                        if scenario == 'duplicate' and i == 2 and serial % 20 == 0:
                            duplicate = harnesses[i].inbound(body, wa_id=wa_id, key=key)
                            if duplicate is None or duplicate.pk != msg.pk:
                                raise AssertionError('Duplicate webhook created another message')
                            events['duplicates'] += 1
                    except Exception as exc:
                        events['errors'].append({'second': second, 'type': type(exc).__name__})
                    next_due[i] += interval
                if second != last_sample:
                    last_sample = second
                    if second % 5 == 0:
                        samples.append({'second': second,
                            'pending_inbound': Message.objects.filter(direction='in', status='pending',
                                organization_id__in=org_ids).count(),
                            'pending_outbound': Message.objects.filter(direction='out', status='pending',
                                organization_id__in=org_ids).count(),
                            'active_work': list(TurnWork.objects.filter(status='PROCESSING',
                                organization_id__in=org_ids).values('organization_id')
                                .annotate(count=__import__('django.db.models', fromlist=['Count']).Count('pk'))),
                        })
                time.sleep(.05)
        start = origin_utc + timedelta(seconds=warmup)
        end = start + timedelta(seconds=measure)
        time.sleep(20)
        receipt = observe(scenario, start, end, org_ids, samples, events, process_info)
        receipt['fixture_organization_ids'] = org_ids
        receipt['profile_version'] = 'profile-beta-1-v1'
        receipt['warmup_seconds'] = warmup
        receipt['measurement_seconds'] = measure
        receipt['smoke_only'] = smoke
        output.write_text(json.dumps(receipt, indent=2, default=str) + '\n', encoding='utf-8')
        print(json.dumps({'receipt': str(output), 'gates': receipt['gates'],
                          'sample_count': receipt['inbound_count']}), flush=True)
    finally:
        stop_path.touch()
        for proc in processes:
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        for handle in child_logs:
            handle.close()
        stop_path.unlink(missing_ok=True)
        stop_path.with_suffix('.blocked').unlink(missing_ok=True)
        stop_path.with_suffix('.measure').unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', required=True,
                        choices=('base', 'blocked_llm', 'meta_slow', 'duplicate', 'saturation'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--role')
    parser.add_argument('--stop', type=Path)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    if args.role:
        worker(args.role, args.scenario, args.stop)
    else:
        if args.output is None:
            parser.error('--output is required for orchestration')
        orchestrate(args.scenario, args.output, smoke=args.smoke)


if __name__ == '__main__':
    main()
