"""Prepared D29 evaluation overlay. No automatic installation or live execution.

Preserves the contained provider's service durations and durable admission
checks. UNCERTAIN is scoped to one case, variant, organization AND boundary.
The old provider and all its receipts remain immutable.
"""
import hashlib
import json
import os
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit


def timestamp(value):
    delta = datetime.fromisoformat(value).astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def append(path, value):
    with Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, separators=(',', ':')) + '\n')
        stream.flush()


def uncertain_target(job, boundary, organization_id):
    return (job['case_id'] == 'R2-09' and job['variant'] == 'uncertain_meta'
            and boundary == 'meta' and organization_id == job['organization_ids'][0])


class Provider:
    def __init__(self, directory, role, job):
        self.directory, self.role, self.job = Path(directory), role, job
        self.calls = defaultdict(int)
        self.serial = self.wire_serial = 0
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
            if not event['admission_verified']:
                raise AssertionError('Meta without committed send admission')
            delay = .2
        affected = event['organization_id'] == self.job['organization_ids'][0]
        if affected and self.job['case_id'] == 'R2-01' and event['boundary'] == 'llm':
            delay *= self.job['slow_multiplier']
        if affected and self.job['case_id'] == 'R2-09' and event['boundary'] == 'meta' and self.job['variant'] == 'slow_meta':
            delay *= self.job['slow_multiplier']
        self.wire_serial += 1
        call_id = f"{self.job['run_id']}:{self.role}:{os.getpid()}:{self.wire_serial}"
        fault = uncertain_target(self.job, event['boundary'], event['organization_id'])
        event.update(call_id=call_id, run_id=self.job['run_id'], role=self.role, os_pid=os.getpid(),
                     provider_revision='d29-meta-isolation-v1', fault_id=call_id + ':uncertain-meta' if fault else None,
                     injected_fault='UNCERTAIN_META' if fault else None)
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
        end = time.perf_counter_ns()
        result_kind = 'UNCERTAIN' if fault else 'ACCEPTED'
        append(self.directory / (self.role + '-wire.jsonl'), dict(event, event='result', result=result_kind,
               monotonic_ns=end, elapsed_ns=end - start))
        if fault:
            raise requests.Timeout('Synthetic uncertain Meta result')
        if host == 'llm.b9a.invalid':
            return response(tool('get_service_catalog') if self.calls[witness.turn_work_id] == 1 else answer())
        self.serial += 1
        return response({'messages': [{'id': f'wamid.d29.controller.{os.getpid()}.{self.serial}'}]})


@contextmanager
def installed(execution):
    """Call only inside each future isolated worker; spawning does not inherit it."""
    with patch.object(execution, 'Provider', Provider):
        yield


def verify_wire(job, rows, claimed_work_ids):
    """Additional gate, never a replacement for durable/service/queue verifiers."""
    issues, pairs, services = [], {}, set()
    for row in rows:
        call_id = row.get('call_id')
        if not call_id:
            issues.append('MISSING_CALL_ID')
            continue
        pair = pairs.setdefault(call_id, {})
        kind = row.get('event')
        if kind not in ('dispatch', 'result') or kind in pair:
            issues.append('DUPLICATE_OR_UNKNOWN_WIRE_EVENT')
        pair[kind] = row
    for call_id, pair in pairs.items():
        if set(pair) != {'dispatch', 'result'}:
            issues.append('INCOMPLETE_CALL:' + call_id)
            continue
        start, end = pair['dispatch'], pair['result']
        keys = ('run_id', 'role', 'os_pid', 'boundary', 'organization_id', 'message_id', 'turn_work_id',
                'epoch', 'lease_fingerprint', 'call_number', 'fault_id', 'injected_fault', 'provider_revision')
        if any(start.get(k) != end.get(k) for k in keys) or start.get('run_id') != job['run_id']:
            issues.append('CALL_CORRELATION_MISMATCH:' + call_id)
        expected = uncertain_target(job, start.get('boundary'), start.get('organization_id'))
        if end.get('result') != ('UNCERTAIN' if expected else 'ACCEPTED') or bool(start.get('fault_id')) != expected:
            issues.append('FAULT_SCOPE_MISMATCH:' + call_id)
        if (start.get('fault_id') != (call_id + ':uncertain-meta' if expected else None)
                or start.get('injected_fault') != ('UNCERTAIN_META' if expected else None)
                or start.get('provider_revision') != 'd29-meta-isolation-v1'):
            issues.append('FAULT_PROVENANCE_MISMATCH:' + call_id)
        if any(r.get('in_atomic') is not False or r.get('external_destination') is not False for r in (start, end)):
            issues.append('PROVIDER_CONTAINMENT_NOT_PROVED:' + call_id)
        if start.get('boundary') not in ('meta', 'llm') or not start.get('admission_verified') or not end.get('admission_verified'):
            issues.append('ADMISSION_OR_BOUNDARY_MISSING:' + call_id)
        if start.get('boundary') == 'meta' and not start.get('message_id'):
            issues.append('META_MESSAGE_MISSING:' + call_id)
        if start.get('boundary') == 'llm':
            if start.get('active_org_work') != 1 or not start.get('matching_active_work'):
                issues.append('LLM_OWNERSHIP_MISSING:' + call_id)
            if end.get('result') == 'ACCEPTED':
                services.add(start.get('turn_work_id'))
        if end['monotonic_ns'] < start['monotonic_ns'] or end['elapsed_ns'] != end['monotonic_ns'] - start['monotonic_ns']:
            issues.append('INVALID_WIRE_TIME:' + call_id)
    missing = sorted(set(claimed_work_ids) - services)
    if missing:
        issues.append('CLAIMED_WORK_WITHOUT_SERVICE_WITNESS')
    return dict(passed=not issues, issues=issues, missing_service_work_ids=missing, calls=len(pairs),
                accreditation=False, scope='ADDITIONAL_PROVIDER_ISOLATION_GATE')
