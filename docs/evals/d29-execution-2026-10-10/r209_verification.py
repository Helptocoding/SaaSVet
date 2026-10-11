"""Prospective R209 supplemental gates; UNCERTAIN remains UNCERTAIN."""
import json
from pathlib import Path
from apps.agent.tests.scheduling_characterization.assessment import demand_gate, invariant_gate, window_gate
from apps.agent.tests.scheduling_characterization.evidence import ClockMap, Interval, NS, reconstruct, timestamp, transactions
from apps.agent.tests.scheduling_characterization.execution import queued_samples, read_lines
from apps.agent.tests.scheduling_characterization.replay import schedule
from apps.agent.tests.scheduling_characterization.recipes import verify_recipe
from apps.agent.tests.scheduling_characterization.scenario_observations import observations
import r106_verifier
from r209_preparation import initial_cohort_gate, provider_gate, definite_overlap


def verify(d, job):
    read = lambda p: json.loads(Path(p).read_text())
    participant = read(d / 'participant-plan.json')
    final = read(d / 'full-durable-final.json')
    journals = [read_lines(d / (r + '.jsonl')) for r in r106_verifier.ROLES]
    roles = dict(zip(r106_verifier.ROLES,journals))
    offers = read_lines(d / 'schedule-offers.jsonl')
    wire = [e for r in r106_verifier.ROLES[1:] for e in read_lines(d / (r + '-wire.jsonl'))]
    report = reconstruct(journals, offers, final['messages'], Interval(final['db_ns'],final['db_ns']), run_id=job['run_id'])
    effects, unresolved = transactions(journals)
    causal = r106_verifier.causal_events(journals,effects)
    original = r106_verifier.reconcile(report,final['messages'],final['works'],wire,final['calls'],causal)
    target = participant['organization_ids'][0]
    outbox = [m for m in final['messages'] if m['direction']=='out']
    provider = provider_gate(wire,final['works'],outbox,job['variant'],target)
    pairs, pair_errors = r106_verifier.pair_wire(wire)
    valid_uncertain = set()
    for m in outbox:
        calls = [(a,b) for a,b in pairs if a['boundary']=='meta' and a.get('message_id')==m['id']]
        if (job['variant']=='uncertain_meta' and m['organization_id']==target and m['status']=='uncertain'
                and not m.get('provider_accepted_at') and m.get('send_admitted_at') and len(calls)==1):
            a,b = calls[0]
            if (b['result']=='UNCERTAIN' and a.get('fault_id')==a['call_id']+':uncertain-meta'
                    and a.get('injected_fault')=='UNCERTAIN_META' and a['admission_verified']):
                valid_uncertain.add(m['id'])
    accepted = set()
    for m in outbox:
        calls = [(a,b) for a,b in pairs if a['boundary']=='meta' and a.get('message_id')==m['id']]
        if len(calls)==1 and calls[0][1]['result']=='ACCEPTED' and m.get('provider_accepted_at') and m.get('send_admitted_at'):
            accepted.add(m['id'])
    by_work = {}
    for m in outbox:
        by_work.setdefault(m['turn_work_id'],[]).append(m['id'])
    resolved = accepted | valid_uncertain
    accounted_work = {wid for wid,mids in by_work.items() if mids and set(mids)<=resolved}
    # Preserve the original verifier result. Only its acceptance-only findings
    # for a positively correlated uncertain endpoint receive variant disposition.
    explained = set()
    for mid in valid_uncertain:
        explained.add('OUTPUT_ACCEPTANCE_NOT_PROVEN:'+str(mid))
    for wid in accounted_work:
        explained.add('RESPONSE_OBLIGATION_UNRESOLVED:'+str(wid))
    obligations = []
    for obligation in original['obligations']:
        endpoint = obligation['terminal_work_id']
        if endpoint in accounted_work:
            explained.add('OBLIGATION_CHAIN_UNRESOLVED:'+str(obligation['work_id']))
        mids = by_work.get(endpoint,[])
        obligations.append(dict(obligation, accepted_output_ids=[mid for mid in mids if mid in accepted],
            uncertain_output_ids=[mid for mid in mids if mid in valid_uncertain],
            endpoint_disposition='UNCERTAIN' if any(mid in valid_uncertain for mid in mids) else
                                 'ACCEPTED' if mids and set(mids)<=accepted else 'PENDING'))
    errors = [e for e in original['errors'] if e not in explained] + provider['errors'] + pair_errors
    clock = ClockMap(roles['ingress'])
    slots = read(d / 'schedule.json')
    start = min(s['due_monotonic_ns'] for s in slots)
    if schedule(participant,start) != slots:
        errors.append('BASE_CALENDAR_CHANGED')
    offsets = [0,120,240,360]
    intervals = [Interval(start+x*NS+clock.offset.lo,start+x*NS+clock.offset.hi) for x in offsets]
    queues = queued_samples(report,offsets,intervals)
    # INITIAL_READY is physically a prestart backlog cohort. Retain its raw
    # label, but present it to the unchanged gate through its BACKLOG interface.
    demand_offers = [dict(o,phase='BACKLOG') if o['phase']=='INITIAL_READY' else o for o in offers]
    demand = demand_gate(dict(participant,boundary_case=True),report,demand_offers,slots,
                         participant['organization_ids'],(intervals[0].lo,intervals[-1].hi))
    invariant = invariant_gate(report,journals,final['messages'],final['works'],[a for a,b in pairs],participant['organization_ids'])
    windows = window_gate(participant,report,queues,participant['organization_ids'])
    events = observations(participant,report,journals,[a for a,b in pairs],read_lines,d,final)
    recipe = verify_recipe(participant,events)
    for name,gate in [('demand',demand),('invariants',invariant),('windows',windows),('scenario',recipe)]:
        errors += [name+':'+x for x in gate['missing']+gate['violations']]
    if any(v in ('INDETERMINATE','OBSERVED_BACKLOG_GROWTH') for v in windows['backlog'].values()):
        errors.append('QUEUE_BACKLOG_NOT_COMPATIBLE')
    cuts = [s for s in read_lines(d/'snapshots.jsonl') if s['stage']=='initial_ready_before_workers']
    initial = [o for o in offers if o['phase']=='INITIAL_READY']
    launches = read_lines(d/'process-launch.jsonl')
    pids = [journal[0]['os_pid'] for journal in journals]
    if len(set(pids)) != 4:
        errors.append('FOUR_SEPARATE_PARTICIPANT_PROCESSES_REQUIRED')
    for role in r106_verifier.ROLES[1:]:
        launch = [r for r in launches if r['event']=='launch' and r['role']==role]
        identities = [r for r in roles[role] if r['event']=='participant_identity']
        ready = [r for r in launches if r['event']=='ready_observed' and r['role']==role]
        if len(launch)!=1 or len(identities)!=1 or len(ready)!=1:
            errors.append('NATIVE_PROCESS_IDENTITY_OR_PREPARATION_MISSING:'+role)
            continue
        l,i,r = launch[0],identities[0],ready[0]
        if (i.get('parent_pid')!=l['launcher_pid'] or not l.get('launcher_creation_filetime')
                or i.get('process_creation_filetime',0)<l['launcher_creation_filetime']
                or not l['start_monotonic_bounds'][0]<=i['monotonic_ns']<=r['monotonic_ns']):
            errors.append('PROCESS_ANCESTRY_CREATION_OR_READY_NOT_CORRELATED:'+role)
    spans = [[r['monotonic_ns'] for r in roles[role] if r['event']=='poll_start'] for role in ('planner_1','planner_2')]
    if any(not s for s in spans) or max(s[0] for s in spans)>=min(s[-1] for s in spans):
        errors.append('CONCURRENT_PLANNERS_NOT_OBSERVED')
    def mapped(lo,hi):
        return clock.execution(dict(execute_start_ns=lo,execute_end_ns=hi)).json()
    starts = []
    for role in ('planner_1','planner_2'):
        identity = [r for r in roles[role] if r['event']=='participant_identity']
        if len(identity)==1 and identity[0].get('process_creation_filetime'):
            # Native creation of the planner process, rather than the earlier
            # Popen bracket of its RTK launcher. FILETIME units are 100ns from
            # 1601; the journal and both ancestry witnesses remain preserved.
            created = (identity[0]['process_creation_filetime']-116444736000000000)*100
            starts.append(dict(role=role,start_ns_bounds=[created,created+99],hold_after_start=False,
                               source='NATIVE_WINDOWS_PROCESS_CREATION'))
    sender = [r for r in launches if r['event']=='ready_observed' and r['role']=='sender']
    sender_ready = dict(ready_ns_bounds=mapped(sender[0]['monotonic_ns'],sender[0]['monotonic_ns'])) if len(sender)==1 else None
    initial_gate = dict(errors=['SEALED_INITIAL_CUT_MISSING'])
    if len(cuts)==1:
        cut = cuts[0]
        clocks = [e for e in roles['ingress'] if e['event']=='db_clock' and timestamp(e['db_timestamp'])==cut['db_ns']]
        if len(clocks)==1:
            calibration = clocks[0]
            end = next(e['seq'] for e in roles['ingress'] if e['event']=='commit_end' and e['transaction_id']==calibration['transaction_id'])
            prefix = [e for e in roles['ingress'] if e['seq']<=end]
            before = reconstruct([prefix],initial,cut['messages'],Interval(cut['db_ns'],cut['db_ns']),run_id=job['run_id'])
            scopes = {o:sorted({m['conversation_id'] for m in cut['messages'] if m['organization_id']==o}) for o in participant['organization_ids']}
            initial_gate = initial_cohort_gate(before['episodes'],[o['message_id'] for o in initial],
                [cut['db_ns'],cut['db_ns']],starts,sender_ready,scopes)
            errors += before['issues']
        if cut['works'] or any(m['turn_work_id'] for m in cut['messages']):
            errors.append('INITIAL_CUT_ALREADY_CLAIMED')
    errors += initial_gate['errors']
    overlap = []
    offer_span = [intervals[0].hi,intervals[-1].lo]
    for a,b in pairs:
        if a['boundary']!='meta' or a['organization_id']!=target:
            continue
        sender_clock = ClockMap(roles['sender'])
        dispatch = sender_clock.execution(dict(execute_start_ns=a['monotonic_ns'],execute_end_ns=a['monotonic_ns'])).json()
        result = sender_clock.execution(dict(execute_start_ns=b['monotonic_ns'],execute_end_ns=b['monotonic_ns'])).json()
        for e in report['episodes']:
            if e['organization_id']==target and e.get('claim_commit_ns_bounds'):
                span = definite_overlap(e['ready_ns_bounds'],e['claim_commit_ns_bounds'],dispatch,result,offer_span)
                if span:
                    overlap.append(dict(episode_id=e['episode_id'],call_id=a['call_id'],definite_db_ns=span))
    if not overlap:
        errors.append('PENDING_NATURAL_OVERLAP')
    peer = participant['organization_ids'][1]
    ordinary_ids = {o['message_id'] for o in offers if o['phase']=='ORDINARY' and o['organization_id']==peer and o['outcome']=='ACCEPTED_DURABLE'}
    peer_progress = [e['episode_id'] for e in report['episodes'] if e['organization_id']==peer
        and set(e['member_ids']) & ordinary_ids and e.get('claim_commit_ns_bounds')
        and offer_span[0]<=e['claim_commit_ns_bounds'][0]<=e['claim_commit_ns_bounds'][1]<=offer_span[1]
        and any(a['boundary']=='llm' and a.get('turn_work_id')==e['turn_work_id'] for a,b in pairs)]
    if not peer_progress:
        errors.append('PHYSICAL_ORDINARY_PEER_PROGRESS_MISSING')
    if final['db_ns'] < start+600*NS+clock.offset.hi:
        errors.append('FULL_FOLLOWUP_NOT_OBSERVED')
    if {k:v for k,v in participant.items() if k!='organization_ids'} != job:
        errors.append('PARTICIPANT_JOB_CHANGED')
    return dict(errors=sorted(set(errors)),gates=dict(demand=demand,invariants=invariant,windows=windows,
        scenario=recipe,initial_cohort=initial_gate,provider=provider),
        original_acceptance_only_reconciliation=original,variant_explained_errors=sorted(set(original['errors']) & explained),
        obligations=obligations,definite_overlaps=overlap,peer_progress=peer_progress,
        reconciliation=dict(counts=dict(original['counts'],uncertain_outputs=len(valid_uncertain))))
