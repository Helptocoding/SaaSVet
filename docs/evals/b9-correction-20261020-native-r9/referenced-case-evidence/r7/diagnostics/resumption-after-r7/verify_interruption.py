"""Read-only r7 audit; outputs confined to this diagnostics directory."""
from collections import Counter
from datetime import datetime, timezone
import bisect, hashlib, json
from pathlib import Path

HERE=Path(__file__).resolve().parent
E=HERE.parent.parent
TREE=Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6/src')
SHA='68dffd746793700071f577a58528b0f9636930db'
h=lambda b:hashlib.sha256(b).hexdigest()
now=lambda:datetime.now(timezone.utc).isoformat()
epoch=lambda s:datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
selector_sha=lambda ids:h(('\n'.join(sorted(ids))+'\n').encode())
def check(items,root=None):
    bad=[];missing=[];n=0
    for name,sha in items:
        p=root/name if root is not None else Path(name);n+=1
        if not p.is_file():missing.append(name)
        elif h(p.read_bytes())!=sha:bad.append(name)
    return dict(checked_files=n,mismatches=bad,missing=missing)
def window(rows,start,end,cases):
    ts=[r['utc_epoch_seconds'] for r in rows]
    a=max(0,bisect.bisect_right(ts,start)-1);b=min(len(rows),bisect.bisect_left(ts,end)+1)
    chosen=rows[a:b]
    gaps=[y['utc_epoch_seconds']-x['utc_epoch_seconds'] for x,y in zip(chosen,chosen[1:])]
    ages=[]
    for case in cases:
        t=epoch(case['utc']);i=bisect.bisect_right(ts,t)-1
        ages.append(dict(id=case['id'],utc=case['utc'],age_seconds=None if i<0 else t-ts[i]))
    return chosen,dict(total_durable_rows=len(rows),window_rows=len(chosen),first_utc=chosen[0]['utc'],
        last_utc=chosen[-1]['utc'],durable_last_utc=rows[-1]['utc'],
        covers_start=chosen[0]['utc_epoch_seconds']<=start,covers_end=chosen[-1]['utc_epoch_seconds']>=end,
        maximum_sample_gap_seconds=max(gaps,default=0),
        gaps_over_ten_seconds=[dict(before_utc=x['utc'],after_utc=y['utc'],seconds=g)
            for x,y,g in zip(chosen,chosen[1:],gaps) if g>10],
        backwards_or_duplicate_epoch_count=sum(g<=0 for g in gaps),
        maximum_preceding_case_sample_age_seconds=max(x['age_seconds'] for x in ages if x['age_seconds'] is not None),
        uncovered_cases=[x for x in ages if x['age_seconds'] is None or not 0<=x['age_seconds']<=10])
