"""The seven D29 DB/process/ownership adapters; guards live separately."""
import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from .evidence import timestamp
from .physical import BoundaryUnavailable, contained, db_peer, independent, lines, read, same_history, wait_db
from .runner import wait_ready, write_json


def work(snapshot, pk):
    return next(w for w in snapshot['works'] if w['id']==pk)


def members(snapshot, pk):
    return sorted(m['id'] for m in snapshot['messages'] if m['direction']=='in' and m['turn_work_id']==pk)


def r1_07(s):
    from apps.agent import durable
    from apps.channels.models import Message
    if s.variant=='deadline_at':
        # Prepare the participant before the runtime creates its 8s deadline.
        # The gate controls fixture reception only; it never changes DB time.
        from apps.agent.services import get_or_create_open_conversation
        from types import SimpleNamespace
        from .physical_guards import inbound
        conv=get_or_create_open_conversation(s.fixtures[0][4],s.fixtures[0][1])
        process=s.child('ingest',SimpleNamespace(conversation_id=conv.pk),'crossing')
        wait_started(s,'crossing',process)
        row=inbound(s,'Consulta sintética del catálogo de servicios')
    else:row=s.offer()
    row.refresh_from_db(); original=row.available_at
    if s.variant=='w1_w2':
        wait_ready(row); _,p=s.snap('first-ready');s.event('first_ready',[p])
        correction=s.offer(); correction.refresh_from_db()
        _,p=s.snap('preclaim-correction')
        s.check('ready_origin_not_reset',correction.available_at==original,[p]);s.event('preclaim_correction',[p])
        w1=s.claim(row);a,p=s.snap('w1-commit')
        s.check('w1_committed_membership',members(a,w1.turn_work_id)==sorted([row.pk,correction.pk]),[p]);s.event('w1_commit',[p])
        later=s.offer(); _,p=s.snap('postclaim-input');s.event('postclaim_input',[p])
        wait_ready(later);a,p=s.snap('w2-ready')
        s.check('w2_ready_while_w1_processing',work(a,w1.turn_work_id)['status']=='PROCESSING' and later.pk not in members(a,w1.turn_work_id),[p]);s.event('w2_ready',[p])
        from apps.agent.services import ingest_inbound_message
        count=Message.objects.count()
        dup=ingest_inbound_message(later.channel_account,wamid=later.external_message_id,wa_id=later.contact.external_id,body='Duplicate technical fixture')
        _,p=s.snap('duplicate');s.check('duplicate_no_new_obligation',dup is None and Message.objects.count()==count,[p]);s.event('duplicate',[p])
        durable.finalize_turn(w1);w2=s.claim(later);a,p=s.snap('w2-commit')
        s.check('w2_separate_work',w2.turn_work_id!=w1.turn_work_id and members(a,w2.turn_work_id)==[later.pk],[p]);s.event('w2_commit',[p])
        durable.finalize_turn(w2)
        return
    if s.variant=='legacy_null':
        # Explicit historical fixture, never a shortcut for ordinary READY.
        Message.objects.filter(pk=row.pk).update(available_at=None)
        a,p=s.snap('legacy-null');s.check('legacy_fixture_is_separate',a['messages'][0]['available_at'] is None,[p]);s.event('legacy_null_captured',[p])
        s.event('legacy_origin_known_or_unknown_retained',[p],origin='UNKNOWN_LEGACY_NO_CONTINUITY_CERTIFICATE')
    elif s.variant=='deadline_before':
        before=durable.db_now();correction=s.offer(); after=durable.db_now()
        _,p=s.snap('accepted-before')
        s.check('accepted_before_actual_deadline',before<original and after<original,[p,'offers.jsonl']);s.event('accepted_before_deadline',[p,'offers.jsonl'])
        wait_ready(row);_,p=s.snap('natural-ready');s.event('first_ready',[p])
    elif s.variant=='deadline_at':
        # Reception starts before D, waits on the real Conversation lock, then
        # reads fresh DB time after D. This is an interval crossing, not equality.
        with db_peer() as peer:
            peer.execute('BEGIN')
            peer.execute('SELECT id FROM agent_conversation WHERE id=%s FOR UPDATE',[row.conversation_id])
            start=s.directory/'crossing-started.json'
            s.check('crossing_starts_before_deadline',read(start)['db_ns']<timestamp(original.isoformat()),[start.name])
            (s.directory/'crossing-go').touch()
            wait_db(original);peer.execute('COMMIT')
            process.wait(timeout=30)
        result=read(s.directory/'crossing-result.json');_,p=s.snap('crossing-accepted')
        from .execution import append
        offer=dict(attempt=len(s.recorder.offers)+1,organization_id=row.organization_id,message_id=result['message_id'],
            offered_db_ns_bounds=result['db_ns_bounds'],outcome='ACCEPTED_DURABLE')
        s.recorder.offers.append(offer);append(s.directory/'offers.jsonl',offer)
        deadline=timestamp(original.isoformat())
        s.check('reception_interval_crosses_real_deadline',result['db_ns_bounds'][0]<deadline<result['db_ns_bounds'][1],['crossing-result.json',p])
        s.event('acceptance_interval_crosses_deadline',['crossing-result.json',p])
        correction=Message.objects.get(pk=result['message_id']);row.refresh_from_db()
        s.check('ready_interval_not_replaced_with_poll',row.available_at==original and correction.available_at==original,[p])
        s.event('ready_interval_retained',[p],reception_ns_bounds=result['db_ns_bounds'])
    elif s.variant=='deadline_after':
        wait_ready(row);_,p=s.snap('ready');s.event('first_ready',[p])
        correction=s.offer();correction.refresh_from_db();_,p=s.snap('accepted-after')
        s.check('acceptance_after_deadline',s.recorder.offers[-1]['offered_db_ns_bounds'][0]>=timestamp(original.isoformat()),[p,'offers.jsonl']);s.event('accepted_after_deadline',[p,'offers.jsonl'])
        s.check('origin_latched',correction.available_at==original,[p]);s.event('origin_not_reset',[p])
    elif s.variant=='no_poll':
        wait_ready(row);_,p=s.snap('deadline-without-poll');s.event('deadline_elapsed_without_poll',[p])
        from apps.agent import worker
        selected=worker._pending_conversation_candidates(None,set())
        write_json(s.directory/'first-poll.json',dict(selected=list(selected),db_ns=timestamp(durable.db_now().isoformat())))
        s.check('first_poll_after_deadline',row.conversation_id in selected and not any(e['event']=='poll_start' for e in lines(s.directory/'driver.jsonl')),['first-poll.json'])
        s.event('first_poll_after_deadline',['first-poll.json']);row.refresh_from_db()
        s.check('deadline_not_poll_time',row.available_at==original,['first-poll.json']);s.event('original_ready_retained',['first-poll.json'])
    w=s.claim(row);a,p=s.snap('claim')
    s.check('outer_commit_and_binding_visible',row.pk in members(a,w.turn_work_id),[p]);s.event('w1_commit',[p])
    durable.finalize_turn(w)


