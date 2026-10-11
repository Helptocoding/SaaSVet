"""Dedicated causal execution adapter. Never imports/invokes PROFILE runners."""
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import defaultdict
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
import infra

OUT, KEY = infra.OUT, infra.KEY
RUN_ID = 'causal-'+KEY

def setup():
    import django
    django.setup()
    from django.db import connection
    assert connection.vendor=='postgresql' and connection.settings_dict['NAME'].startswith(infra.PREFIX)
    connection.ensure_connection()
    return connection.connection.info.backend_pid

def emit(kind, **data):
    print('CAUSAL_'+kind+' '+json.dumps(data),flush=True)

def worker(role):
    pid=setup()
    import requests
    from django.core.management import call_command
    from django.db import connection
    from django.test import Client, override_settings
    from apps.agent.turn_changes import current_changes
    from apps.agent.claim_diagnostics import capture
    from apps.agent.tests.b9a_harness import SETTINGS, answer, response, tool
    calls, wire = defaultdict(int), defaultdict(int)
    serial=0
    def request(session, method, url, **kwargs):
        nonlocal serial
        target=urlsplit(url)
        if target.hostname=='b9a.internal.test':
            time.sleep(.1)
            headers={'HTTP_'+k.upper().replace('-','_'):v for k,v in kwargs.get('headers',{}).items()}
            path=target.path+('?' + target.query if target.query else '')
            client=Client()
            if kwargs.get('json') is not None:
                reply=client.generic(method.upper(),path,json.dumps(kwargs['json']),content_type='application/json',**headers)
            else:
                reply=getattr(client,method.lower())(path,kwargs.get('params') or {},**headers)
            result=requests.Response(); result.status_code,result._content=reply.status_code,reply.content
            result.headers.update(dict(reply.headers)); wire['domain_http']+=1
            return result
        if target.hostname=='llm.b9a.invalid':
            assert not connection.in_atomic_block
            changes=current_changes(); assert changes is not None
            work=changes.witness.turn_work_id; calls[work]+=1; wire['llm']+=1
            journal.emit('provider_start',provider_kind='llm',call=calls[work])
            time.sleep(.5)
            journal.emit('provider_end',provider_kind='llm',call=calls[work])
            return response(tool('get_service_catalog') if calls[work]==1 else answer())
        if target.hostname=='meta.b9a.invalid':
            assert not connection.in_atomic_block
            wire['meta']+=1; time.sleep(.2); serial+=1
            return response({'messages':[{'id':f'wamid.causal.{KEY}.{os.getpid()}.{serial}'}]})
        raise AssertionError('External destination forbidden in diagnostic load')
    with override_settings(**dict(SETTINGS,AGENT_SAFETY_AUTOMATION_ENABLED=True)), \
            patch.object(requests.Session,'request',request), \
            capture(OUT/(role+'.jsonl'),run_id=RUN_ID,worker=role) as journal:
        emit('READY',role=role,backend_pid=pid,os_pid=os.getpid(),session_id=journal.session_id)
        while not (OUT/'workers.stop').exists():
            call_command('run_agent_worker',once=True,mode='sender' if role=='sender' else 'planner',
                         batch=1,poll=1,stdout=io.StringIO())
            time.sleep(1)
    emit('RESULT',role=role,wire=dict(wire),calls_per_work=dict(calls))

