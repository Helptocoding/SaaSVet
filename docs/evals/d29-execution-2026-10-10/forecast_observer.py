"""Passive preselection reads and native poll-end publication; no worker gates."""
import json
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


def eligible(pre,arm):
    from apps.agent.tests.scheduling_characterization.evidence import timestamp, NS
    messages = {m['id']:m for m in pre['messages']}
    if any(mid not in messages for mid in (arm['waiter'],arm['future'])):
        return False
    w,f = messages[arm['waiter']],messages[arm['future']]
    at = pre['db_ns']
    w_claims=[work['claimed_at'] for work in pre['works'] if work['organization_id']==w['organization_id'] and work['claimed_at']]
    f_claims=[work['claimed_at'] for work in pre['works'] if work['organization_id']==f['organization_id'] and work['claimed_at']]
    return (all(m['status']=='pending' and m['turn_work_id'] is None and m['available_at'] for m in (w,f))
        and w['organization_id']!=f['organization_id']
        and timestamp(w['available_at'])<=at<timestamp(f['available_at'])<=at+NS
        and all(work['status']=='COMPLETED' for work in pre['works'])
        and bool(w_claims) and (not f_claims or max(map(timestamp,f_claims))<max(map(timestamp,w_claims))))


def snapshot(peer):
    from psycopg.rows import dict_row
    from apps.agent.tests.scheduling_characterization.evidence import timestamp
    with peer.transaction(),peer.cursor(row_factory=dict_row) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        c.execute('SELECT clock_timestamp() AS at, pg_backend_pid() AS pid')
        clock = c.fetchone()
        c.execute('SELECT id,organization_id,conversation_id,direction,status,semantic_type,available_at,turn_work_id,created_at FROM channels_message ORDER BY id')
        messages = c.fetchall()
        c.execute('SELECT id,organization_id,conversation_id,status,claimed_at FROM agent_turnwork ORDER BY id')
        works = c.fetchall()
    return json.loads(json.dumps(dict(db_ns=timestamp(clock['at'].isoformat()),backend_pid=clock['pid'],
        messages=messages,works=works,source='INDEPENDENT_PRE_SELECTION_READ_ONLY'),default=str))


def qualifies_yield(event,data,observation):
    return bool(event=='poll_end' and data.get('outcome')=='returned' and observation
        and not observation['conversation_ids'] and observation['eligible'])


def find_arm(pre):
    from apps.agent.tests.scheduling_characterization.evidence import timestamp,NS
    pending=[m for m in pre['messages'] if m.get('direction','in')=='in' and m['status']=='pending'
        and m['turn_work_id'] is None and m['available_at']]
    ready=[m for m in pending if timestamp(m['available_at'])<=pre['db_ns']]
    future=[m for m in pending if pre['db_ns']<timestamp(m['available_at'])<=pre['db_ns']+NS]
    return next((dict(waiter=w['id'],future=f['id']) for w in ready for f in future
        if eligible(pre,dict(waiter=w['id'],future=f['id']))),None)


@contextmanager
def installed(directory,job,role):
    if job['case_id']!='R1-04' or role=='sender':
        yield
        return
    from apps.agent import claim_diagnostics as trace
    from apps.agent.tests.scheduling_characterization.physical import db_peer
    directory = Path(directory)
    select,emit = trace.select_candidates,trace.Journal.emit
    observations = {}
    with db_peer() as peer:
        def observed_select(factory,*args):
            journal = trace._active.get()
            pre = None
            if journal is not None and not (directory/'forecast-disarm').exists():
                lo = time.perf_counter_ns()
                pre = snapshot(peer)
                hi = time.perf_counter_ns()
                arm=find_arm(pre)
                emit(journal,'forecast_prequery',prequery=pre,read_monotonic_bounds=[lo,hi])
            result = select(factory,*args)
            if pre is not None:
                poll = (trace._scope.get() or {}).get('poll_id')
                observations[poll] = dict(prequery=pre,conversation_ids=result,arm=arm,
                    prequery_monotonic_bounds=[lo,hi],eligible=arm is not None)
            return result

        def observed_emit(journal,event,**data):
            emit(journal,event,**data)
            if event!='poll_end':
                return
            poll = (trace._scope.get() or {}).get('poll_id')
            observation = observations.pop(poll,None)
            if not qualifies_yield(event,data,observation):
                return
            # The native poll has exited its empty-selection branch. Publishing
            # a signal never pauses a planner or performs the correction itself.
            at = time.perf_counter_ns()
            emit(journal,'forecast_empty_poll_returned',native_poll_id=poll,**observation)
            value = dict(observation,role=role,poll_id=poll,yield_monotonic_ns=at)
            pending = directory/(role+'-yield.writing')
            pending.write_text(json.dumps(value),encoding='utf-8')
            marker = directory/(role+'-yield.json')
            if not marker.exists():
                pending.rename(marker)
            else:
                pending.unlink()
        with patch.object(trace,'select_candidates',observed_select),patch.object(trace.Journal,'emit',observed_emit):
            yield