def r2_03(s):
    row=s.offer();wait_ready(row)
    s.child('precommit',row,'crash');marker=s.marker('crash')
    journal=lines(s.directory/'crash.jsonl')
    bound=next((e for e in journal if e['event']=='claim_bound' and e['turn_work_id']==marker['turn_work_id']),None)
    s.check('membership_prepared_in_uncommitted_transaction',bound is not None and bound['member_ids']==[row.pk] and bound['transaction_id'] is not None,['crash.jsonl','crash-barrier.json'])
    s.event('prepared_membership',['crash.jsonl','crash-barrier.json'],source='JOURNAL')
    exitfile=s.kill('crash');s.event('precommit_crash',[exitfile],source='PROCESS_EXIT')
    a,p=s.snap('rollback-resolved')
    s.check('crash_rolled_back_work_and_membership',not a['works'] and next(m for m in a['messages'] if m['id']==row.pk)['turn_work_id'] is None,[p,exitfile])
    s.event('rollback_resolved',[p,exitfile])
    w=s.claim(row);a,p=s.snap('next-new-claim')
    s.check('new_claim_after_physical_rollback',members(a,w.turn_work_id)==[row.pk] and work(a,w.turn_work_id)['attempts']==1,[p]);s.event('next_new_claim',[p])
    from apps.agent import durable
    durable.finalize_turn(w)