def functional():
    setup()
    from apps.agent import claim_diagnostics as trace
    from apps.agent.tests import test_claim_diagnostic_processes as processes
    original_capture=trace.capture
    prefix='f-'+KEY+'-'
    def capture(path,*,run_id,**kwargs):
        return original_capture(path,run_id=prefix+run_id,**kwargs)
    original_sample=processes.sample
    def sample(connection,targets,*,run_id):
        return original_sample(connection,targets,run_id=prefix+run_id)
    original_popen=subprocess.Popen
    def popen(command,*args,**kwargs):
        command=list(command)
        if 'apps.agent.tests.claim_diagnostic_process' in command:
            command[command.index('process-test')]=prefix+'process-test'
        return original_popen(command,*args,**kwargs)
    # Explicit labels only: no profile or acceptance load suite.
    selected=['apps.agent.tests.test_claim_diagnostic_processes']+[
        'apps.agent.tests.test_claim_diagnostics.ClaimDiagnosticTests.'+name for name in (
        'test_02_on_off_identical_sql_and_durable_state_new_retry_and_reclaim',
        'test_03_outer_rollback_and_savepoint_rollback_are_not_commits',
        'test_12_reconnect_and_on_off_ready_join_do_not_change_deadline_or_membership')]
    infra.write('functional-ids.json',selected)
    os.environ['E4_TRACE_EVIDENCE_DIR']=str(OUT/'functional-artifacts')
    sys.argv=['run_b9a_acceptance','--suite','targeted','--database',infra.EQUIV,
        '--output',str(OUT/'functional-results'),'--ids-file',str(OUT/'functional-ids.json')]
    import runpy
    with patch.object(trace,'capture',capture),patch.object(processes,'sample',sample), \
            patch.object(subprocess,'Popen',popen):
        runpy.run_module('apps.agent.tests.run_b9a_acceptance',run_name='__main__')

