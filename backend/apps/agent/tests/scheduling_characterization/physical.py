"""Finite physical D29 accreditation. No adaptive search or rate trial.

Fresh database per variant, real commits/locks/process death/DB deadlines.
Crash journals remain incomplete; independent DB evidence resolves only the
specific killed transaction, never repairs an E4 journal or certifies a level.
"""
import argparse
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from .evidence import timestamp
from .execution import Provider, verify_sources
from .recipes import RECIPES, verify_recipe
from .runner import BASELINE, Recorder, bootstrap, network_denied, require_empty_database, source_manifest, wait_ready, write_json

MODULE = 'apps.agent.tests.scheduling_characterization.physical'
ADAPTERS = ('R1-07', 'R2-03', 'R2-04', 'R2-05', 'R2-06', 'R2-07', 'R2-08', 'R2-10')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines()] if Path(path).exists() else []


def db_peer():
    import psycopg
    from django.db import connection
    c = connection.settings_dict
    return psycopg.connect(dbname=c['NAME'], user=c['USER'], password=c['PASSWORD'], host=c['HOST'], port=c['PORT'], autocommit=True)


def independent():
    """One independent repeatable-read snapshot; technical metadata only."""
    from psycopg.rows import dict_row
    with db_peer() as p, p.transaction():
        p.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        with p.cursor(row_factory=dict_row) as c:
            c.execute('SELECT clock_timestamp() AS at, pg_backend_pid() AS pid')
            clock = c.fetchone()
            c.execute('SELECT id, organization_id, conversation_id, direction, status, semantic_type, available_at, '
                      'turn_work_id, process_attempts, provider_accepted_at, send_admitted_at FROM channels_message ORDER BY id')
            messages = c.fetchall()
            c.execute('SELECT id, organization_id, conversation_id, ownership_epoch, status, attempts, lease_token, '
                      'lease_expires_at, next_attempt_at, claimed_at, context_at, anchor_message_id, anchor_created_at, '
                      'cursor_message_id, cursor_created_at, llm_calls_admitted, llm_output_tokens_reserved, '
                      'llm_call_limit, llm_output_token_limit, outcome_code FROM agent_turnwork ORDER BY id')
            works = c.fetchall()
            for w in works:
                token = w.pop('lease_token')
                w['lease_fingerprint'] = hashlib.sha256(token.bytes).hexdigest() if token else None
            c.execute('SELECT id, organization_id, ownership_epoch, state FROM agent_conversation ORDER BY id')
            conversations = c.fetchall()
            c.execute('SELECT id, organization_id, conversation_id, turn_work_id, reserved_output_tokens, '
                      'admitted_at, recorded_at, error FROM agent_llmcall ORDER BY id')
            calls = c.fetchall()
            c.execute('SELECT id,organization_id,conversation_id,contact_id,source_turn_id,source_message_id,goal_id, '
                      'ownership_epoch,consent_state,execution_state,expires_at,created_at,authorized_at, '
                      'authorization_message_id,proposal_message_id,operation_kind,parameters_digest,binding_revision, '
                      'identity_revision FROM agent_conversationoperation ORDER BY id')
            operations=c.fetchall()
            c.execute('SELECT count(*) AS n FROM appointments_appointment')
            effects = c.fetchone()['n']
            c.execute('SELECT count(*) AS n FROM patients_pet')
            pets=c.fetchone()['n']
            c.execute('SELECT count(*) AS n FROM patients_petregistrationeffect')
            registrations=c.fetchone()['n']
            c.execute("SELECT count(*) AS n FROM agent_toolexecution WHERE policy_decision='confirmed'")
            executions=c.fetchone()['n']
    value = dict(db_ns=timestamp(clock['at'].isoformat()), backend_pid=clock['pid'], messages=messages,
                 works=works, conversations=conversations, calls=calls, operations=operations,appointment_count=effects,
                 domain_counts=dict(appointments=effects,pets=pets,pet_registration_effects=registrations,confirmed_tool_executions=executions))
    # Normalize timestamps for stable offline receipts, not for clock decisions.
    return json.loads(json.dumps(value, default=str))


class BoundaryUnavailable(RuntimeError):
    pass