def main():
    started=now()
    names=['blocks/full-general-remainder.ids.jsonl','blocks/full-general-remainder.command.json',
        'blocks/full-general-remainder.command.log','invocation-formal.json','invocation-formal.log',
        'resource-observer/samples.jsonl','awake-request/heartbeat.jsonl','full-general-remainder-selected.json',
        'full-general-selected.json','retained-general-observed-ids.json',
        'referenced-case-evidence/r6/blocks/full-general.ids.jsonl','case-resumption-authorization.json',
        'case-resumption-manifest.json','case-resumption-validation.json','candidate-sources.json',
        'dependency-files.json','evaluation-seal.json','integrity-before-full-general-remainder.json',
        'dependency-check-before-full-general-remainder.json','seal-check-before-full-general-remainder.json']
    raw={n:(E/n).read_bytes() for n in names}
    obj=lambda n:json.loads(raw[n])
    lines=lambda n:[json.loads(s) for s in raw[n].decode().splitlines()]
    journal=lines(names[0]);old=lines('referenced-case-evidence/r6/blocks/full-general.ids.jsonl')
    selected=obj('full-general-remainder-selected.json');full=obj('full-general-selected.json')
    retained=obj('retained-general-observed-ids.json');ids=[r['id'] for r in journal];oldids=[r['id'] for r in old]
    counts=Counter(r['outcome'] for r in journal)
    pending=sorted(set(selected)-set(ids));passed=sorted(r['id'] for r in journal if r['outcome']=='PASS')
    failed=sorted(r['id'] for r in journal if r['outcome']=='FAIL')
    prefix=dict(old_retained_count=len(retained),old_journal_count=len(old),
        old_retained_matches_journal=set(retained)==set(oldids),new_selected_count=len(selected),
        new_selected_unique=len(set(selected)),new_journal_count=len(journal),new_journal_unique=len(set(ids)),
        new_outcomes=dict(counts),new_unexpected_ids=sorted(set(ids)-set(selected)),
        new_duplicate_ids=[n for n,c in Counter(ids).items() if c>1],
        new_unexpected_outcomes=[r for r in journal if r['outcome'] not in {'PASS','FAIL'}],
        prior_new_overlap=sorted(set(retained)&set(selected)),observed_pending_overlap=sorted(set(ids)&set(pending)),
        old_plus_observed_plus_missing_equals_full=set(retained)|set(ids)|set(pending)==set(full),
        sum_counts=len(retained)+len(ids)+len(pending),full_general_count=len(full),missing_count=len(pending),
        final_newline=raw[names[0]].endswith(b'\n'),
        journal_utc_monotonic=all(epoch(a['utc'])<=epoch(b['utc']) for a,b in zip(journal,journal[1:])),
        first_case=journal[0],last_case=journal[-1],failed_cases=[r for r in journal if r['outcome']=='FAIL'],
        retained_new_pass_selector_digest=selector_sha(passed),observed_new_failed_selector_digest=selector_sha(failed),
        missing_selector_digest=selector_sha(pending),observed_new_selector_digest=selector_sha(ids),
        logical_general_result='NON_PASS_TWO_RECORDED_FAILURES_AND_321_WITHOUT_OUTCOME',
        failed_cases_are_not_dropped_or_changed_to_pass=True)
    cmd=obj('blocks/full-general-remainder.command.json')
    start=cmd['resources_before']['host']['utc_epoch_seconds'];end=epoch(journal[-1]['utc'])+1
    samples=lines('resource-observer/samples.jsonl');awake=lines('awake-request/heartbeat.jsonl')
    covered,obs=window(samples,start,end,journal);aw,aws=window(awake,start,end,journal)
    obs.update(minimum_ram_bytes=min(r['physical_available'] for r in covered),
        minimum_disk_bytes=min(r['disk_available'] for r in covered),
        maximum_absolute_wall_monotonic_skew_seconds=max(abs(r['wall_minus_monotonic_seconds']) for r in covered),
        below_2_gib_ram=[r for r in covered if r['physical_available']<2*1024**3],
        below_1_gib_disk=[r for r in covered if r['disk_available']<1024**3],
        skew_over_one_second=[r for r in covered if abs(r['wall_minus_monotonic_seconds'])>1],
        observer_pid_values=sorted(set(r['observer_pid'] for r in covered)),
        scope='actual command start through final observed case second; no command completion claimed')
    aws.update(unexpected_api_state_rows=[r for r in aw if r['api_previous_state']!='0x80000001'],
        pid_values=sorted(set(r['pid'] for r in aw)),thread_id_values=sorted(set(r['thread_id'] for r in aw)),
        old_request_api_restoration_claimed=False)
    integ=dict(candidate_tree=SHA,scope='post interruption current bytes; not historical after-run checks',
        sources=check(((r['path'],r['sha256']) for r in obj('candidate-sources.json')['files']),TREE),
        dependencies=check(obj('dependency-files.json')['files'].items()),
        evaluation_seal=check(obj('evaluation-seal.json')['files'].items()))
    unchanged={n:h((E/n).read_bytes())==h(b) for n,b in raw.items()}
    problems=[]
    if len(journal)!=407 or counts!=Counter(PASS=405,FAIL=2):problems.append('unexpected journal counts')
    if len(pending)!=321 or prefix['sum_counts']!=3213:problems.append('unexpected exact partition counts')
    for k in ['new_unexpected_ids','new_duplicate_ids','new_unexpected_outcomes','prior_new_overlap','observed_pending_overlap']:
        if prefix[k]:problems.append(k)
    for k in ['old_retained_matches_journal','old_plus_observed_plus_missing_equals_full','final_newline','journal_utc_monotonic']:
        if not prefix[k]:problems.append(k)
    for k in ['sources','dependencies','evaluation_seal']:
        if integ[k]['mismatches'] or integ[k]['missing']:problems.append('current byte drift: '+k)
    if not all(unchanged.values()):problems.append('input changed during audit')
    guards=[]
    for k,r in [('observer',obs),('awake',aws)]:
        if r['gaps_over_ten_seconds'] or r['backwards_or_duplicate_epoch_count'] or r['uncovered_cases']:guards.append(k+' sample coverage')
        if not r['covers_start'] or not r['covers_end']:guards.append(k+' interval endpoints')
    if obs['below_2_gib_ram'] or obs['below_1_gib_disk'] or obs['skew_over_one_second']:guards.append('resource or clock threshold incident')
    if aws['unexpected_api_state_rows']:guards.append('awake api state')
    result=dict(schema='b9.r7-interruption-observation.v1',
        state='PASS_INTEGRITY_WITH_RECORDED_FAILURES' if not problems else 'AUDIT_NONPASS',
        utc_started=started,utc_finished=now(),candidate_tree=SHA,application_tests_executed=False,
        services_changed=False,prior_files_modified=False,helper_sha256=h(Path(__file__).read_bytes()),
        input_artifacts={n:dict(sha256=h(b),bytes=len(b)) for n,b in raw.items()},
        original_inputs_unchanged_during_audit=unchanged,prefix=prefix,durable_host_observer=obs,
        durable_awake_observer=aws,current_byte_integrity=integ,audit_problems=problems,guard_coverage_problems=guards,
        interruption=dict(original_command_state=cmd['state'],original_invocation_state=obj('invocation-formal.json').get('state'),
            final_exit_code=None,suite_final_receipt_present=(E/'blocks/full-general-remainder.results.json').exists(),
            controller_final_monitor_present=(E/'monitor-full-general-remainder.json').exists(),r7_completed_gate_claimed=False,
            exact_windows_last_boot_utc='2026-10-20T04:06:40.5000000Z',
            boot_value_provenance='root readonly Get-CimInstance Win32_OperatingSystem UTC2026-10-20T04:22:52Z',
            cause_of_interruption_established=False,raw_controller_after_checks_or_exit_code_synthesized=False,
            durable_observer_covers_recorded_cases_subject_to_reported_gap_checks=not guards),
        proposed_selection_only=dict(new_missing=321,retained_new_pass=405,preserved_new_fail=2,old_retained=2485,
            permission_to_rerun_failed_cases_is_inferred=False,selector_file_is_a_proposal_not_execution=True))
    for name,values in [('remaining-unexecuted-selected.json',pending),('observed-r7-pass-selected.json',passed),('observed-r7-fail-selected.json',failed)]:
        (HERE/name).write_text(json.dumps(values,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
    target=HERE/'prefix-validation.json'
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(state=result['state'],proof_sha256=h(target.read_bytes()),outcomes=dict(counts),pending=len(pending),
        integrity=integ,guard_coverage_problems=guards,
        observer_summary={k:obs[k] for k in ['maximum_sample_gap_seconds','gaps_over_ten_seconds','minimum_ram_bytes','minimum_disk_bytes','maximum_absolute_wall_monotonic_skew_seconds']},
        awake_summary={k:aws[k] for k in ['maximum_sample_gap_seconds','gaps_over_ten_seconds']},audit_problems=problems)),flush=True)
if __name__=='__main__':main()

