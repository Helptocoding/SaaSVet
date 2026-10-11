"""Independent offline reader of the NEW minimal provider validation evidence."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
DIRECTORY=HERE/'provider-validation-03'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def verify(directory):
    job=read(directory/'participant-plan.json')
    durable=read(directory/'final-durable.json')
    report=read(directory/'episode-reconstruction.json')
    roles=('planner_1','planner_2','sender')
    evidence={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    errors=[]
    def require(test,name):
        if not test: errors.append(name)
    starts={role:read(directory/(role+'-provider-start.json')) for role in roles}
    end={role:read(directory/(role+'-provider-end.json')) for role in roles}
    wire=[r for role in roles for r in rows(directory/(role+'-wire.jsonl'))]
    delays=[r for role in roles for r in rows(directory/(role+'-service-delays.jsonl'))]
    requests=[r for role in roles for r in rows(directory/(role+'-requests.jsonl'))]
    job_sha=hashlib.sha256(json.dumps(job,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    require(len({r['os_pid'] for r in starts.values()})==3,'THREE_DISTINCT_PROCESS_IDS_REQUIRED')
    for role in roles:
        require(starts[role]['job_sha256']==job_sha and starts[role]['provider_file_sha256']==job['provider_sha256'],'PROCESS_PROVENANCE:'+role)
        require(starts[role]['platform']=='nt' and end[role]['os_pid']==starts[role]['os_pid'],'WINDOWS_PROCESS_IDENTITY:'+role)
        require(end[role]['original_provider_restored'] and end[role]['observer_sleep_restored'],'PROCESS_PATCH_CLEANUP:'+role)
        journal=rows(directory/(role+'.jsonl'))
        require(journal[0]['event']=='capture_start' and journal[-1]['event']=='capture_end','CAPTURE_INCOMPLETE:'+role)
        require(all(r['os_pid']==starts[role]['os_pid'] for r in journal),'JOURNAL_PID:'+role)
    for row in wire+requests+delays:
        require(row['os_pid']==starts[row['role']]['os_pid'],'WIRE_PID')
    pairs={}
    for row in wire:
        pair=pairs.setdefault(row['call_id'],{})
        require(row['event'] not in pair,'DUPLICATE_CALL_EVENT')
        pair[row['event']]=row
    llm_by_work={}
    faults=[]
    for call_id,pair in pairs.items():
        require(set(pair)=={'dispatch','result'},'INCOMPLETE_CALL_PAIR')
        if set(pair)!={'dispatch','result'}: continue
        a,b=pair['dispatch'],pair['result']
        require(all(a.get(k)==b.get(k) for k in ('boundary','organization_id','message_id','turn_work_id','epoch',
            'lease_fingerprint','call_number','fault_id','injected_fault','os_pid','run_id')),'CALL_IDENTITY_MISMATCH')
        require(a['run_id']==job['run_id'] and a['admission_verified'] and b['admission_verified'],'CALL_ADMISSION')
        require(a['in_atomic'] is False and a['external_destination'] is False,'CONTAINMENT')
        affected=a['boundary']=='meta' and a['organization_id']==job['organization_ids'][0]
        require(b['result']==('UNCERTAIN' if affected else 'ACCEPTED'),'FAULT_SCOPE')
        require(a['fault_id']==(call_id+':uncertain-meta' if affected else None),'FAULT_CORRELATION')
        if affected: faults.append(b)
        if a['boundary']=='llm':
            llm_by_work.setdefault(a['turn_work_id'],[]).append(b)
            require(a['active_org_work']==1 and a['matching_active_work'],'LLM_OWNERSHIP')
    require(len(faults)==1,'ONE_TARGET_META_FAULT_REQUIRED')
    require(set(llm_by_work)=={w['id'] for w in durable['works']},'CLAIMED_WORK_WITHOUT_SERVICE_WITNESS')
    for work in durable['works']:
        calls=llm_by_work.get(work['id'],[])
        db_calls=[c for c in durable['calls'] if c['turn_work_id']==work['id']]
        require(len(calls)==2 and {r['call_number'] for r in calls}=={1,2},'LLM_TWO_CALL_PROTOCOL')
        require(len(db_calls)==2 and all(c['admitted_at'] and c['recorded_at'] and not c['error'] for c in db_calls),'LLM_DURABLE_SERVICE')
        require(all(r['organization_id']==work['organization_id'] for r in calls),'LLM_ORG_CORRELATION')
        require(work['status']=='COMPLETED','WORK_NOT_COMPLETED')
    for role in ('planner_1','planner_2'):
        require(any(r['role']==role and r['boundary']=='llm' for r in wire),'PLANNER_UNUSED:'+role)
    expected={'llm':.5,'domain':.1,'meta':.2}
    durations={key:[] for key in expected}
    for row in delays:
        duration=row['elapsed_ns']/1e9
        durations[row['boundary']].append(duration)
        require(row['requested_seconds']==expected[row['boundary']] and duration>=expected[row['boundary']],'SERVICE_DELAY_CHANGED')
        ends=[r for r in requests if r['request_id']==row['request_id'] and r['event']=='end']
        begins=[r for r in requests if r['request_id']==row['request_id'] and r['event']=='begin']
        require(len(ends)==len(begins)==1,'REQUEST_CORRELATION')
        if ends and begins:
            target=row['boundary']=='meta' and row['organization_id']==job['organization_ids'][0]
            require(ends[0]['exception_class']==('Timeout' if target else None),'UNDECLARED_PROVIDER_EXCEPTION')
            require(begins[0]['monotonic_ns']<=row['start_ns']<=row['end_ns']<=ends[0]['monotonic_ns'],'SERVICE_BRACKET')
    require({k:len(v) for k,v in durations.items()}=={'llm':4,'domain':2,'meta':2},'SERVICE_POPULATION')
    for fault in faults:
        match=[m for m in durable['messages'] if m['id']==fault['message_id'] and m['direction']=='out']
        require(len(match)==1 and match[0]['organization_id']==job['organization_ids'][0] and match[0]['status']=='uncertain'
            and match[0]['send_admitted_at'] and not match[0]['provider_accepted_at'],'FAULT_OUTBOX_CORRELATION')
    require(any(m['direction']=='out' and m['organization_id']==job['organization_ids'][1] and m['provider_accepted_at'] for m in durable['messages']),'PEER_OUTBOUND_ACCEPTED')
    accepted=rows(directory/'offers.jsonl')
    require(len(accepted)==2 and all(o['outcome']=='ACCEPTED_DURABLE' for o in accepted),'TWO_ACCEPTED_INPUTS')
    require(len(report['episodes'])==2 and not report['issues'],'EPISODE_EVIDENCE_INCOMPLETE')
    require({o['message_id'] for o in accepted}=={m for ep in report['episodes'] for m in ep['member_ids']},'COHORT_NOT_RECONCILED')
    own=read(directory/'provider-validation-receipt.json')
    require(own['idle_guard_restored'] and own['host_clock']['host_event_window_valid'],'CLOCK_GUARD_OR_HOST')
    require(not own['invariant_gate']['missing'] and not own['invariant_gate']['violations'],'ORIGINAL_INVARIANT_GATE')
    # Clock arithmetic is rechecked on raw rows, not the driver PASS field.
    import importlib.util
    spec=importlib.util.spec_from_file_location('approved_clock_guard',HERE/'orchestration-v3/clock_guard.py')
    clock=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clock)
    for role in ('ingress',)+roles:
        state=clock.Continuity()
        for row in rows(directory/(role+'.jsonl')): state.feed(row)
        state.finish()
    clock.verify_host_cuts(read(directory/'host-before.json'),read(directory/'host-after.json'))
    return dict(status='PROVIDER_INFRASTRUCTURE_VALIDATED' if not errors else 'NOT_VALIDATED', errors=sorted(set(errors)),
        validation_scope='NEW_FINITE_PHYSICAL_PROVIDER_EVIDENCE_ONLY', accredited_scenario=False,
        actual_inputs=len(accepted),actual_works=len(durable['works']),actual_llm_calls=len(durable['calls']),
        service_seconds={k:dict(declared=expected[k],observed=v) for k,v in durations.items()},
        fault_ids=[r['fault_id'] for r in faults],process_ids={k:r['os_pid'] for k,r in starts.items()},
        confirmed_base_sha256=job['confirmed_base_reference']['sha256'],evidence_sha256=evidence,
        historical_runs_used_as_provider_evidence=False,slow_meta_queue_accredited=False)


if __name__=='__main__':
    result=verify(DIRECTORY)
    with (HERE/'independent-provider-verification.json').open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2)
        stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='evidence_sha256'}))
    raise SystemExit(0 if result['status']=='PROVIDER_INFRASTRUCTURE_VALIDATED' else 1)
