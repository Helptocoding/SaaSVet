"""Inactive fixture plans and conservative offline R2-09 observation gates."""
from collections import defaultdict
from copy import deepcopy

from common import BASE, BASE_HASH, BASELINE, PRIOR, read, sha
from r106_verifier import NS, pair_wire


def plan(variant):
    if variant not in ('uncertain_meta','slow_meta'):
        raise ValueError('Separate, explicitly named Meta variants only')
    prior=PRIOR/'r2-09/authorized-r209-uncertain-meta-20261007-0002/participant-plan.json'
    p=read(prior)
    # The executor job is retained as a reference, not resealed as executed.
    return {'schema':'D29_R209_OFFLINE_FIXTURE_PREPARATION_V1','status':'PREPARED_NOT_EXECUTED',
            'case_id':'R2-09','variant':variant,'execution_authorized':False,
            'baseline':BASELINE,'confirmed_base_reference':{'path':str(BASE),'sha256':BASE_HASH},
            'prior_job_reference':{'path':str(prior),'sha256':sha(prior)},
            'base_configuration':{'rates':p['confirmed_base_rates'],'organizations':2,'conversations_per_org':3,
                                  'planners':2,'sender':1,'offer_seconds':360,'followup_seconds':240,
                                  'calendar':'UNCHANGED_BASE_HALF_OPEN_PACING','ordinary_rotation':'UNCHANGED_GLOBAL_ORDINAL_MOD_3'},
            'provider_reference':{'path':str(PRIOR/'revision2/evaluation_provider.py'),
                                  'sha256':sha(PRIOR/'revision2/evaluation_provider.py')},
            'provider_parameters':{'llm_calls':2,'llm_seconds':0.5,'domain_seconds':0.1,'meta_seconds':0.2,
                                   'slow_multiplier':p['slow_multiplier'],'affected_boundary':'meta','target_org_index':0},
            'initial_cohort':[{'organization_index':o,'conversation_slot':s,'phase':'INITIAL_READY',
                               'ingress':'EXISTING_ORDINARY_PUBLIC_READ','natural_ready':True} for o in (0,1) for s in (0,1,2)],
            'launch_order':['fresh_private_database','start_ingress_capture','six_ordinary_inputs_workers_absent',
                            'wait_native_ready_no_updates','sealed_prestart_cut','start_sender_and_observe_ready',
                            'start_planner_1','start_planner_2','observe_both_ready','open_unchanged_base_offer',
                            'continue_freely_360s_offer_plus_240s_followup','final_reconciliation','cleanup_and_integrity'],
            'after_planner_start':{'holds':False,'barriers':False,'forced_delays':False,'provider_changes':False},
            'cohorts_separate':True,'do_not_require_equal_input_episode_counts':True,
            'no_overlap_result':'NOT_ACCREDITED / PENDING_NATURAL_OVERLAP',
            'on_failure':'PRESERVE_ATTEMPT_AND_STOP_NO_AUTOMATIC_RETRY',
            'required_receipts':['initial-ingress-ledger','initial-ready-cut','process-launch-and-ready',
                                 'base-schedule-and-actual-acceptances','all-raw-journals','all-wire',
                                 'full-durable-final','obligation-causal-events','clock-and-host-cuts',
                                 'peer-progress','authority-outbox-no-blind-retry','cleanup-and-source-integrity']}


def validate_plan(p):
    errors=[]
    expected=plan(p['variant'])
    for key in ('baseline','confirmed_base_reference','base_configuration','provider_reference','provider_parameters',
                'initial_cohort','launch_order','after_planner_start','cohorts_separate'):
        if p.get(key)!=expected[key]:errors.append('PREPARATION_CHANGED:'+key)
    if p.get('execution_authorized') is not False:errors.append('OFFLINE_PLAN_IS_NOT_EXECUTION_AUTHORIZATION')
    return {'errors':errors,'offline_plan_valid':not errors,'physical_accreditation':False}


def initial_cohort_gate(episodes, accepted_initial_ids, cut, launches, sender_ready, org_conversations):
    """Inputs must come from raw reconstruction; later READY queries do not fit."""
    errors=[]
    if len(accepted_initial_ids)!=6 or len(set(accepted_initial_ids))!=6:
        errors.append('EXACTLY_SIX_INITIAL_INPUTS_REQUIRED')
    initial=[e for e in episodes if set(e['member_ids']) & set(accepted_initial_ids)]
    if len(initial)!=6 or {m for e in initial for m in e['member_ids']}!=set(accepted_initial_ids):
        errors.append('SIX_DISTINCT_INITIAL_EPISODES_NOT_RECONCILED')
    scopes={(e['organization_id'],e['conversation_id']) for e in initial}
    expected={(o,c) for o,cs in org_conversations.items() for c in cs}
    if scopes!=expected or len(expected)!=6:errors.append('EXISTING_2X3_POPULATION_NOT_PRESERVED')
    for e in initial:
        if e['ready_ns_bounds'][1] is None or e['ready_ns_bounds'][1]>cut[0]:
            errors.append('NATURAL_READY_NOT_PROVEN_BEFORE_START')
        if e.get('claim_commit_ns_bounds') and e['claim_commit_ns_bounds'][0]<=cut[1]:
            errors.append('INITIAL_EPISODE_ALREADY_CLAIMED_AT_CUT')
    if len(launches)!=2 or {r['role'] for r in launches}!={'planner_1','planner_2'}:
        errors.append('BOTH_PLANNER_LAUNCHES_REQUIRED')
    for launch in launches:
        if launch['start_ns_bounds'][0]<=cut[1]:errors.append('PLANNER_STARTED_BEFORE_PRESTART_CUT')
        if sender_ready is None or sender_ready['ready_ns_bounds'][1]>=launch['start_ns_bounds'][0]:
            errors.append('SENDER_NOT_PREPARED_BEFORE_PLANNERS')
        if launch.get('hold_after_start') is not False:errors.append('ARTIFICIAL_POSTSTART_HOLD')
    return {'errors':sorted(set(errors)),'physical_accreditation':False}