class Session:
    def __init__(self, directory, case, variant, run_id):
        self.directory, self.case, self.variant, self.run_id = Path(directory), case, variant, run_id
        self.recorder = Recorder(self.directory, run_id)
        self.events, self.checks, self.children, self.snapshots = [], [], [], []
        self.fixtures = []

    def snap(self, label):
        v = independent()
        name = f'db-{len(self.snapshots):03d}-{label}.json'
        write_json(self.directory / name, v)
        self.snapshots.append(name)
        return v, name

    def check(self, name, condition, evidence, **facts):
        item = dict(name=name, passed=bool(condition), evidence=list(evidence), facts=facts)
        self.checks.append(item)
        write_json(self.directory / f'check-{len(self.checks):03d}.json', item)
        if not condition:
            raise AssertionError(name)

    def event(self, name, evidence, org=0, source='INDEPENDENT_DB_WITNESS', **facts):
        from apps.agent import durable
        if not evidence or any(not (self.directory / p).is_file() for p in evidence):
            raise ValueError('An event needs captured physical evidence')
        at = timestamp(durable.db_now().isoformat())
        self.events.append(dict(event=name, run_id=self.run_id, organization_index=org,
            observed=True, db_ns=at, source=source, evidence=list(evidence), **facts))

    def seed(self, count=2):
        from apps.agent.tests.test_b9a_e2e import seed_domain
        self.fixtures = [seed_domain(self.run_id + '-' + str(i)) for i in range(count)]

    def offer(self, org=0, slot=0, body=None):
        if body is None:
            row = self.recorder.offer(self.fixtures[org][1], slot=slot)
        else:
            from apps.agent.services import ingest_inbound_message
            from apps.agent import durable
            before = durable.db_now()
            key = f'wamid.d29.physical.{self.run_id}.{len(self.recorder.offers)}'
            row = ingest_inbound_message(self.fixtures[org][1], wamid=key,
                wa_id=f'52155123{slot:05d}', body=body)
            after = durable.db_now()
            item = dict(attempt=len(self.recorder.offers)+1, organization_id=self.fixtures[org][0].pk,
                offered_db_ns_bounds=[timestamp(before.isoformat()), timestamp(after.isoformat())],
                message_id=row.pk if row else None, outcome='ACCEPTED_DURABLE' if row else 'UNCERTAIN')
            self.recorder.offers.append(item)
            from .execution import append
            append(self.directory / 'offers.jsonl', item)
        if row is None:
            raise AssertionError('Ingress did not commit')
        return row

    def claim(self, row):
        from apps.agent import durable
        w = durable.claim_turn(row.conversation_id)
        if w is None:
            raise AssertionError('Expected committed claim')
        return w

    def fence(self, witness):
        from apps.agent import durable
        from apps.channels.models import Message
        count = Message.objects.filter(direction='out').count()
        try:
            durable.finalize_turn(witness, outputs=[{'body': 'synthetic stale output'}])
        except (durable.OwnershipLost, TimeoutError):
            denied = True
        else:
            denied = False
        v, p = self.snap('fencing')
        self.check('stale_witness_has_no_effect', denied and Message.objects.filter(direction='out').count() == count, [p])
        self.event('old_witness_fenced', [p], effect_published=False)

    def child(self, action, row, label):
        log = (self.directory / (label + '.log')).open('x', encoding='utf-8')
        p = subprocess.Popen(['rtk', 'proxy', sys.executable, '-X', 'utf8', '-m', MODULE,
            'child', '--output', str(self.directory), '--case', self.case, '--variant', self.variant,
            '--run-id', self.run_id, '--action', action, '--conversation', str(row.conversation_id), '--label', label],
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.children.append((p, log, label))
        return p

    def marker(self, label, timeout=45):
        path = self.directory / (label + '-barrier.json')
        end = time.monotonic() + timeout
        while not path.exists():
            process = next(p for p, _, l in self.children if l == label)
            if process.poll() is not None or time.monotonic() > end:
                raise BoundaryUnavailable('Physical process barrier missing: ' + label)
            time.sleep(.05)
        return read(path)

    def kill(self, label):
        marker = self.marker(label)
        process = next(p for p, _, l in self.children if l == label)
        # Kill actual Python participant, not merely its RTK parent wrapper.
        os.kill(marker['os_pid'], signal.SIGTERM)
        process.wait(timeout=20)
        end = time.monotonic()+30
        with db_peer() as peer:
            while peer.execute('SELECT 1 FROM pg_stat_activity WHERE pid=%s', [marker['backend_pid']]).fetchone():
                if time.monotonic()>end:
                    raise BoundaryUnavailable('Killed backend still alive')
                time.sleep(.05)
        name = label + '-exit.json'
        write_json(self.directory / name, dict(os_pid=marker['os_pid'], backend_pid=marker['backend_pid'],
            exit_code=process.returncode, backend_absent=True, journal_expected_incomplete=True))
        self.check('real_process_exit_'+label, process.returncode != 0, [name])
        return name

    def cleanup(self):
        failures=[]
        for p, log, label in self.children:
            if p.poll() is None:
                marker = self.directory / (label+'-barrier.json')
                if not marker.exists():marker=self.directory/(label+'-started.json')
                if marker.exists():
                    try: os.kill(read(marker)['os_pid'], signal.SIGTERM)
                    except OSError: pass
                else: p.terminate()
                try: p.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait(timeout=10); failures.append(label)
            log.close()
        write_json(self.directory/'participants-cleanup.json', dict(all_reaped=not failures, failures=failures))
        return not failures


def same_history(a, b):
    keys = ('id','organization_id','conversation_id','ownership_epoch','context_at','anchor_message_id',
            'anchor_created_at','cursor_message_id','cursor_created_at','llm_call_limit','llm_output_token_limit')
    return all(a[k] == b[k] for k in keys) and b['llm_calls_admitted'] >= a['llm_calls_admitted'] and b['llm_output_tokens_reserved'] >= a['llm_output_tokens_reserved']


def wait_db(due):
    from apps.agent import durable
    if isinstance(due, str):
        from datetime import datetime
        due = datetime.fromisoformat(due)
    end = time.monotonic()+max(0,(due-durable.db_now()).total_seconds())+40
    while durable.db_now() < due:
        if time.monotonic() > end:
            raise BoundaryUnavailable('Natural DB deadline not reached')
        time.sleep(min(.5, max(.01,(due-durable.db_now()).total_seconds())))


@contextmanager
def contained(s, role='service', **extra):
    import requests
    from django.test import override_settings
    from apps.agent import sender
    from apps.agent.tests.b9a_harness import SETTINGS
    job=dict(case_id=s.case, variant=s.variant, run_id=s.run_id,
        organization_ids=[f[0].pk for f in s.fixtures], slow_multiplier=2, blocked_llm_hold_seconds=120)
    provider=Provider(s.directory,role,job)
    original=sender.admit_dispatch
    def admit(claim):
        row=original(claim); provider.meta_message=row; return row
    with override_settings(**dict(SETTINGS,AGENT_SAFETY_AUTOMATION_ENABLED=True,**extra)), \
            patch.object(requests.Session,'request',lambda session,method,url,**kw:provider.request(session,method,url,**kw)), \
            patch.object(sender,'admit_dispatch',admit):
        yield provider


def child(directory, case, variant, run_id, action, conversation, label):
    bootstrap()
    from django.db import connection
    from apps.agent import durable
    from apps.agent.models import Conversation
    s=Session(directory,case,variant,run_id)
    # Child consumes already committed synthetic fixtures only.
    from apps.agent.tests.test_b9a_e2e import seed_domain
    from apps.organizations.models import Organization
    from apps.channels.models import ChannelAccount
    s.fixtures=[(o,ChannelAccount.objects.filter(organization=o).first()) for o in Organization.objects.order_by('pk')]
    def barrier(w):
        write_json(Path(directory)/(label+'-barrier.json'), dict(os_pid=os.getpid(),backend_pid=connection.connection.info.backend_pid,
            turn_work_id=w.turn_work_id,organization_id=w.organization_id,conversation_id=w.conversation_id,
            epoch=w.ownership_epoch,lease_fingerprint=hashlib.sha256(w.lease_token.bytes).hexdigest(), action=action))
        while True: time.sleep(.2)
    with network_denied(), s.recorder.capture(label):
        if action == 'precommit':
            original=durable._claim_turn_locked
            def prepared(*a,**kw):
                w=original(*a,**kw)
                if w is None: raise AssertionError('No prepared membership')
                barrier(w)
            with patch.object(durable,'_claim_turn_locked',prepared): durable.claim_turn(conversation)
        elif action == 'postcommit':
            w=durable.claim_turn(conversation)
            if w is None: raise AssertionError('No durable claim')
            from apps.agent import llm_budget
            from uuid import uuid4
            llm_budget.admit(w,admission_id=uuid4(),purpose='planner',max_tokens=600,model_id='d29-contained',prompt_version='physical-v1')
            barrier(w)
        elif action == 'claim':
            connection.ensure_connection()
            write_json(Path(directory)/(label+'-started.json'),dict(os_pid=os.getpid(),backend_pid=connection.connection.info.backend_pid))
            w=durable.claim_turn(conversation)
            if w is None: raise AssertionError('No claim after lock release')
            write_json(Path(directory)/(label+'-result.json'),dict(turn_work_id=w.turn_work_id))
        elif action == 'ingest':
            from apps.agent.services import ingest_inbound_message
            conv=Conversation.objects.select_related('contact','channel_account').get(pk=conversation)
            before=durable.db_now()
            write_json(Path(directory)/(label+'-started.json'),dict(os_pid=os.getpid(),backend_pid=connection.connection.info.backend_pid,db_ns=timestamp(before.isoformat())))
            end=time.monotonic()+60
            while variant=='deadline_at' and not (Path(directory)/(label+'-go')).exists():
                if time.monotonic()>end:raise BoundaryUnavailable('Reception fixture gate not released')
                time.sleep(.05)
            row=ingest_inbound_message(conv.channel_account,wamid='wamid.d29.'+run_id+'.cross',wa_id=conv.contact.external_id,body='Corrección sintética')
            after=durable.db_now()
            write_json(Path(directory)/(label+'-result.json'),dict(message_id=row.pk,db_ns_bounds=[timestamp(before.isoformat()),timestamp(after.isoformat())]))
        else:
            raise ValueError('Unknown child action')


def verify_receipt(directory):
    """Offline integrity/coverage verifier; never accepts declared model PASS."""
    directory=Path(directory)
    r=read(directory/'receipt.json')
    errors=[]
    for path, sha in r['artifacts'].items():
        p=directory/path
        if Path(path).is_absolute() or '..' in Path(path).parts or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            errors.append('ARTIFACT_MISMATCH:'+path)
    if r.get('source_kind')!='PHYSICAL_POSTGRESQL' or r.get('baseline')!=BASELINE:
        errors.append('WRONG_PROVENANCE')
    check_files=[p for p in r['artifacts'] if p.startswith('check-')]
    if not check_files or not all(read(directory/p).get('passed') is True for p in check_files):
        errors.append('INVARIANT_FAILURE_OR_ABSENT')
    for p in check_files:
        if not read(directory/p).get('evidence') or any(x not in r['artifacts'] for x in read(directory/p)['evidence']):
            errors.append('CHECK_WITHOUT_EVIDENCE:'+p)
    recipe=verify_recipe(dict(case_id=r['case_id'],variant=r['variant'],run_id=r['run_id'],organization_count=r['organization_count']),r['events'])
    errors+=recipe['missing']+recipe['violations']
    for e in r['events']:
        if e.get('source')=='REPLAY' or not e.get('evidence') or any(x not in r['artifacts'] for x in e['evidence']):
            errors.append('EVENT_WITHOUT_PHYSICAL_EVIDENCE:'+e['event'])
    if not read(directory/'participants-cleanup.json')['all_reaped']:
        errors.append('PARTICIPANT_LEAK')
    # Partial captures are deliberately retained and explicitly accounted for.
    from apps.agent.claim_diagnostic_report import read_journal
    for name in r['artifacts']:
        if name.endswith('.jsonl') and name not in ('offers.jsonl','snapshots.jsonl') and '-wire' not in name and '-events' not in name:
            try: read_journal(directory/name)
            except ValueError:
                label=Path(name).stem
                exit_path=directory/(label+'-exit.json')
                if not exit_path.exists() or not read(exit_path)['backend_absent']:
                    errors.append('UNRESOLVED_INCOMPLETE_CAPTURE:'+name)
    if r.get('error') is not None: errors.append('EXECUTION_ERROR')
    return dict(status='PHYSICALLY_ACCREDITED' if not errors else 'NOT_ACCREDITED',errors=sorted(set(errors)),recipe=recipe,
                level_acceptance=False,sustainable_envelope=None)


def execute(directory, case, variant, run_id):
    bootstrap(); require_empty_database(); verify_sources()
    if case not in ADAPTERS or variant not in RECIPES[case].variants:
        raise ValueError('Only declared physical adapters/variants allowed')
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=False)
    source_manifest(directory)
    s=Session(directory,case,variant,run_id)
    error=None
    from django.test import override_settings
    from .physical_cases import CASES
    try:
        with network_denied(),override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True),s.recorder.capture('driver'):
            s.seed(); CASES[case](s)
            v,p=s.snap('final')
            population=dict(offers=s.recorder.offers,inbound_ids=[m['id'] for m in v['messages'] if m['direction']=='in'],
                pending=[m['id'] for m in v['messages'] if m['direction']=='in' and m['status']=='pending'],
                interrupted=case=='R2-08',legacy_origin='UNKNOWN' if variant=='legacy_null' else None,
                completed_only_denominator=False,recovery_is_new_ordinary_episode=False)
            write_json(directory/'population.json',population)
            accepted=[o['message_id'] for o in s.recorder.offers if o['outcome']=='ACCEPTED_DURABLE']
            s.check('accepted_population_retained',sorted(accepted)==sorted(population['inbound_ids']),[p,'population.json','offers.jsonl'])
            s.check('tenant_membership',all(m['organization_id']==next(w['organization_id'] for w in v['works'] if w['id']==m['turn_work_id'])
                and m['conversation_id']==next(w['conversation_id'] for w in v['works'] if w['id']==m['turn_work_id'])
                for m in v['messages'] if m['turn_work_id']),[p])
            s.check('budget_ledger_matches',all(w['llm_calls_admitted']==len([c for c in v['calls'] if c['turn_work_id']==w['id']])
                and w['llm_output_tokens_reserved']==sum(c['reserved_output_tokens'] for c in v['calls'] if c['turn_work_id']==w['id']) for w in v['works']),[p])
            active={}
            for w in v['works']:
                conv=next(c for c in v['conversations'] if c['id']==w['conversation_id'])
                if w['status']=='PROCESSING' and w['lease_expires_at'] and timestamp(w['lease_expires_at'])>v['db_ns'] and conv['ownership_epoch']==w['ownership_epoch']:
                    active[w['organization_id']]=active.get(w['organization_id'],0)+1
            s.check('n1_committed_org_authority',all(n<=1 for n in active.values()),[p],counts=active)
    except Exception as exc:
        error=dict(kind='PHYSICAL_BOUNDARY_NOT_OBSERVED' if isinstance(exc,BoundaryUnavailable) else 'IMPLEMENTATION_OR_INVARIANT_FAILURE',
                   exception_class=type(exc).__name__,message=str(exc),missing_physical_primitive=None)
    finally:
        s.cleanup()
    artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    receipt=dict(schema='d29-physical-boundary-v1',case_id=case,variant=variant,run_id=run_id,baseline=BASELINE,
        source_kind='PHYSICAL_POSTGRESQL',organization_count=len(s.fixtures),events=s.events,checks=s.checks,error=error,
        artifacts=artifacts,characterization=False,benchmark=False,sustainable_envelope=None,level_acceptance=False)
    write_json(directory/'receipt.json',receipt)
    result=verify_receipt(directory)
    write_json(directory/'verification.json',result)
    print(json.dumps(dict(case_id=case,variant=variant,**result)))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('run','child','verify'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case',choices=ADAPTERS)
    p.add_argument('--variant');p.add_argument('--run-id')
    p.add_argument('--action',choices=('precommit','postcommit','claim','ingest'))
    p.add_argument('--conversation',type=int);p.add_argument('--label')
    a=p.parse_args()
    if a.command=='verify':
        r=verify_receipt(a.output);print(json.dumps(r))
    elif a.command=='child':
        child(a.output,a.case,a.variant,a.run_id,a.action,a.conversation,a.label);return
    else:
        if not all((a.case,a.variant,a.run_id)):p.error('Explicit case, variant and run ID required')
        r=execute(a.output,a.case,a.variant,a.run_id)
    if r['status']!='PHYSICALLY_ACCREDITED':raise SystemExit(1)


if __name__=='__main__':main()