def crash_committed(s):
    from apps.agent import durable
    from apps.agent.models import TurnWork
    row=s.offer();wait_ready(row)
    s.child('postcommit',row,'crash');marker=s.marker('crash')
    a,p=s.snap('committed-before-crash');old=work(a,marker['turn_work_id'])
    obj=TurnWork.objects.get(pk=old['id'])
    witness=durable.OwnershipWitness(obj.organization_id,obj.conversation_id,obj.pk,obj.lease_token,obj.ownership_epoch)
    s.check('claim_commit_independently_visible',members(a,obj.pk)==[row.pk] and old['lease_fingerprint']==marker['lease_fingerprint'] and old['llm_calls_admitted']==1,[p,'crash-barrier.json'])
    return row,witness,old,a,p


def r2_04(s):
    from apps.agent import durable
    row,witness,old,a,p=crash_committed(s);s.event('outer_commit',[p,'crash.jsonl'])
    exitfile=s.kill('crash');s.event('postcommit_crash',[exitfile],source='PROCESS_EXIT')
    miss=durable.claim_turn(row.conversation_id);_,p=s.snap('before-expiry')
    s.check('no_early_reclaim',miss is None,[p,'driver.jsonl'])
    wait_db(old['lease_expires_at']);a,p=s.snap('natural-expiry')
    due=timestamp(old['lease_expires_at']);s.check('original_lease_due_reached',a['db_ns']>=due,[p])
    s.event('natural_expiry',[p],runtime_clock_or_deadline_changed=False,due_db_ns=due)
    new=s.claim(row);a,p=s.snap('reclaimed');current=work(a,new.turn_work_id)
    s.check('reclaim_same_history_budget_membership',same_history(old,current) and members(a,new.turn_work_id)==[row.pk] and new.turn_work_id==witness.turn_work_id and current['attempts']==old['attempts']+1 and current['lease_fingerprint']!=old['lease_fingerprint'] and current['llm_calls_admitted']==old['llm_calls_admitted'],[p])
    s.event('same_work_reclaimed',[p],same_work_and_membership=True,budget_reset=False)
    s.fence(witness);durable.finalize_turn(new)


