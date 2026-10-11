"""Isolated D29 recorder and finite accreditation; production code is unchanged.

Run from backend using python -m apps.agent.tests.scheduling_characterization.runner.
No DB is opened by --help or offline analysis. No load is the default command.
"""
import argparse
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlsplit

from .evidence import Interval, NS, reconstruct, timestamp

BASELINE = '825db75df68bf076929fa787e77beefe96803350'
MODULE = 'apps.agent.tests.scheduling_characterization.runner'
SUPPORTED_LOAD_CASES = ('R1-01','R1-02','R1-03','R1-04','R1-05','R1-06')


def write_json(path, value):
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')


def source_manifest(directory):
    backend=Path(__file__).resolve().parents[4]
    sources={p.relative_to(backend).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(backend.rglob('*.py')) if '__pycache__' not in p.parts}
    write_json(directory/'source-manifest.json',{'declared_baseline':BASELINE,'backend_source_sha256':sources,
        'provenance_requirement':'Verify against the isolated git archive before load; this inventory does not sign a commit.'})


def bootstrap():
    # Validate the explicit configuration before django.setup() can open a DB.
    config = json.loads(os.environ.get('B3_TEST_DATABASE','{}'))
    if (config.get('ENGINE') != 'django.db.backends.postgresql'
            or not str(config.get('NAME','')).startswith('test_')
            or config.get('HOST') not in ('127.0.0.1','localhost')
            or not str(config.get('PORT','')).isdigit()):
        raise RuntimeError('Explicit local PostgreSQL test_* configuration required')
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',
        DATABASE_URL='postgresql://'+quote(config['USER'],safe='')+':'+quote(config['PASSWORD'],safe='')
        +'@'+config['HOST']+':'+str(config['PORT'])+'/'+config['NAME'],
        DISABLE_SENTRY='True',SENTRY_DSN='',REDIS_URL='',DISCORD_WEBHOOK_URL='',
        HEALTHCHECK_AGENT_WORKER_URL='',HEALTHCHECK_AGENT_SENDER_URL='')
    import django
    django.setup()
    from django.db import connection
    effective=connection.settings_dict
    if connection.vendor != 'postgresql' or any(str(effective[k]) != str(config[k]) for k in ('NAME','HOST','PORT','USER')):
        raise RuntimeError('Effective database differs from isolated configuration')
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('fsync'), current_setting('synchronous_commit')")
        if cursor.fetchone() != ('on','on'):
            raise RuntimeError('Durable PostgreSQL required')
    return config


@contextmanager
def network_denied():
    import requests
    with patch.object(requests.Session,'request',side_effect=AssertionError('External network prohibited')):
        yield


def require_empty_database():
    from apps.channels.models import Message
    from apps.agent.models import TurnWork
    if Message.objects.exists() or TurnWork.objects.exists():
        raise RuntimeError('A fresh test database with no messages/work is required')