def start_child(command, role, environment):
    proc=subprocess.Popen(command,cwd=infra.ROOT/'backend',env=environment,stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
    events=queue.Queue(); proc.events=events
    def consume():
        with (OUT/(role+'.log')).open('x',encoding='utf-8') as stream:
            for line in proc.stdout:
                stream.write(line); stream.flush()
                if line.startswith('CAUSAL_'):
                    kind,data=line.strip().split(' ',1); events.put((kind,json.loads(data)))
    thread=threading.Thread(target=consume,daemon=True); thread.start(); proc.reader=thread
    return proc

def load():
    setup()
    from django.db import connection
    from django.test import override_settings
    from django.utils import timezone
    from apps.agent.models import TurnWork
    from apps.channels.models import Message
    from apps.agent.claim_diagnostics import capture
    from apps.agent.tests.b9a_harness import ApplicationHarness,SETTINGS
    from apps.agent.tests.test_b9a_e2e import seed_domain
    fixtures=[seed_domain('CAUSAL-'+KEY[:8]+'-'+str(i)) for i in range(3)]
    orgs=[row[0].pk for row in fixtures]; harnesses=[ApplicationHarness(row[1]) for row in fixtures]
    roles=('planner-1','planner-2','sender'); children=[]; observer=None
    sent=[0,0,0]; safety=0; errors=[]; inputs=[]
    try:
        for role in roles:
            children.append(start_child([sys.executable,OUT/'run.py',role],role,dict(os.environ)))
        ready=[]
        for proc,role in zip(children,roles):
            kind,data=proc.events.get(timeout=60); assert kind=='CAUSAL_READY' and data['role']==role
            ready.append(data)
        with capture(OUT/'ingress.jsonl',run_id=RUN_ID,worker='ingress'):
            environment=dict(os.environ,PGHOST='127.0.0.1',PGPORT=str(infra.PORT),PGUSER=infra.USER,
                             PGDATABASE=infra.LOAD,PGPASSWORD='')
            observer=start_child([sys.executable,'-m','apps.agent.claim_diagnostic_waits',
                '--run-id',RUN_ID,'--output',OUT/'waits.jsonl','--stop',OUT/'observer.stop',
                '--interval','.02',OUT/'ingress.jsonl',OUT/'planner-1.jsonl',OUT/'planner-2.jsonl'],
                'observer',environment)
            deadline=time.monotonic()+30
            while not (OUT/'waits.jsonl').exists():
                assert observer.poll() is None and time.monotonic()<deadline
                time.sleep(.05)
            origin=time.monotonic(); origin_utc=timezone.now(); next_due=[origin]*3
            infra.write('load-definition.json',dict(classification='DIAGNOSTIC_ONLY',run_id=RUN_ID,
                head=infra.HEAD,organization_ids=orgs,processes=ready,warmup_seconds=30,
                load_seconds=300,drain_seconds=20,healthy_interval_seconds=10,noisy_interval_seconds=1,
                batch=1,poll_seconds=1,llm_seconds=.5,domain_http_seconds=.1,meta_seconds=.2,
                started_at=origin_utc.isoformat(),acceptance_run=False,profile_runner_invoked=False))
            with override_settings(**dict(SETTINGS,AGENT_SAFETY_AUTOMATION_ENABLED=True)):
                while time.monotonic()-origin<330:
                    for i in range(3):
                        if time.monotonic()<next_due[i]: continue
                        serial=sent[i]; is_safety=i<2 and serial%3==0
                        body='Mi perro está convulsionando ahora' if is_safety else '¿Qué servicios ofrecen?'
                        wa_id=f'5215500{i}{serial:06d}' if i==2 or is_safety else '5215512345678'
                        key=f'wamid.causal.{KEY}.{i}.{serial}'
                        scheduled=next_due[i]; began=time.perf_counter_ns()
                        msg=harnesses[i].inbound(body,wa_id=wa_id,key=key)
                        assert msg is not None
                        ended=time.perf_counter_ns()
                        inputs.append(dict(message_id=msg.pk,organization_index=i,organization_id=orgs[i],
                            serial=serial,safety=is_safety,scheduled_offset_seconds=scheduled-origin,
                            ingest_start_ns=began,ingest_end_ns=ended,created_at=msg.created_at.isoformat()))
                        sent[i]+=1; safety+=int(is_safety); next_due[i]+=10 if i<2 else 1
                    time.sleep(.05)
            # Original diagnostic drain, with workers continuing unchanged.
            drain_deadline=time.monotonic()+20
            while time.monotonic()<drain_deadline:
                time.sleep(min(1,drain_deadline-time.monotonic()))
        infra.write('load-inputs.json',dict(run_id=RUN_ID,classification='DIAGNOSTIC_ONLY',
            inputs=inputs,sent=sent,safety=safety,errors=errors))
    finally:
        (OUT/'workers.stop').touch(exist_ok=False)
        exits=[]
        for proc,role in zip(children,roles):
            try: code=proc.wait(timeout=45)
            except subprocess.TimeoutExpired: proc.kill(); code=proc.wait(timeout=10)
            proc.reader.join(timeout=10)
            exits.append(dict(role=role,exit_code=code,reader_stopped=not proc.reader.is_alive()))
        if observer is not None:
            # Let it consume the closed worker journals before its stop signal.
            time.sleep(.1); (OUT/'observer.stop').touch(exist_ok=False)
            try: code=observer.wait(timeout=20)
            except subprocess.TimeoutExpired: observer.kill(); code=observer.wait(timeout=10)
            observer.reader.join(timeout=10)
            exits.append(dict(role='observer',exit_code=code,reader_stopped=not observer.reader.is_alive()))
        infra.write('process-exits.json',exits)
    assert all(e['exit_code']==0 and e['reader_stopped'] for e in exits)
    messages=list(Message.objects.filter(organization_id__in=orgs,direction='in').order_by('pk').values(
        'id','organization_id','conversation_id','semantic_type','created_at','available_at','turn_work_id',
        'process_attempts','status'))
    works=list(TurnWork.objects.filter(organization_id__in=orgs).order_by('pk').values('id',
        'organization_id','conversation_id','ownership_epoch','attempts','status','claimed_at','completed_at',
        'lease_expires_at','next_attempt_at','llm_calls_admitted','llm_output_tokens_reserved'))
    infra.write('durable-state.json',dict(run_id=RUN_ID,classification='DIAGNOSTIC_ONLY',
        messages=messages,works=works))

if __name__=='__main__':
    if sys.argv[1]=='functional': functional()
    elif sys.argv[1]=='load': load()
    else: worker(sys.argv[1])