def r2_05(s):
    from apps.agent import durable, llm_budget, worker
    from apps.agent.llm import OpenAICompatibleClient, LLMError
    from apps.agent.turn_changes import TurnChanges
    from apps.agent.models import Conversation
    import requests
    from .execution import append
    row=s.offer();wait_ready(row);w=s.claim(row);a,p=s.snap('initial-work');old=work(a,w.turn_work_id)
    loops=3 if s.variant=='exhaustion' else 1
    for i in range(loops):
        conv=Conversation.objects.get(pk=row.conversation_id)
        def failure(session,method,url,**kw):
            from django.db import connection
            from urllib.parse import urlsplit
            if urlsplit(url).hostname!='llm.b9a.invalid' or connection.in_atomic_block:
                raise AssertionError('Provider error outside contained LLM frontier')
            a,p=s.snap('provider-admission-'+str(i))
            s.check('provider_error_follows_durable_admission_'+str(i),work(a,w.turn_work_id)['llm_calls_admitted']==i+1 and durable.active_org_work(w.organization_id).count()==1,[p])
            append(s.directory/'error-wire.jsonl',dict(boundary='llm',result='ERROR',in_atomic=False,external_destination=False,db_ns=a['db_ns'],turn_work_id=w.turn_work_id))
            raise requests.Timeout('Contained provider fault')
        error=None
        with contained(s),patch.object(requests.Session,'request',failure):
            with TurnChanges(w,conv).activate():
                try:
                    llm_budget.complete(conv,OpenAICompatibleClient(),purpose='planner',prompt_version='d29-physical',system='synthetic',messages=[])
                except LLMError as exc:error=exc
                else:raise AssertionError('Provider fault did not reach failure handler')
            # Match process_pending_conversations: failure handling follows
            # _run_turn's unwind and must not inherit volatile TurnChanges.
            worker._handle_turn_failure(w,error)
        a,p=s.snap('retry-scheduled-'+str(i));state=work(a,w.turn_work_id)
        s.check('error_accounted_no_budget_refund_'+str(i),state['llm_calls_admitted']==i+1 and len([c for c in a['calls'] if c['error']=='provider_error'])==i+1,[p,'error-wire.jsonl'])
        if i==0:
            s.event('provider_error',[p,'error-wire.jsonl'],source='CONTAINED_PROVIDER');s.event('retry_scheduled',[p])
        if state['status']=='FAILED':break
        s.check('retry_wait_not_advanced_'+str(i),durable.claim_turn(row.conversation_id) is None,[p,'driver.jsonl'])
        wait_db(state['next_attempt_at']);a,p=s.snap('retry-due-'+str(i))
        if i==0:s.event('natural_retry_due',[p],runtime_clock_or_deadline_changed=False,due_db_ns=timestamp(state['next_attempt_at']))
        w=s.claim(row);a,p=s.snap('retry-claim-'+str(i));new=work(a,w.turn_work_id)
        s.check('same_work_retry_budget_retained_'+str(i),same_history(old,new) and members(a,w.turn_work_id)==[row.pk] and new['llm_calls_admitted']==i+1,[p])
        if i==0:s.event('same_work_retry',[p],same_work_and_membership=True,budget_reset=False)
    if s.variant=='retry':
        with contained(s):worker._run_turn(w)
    a,p=s.snap('retry-terminal');terminal=work(a,w.turn_work_id)
    exhausted=s.variant=='exhaustion'
    s.check('real_retry_terminal',terminal['status']==('FAILED' if exhausted else 'COMPLETED') and (not exhausted or terminal['attempts']==durable.MAX_ATTEMPTS),[p])
    s.event('retry_terminal',[p],attempts_exhausted=exhausted)


def r2_06(s):
    from apps.agent import durable
    from .execution import participants
    row,witness,old,a,p=crash_committed(s)
    pending=s.offer(org=1);wait_ready(pending);a,p=s.snap('pending-and-processing')
    s.check('restart_population_captured',work(a,old['id'])['status']=='PROCESSING' and next(m for m in a['messages'] if m['id']==pending.pk)['turn_work_id'] is None,[p])
    s.event('pending_and_processing',[p]);exitfile=s.kill('crash');s.event('workers_stop',[exitfile],source='PROCESS_EXIT')
    wait_db(old['lease_expires_at'])
    job=dict(case_id='R2-06',variant=s.variant,run_id=s.run_id,organization_ids=[f[0].pk for f in s.fixtures],slow_multiplier=2,blocked_llm_hold_seconds=120)
    with participants(s.directory,job) as procs:
        _,p=s.snap('restart-processes-ready');s.event('workers_restart',[p,'participant-plan.json'],source='PROCESS_EXIT')
        end=time.monotonic()+90
        while True:
            a=independent()
            if len(a['works'])==2 and all(w['status']=='COMPLETED' for w in a['works']):break
            if any(x.poll() is not None for x in procs) or time.monotonic()>end:raise BoundaryUnavailable('Restart failed to recover committed population')
            time.sleep(.1)
    a,p=s.snap('history-preserved');new=work(a,old['id'])
    s.check('restart_same_work_membership_budget',same_history(old,new) and members(a,old['id'])==[row.pk] and new['attempts']==old['attempts']+1 and new['llm_calls_admitted']==old['llm_calls_admitted']+2,[p,'planner_1.jsonl','planner_2.jsonl'])
    s.event('history_preserved',[p],same_work_and_membership=True,budget_reset=False)
    s.check('pending_and_processing_recovered',all(w['status']=='COMPLETED' for w in a['works']) and all(x.returncode==0 for x in procs),[p,'sender.jsonl'])
    s.event('recovery_terminal',[p])