def definite_overlap(ready, claim, dispatch, result, offer):
    """Interior shared by all possible realizations, not merely possible overlap."""
    xs=(ready,claim,dispatch,result,offer)
    if any(len(x)!=2 or None in x or x[0]>x[1] for x in xs):return None
    lo=max(ready[1],dispatch[1],offer[0])
    hi=min(claim[0],result[0],offer[1])
    return [lo,hi] if lo<hi else None


def provider_gate(wire, works, outbox, variant, target_org):
    errors=[]
    pairs,pair_errors=pair_wire(wire);errors.extend(pair_errors)
    calls=defaultdict(list);meta=defaultdict(list);faults=[]
    wmap={w['id']:w for w in works};mmap={m['id']:m for m in outbox}
    for d,r in pairs:
        if d['boundary']=='llm':
            calls[d.get('turn_work_id')].append((d,r))
            if d.get('fault_id') or d.get('injected_fault') or r.get('result')!='ACCEPTED':
                errors.append('META_INJECTION_CONTAMINATED_LLM')
        elif d['boundary']=='meta':
            meta[d.get('message_id')].append((d,r))
            message=mmap.get(d.get('message_id'))
            if not message or message['organization_id']!=d['organization_id'] or not message.get('send_admitted_at'):
                errors.append('META_DISPATCH_OUTBOX_ADMISSION_NOT_CORRELATED')
            affected=d['organization_id']==target_org
            if d.get('fault_id'):
                faults.append(d['fault_id'])
                if (not affected or variant!='uncertain_meta' or d.get('injected_fault')!='UNCERTAIN_META'
                        or d.get('fault_id')!=d['call_id']+':uncertain-meta' or r.get('result')!='UNCERTAIN'):
                    errors.append('FAULT_OUTSIDE_DECLARED_META_FRONTIER')
            if variant=='uncertain_meta' and affected:
                if not d.get('fault_id') or r.get('result')!='UNCERTAIN':errors.append('UNCERTAIN_META_FAULT_NOT_CORRELATED')
                if message and message.get('provider_accepted_at'):errors.append('UNCERTAIN_OUTPUT_COUNTED_AS_ACCEPTED')
            elif r.get('result')!='ACCEPTED':errors.append('UNDECLARED_META_UNCERTAINTY')
            if variant=='slow_meta' and (d.get('fault_id') or d.get('injected_fault')):
                errors.append('SLOW_META_MUST_NOT_INJECT_UNCERTAINTY')
            minimum=NS*2//5 if variant=='slow_meta' and affected else NS//5
            if r.get('elapsed_ns',-1)<minimum:errors.append('UNCHANGED_META_SERVICE_COST_NOT_OBSERVED')
    if len(set(faults))!=len(faults):errors.append('FAULT_ID_NOT_UNIQUE')
    if set(calls)!=set(wmap):errors.append('CLAIMED_WORK_WITHOUT_SERVICE_WITNESS_OR_ORPHAN_SERVICE')
    for wid,work in wmap.items():
        values=calls[wid]
        if len(values)!=2 or {d.get('call_number') for d,r in values}!={1,2} or any(r.get('elapsed_ns',-1)<NS//2 for d,r in values):
            errors.append('COMPLETE_BASE_LLM_WITNESS_MISSING')
        if any(d.get('organization_id')!=work['organization_id'] or d.get('epoch')!=work['ownership_epoch'] or d.get('lease_fingerprint')!=work['lease_fingerprint'] for d,r in values):
            errors.append('LLM_AUTHORITY_WITNESS_MISMATCH')
    if set(meta)!=set(mmap):errors.append('OUTBOX_META_POPULATION_NOT_RECONCILED')
    if any(len(values)!=1 for values in meta.values()):errors.append('BLIND_RETRY_OR_DUPLICATE_DISPATCH')
    # These gates are a supplement; peer, authority, clocks and causal obligation
    # gates from raw capture remain mandatory. No physical PASS issued here.
    return {'errors':sorted(set(errors)),'physical_accreditation':False}