class Recorder:
    def __init__(self, directory, run_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',run_id):
            raise ValueError('Technical run_id required')
        self.directory,self.run_id=Path(directory),run_id
        self.offers,self.snapshots,self.resolutions=[],[],[]
        self.serial=0

    @contextmanager
    def capture(self, role):
        from apps.agent.claim_diagnostics import capture
        from apps.agent import durable
        with capture(self.directory/(role+'.jsonl'),run_id=self.run_id,worker=role) as journal:
            durable.db_now()
            try:
                yield journal
            finally:
                durable.db_now()

    def offer(self, channel, *, slot=0, key=None, rollback_fixture=False):
        from django.db import connection
        from apps.agent import services, durable
        from apps.channels.models import Message
        if connection.in_atomic_block and not rollback_fixture:
            raise RuntimeError('Ordinary offers must resolve their outer transaction before durable acknowledgement')
        self.serial+=1
        key=key or f'wamid.d29.{self.run_id}.{self.serial}'
        # Correlation ledger intentionally excludes input text and external IDs.
        existing=Message.objects.filter(channel_account=channel,direction='in',external_message_id=key).first()
        before=durable.db_now()
        outcome='UNCERTAIN'
        mid=None
        try:
            row=services.ingest_inbound_message(channel,wamid=key,
                wa_id=f'52155123{slot:05d}',body='Consulta sintética del catálogo de servicios')
            if row is None:
                if existing is not None:
                    row=existing
                    outcome='DUPLICATE_CONFIRMED'
            elif row.status == Message.STATUS_PENDING:
                outcome='ACCEPTED_DURABLE' if not rollback_fixture else 'ROLLED_BACK_FIXTURE'
            else:
                outcome='REJECTED_CONFIRMED'
            mid=row.pk if row else None
        except Exception as exc:
            error=type(exc).__name__
        else:
            error=None
        after=durable.db_now()
        attempt=dict(attempt=self.serial,organization_id=channel.organization_id,
                     offered_db_ns_bounds=[timestamp(before.isoformat()),timestamp(after.isoformat())],
                     outcome=outcome,message_id=mid,error_class=error)
        self.offers.append(attempt)
        # Append/flush an offer before a later failure can erase the population.
        with (self.directory/'offers.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(attempt,separators=(',',':'))+'\n')
            stream.flush()
        return row if error is None else None

    def snapshot(self, stage):
        from django.db import connection,transaction
        from apps.agent import durable
        from apps.agent.models import Conversation,TurnWork
        from apps.channels.models import Message
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            clock=durable.db_now()
            rows=list(Message.objects.filter(direction='in').order_by('id').values(
                'id','organization_id','conversation_id','direction','status','semantic_type',
                'available_at','turn_work_id'))
            works=list(TurnWork.objects.order_by('id').values('id','organization_id','conversation_id',
                'status','attempts','ownership_epoch','claimed_at','lease_expires_at','next_attempt_at'))
            convs=list(Conversation.objects.order_by('id').values('id','organization_id','ownership_epoch','state'))
        item={'stage':stage,'db_ns':timestamp(clock.isoformat()),'messages':rows,'works':works,'conversations':convs,
              'offers_so_far':len(self.offers)}
        # Persist every cut, not just the successful final receipt.
        with (self.directory/'snapshots.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(item,default=str,separators=(',',':'))+'\n')
            stream.flush()
        self.snapshots.append(item)
        return item

    def resolve_lost_ack(self,journal,tx,bound):
        import psycopg
        from django.db import connection
        cfg=connection.settings_dict
        # This independent connection only reads synthetic fixture data.
        with psycopg.connect(dbname=cfg['NAME'],user=cfg['USER'],password=cfg['PASSWORD'],
                host=cfg['HOST'],port=cfg['PORT'],autocommit=True) as peer:
            with peer.transaction():
                peer.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                row=peer.execute('SELECT clock_timestamp(), organization_id, conversation_id, '
                    'ownership_epoch, lease_token FROM agent_turnwork WHERE id=%s',[bound['turn_work_id']]).fetchone()
                members=[r[0] for r in peer.execute('SELECT id FROM channels_message WHERE turn_work_id=%s '
                    'AND direction=%s ORDER BY id',[bound['turn_work_id'],'in']).fetchall()]
        verified=bool(row and row[1:4] == (bound['organization_id'],bound['conversation_id'],bound['epoch'])
                      and hashlib.sha256(row[4].bytes).hexdigest()==bound['lease_fingerprint']
                      and set(members)==set(bound['member_ids']))
        receipt={'session_id':journal.session_id,'transaction_id':tx,'result':'COMMITTED' if verified else 'UNRESOLVED',
                 'witness_verified':verified,'visible_by_db_ns':timestamp(row[0].isoformat()) if verified else None,
                 'source':'INDEPENDENT_REPEATABLE_READ_DURABLE_WITNESS'}
        self.resolutions.append(receipt)
        write_json(self.directory/'durable-resolutions.json',self.resolutions)
        return receipt

    def analyze(self, *, snapshot=None, queue_cuts=(), level_evidence=None):
        from apps.agent.claim_diagnostic_report import read_journal
        journals,errors=[],[]
        for path in sorted(self.directory.glob('*.jsonl')):
            if path.name in ('offers.jsonl','snapshots.jsonl'):
                continue
            try:
                journals.append(read_journal(path))
            except (ValueError,KeyError,json.JSONDecodeError):
                errors.append('INCOMPLETE_CAPTURE:'+path.name)
        snap=snapshot or self.snapshots[-1]
        return reconstruct(journals,self.offers[:snap['offers_so_far']],snap['messages'],
            Interval(snap['db_ns'],snap['db_ns']),run_id=self.run_id,resolutions=self.resolutions,
            queue_cuts=queue_cuts,capture_errors=errors,level_evidence=level_evidence)


def wait_ready(row, limit=35):
    from apps.agent import durable
    row.refresh_from_db()
    end=time.monotonic()+limit
    while row.available_at and durable.db_now() < row.available_at:
        if time.monotonic() >= end:
            raise RuntimeError('Natural READY not reached; deadlines remain unchanged')
        time.sleep(.05)


class FixtureRollback(Exception):
    pass


def accredit(directory, run_id):
    bootstrap()
    require_empty_database()
    directory.mkdir(parents=True,exist_ok=False)
    source_manifest(directory)
    recorder=Recorder(directory,run_id)
    from django.db import connection,transaction,DatabaseError
    from apps.agent import durable
    from apps.agent.tests.test_b9a_e2e import seed_domain
    from apps.agent.claim_diagnostics import Journal
    org_a,channel_a,*_=seed_domain('D29-A-'+run_id)
    org_b,channel_b,*_=seed_domain('D29-B-'+run_id)
    checks={}
    ack_active=False
    raw_commit=connection._commit
    def lost_ack():
        result=raw_commit()
        if ack_active:
            raise DatabaseError('Synthetic lost COMMIT acknowledgement')
        return result
    # Inject beneath the recorder so its bracket includes the failed ACK.
    with network_denied(),patch.object(connection,'_commit',lost_ack),recorder.capture('accredit') as journal:
        a=recorder.offer(channel_a)
        b=recorder.offer(channel_b)
        if not a or not b:
            raise RuntimeError('Synthetic ingress not accepted')
        wait_ready(a); wait_ready(b)
        pending_cut=recorder.snapshot('two_ready_without_claim')
        correction=recorder.offer(channel_a)
        correction_cut=recorder.snapshot('preclaim_correction')
        recorder.offer(channel_b,key=f'wamid.d29.{run_id}.2')
        # A successful savepoint release is not an outer COMMIT. Its later
        # enclosing rollback must leave the episode pending with the same age.
        try:
            with transaction.atomic():
                with transaction.atomic():
                    durable.claim_turn(a.conversation_id)
                raise FixtureRollback()
        except FixtureRollback:
            pass
        # Independent savepoint rollback followed by a successful outer COMMIT.
        with transaction.atomic():
            try:
                with transaction.atomic():
                    durable.claim_turn(a.conversation_id)
                    raise FixtureRollback()
            except FixtureRollback:
                pass
        try:
            with transaction.atomic():
                recorder.offer(channel_a,slot=9,rollback_fixture=True)
                raise FixtureRollback()
        except FixtureRollback:
            pass
        witness=durable.claim_turn(a.conversation_id)
        if witness is None:
            raise RuntimeError('Accreditation claim miss')
        later=recorder.offer(channel_a)
        wait_ready(later)
        w2_cut=recorder.snapshot('w2_ready_while_w1_processing')
        durable.finalize_turn(witness)
        second=durable.claim_turn(a.conversation_id)
        if second is None:
            raise RuntimeError('Accreditation W2 claim miss')
        ack_bound=[]
        original_emit=Journal.emit
        def observe_emit(instance,event,**data):
            if instance is journal and event=='claim_bound' and data['conversation_id']==b.conversation_id:
                ack_bound.append((instance.transaction_id,dict(data)))
            return original_emit(instance,event,**data)
        ack_active=True
        with patch.object(Journal,'emit',observe_emit):
            try:
                durable.claim_turn(b.conversation_id)
            except DatabaseError:
                pass
            finally:
                ack_active=False
        if len(ack_bound)!=1:
            raise RuntimeError('Lost ACK fixture did not reach the intended boundary')
        tx,bound=ack_bound[0]
        resolution=recorder.resolve_lost_ack(journal,tx,bound)
        final=recorder.snapshot('final')
    pending_report=recorder.analyze(snapshot=pending_cut)
    correction_report=recorder.analyze(snapshot=correction_cut)
    w2_report=recorder.analyze(snapshot=w2_cut)
    final_report=recorder.analyze(snapshot=final)
    checks['both_unclaimed_ready_episodes_retained']=pending_report['summary']['PENDING_CENSORED']==2
    checks['correction_coalesces_without_reset']=len(correction_report['episodes'])==2 and any(
        e['member_ids']==[a.pk,correction.pk] and e['ready_ns_bounds']==pending_report['episodes'][0]['ready_ns_bounds']
        for e in correction_report['episodes'])
    checks['w2_ready_with_w1_still_processing']=w2_report['summary']['PENDING_CENSORED']==2 and any(
        w['id']==witness.turn_work_id and w['status']=='PROCESSING' for w in w2_cut['works'])
    checks['outer_and_savepoint_rollback_do_not_close_episode']=len(final_report['episodes'])==3 and len(final_report['recovery'])==0
    checks['rolled_back_ingress_not_accepted_population']=final_report['population']['accepted_durable_inputs']==4
    checks['duplicate_not_new_episode']=final_report['population']['technical_duplicates']==1
    checks['lost_ack_resolved_from_independent_visibility']=resolution['witness_verified'] and not final_report['uncertain_transactions']
    from apps.agent.claim_diagnostic_report import read_journal
    recorded=read_journal(directory/'accredit.jsonl')
    checks['failed_ack_recorded_inside_commit_bracket']=any(r['event']=='commit_end' and r['transaction_id']==tx and r['error_class']=='DatabaseError' for r in recorded)
    checks['all_four_inputs_reconciled_to_three_episodes']=final_report['population']['represented_inputs']==4 and len(final_report['episodes'])==3
    checks['no_claimed_at_as_commit_frontier']=all(e['claim_commit_ns_bounds'] and e['claim_commit_ns_bounds'][0]<=e['claim_commit_ns_bounds'][1] for e in final_report['episodes'])
    checks['complete_final_cohort_without_data_issues']=not final_report['issues'] and final_report['summary']['OBSERVED_WITHIN_TARGET']==3
    checks['cohort_never_certifies_level_or_E']=final_report['dispositions']==['COHORT_ONLY_NOT_LEVEL_ACCEPTANCE'] and not final_report['contract_accepted']
    for name,report in [('pending',pending_report),('correction',correction_report),('w2',w2_report),('final',final_report)]:
        write_json(directory/(name+'-cohort.json'),report)
    result={'schema':'saaslyvet-d29-accreditation-v1','run_id':run_id,'status':'PASS' if all(checks.values()) else 'FAIL',
            'checks':checks,'new_claims':3,'accepted_inputs':4,'organizations':2,
            'purpose':'FINITE_MEASUREMENT_INSTRUMENT_ACCREDITATION','benchmark':False,'sustainable_envelope':None,
            'limits':['Direct claims and explicit finalization are frontier fixtures, not capacity measurements.',
                      'Clock intervals are conditional on same-host calibration and no unobserved clock step.',
                      'Fault scenario coverage and load matrix have not been executed.']}
    write_json(directory/'accreditation.json',result)
    if result['status']!='PASS':
        raise RuntimeError('Accreditation failed; inspect accreditation.json')
    return result


def worker(directory, run_id, role):
    bootstrap()
    from apps.agent.tests.e4_profile import _worker
    # Existing controlled service fixtures and command semantics are reused;
    # its historical observer, gates and orchestrator are never called.
    with Recorder(directory,run_id).capture(role):
        _worker('sender' if role=='sender' else 'planner','base',directory/'stop')


def participant_env(first_org_id):
    return dict(os.environ,B9E_NOISY_ORG_ID=str(first_org_id),PYTHONDONTWRITEBYTECODE='1',
                PYTHONIOENCODING='utf-8',E4_BATCH='1',E4_POLL_SECONDS='1',E4_LLM_SECONDS='.5')


@contextmanager
def participants(directory,run_id,first_org_id):
    processes,streams=[],[]
    try:
        for role in ('planner_1','planner_2','sender'):
            stream=(directory/(role+'.log')).open('x',encoding='utf-8')
            streams.append(stream)
            processes.append(subprocess.Popen(['rtk','proxy',sys.executable,'-X','utf8','-m',MODULE,
                'worker','--output',str(directory),'--run-id',run_id,'--role',role],
                env=participant_env(first_org_id),stdout=stream,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        deadline=time.monotonic()+45
        while not all('B9E_READY ' in (directory/(role+'.log')).read_text(encoding='utf-8') for role in ('planner_1','planner_2','sender')):
            if time.monotonic()>=deadline or any(p.poll() is not None for p in processes):
                raise RuntimeError('Participants failed preparation')
            time.sleep(.05)
        yield processes
    finally:
        (directory/'stop').touch(exist_ok=True)
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.terminate(); process.wait(timeout=10)
        for stream in streams:
            stream.close()


def smoke(directory,run_id):
    """Two finite READ episodes through real planners/sender, never a rate trial."""
    bootstrap(); require_empty_database()
    directory.mkdir(parents=True,exist_ok=False)
    source_manifest(directory)
    from apps.agent.tests.test_b9a_e2e import seed_domain
    from apps.agent.models import TurnWork
    from apps.channels.models import Message
    fixtures=[seed_domain('D29-SMOKE-'+run_id+'-'+str(i)) for i in range(2)]
    recorder=Recorder(directory,run_id)
    with network_denied(),recorder.capture('ingress'),participants(directory,run_id,fixtures[0][0].pk) as processes:
        for fixture in fixtures:
            if recorder.offer(fixture[1]) is None:
                raise RuntimeError('Smoke ingress failed')
        deadline=time.monotonic()+45
        while True:
            completed=TurnWork.objects.filter(status=TurnWork.COMPLETED).count()
            accepted=Message.objects.filter(direction='out',provider_accepted_at__isnull=False).count()
            if completed==2 and accepted==2:
                break
            if time.monotonic()>=deadline or any(p.poll() is not None for p in processes):
                raise RuntimeError('Finite planner/sender smoke did not finish')
            time.sleep(.05)
        final=recorder.snapshot('final')
    receipt=recorder.analyze(snapshot=final)
    checks={'three_processes_exited_normally':all(p.returncode==0 for p in processes),
            'two_durable_ordinary_inputs':receipt['population']['accepted_durable_inputs']==2,
            'two_new_claims_two_organizations':len(receipt['episodes'])==2 and len(receipt['organization_counts'])==2,
            'complete_captures_no_cohort_issues':not receipt['issues'],
            'both_frontiers_decidable':receipt['summary']['OBSERVED_WITHIN_TARGET']==2,
            'two_completed_works_two_provider_acceptances':completed==2 and accepted==2,
            'not_level_or_contract_acceptance':receipt['dispositions']==['COHORT_ONLY_NOT_LEVEL_ACCEPTANCE']}
    write_json(directory/'cohort.json',receipt)
    result={'schema':'saaslyvet-d29-pipeline-smoke-v1','run_id':run_id,'status':'PASS' if all(checks.values()) else 'FAIL',
            'checks':checks,'benchmark':False,'offered_inputs':2,'topology':{'planners':2,'sender':1,'batch':1,'pause_seconds':1},
            'sustainable_envelope':None,'external_requests':0,'provider':'EXISTING_SYNTHETIC_PUBLIC_READ_FIXTURE'}
    write_json(directory/'smoke.json',result)
    if result['status']!='PASS':
        raise RuntimeError('Pipeline smoke failed; inspect smoke.json')
    return result


def validate_level_plan(plan):
    if plan['case_id'] not in SUPPORTED_LOAD_CASES:
        raise ValueError('This entrypoint supports R1 load observation only; fault recipes require separate accreditation')
    if plan['baseline']!=BASELINE or plan['protocol_version']!='D29-v1':
        raise ValueError('Unexpected baseline/protocol')
    for key in ('plan_conformance','invariants_accredited','population_complete','queue_windows_complete'):
        if key in plan:
            raise ValueError('Acceptance evidence cannot be supplied as a plan assertion')
    if not isinstance(plan['conversations_per_org'],int) or not 1<=plan['conversations_per_org']<=100:
        raise ValueError('Explicit positive bounded fixture size required')
    rates=plan['offered_rates_per_minute']
    if len(rates) not in (1,2) or any(isinstance(r,bool) or not isinstance(r,(int,float)) or not math.isfinite(r) or r<=0 for r in rates):
        raise ValueError('One/two explicit positive finite rates required')
    duration=plan['offer_seconds']
    if duration not in (360,900):
        raise ValueError('Use the approved screen or confirmation duration; revisions require new protocol')
    if plan['case_id']=='R1-01' and len(rates)!=1:
        raise ValueError('R1-01 needs one org')
    if plan['case_id']=='R1-02' and (len(rates)!=2 or rates[0]!=rates[1]):
        raise ValueError('R1-02 needs equal offered rates')
    if plan['case_id']=='R1-03' and (len(rates)!=2 or rates[0]!=2*rates[1]):
        raise ValueError('R1-03 needs the declared 2:1 ratio')
    if plan['case_id']=='R1-04' and len(rates)!=2:
        raise ValueError('R1-04 needs two orgs; actual forecasts must be witnessed in the journal')
    if plan['case_id']=='R1-05' and plan.get('burst_org_indexes') not in ([0],[0,1]):
        raise ValueError('R1-05 declares simultaneous or concentrated burst participants')
    return plan


def level(directory,run_id,plan):
    validate_level_plan(plan)
    bootstrap()
    require_empty_database()
    directory.mkdir(parents=True,exist_ok=False)
    source_manifest(directory)
    write_json(directory/'sealed-plan.json',plan)
    from apps.agent.tests.test_b9a_e2e import seed_domain
    from apps.agent import durable
    recorder=Recorder(directory,run_id)
    fixtures=[seed_domain('D29-'+run_id+'-'+str(i)) for i in range(len(plan['offered_rates_per_minute']))]
    processes=[]
    cuts=[]
    offers_sent=[0]*len(fixtures)
    with network_denied(),recorder.capture('ingress'):
            if plan['case_id']=='R1-06':
                for i,rate in enumerate(plan['offered_rates_per_minute']):
                    needed=math.ceil(rate*2)
                    if needed>plan['conversations_per_org']:
                        raise ValueError('Initial backlog needs distinct conversations; declare sufficient fixture size')
                    for slot in range(needed):
                        if recorder.offer(fixtures[i][1],slot=slot) is None:
                            raise RuntimeError('Backlog ingress failed')
            with participants(directory,run_id,fixtures[0][0].pk) as processes:
                _offer_level(recorder,fixtures,processes,plan,cuts,offers_sent)
    receipt=recorder.analyze(queue_cuts=cuts)
    # This driver does not manufacture invariant or demand-conformance proofs.
    # A level stays observational until its independent checks are accredited.
    receipt['offered_attempts_per_org']=offers_sent
    receipt['worker_exit_codes']=[p.returncode for p in processes]
    receipt['load_case_id']=plan['case_id']
    write_json(directory/'cohort.json',receipt)
    return receipt


def _offer_level(recorder,fixtures,processes,plan,cuts,offers_sent):
    from apps.agent import durable
    start=time.monotonic()
    start_db=timestamp(durable.db_now().isoformat())
    cuts.append([start_db,start_db])
    recorder.snapshot('offer_start')
    next_offer=[start]*len(fixtures)
    next_cut=start+120
    offer_end=start+plan['offer_seconds']
    while time.monotonic()<offer_end:
        now=time.monotonic()
        if any(p.poll() is not None for p in processes):
            raise RuntimeError('Participant exited during offer')
        for i,rate in enumerate(plan['offered_rates_per_minute']):
            if now>=next_offer[i]:
                if recorder.offer(fixtures[i][1],slot=offers_sent[i]%plan['conversations_per_org']) is None:
                    raise RuntimeError('Offered ingress unresolved')
                offers_sent[i]+=1
                multiplier=2 if plan['case_id']=='R1-05' and i in plan['burst_org_indexes'] and now-start<120 else 1
                next_offer[i]+=60/(rate*multiplier)
        if now>=next_cut:
            snap=recorder.snapshot('window_cut')
            cuts.append([snap['db_ns'],snap['db_ns']])
            next_cut+=120
        time.sleep(.01)
    final_offer=recorder.snapshot('offer_end')
    cuts.append([final_offer['db_ns'],final_offer['db_ns']])
    # Follow each outstanding obligation. Ordinary horizon is finite;
    # the analyzer retains future-ready and uncertain episodes.
    follow_end=time.monotonic()+240
    while time.monotonic()<follow_end:
        snap=recorder.snapshot('followup')
        waiting=[m for m in snap['messages'] if m['status']=='pending' and m['turn_work_id'] is None]
        if not waiting:
            break
        if any(p.poll() is not None for p in processes):
            raise RuntimeError('Participant exited during followup')
        time.sleep(.25)
    recorder.snapshot('final')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('accredit','smoke','level','worker','analyze'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--role',choices=('planner_1','planner_2','sender'))
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--execute-load',action='store_true')
    args=parser.parse_args()
    if args.command in ('accredit','smoke'):
        result=(accredit if args.command=='accredit' else smoke)(args.output,args.run_id)
        print(json.dumps({'status':result['status'],'checks':result['checks']}))
    elif args.command=='worker':
        if args.role is None:
            parser.error('worker requires --role')
        worker(args.output,args.run_id,args.role)
    elif args.command=='level':
        if not args.execute_load or args.plan is None:
            parser.error('level requires a sealed --plan and explicit --execute-load; no default load')
        result=level(args.output,args.run_id,json.loads(args.plan.read_text(encoding='utf-8')))
        print(json.dumps({'dispositions':result['dispositions'],'case_id':result['load_case_id']}))
    else:
        recorder=Recorder(args.output,args.run_id)
        recorder.offers=[json.loads(s) for s in (args.output/'offers.jsonl').read_text(encoding='utf-8').splitlines()]
        recorder.snapshots=[json.loads(s) for s in (args.output/'snapshots.jsonl').read_text(encoding='utf-8').splitlines()]
        if (args.output/'durable-resolutions.json').exists():
            recorder.resolutions=json.loads((args.output/'durable-resolutions.json').read_text(encoding='utf-8'))
        write_json(args.output/'cohort-offline.json',recorder.analyze())


if __name__=='__main__':
    main()