def wait_started(s,label,process):
    p=s.directory/(label+'-started.json');end=time.monotonic()+45
    while not p.exists():
        if process.poll() is not None or time.monotonic()>end:raise BoundaryUnavailable('Lock waiter did not start')
        time.sleep(.05)
    return read(p)


def r2_07(s):
    from apps.agent import durable
    from django.db import transaction,connection,DatabaseError
    row=s.offer();wait_ready(row)
    if s.variant in ('org_lock','message_lock'):
        with db_peer() as peer:
            peer.execute('BEGIN')
            table='organizations_organization' if s.variant=='org_lock' else 'channels_message'
            pk=row.organization_id if s.variant=='org_lock' else row.pk
            peer.execute('SELECT id FROM '+table+' WHERE id=%s FOR '+('NO KEY UPDATE' if s.variant=='org_lock' else 'UPDATE'),[pk])
            with db_peer() as observer:
                state=observer.execute('SELECT state, xact_start FROM pg_stat_activity WHERE pid=%s',[peer.info.backend_pid]).fetchone()
                held=observer.execute('SELECT mode,granted FROM pg_locks WHERE pid=%s AND relation=%s::regclass',[peer.info.backend_pid,table]).fetchall()
            name='lock-acquisition.json';write_json(s.directory/name,dict(holder_pid=peer.info.backend_pid,relation=table,object_id=pk,state=state[0],transaction_started_at=str(state[1]),locks=held))
            s.check('real_lock_holder_transaction',state[0]=='idle in transaction' and ('RowShareLock',True) in held,[name])
            _,p=s.snap('lock-held');s.event('lock_acquired',[p,name])
            try:
                if s.variant=='org_lock':
                    miss=durable.claim_turn(row.conversation_id);a,p=s.snap('first-miss')
                    s.check('skip_locked_miss_before_release',miss is None and not a['works'],[p,'driver.jsonl']);s.event('first_proven_miss',[p,'driver.jsonl'])
                else:
                    process=s.child('claim',row,'waiter');marker=wait_started(s,'waiter',process)
                    end=time.monotonic()+120;waiting=None
                    with db_peer() as observer:
                        while time.monotonic()<end:
                            waiting=observer.execute('SELECT pid, wait_event_type, wait_event, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s',[marker['backend_pid']]).fetchone()
                            if waiting and waiting[1]=='Lock' and peer.info.backend_pid in waiting[3]:break
                            if process.poll() is not None:raise BoundaryUnavailable('Message lock did not block real claim')
                            time.sleep(.05)
                        else:raise BoundaryUnavailable('No PostgreSQL transaction wait witness')
                    name='postgres-lock-wait.json';write_json(s.directory/name,dict(waiter_pid=waiting[0],wait_event_type=waiting[1],wait_event=waiting[2],blocking_pids=waiting[3],holder_pid=peer.info.backend_pid))
                    s.check('actual_postgres_wait',waiting[1]=='Lock',[name]);s.event('transaction_wait_witness',[name])
            finally:peer.execute('ROLLBACK')
            with db_peer() as observer:
                held=observer.execute('SELECT mode,granted FROM pg_locks WHERE pid=%s AND relation=%s::regclass',[peer.info.backend_pid,table]).fetchall()
            name='lock-release.json';write_json(s.directory/name,dict(holder_pid=peer.info.backend_pid,relation=table,locks=held))
            s.check('real_holder_lock_released',not held,[name])
            _,p=s.snap('lock-released');s.event('lock_released',[p,name])
            if s.variant=='message_lock':
                process.wait(timeout=30);a,p=s.snap('after-release');w=next(w for w in a['works'] if w['conversation_id']==row.conversation_id)
                s.check('waiter_committed_after_release',process.returncode==0 and members(a,w['id'])==[row.pk],[p,'waiter-result.json'])
            else:
                witness=s.claim(row);a,p=s.snap('after-release');w=work(a,witness.turn_work_id)
                s.check('claim_after_org_release',members(a,w['id'])==[row.pk],[p])
            s.event('next_new_claim',[p]);return
    if s.variant in ('outer_rollback','savepoint_rollback'):
        class Rollback(Exception):pass
        if s.variant=='outer_rollback':
            try:
                with transaction.atomic():
                    w=s.claim(row);s.event('prepared_membership',['driver.jsonl'],source='JOURNAL');raise Rollback()
            except Rollback:pass
            s.event('outer_rollback',['driver.jsonl'],source='JOURNAL');a,p=s.snap('rollback-resolved')
            s.check('no_rolled_back_membership',not a['works'] and not any(m['turn_work_id'] for m in a['messages']),[p,'driver.jsonl']);s.event('rollback_resolved',[p])
        else:
            with transaction.atomic():
                try:
                    with transaction.atomic():
                        w=s.claim(row);s.event('prepared_membership',['driver.jsonl'],source='JOURNAL');raise Rollback()
                except Rollback:pass
                s.event('savepoint_rollback',['driver.jsonl'],source='JOURNAL')
            a,p=s.snap('outer-resolved');s.check('savepoint_removed_membership_outer_committed',not a['works'],[p,'driver.jsonl']);s.event('outer_resolved',[p,'driver.jsonl'])
        w=s.claim(row);a,p=s.snap('next-claim');s.check('new_committed_claim_only',members(a,w.turn_work_id)==[row.pk],[p]);s.event('next_new_claim',[p]);durable.finalize_turn(w);return
    # Inject below Journal's _commit wrapper, at the actual psycopg COMMIT.
    import psycopg
    original=psycopg.Connection.commit
    fired=False
    def lost_ack(peer):
        nonlocal fired
        result=original(peer)
        if peer is connection.connection and not fired:
            fired=True;raise DatabaseError('Contained lost commit acknowledgement')
        return result
    with patch.object(psycopg.Connection,'commit',lost_ack):
        try:durable.claim_turn(row.conversation_id)
        except DatabaseError:pass
        else:raise AssertionError('Lost acknowledgement not observed')
    s.check('actual_commit_ack_error',fired and any(e['event']=='commit_end' and e.get('error_class')=='DatabaseError' for e in lines(s.directory/'driver.jsonl')),['driver.jsonl'])
    s.event('outer_commit_ack_error',['driver.jsonl'],source='JOURNAL');a,p=s.snap('independent-visibility');s.event('independent_visibility',[p])
    bound=next(e for e in reversed(lines(s.directory/'driver.jsonl')) if e['event']=='claim_bound')
    current=work(a,bound['turn_work_id'])
    s.check('ack_resolved_by_independent_durable_witness',current['lease_fingerprint']==bound['lease_fingerprint'] and current['organization_id']==bound['organization_id'] and current['ownership_epoch']==bound['epoch'] and members(a,current['id'])==bound['member_ids'],[p,'driver.jsonl'])
    write_json(s.directory/'ack-resolution.json',dict(transaction_id=bound['transaction_id'],session_id=bound['session_id'],result='COMMITTED',witness_verified=True,visible_by_db_ns=a['db_ns'],source='INDEPENDENT_REPEATABLE_READ_DURABLE_WITNESS'))
    s.event('durable_witness_verified',[p,'ack-resolution.json'])


def r2_08(s):
    from apps.agent import durable
    from apps.agent.models import Conversation
    row=s.offer();wait_ready(row);a,p=s.snap('ordinary-population');s.event('ordinary_population_captured',[p,'offers.jsonl'])
    witness=None
    if s.variant.endswith('after') or s.variant=='w1_w2':
        witness=s.claim(row);a,p=s.snap('ordinary-claim')
        if s.variant.endswith('after'):s.event('ordinary_claim_committed',[p])
    if s.variant=='w1_w2':
        later=s.offer();wait_ready(later);a,p=s.snap('w1-processing-w2-ready')
        s.check('interruption_both_populations_retained',members(a,witness.turn_work_id)==[row.pk] and next(m for m in a['messages'] if m['id']==later.pk)['turn_work_id'] is None,[p]);s.event('w1_processing_with_w2_ready',[p])
    epoch=Conversation.objects.get(pk=row.conversation_id).ownership_epoch
    if s.variant.startswith('safety') or s.variant=='w1_w2':
        signal=s.offer(body='mi gato está intentando orinar y no sale nada')
        if witness is not None:
            # Baseline B5 intentionally keeps W1 membership fixed: reception
            # tags the signal, W1 publication defers, and W2 consolidates safety.
            # Do not manufacture immediate preemption or mutate W1's members.
            a,p=s.snap('safety-signal-deferred')
            s.check('safety_received_after_claim_keeps_w1_fixed',members(a,witness.turn_work_id)==[row.pk]
                and next(m for m in a['messages'] if m['id']==signal.pk)['semantic_type']=='safety_signal',[p])
            outcome=durable.finalize_turn(witness,outputs=[{'body':'Contained ordinary output to be deferred'}])
            a,p=s.snap('w1-deferred')
            s.check('w1_commercial_publication_suppressed',outcome=='deferred_to_new_input' and not any(m['direction']=='out' for m in a['messages']),[p])
            w2=s.claim(signal)
            from apps.agent import worker
            with contained(s):worker._run_turn(w2)
        a,p=s.snap('safety-committed')
        from apps.agent.models import HumanHandoff
        s.check('real_safety_handoff',HumanHandoff.objects.filter(conversation_id=row.conversation_id,reason_code=HumanHandoff.REASON_SAFETY).exists(),[p])
    else:
        from apps.agent.tests.test_inbox_api import _make_user
        from rest_framework.test import APIClient
        actor=_make_user(s.run_id,s.fixtures[0][0],'ADMIN')
        client=APIClient();client.force_authenticate(actor)
        conv=Conversation.objects.get(pk=row.conversation_id)
        from django.test import override_settings
        with override_settings(ALLOWED_HOSTS=['testserver','localhost']):
            reply=client.post(f'/api/inbox/conversations/{conv.public_id}/claim/')
        name='takeover-http.json';write_json(s.directory/name,dict(status_code=reply.status_code,route='inbox.conversation.claim'))
        s.check('real_human_takeover_endpoint',reply.status_code==200,[name]);a,p=s.snap('takeover-committed')
    s.event('safety_or_takeover',[p]);conv=next(c for c in a['conversations'] if c['id']==row.conversation_id)
    s.check('epoch_advanced_physically',conv['ownership_epoch']>epoch,[p]);s.event('epoch_advanced',[p])
    if witness is not None:s.fence(witness)
    else:
        # No ordinary claim existed before interruption. A forged old epoch
        # cannot grant publication and is explicitly identified as negative.
        from uuid import uuid4
        forged=durable.OwnershipWitness(row.organization_id,row.conversation_id,0,uuid4(),epoch)
        s.fence(forged)
    a,p=s.snap('interruption-inventory')
    ordinary=[m for m in a['messages'] if m['id'] in [o['message_id'] for o in s.recorder.offers[:-1] if o['message_id']]] if s.variant.startswith('safety') or s.variant=='w1_w2' else a['messages']
    s.check('ordinary_inputs_preserved_as_interrupted',row.pk in [m['id'] for m in ordinary],[p,'offers.jsonl'])
    s.event('interruption_inventory',[p,'offers.jsonl'],ordinary_success=False,classification='EXCEPTION_INTERRUPTED_RETAINED')


from .physical_guards import r2_10
CASES={'R1-07':r1_07,'R2-03':r2_03,'R2-04':r2_04,'R2-05':r2_05,'R2-06':r2_06,'R2-07':r2_07,'R2-08':r2_08,'R2-10':r2_10}
