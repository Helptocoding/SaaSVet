"""Report explicit composite acceptance from original and new receipts, after cleanup."""
import hashlib
import json
import sys
from pathlib import Path
from collections import Counter
from functools import cache

HERE=Path(__file__).resolve().parents[1]
REPO=HERE.parents[2]
sys.path.insert(0,str(HERE))
from composite_evidence import source_for, block_path, read_block, provenance, is_reused, validate_references

# Reporting reads a fixed, closed receipt set.  Avoid re-resolving identical
# artifacts for tables, counters and journals; validate the references again
# before publishing the calculated status snapshot.
source_for=cache(source_for)
block_path=cache(block_path)
read_block=cache(read_block)
provenance=cache(provenance)
is_reused=cache(is_reused)

def read(name):return json.loads((HERE/name).read_text(encoding='utf-8'))
def digest(data):return hashlib.sha256(data).hexdigest()
def save(name,data):
    assert not (HERE/name).exists(),name
    (HERE/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

FULL_GROUPS=['full-'+family for family in ('b8b','b8c','b8d','b8e','general')]
CONDITIONAL_PASS='PASS_BAJO_CONDICION_DE_EVIDENCIA_ENMENDADA'

def artifact_path(path):
    path=Path(path)
    try:return path.relative_to(HERE).as_posix()
    except ValueError:return path.as_posix()

def block_origin(label):
    source=provenance(label)
    return {'evidence_origin':'REFERENCED_PASS' if is_reused(label) else
            'COMPOSITE_CASE_EVIDENCE' if source.get('origin')=='COMPOSITE_CASE_EVIDENCE' else 'CURRENT_EXECUTION',
        'source_campaign':str(source['campaign']),
        'source_artifact_dir':artifact_path(source['artifactdir'])}

def optional_block_path(label,suffix):
    # A missing optional alias/result is not an artifact in the reference
    # whitelist.  Existing artifacts always pass the strict SHA-verifying API.
    assert suffix in ('.command.json','.gate.json','.results.json','.ids.jsonl','.results.passed.jsonl')
    source=Path(source_for(label))
    filename='full-general-assemble.command.json' if label=='full-general' and suffix=='.command.json' else label+suffix
    candidate=source/'blocks'/filename
    assert candidate.resolve().is_relative_to(source.resolve())
    assert not candidate.parent.is_symlink() and not candidate.parent.is_junction()
    assert not candidate.is_symlink() and not candidate.is_junction()
    if candidate.exists():return Path(block_path(label,suffix))
    return candidate

def journal_path(label):
    path=optional_block_path(label,'.ids.jsonl')
    if label=='directed' and not path.exists():
        path=optional_block_path(label,'.results.passed.jsonl')
    return path

def journal_sources(label):
    path=journal_path(label)
    if path.exists():return [path]
    if label!='full-general':return []
    return [path for path in (HERE/'referenced-case-evidence/r6/blocks/full-general.ids.jsonl',
        HERE/'referenced-case-evidence/r7/blocks/full-general-remainder.ids.jsonl',
        HERE/'blocks/full-general-remainder.ids.jsonl') if path.exists()]

def journal_entries(label):
    path=journal_path(label)
    if not path.exists():
        if label!='full-general':return []
        rows=[]
        for item in journal_sources(label):
            entries=[json.loads(line) for line in item.read_text(encoding='utf-8').splitlines() if line.strip()]
            if 'referenced-case-evidence/r7/' in item.as_posix():
                entries=[row for row in entries if row['outcome']=='PASS']
            rows.extend(entries)
        return rows
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if label=='directed' and path.name.endswith('.passed.jsonl'):
        assert all(row['status']=='ok' for row in rows)
        return [{'id':row['test_id'],'outcome':'PASS'} for row in rows]
    return rows

def main():
    validate_references()
    read('reuse-manifest.json')
    from case_resumption import validate_case_references, case_summary, retained_case_ids, remaining_case_ids
    validate_case_references()
    case_proof=case_summary()
    retained_ids=retained_case_ids();remaining_ids=remaining_case_ids()
    assert len(retained_ids)==len(set(retained_ids))==2890
    assert len(remaining_ids)==len(set(remaining_ids))==323 and not set(retained_ids)&set(remaining_ids)
    assert sorted(retained_ids+remaining_ids)==read('full-general-selected.json')
    assert case_proof['accepted_historical_evidence_limitation'] is True
    assert case_proof['historical_disk_and_monotonic_evidence_verified'] is False
    assert case_proof['retained_PASS']==2888 and case_proof['retained_SKIP']==2
    assert case_proof['historical_failed_attempts']==2
    old_r7_path=HERE/'referenced-case-evidence/r7/blocks/full-general-remainder.ids.jsonl'
    old_r7_rows=[json.loads(line) for line in old_r7_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    historical_failures=[row for row in old_r7_rows if row['outcome']=='FAIL']
    assert len(old_r7_rows)==407 and len(historical_failures)==2
    assert {row['id'] for row in historical_failures}==set(case_proof['corrected_failed_case_ids'])
    assert sum(row['outcome']=='PASS' for row in old_r7_rows)==405
    save('historical-failed-attempts.json',{'state':'PRESERVED_HISTORICAL_FAIL',
        'source':artifact_path(old_r7_path),'observations':407,'retained_PASS':405,
        'historical_FAIL':historical_failures,'included_as_accepted_PASS':False,
        'corrected_current_case_ids':case_proof['corrected_failed_case_ids'],
        'no_PASS_reruns':True})
    classification=read('final-classification.json')
    assert classification['decision'] in ('PASS','FAIL','PENDING')
    if classification['decision']=='PASS':assert classification['accepted_historical_evidence_limitation'] is True
    decision_label=CONDITIONAL_PASS if classification['decision']=='PASS' else classification['decision']
    assert read('cleanup.json')['state']=='PASS'
    native=read('native-closure.json')
    assert native['state']=='PASS' and native['host_clock_configuration_changed'] is False
    assert read('resource-observer-closure.json')['state']=='PASS'
    awake=read('awake-request/closure.json')
    assert awake['state']=='PASS_API_REQUEST_AND_RESTORATION' and awake['matches_original_thread_state']
    candidate=read('candidate.json')
    fixture_authorization=read('fixture-clock-authorization.json')
    previous_tree=fixture_authorization['source_candidate_tree']
    assert fixture_authorization['current_candidate_tree']==candidate['previous_candidate_tree']
    snapshot_equivalence=read('snapshot-equivalence.json')
    snapshot_authorization=read('snapshot-resumption-authorization.json')
    assert snapshot_equivalence['previous_candidate_tree']==candidate['previous_candidate_tree']
    assert snapshot_equivalence['candidate_tree']==candidate['candidate_tree']
    assert snapshot_authorization['user_answer']=='Sí, corregir esos snapshots y continuar sin repetir PASS'
    assert snapshot_authorization['no_PASS_reruns'] is True and snapshot_authorization['old_FAILs_preserved'] is True
    assert snapshot_equivalence['only_two_expected_literal_lists_change_ast'] is True
    assert snapshot_equivalence['assertions_other_AST_unchanged'] is True
    assert snapshot_equivalence['all_other_3331_blobs_identical'] is True
    assert fixture_authorization['all_other_3331_blobs_identical'] is True
    assert fixture_authorization['body_AST_identical'] is True
    assert fixture_authorization['product_runtime_locks_assertions_changed'] is False
    assert fixture_authorization['complete_general_rerun_required'] is True
    equivalence=read('reuse-validation.json')['inputs']['fixture_clock_equivalence']
    prior=read('prior-evidence-before.json')
    drift=[n for n,h in prior.items() if not (REPO/n).is_file() or digest((REPO/n).read_bytes())!=h]
    original=read('checkout-before.json')['unrelated']
    current={n:{'exists':(REPO/n).exists(),'sha256':digest((REPO/n).read_bytes()) if (REPO/n).exists() else None} for n in original}
    assert not drift and current==original
    save('preservation-of-prior-work.json',{'prior_campaign_files_checked':len(prior),
        'prior_campaign_mismatches':drift,'unrelated_unchanged':True,'unrelated':current})
    integrity=[];integrity_mismatches={}
    for pattern in ('integrity-*.json','dependency-check-*.json','seal-check-*.json'):
        for file in HERE.glob(pattern):
            if file.name=='integrity-summary.json':continue
            receipt=read(file.name)
            if receipt['mismatches']:integrity_mismatches[file.name]=receipt['mismatches']
            integrity.append(file.name)
    if integrity_mismatches:assert classification['decision']=='PENDING'
    save('integrity-summary.json',{'state':'PENDING' if integrity_mismatches else 'PASS',
        'receipts':integrity,'mismatches':integrity_mismatches})
    statuses={}
    partitioned=(HERE/'full-partition.json').exists() or any(optional_block_path(label,'.command.json').exists() for label in FULL_GROUPS)
    suite_observations=[];current_suite_observations=[];referenced_suite_observations=[]
    partial_journals={};partial_observations=[];current_partial_observations=[]
    labels=['directed','django-check','migration-drift','migrate','billing-schema','b0','b3','b4','b5',*FULL_GROUPS,'full',
        'frontend-build','frontend-test','frontend-lint','frontend-smoke-urls','security','pip-audit','pnpm-audit',
        'profile-base','profile-blocked_llm','profile-meta_slow','profile-duplicate','profile-saturation']
    for label in labels:
        cmd=optional_block_path(label,'.command.json');gate=optional_block_path(label,'.gate.json')
        if label=='full' and partitioned:
            aggregate=HERE/'blocks/full.aggregate.json'
            result=HERE/'blocks/full.results.json'
            executed=[name for name in FULL_GROUPS if statuses[name]['source_formal_runs']]
            statuses[label]={'state':'INCOMPLETE' if executed else 'NOT_EXECUTED',
                'formal_runs':0,'source_formal_runs':0,'logical_aggregate':True,'groups':FULL_GROUPS,
                'evidence_origin':'COMPOSITE_AGGREGATE','source_campaign':HERE.name,
                'source_artifact_dir':'.',
                'seconds_scope':'Known group durations plus new remainder; historical r6/r7 prefix durations unavailable',
                'seconds':sum(statuses[name].get('seconds',0) for name in FULL_GROUPS)}
            expected=read('full-selected.json')
            entries=[row for name in FULL_GROUPS for row in journal_entries(name)]
            if aggregate.exists() and result.exists() and gate.exists():
                a=read('blocks/full.aggregate.json');r=read('blocks/full.results.json')
                passed=read('blocks/full.gate.json')['state']=='PASS' and a['state']=='PASS'
                passed=passed and all(statuses[name]['state']=='PASS' for name in FULL_GROUPS)
                passed=passed and sorted(r['test_ids'])==expected and r['tests']==len(expected)
                assert not passed or len(r['test_ids'])==len(set(r['test_ids']))
                if passed:
                    statuses[label].update(state='PASS',exit_code=0,tests=r['tests'],
                        acceptance_label=CONDITIONAL_PASS,accepted_historical_evidence_limitation=True,
                        outcomes={k:r.get(k) for k in ('failures','errors','skips','xfail','xpass')},
                        failed_ids=r.get('failed_ids',[]),aggregate_receipt='blocks/full.aggregate.json')
            if statuses[label]['state']!='PASS' and executed:
                observed={row['id'] for row in entries}
                statuses[label]['partial_journal']={'observations':len(entries),'unique_ids':len(observed),
                    'outcomes':dict(Counter(row['outcome'] for row in entries)),
                    'skips':[row for row in entries if row['outcome']=='SKIP'],
                    'selected_ids':len(expected),'missing_ids':sorted(set(expected)-observed),
                    'complete_suite_receipt':False,'accepted_as_complete_gate':False,
                    'sources':[artifact_path(path) for name in FULL_GROUPS for path in journal_sources(name)]}
            continue
        if cmd.exists():
            c=read_block(label,'.command.json');assert c['state']=='COMPLETED'
            statuses[label]={'state':read_block(label,'.gate.json')['state'] if gate.exists() else 'INCOMPLETE',
                'exit_code':c['exit_code'],'seconds':c['seconds'],
                'formal_runs':0 if is_reused(label) else 1,'source_formal_runs':1,
                'executed_candidate_tree':c['candidate_sha'],
                'accepted_candidate_tree':candidate['candidate_tree'],
                'invalidating_incident':c['invalidating_incident'],
                'command_receipt':artifact_path(cmd),**block_origin(label)}
            if label=='full-general':
                assert c['label']=='full-general-assemble'
                statuses[label].update(formal_runs=0,assembler_formal_runs=1,
                    command_origin='CURRENT_ASSEMBLER',exit_scope='aggregate',
                    original_r6_exit_code=None,original_r6_exit_status='UNKNOWN',
                    original_r7_exit_code=None,original_r7_exit_status='UNKNOWN',
                    retained_case_ids=2890,retained_PASS=2888,retained_SKIP=2,
                    historical_failed_attempts=2,retained_sources=case_proof['retained_sources'],
                    new_selected_ids=323,accepted_historical_evidence_limitation=True,
                    historical_disk_and_monotonic_evidence_verified=False,
                    case_manifest='case-resumption-manifest.json')
            if c['invalidating_incident']:statuses[label]['state']='PENDING_ENVIRONMENT_INTERRUPTION'
            if label=='full-general' and statuses[label]['state']=='PASS':statuses[label]['acceptance_label']=CONDITIONAL_PASS
            result=optional_block_path(label,'.results.json')
            complete_receipt=False
            if result.exists():
                r=read_block(label,'.results.json');statuses[label]['tests']=r['tests']
                if label=='full-general':
                    assert r['exit_scope']=='aggregate' and r['accepted_historical_evidence_limitation'] is True
                    statuses[label].update(assembler_seconds=c['seconds'],seconds=r['seconds'],
                        seconds_scope=r['seconds_scope'])
                statuses[label]['outcomes']={k:r.get(k) for k in ('failures','errors','skips','xfail','xpass')}
                statuses[label]['failed_ids']=r.get('failed_ids',[])
                expected=read(label+'-selected.json')
                complete_receipt=sorted(r['test_ids'])==expected and r['tests']==len(expected)
                if complete_receipt:
                    suite_observations+=r['test_ids']
                    if label=='full-general':current_suite_observations+=remaining_ids
                    elif is_reused(label):referenced_suite_observations+=r['test_ids']
                    else:current_suite_observations+=r['test_ids']
            journal=journal_path(label)
            selected=HERE/(label+'-selected.json')
            if not complete_receipt and selected.exists():
                entries=journal_entries(label)
                partial_observations.extend(row['id'] for row in entries)
                current_partial_observations.extend(row['id'] for row in entries
                    if label!='full-general' or row['id'] in set(remaining_ids))
                partial_journals[label]={'path':artifact_path(journal) if journal.exists() else None,
                    'journal_present':journal.exists(),
                    'journal_scope':'PASS_ONLY' if journal.name.endswith('.passed.jsonl') else 'ALL_RECORDED_OUTCOMES',
                    'observations':len(entries),
                    'outcomes':dict(Counter(row['outcome'] for row in entries)),
                    'skips':[row for row in entries if row['outcome']=='SKIP'],
                    'unique_ids':len({row['id'] for row in entries}),
                    'selected_ids':len(read(label+'-selected.json')),
                    'missing_ids':sorted(set(read(label+'-selected.json'))-{row['id'] for row in entries}),
                    'complete_suite_receipt':False,'accepted_as_complete_gate':False}
                statuses[label]['partial_journal']=partial_journals[label]
        else:
            statuses[label]={'state':'NOT_EXECUTED','formal_runs':0,'source_formal_runs':0,**block_origin(label)}
            if label=='full-general':
                entries=journal_entries(label);observed={row['id'] for row in entries}
                selected=read('full-general-selected.json')
                partial_observations.extend(row['id'] for row in entries)
                current_partial_observations.extend(row['id'] for row in entries if row['id'] in set(remaining_ids))
                statuses[label].update(state='INCOMPLETE',source_formal_runs=1,
                    accepted_historical_evidence_limitation=True,
                    historical_disk_and_monotonic_evidence_verified=False,
                    retained_case_ids=2890,new_selected_ids=323,historical_failed_attempts=2,
                    partial_journal={'observations':len(entries),'unique_ids':len(observed),
                        'outcomes':dict(Counter(row['outcome'] for row in entries)),
                        'selected_ids':len(selected),'missing_ids':sorted(set(selected)-observed),
                        'complete_suite_receipt':False,'accepted_as_complete_gate':False,
                        'sources':[artifact_path(path) for path in journal_sources(label)]})
                partial_journals[label]=statuses[label]['partial_journal']
    references={label:{**block_origin(label),'command_receipt':statuses[label].get('command_receipt'),
        'executed_candidate_tree':statuses[label].get('executed_candidate_tree'),
        'accepted_candidate_tree':candidate['candidate_tree']}
        for label in labels if is_reused(label)}
    assert len(references)==13
    assert all(row['executed_candidate_tree']==previous_tree for row in references.values())
    assert all(statuses[label]['state']=='PASS' and statuses[label]['formal_runs']==0 for label in references)
    validate_references()
    validate_case_references()
    save('composite-evidence-provenance.json',{'state':'PASS','evidence_mode':'COMPOSITE_ACCEPTANCE',
        'continuous_single_campaign':False,'manifest':'reuse-manifest.json',
        'manifest_sha256':digest((HERE/'reuse-manifest.json').read_bytes()),
        'referenced_pass_blocks':references,'reference_count':len(references),
        'accepted_candidate_tree':candidate['candidate_tree'],'previous_candidate_tree':previous_tree,
        'acceptance_label':decision_label,'accepted_historical_evidence_limitation':True,
        'case_resumption_manifest':'case-resumption-manifest.json','case_resumption_summary':case_proof,
        'historical_disk_and_monotonic_evidence_verified':False,
        'fixture_clock_authorization':'fixture-clock-authorization.json',
        'fixture_clock_equivalence':equivalence,
        'snapshot_authorization':'snapshot-resumption-authorization.json',
        'snapshot_equivalence':snapshot_equivalence,
        'historical_failed_attempts':'historical-failed-attempts.json',
        'historical_receipts_copied_as_current_execution':False,
        'preservation_copies_identified_by_manifest':True})
    save('block-status.json',statuses)
    save('execution-summary.json',{'candidate_tree':candidate['candidate_tree'],
        'acceptance_label':decision_label,'accepted_historical_evidence_limitation':True,
        'frontend_results_reused':False,'prepared_frontend_installation_reused':True,
        'runtime_reference':'prepared-runtime-references.json',
        'historical_disk_and_monotonic_evidence_verified':False,
        'retained_case_observations':2890,'retained_case_PASS':2888,'retained_case_SKIP':2,
        'retained_case_sources':case_proof['retained_sources'],
        'historical_failed_attempts':2,'historical_failed_attempt_receipt':'historical-failed-attempts.json',
        'new_remainder_selected_ids':323,'previous_FAILED_cases_corrected_and_selected':2,
        'new_missing_selected_ids':321,'previous_PASS_cases_rerun':0,
        'new_remainder_command':'blocks/full-general-remainder.command.json',
        'new_remainder_command_invocations':int((HERE/'blocks/full-general-remainder.command.json').exists()),
        'new_remainder_result_tests':read('blocks/full-general-remainder.results.json')['tests']
            if (HERE/'blocks/full-general-remainder.results.json').exists() else None,
        'general_assembler_command':'blocks/full-general-assemble.command.json',
        'general_assembler_counted_as_application_test_execution':False,
        'historical_r6_general_exit_code':None,'historical_r6_general_exit_status':'UNKNOWN',
        'historical_r7_general_exit_code':None,'historical_r7_general_exit_status':'UNKNOWN',
        'referenced_blocks_executed_candidate_tree':previous_tree,
        'new_executions_candidate_tree':candidate['candidate_tree'],
        'authorized_cross_candidate_exceptions':['fixture-clock-authorization.json','snapshot-resumption-authorization.json'],
        'unchanged_other_candidate_blobs_between_68_and_current':3331,
        'unchanged_other_candidate_blobs_between_original_and_current':3330,
        'evidence_mode':'COMPOSITE_ACCEPTANCE','continuous_single_campaign':False,
        'formal_controller_invocations':int((HERE/'invocation-formal.json').exists()),
        'formal_command_blocks':len(list((HERE/'blocks').glob('*.command.json'))),
        'referenced_pass_blocks':len(references),'referenced_source_campaigns':sorted({s['source_campaign'] for s in references.values()}),
        'formal_reruns':0,'full_execution_sources':FULL_GROUPS if partitioned else ['full'],
        'full_group_provenance':{label:{**block_origin(label),
            'executed_candidate_tree':statuses[label].get('executed_candidate_tree'),
            'accepted_candidate_tree':candidate['candidate_tree'],
            **({'case_provenance':provenance(label)} if label=='full-general' else {})} for label in FULL_GROUPS},
        'logical_full_aggregate_counted_as_additional_execution':False,
        'complete_receipt_totals_scope':'Accepted composite evidence, including referenced PASS blocks',
        'backend_id_observations_in_complete_receipts':len(suite_observations),
        'backend_unique_ids_in_complete_receipts':len(set(suite_observations)),
        'duplicate_observations_in_complete_receipts':len(suite_observations)-len(set(suite_observations)),
        'backend_id_observations_in_current_complete_receipts':len(current_suite_observations),
        'backend_unique_ids_in_current_complete_receipts':len(set(current_suite_observations)),
        'backend_id_observations_in_referenced_complete_receipts':len(referenced_suite_observations),
        'backend_unique_ids_in_referenced_complete_receipts':len(set(referenced_suite_observations)),
        'backend_id_observations_in_current_receipts_including_partial_journals':len(current_suite_observations)+len(current_partial_observations),
        'backend_unique_observed_ids_in_current_receipts_including_partial_journals':len(set(current_suite_observations+current_partial_observations)),
        'backend_id_observations_including_partial_journals':len(suite_observations)+len(partial_observations),
        'backend_unique_observed_ids_including_partial_journals':len(set(suite_observations+partial_observations)),
        'duplicate_observations_including_partial_journals':len(suite_observations)+len(partial_observations)-len(set(suite_observations+partial_observations)),
        'incomplete_suite_journals':partial_journals,
        'focused_development_verification_separate':read('prior-focused-verification.json'),
        'profile_variants_executed':sum(statuses['profile-'+s]['formal_runs'] for s in ['base','blocked_llm','meta_slow','duplicate','saturation']),
        'historical_pass_evidence_referenced':bool(references),
        'historical_receipts_copied_as_current_execution':False})
    monitors={}
    for label in [*statuses,'full-general-remainder']:
        monitor_label='full-general-assemble' if label=='full-general' else label
        file=Path(source_for(label))/('monitor-'+monitor_label+'.json')
        if not file.exists():continue
        rows=json.loads(file.read_text(encoding='utf-8'))
        if rows:monitors[label]={'samples':len(rows),
            'source':artifact_path(file),**block_origin(label),
            'command_label':monitor_label,
            'monitor_scope':'ASSEMBLER_ONLY' if label=='full-general' else 'CURRENT_OR_REFERENCED_COMMAND',
            'min_host_bytes':min(r['host']['physical_available'] for r in rows),
            'guest_metrics':'NOT_APPLICABLE_WINDOWS_NATIVE',
            'min_disk_bytes':min(r['host']['disk_available'] for r in rows),
            'max_clock_skew_seconds':max(abs(r['wall_minus_monotonic_seconds']) for r in rows)}
    save('monitor-summary.json',monitors)
    complete=classification['decision']=='PASS'
    if complete:assert read('technical-completion.json')['state']=='PASS'
    directed=statuses['directed']['state']=='PASS'
    scenario_names=['base','blocked_llm','meta_slow','duplicate','saturation']
    profiles={s:read('blocks/profile-'+s+'.json') for s in scenario_names if (HERE/('blocks/profile-'+s+'.json')).exists()}
    temporal_states={s:statuses['profile-'+s]['state'] for s in scenario_names}
    all_temporal=all(s=='PASS' for s in temporal_states.values())
    R={f'R{i:02}':(CONDITIONAL_PASS if complete else 'PENDING_INTEGRAL') for i in range(1,16)}
    if directed:
        for i in [2,3,4,5,10,12,13]:R[f'R{i:02}']='PASS_DIRECTED_SCOPE; integral decision '+classification['decision']
    R['R08']='DECISION_AND_LIMITS_DOCUMENTED'
    blocking=['directed','django-check','migration-drift','migrate','billing-schema','b0','b3','b4','b5',
        'full','frontend-build','frontend-test','frontend-smoke-urls','security']
    if complete:
        assert all(statuses[n]['state']=='PASS' for n in blocking) and all_temporal
        current_general=journal_entries('full-general')
        for corrected_id in case_proof['corrected_failed_case_ids']:
            accepted=[row for row in current_general if row['id']==corrected_id]
            assert len(accepted)==1 and accepted[0]['outcome']=='PASS'
        assert read('blocks/full-general-remainder.results.json')['tests']==323
    R['R06']='PASS_LOCAL_BLOCKING_CHECKS; remote CI and real promotion separate' if all(statuses[n]['state']=='PASS' for n in blocking) else 'PENDING_LOCAL_BLOCKING_CHECKS'
    R['R07']='PASS_FIXED_PROFILE' if all_temporal else 'FAIL_APPLICABLE_PROFILE_GATE' if 'FAIL' in temporal_states.values() else 'PENDING_PROFILE_INCOMPLETE'
    R['R09']='PASS_ALL_FIVE_TEMPORAL_RECEIPTS' if len(profiles)==5 and all(statuses['profile-'+s].get('invalidating_incident') is None for s in scenario_names) else 'PENDING_TEMPORAL_COVERAGE; see profile-results-index.json'
    R['R11']='PASS_SCHEMA_AND_DIRECTED_COST_SCOPE' if directed and all(statuses[n]['state']=='PASS' for n in ['migration-drift','migrate','billing-schema']) else 'PENDING_SCHEMA_AND_COST_SCOPE'
    R['R14']='EXACT_CORRECTED_TREE_AND_METHOD_DOCUMENTED'
    R['R15']='DECISION_AND_RECOVERY_DOCUMENTED; operational privacy separate'
    I={f'I{i:02}':(CONDITIONAL_PASS if complete else 'PASS_DIRECTED_SCOPE; integral decision '+classification['decision'] if directed else 'PENDING_NO_COMPLETE_DIRECTED_GATE') for i in range(1,15)}
    if not all_temporal:
        I['I08']=('PASS_DIRECTED_SCOPE; ' if directed else '')+'PENDING_FULL_TEMPORAL_SAFETY_COVERAGE'
    if temporal_states['meta_slow']!='PASS':
        I['I11']=('PASS_DIRECTED_SCOPE; ' if directed else '')+'PENDING_META_SLOW_TEMPORAL_COVERAGE'
    save('candidate-decision.json',{'candidate_tree':candidate['candidate_tree'],'base_commit':candidate['base_commit'],
        'acceptance_label':decision_label,'accepted_historical_evidence_limitation':True,
        'historical_disk_and_monotonic_evidence_verified':False,
        'case_resumption_manifest':'case-resumption-manifest.json','case_resumption_summary':case_proof,
        'previous_candidate_tree':previous_tree,
        'referenced_blocks_executed_on_previous_candidate':True,
        'cross_candidate_exception_authorizations':['fixture-clock-authorization.json','snapshot-resumption-authorization.json'],
        'cross_candidate_equivalence_proof':'reuse-validation.json',
        'evidence_mode':'COMPOSITE_ACCEPTANCE','continuous_single_campaign':False,
        'reference_count':len(references),'reference_manifest':'reuse-manifest.json',
        'decision':classification['decision'],'cause':classification['cause'],'R01_R15':R,'I01_I14':I,
        'temporal_variant_states':temporal_states,
        'activation':'PENDING_ACTIVATION_REQUIREMENTS','R1-04':'PENDING_WITH_ACCEPTED_LIMITATION; zero new physical attempts',
        'E_P_UX':'SEPARATE_UNCHANGED_SCOPES','operational_requirements':{
            'R06_real_promotion_eval':'PENDING_SEPARATE','R13_release_readiness':'PENDING_SEPARATE','R15_P_A_P_B':'PENDING_SEPARATE'},
        'production_runtime_changed':False,'locks_changed':False,'test_changes':candidate['changed_paths'],
        'commits_created':0,'pushes_performed':0,'production_activation_or_deployment':False})
    table_rows=[]
    for label,s in statuses.items():
        scope=('PASS referenciado' if s['evidence_origin']=='REFERENCED_PASS' else
            'Agregado por casos; ensamblador actual' if s['evidence_origin']=='COMPOSITE_CASE_EVIDENCE' else
            'Agregado compuesto' if s['evidence_origin']=='COMPOSITE_AGGREGATE' else
            'Nueva ejecución' if s['formal_runs'] else 'Sin ejecución nueva')
        receipt=s.get('command_receipt',s.get('aggregate_receipt'))
        origin='['+s['source_campaign']+']('+receipt+')' if receipt else s['source_campaign']
        count=str(s.get('tests',str(s['partial_journal']['observations'])+'/'+str(s['partial_journal']['selected_ids'])+' parciales' if 'partial_journal' in s else '—'))
        table_rows.append('| '+label+' | '+s.get('acceptance_label',s['state'])+' | '+count+' | '+str(s.get('exit_code','—'))+' | '+scope+' | '+origin+' |')
    rows='\n'.join(table_rows)
    metrics=['window_utc','inbound_count','outbound_count','healthy_claim','safety_dispatch','outbox_dispatch',
        'max_active_per_org_observed','max_pending_inbound_observed','max_outbound_attempts','generator_events',
        'turnwork_status','outbound_status','llm_calls','llm_call_count','provider_calls']
    save('profile-results-index.json',{'variants':{s:{'path':'blocks/profile-'+s+'.json','technical_pass':r.get('technical_pass'),'gates':r.get('gates'),
        'measurements':{k:r[k] for k in metrics if k in r}} for s,r in profiles.items()},
        'not_executed':[s for s in scenario_names if statuses['profile-'+s]['state']=='NOT_EXECUTED'],
        'without_complete_receipt':[s for s in scenario_names if s not in profiles],
        'historical_metrics_transferred':False})
    profile_rows=[]
    for s in scenario_names:
        r=profiles.get(s,{})
        for metric in ['healthy_claim','safety_dispatch','outbox_dispatch']:
            m=r.get(metric,{})
            profile_rows.append('| '+s+' | '+metric+' | '+str(m.get('count','—'))+' | '+str(m.get('missing','no field' if m else '—'))+' | '+str(m.get('p95_seconds','—'))+' | '+str(m.get('max_seconds','—'))+' |')
    profile_table='\n'.join(profile_rows)
    integrity_statement='PASS en todas las comparaciones registradas' if not integrity_mismatches else 'PENDING: diferencias registradas en integrity-summary.json'
    focused=read('prior-focused-verification.json')['receipt']
    focused_statement=f"{focused['PASS']} PASS, {focused['FAIL']} fallos, {focused['ERROR']} errores y {len(focused['SKIP'])} skips identificados, de {focused['tests']} IDs"
    current_skips={row['id']:row for label in (FULL_GROUPS if partitioned else ['full'])
        for row in statuses[label].get('outcomes',{}).get('skips',[]) or []}
    current_skips.update({row['id']:row for label in (FULL_GROUPS if partitioned else ['full'])
        for row in journal_entries(label) if row['outcome']=='SKIP'})
    has_full_receipts=any(optional_block_path(label,'.results.json').exists() or journal_entries(label)
        for label in (FULL_GROUPS if partitioned else ['full']))
    if has_full_receipts:
        skip_statement=f"Los recibos aceptados de full, referenciados y nuevos, contienen {len(current_skips)} skips observados; sus IDs y motivos figuran en [block-status.json](block-status.json). Si full está incompleto, este conteo es parcial. Un skip no cubre un requisito pendiente."
    else:
        skip_statement="No hay recibos por ID de full disponibles para este cierre compuesto; no se infiere que hubo cero skips."
    if partitioned:
        partition=read('full-partition.json') if (HERE/'full-partition.json').exists() else None
        group_description=', '.join(row['label']+': '+str(row['count'])+' IDs en `'+row['database']+'`' for row in partition['groups']) if partition else 'partición sin recibo completo de preparación'
        orchestration_statement=f"La partición conserva cinco grupos nativos del mismo inventario: {group_description}. Se referencian los grupos completos aprobados y se ejecutan completos los pendientes. La selección y los prefijos de los workers se comprueban antes de ejecutar; las comprobaciones y la concurrencia interna de las pruebas se conservan. El bloque lógico full queda **{statuses['full']['state']}** y solo aprueba con los cinco grupos y su agregado completos, 3331 IDs sin duplicados ni omisiones. [Partición](full-partition.json)."
    else:
        orchestration_statement='No existe un recibo actual de preparación de la partición. Los estados de ejecución se conservan en la tabla.'
    resource_statement=f"Los monitores disponibles contienen muestras de {len(monitors)} comandos originales y nuevos; su procedencia se identifica por bloque."
    if monitors:
        minimum=min(row['min_host_bytes'] for row in monitors.values())/1024**3
        resource_statement+=f" El mínimo Windows registrado en ellos fue {minimum:.3f} GiB; las incidencias se conservan por comando."
    if (HERE/'resource-observation-validation.json').exists():
        resource_statement+=' [Validación de muestras y sus intervalos](resource-observation-validation.json).'
    preparation_only=not (HERE/'invocation-formal.json').exists()
    preparation_statement=('Esta reanudación no invocó el controlador formal. '
        '**Se ejecutaron cero pruebas nuevas de aplicación**; los PASS referenciados conservan '
        'su origen y los bloques pendientes no se consideran ejecutados. '
        'La preparación no sustituye la aceptación integral.\n\n') if preparation_only else ''
    full_journal_statement=('Los journals presentes de grupos conservan las ejecuciones originales. '
        'El agregado full reúne sus recibos; no ejecuta pruebas adicionales ni se cuenta de nuevo '
        'en los totales backend.') if any(journal_path(label).exists() for label in FULL_GROUPS) else 'No se generaron journals de ejecución de full en este intento.'
    report=f'''# B9: aceptación compuesta del árbol corregido, Windows nativo r8 — {decision_label}

**Decisión técnica compuesta: {decision_label}.** {classification['cause']}

El campo de máquina `decision` conserva `{classification['decision']}`. Un PASS
de este expediente significa exclusivamente **{CONDITIONAL_PASS}**, conforme a
la limitación histórica aceptada expresamente por el usuario: «Sí, continuar con
esa limitación». **La condición original de monitorización histórica de disco y
desviación de reloj monotónico no está acreditada para el prefijo r6.** No se
reconstruyen muestras inexistentes ni se declara que esa condición original pasó.
[Autorización](case-resumption-authorization.json) ·
[Manifiesto de casos](case-resumption-manifest.json) ·
[Validación y limitación](case-resumption-validation.json).

Se conservan **2483 PASS y 2 SKIP** del journal parcial r6 y **405 PASS** de r7.
Se seleccionan exactamente **321 casos sin resultado y los 2 snapshots corregidos**;
ningún PASS anterior se repite. Los **2 FAIL originales de r7** permanecen visibles
con sus trazas en [historical-failed-attempts.json](historical-failed-attempts.json)
y en su journal íntegro. Las invocaciones r6/r7 permanecen interrumpidas,
con exits desconocidos y sin recibos completos.
El comando de `full-general` mostrado abajo es el **ensamblador actual**:
su exit pertenece al agregado (`exit_scope=aggregate`), nunca a las ejecuciones r6/r7.
Los tests nuevos pertenecen a `full-general-remainder`; la unión lógica debe
contener exactamente los 3213 IDs, sin duplicados u omisiones.

Este cierre reúne ejecuciones del candidato actual, casos completos del journal
interrumpidos r6/r7 y bloques anteriores no afectados por las correcciones de tests
autorizada; **no es una corrida continua**.
La reanudación por bloques y la excepción entre árboles fueron autorizadas por el usuario.
Se conservan {len(references)} bloques completos en PASS mediante referencias
verificadas a sus recibos originales, sin volver a ejecutarlos. Los bloques
pendientes se ejecutan completos con sus pruebas, aserciones, cargas y umbrales.
[Manifiesto de reutilización](reuse-manifest.json) ·
[Procedencia verificada](composite-evidence-provenance.json).

{preparation_statement}\
Base `{candidate['base_commit']}`; árbol evaluado **`{candidate['candidate_tree']}`**.
Es un árbol Git reproducible con el [diff de cuatro archivos de tests](correction.diff),
sin commit nuevo. Runtime productivo, locks, cargas, tiempos y gates originales
se conservaron. El resultado corresponde a ese árbol, no se atribuye al commit
base sin las correcciones ni sustituye los resultados históricos de r9.

Los 13 bloques referenciados se ejecutaron sobre el árbol anterior
**`{previous_tree}`**; no se atribuyen al árbol nuevo como ejecuciones nuevas.
La primera diferencia adicional autorizada fue
`backend/apps/notifications/tests/test_notifications.py`: un reloj UTC fijo al
mediodía para `test_upcoming_window`, con su cuerpo y aserciones intactos.
Los otros **3331 blobs** coincidían entre el árbol original y el intermedio. La prueba de equivalencia
verifica imports, decorador y parámetro del mock permitidos, selección y fuentes
de los bloques no afectados. [Autorización](fixture-clock-authorization.json) ·
[Prueba de equivalencia](reuse-validation.json).

La segunda excepción autorizada modifica únicamente las dos listas esperadas de
`test_contracts.py`: los 17 campos tipados de `ToolOutcome` aprobados en B2
(`ok` es una propiedad derivada) y los cuatro campos de binding de B6 en
`ConversationGoal`. Se conserva la igualdad exhaustiva y exacta. Los IDs,
imports, hooks, aserciones y todo el resto del AST son idénticos. Entre el árbol
intermedio y el actual coinciden **3331 blobs**; desde el árbol original,
**3330 blobs** son idénticos y los otros dos se validan mediante sus transformaciones
exactas autorizadas. [Autorización](snapshot-resumption-authorization.json) ·
[Equivalencia](snapshot-equivalence.json) · [Parche](snapshot-correction.diff).

El grupo `full-general`, que contiene ese fixture, se completa por la unión
autorizada de 2485 casos r6 y 405 PASS r7 sobre el árbol intermedio con los 323 seleccionados actuales. El ERROR
y la interrupción de vigilia de r5 permanecen documentados en su expediente
original y no aportan casos aprobados a esta unión.

## Correcciones y verificación

F2 era un componente legacy explícito: sus argumentos del stub no aportaban
provenance B6. Su helper de turnos ahora evita crear accidentalmente un binding
en fixtures sin versión; los bindings existentes conservan el resolver real.
Se mantienen las aserciones de autorización/confirmación, vencimiento, carrera,
efecto único y ausencia de mutaciones indebidas. La oferta tras cancelar se
comprueba por su contenido y ausencia de una reserva nueva.

La prueba de precio exige servicio, precio y moneda del catálogo validado y
rechaza el precio/moneda contradictorios del modelo. No se acepta prosa sensible
no respaldada. No se cambió código productivo.

La tercera corrección fija únicamente `django.utils.timezone.now` durante
`test_upcoming_window`, con restauración automática al terminar el método.
Evita que el intervalo relativo de +5 horas y duración de 30 minutos cruce
medianoche en los campos horarios legacy del fixture. Se conservan los offsets,
la validación `appointment_end_after_start` y las aserciones de la respuesta;
no se modifica el reloj del sistema, PostgreSQL ni el runtime productivo.

Verificación enfocada de la campaña anterior, sin repetición actual:
**{focused_statement}**. Esta referencia no sustituye los recibos actuales
ni se transfiere a sus gates integrales.
[Referencia conservada](prior-focused-verification.json).

Los dos snapshots antes fallidos solo se aceptan si sus resultados nuevos son PASS; los FAIL históricos se conservan. Los resultados aceptados de los casos corregidos son los registrados por ID
en los recibos originales identificados y en los nuevos. {skip_statement}

## Bloques y procedencia

| Bloque | Estado | IDs | Exit | Evidencia | Origen |
|---|---|---:|---:|---|---|
{rows}

Los recibos referenciados se conservan byte por byte bajo `referenced-evidence/`,
con ruta original y SHA-256 en el manifiesto; son copias de preservación
identificadas, sin presentarlas como ejecuciones de esta reanudación.
Los prefijos de casos r6/r7 se conservan aparte bajo `referenced-case-evidence/r6/` y `referenced-case-evidence/r7/`,
con su propio manifiesto y la limitación histórica aceptada. Sus 2 SKIP siguen
siendo SKIP identificados; no se transforman en PASS ni cubren un requisito crítico.
La equivalencia de reutilización cubre el backend, Python y PostgreSQL.
Los bloques referenciados aportan **369 IDs completos**, incluidos **118 IDs**
de los cuatro grupos completos de full, con la excepción de fixture indicada
entre el árbol anterior y el actual. Esos 13 bloques conservan su identidad original.
Los gates del frontend requieren ejecuciones nuevas, según los estados de la
tabla. Se conserva la instalación preparada r6 verificada en
`prepared-runtime-references.json`; no se presenta como una reinstalación ni se
reutilizan resultados frontend. No se afirma identidad total de los metadatos
pnpm de las antiguas campañas referenciadas.

Cada bloque pendiente/variante formal se ejecutó como máximo una vez en esta
reanudación. Se distinguen {len(current_suite_observations)} observaciones backend
nuevas completas, {len(referenced_suite_observations)} de bloques completos
referenciados y 2890 casos conservados (2485 r6 y 405 PASS r7) bajo la condición aceptada. Los solapes
entre corpus, runners y full están deduplicados en
[execution-summary.json](execution-summary.json), que separa IDs nuevos y evidencia
compuesta aceptada. Los ensambladores `full-general` y full son metadatos;
no añaden ejecuciones de tests ni IDs. El primer comando físico nuevo del corpus
general es [full-general-remainder](blocks/full-general-remainder.command.json).
Los skips/advisories conservan su aplicabilidad; no cubren requisitos críticos.
La orquestación local usa suites secuenciales, preservando los procesos internos
de los tests. No se afirma ejecución de CI remoto.

Los journals incompletos y sus IDs faltantes figuran en el resumen. Sus
observaciones no sustituyen un recibo completo ni acreditan un gate aprobado.

Los [recibos PROFILE](profile-results-index.json) conservan denominadores,
faltantes, latencias, máximos, colas, errores y gates de cada variante. No se
promedian percentiles entre organizaciones ni se transfieren métricas históricas.
Cuando una variante está NOT_EXECUTED, no existe evidencia temporal actual de ella.

| Variante | Frontera | Muestras | Faltantes | p95 s | Máximo s |
|---|---|---:|---:|---:|---:|
{profile_table}

`no field` conserva la ausencia del campo en el recibo; no se interpreta como
cero faltantes. Los gates, errores, estados durables y máximos de cola se
publican en el índice; las muestras originales permanecen en cada recibo.

## Orquestación de la suite completa

{orchestration_statement}

{full_journal_statement} Un grupo nuevo incompleto deja los bloques pendientes
posteriores NOT_EXECUTED conforme a la parada de esta reanudación; conserva
la evidencia original completa de los bloques referenciados.

## Conservación y cierre

Fuentes del árbol, dependencias y evaluador de esta reanudación:
**{integrity_statement}**. La evidencia reutilizada se valida contra su
manifiesto, fuentes originales y equivalencia de backend antes del reporte,
incluidas las dos excepciones autorizadas de reloj de fixture y listas esperadas de snapshots entre árboles.
La validación del prefijo r6 no acredita retrospectivamente el guard de disco
ni la desviación de reloj monotónico ausentes; esa limitación se acepta y publica. El monitor durable r7 y sus comprobaciones disponibles se preservan sin inventar un cierre del proceso interrumpido.
{resource_statement}
Los [monitores por bloque](monitor-summary.json) conservan mínimos
de recursos y desviación de reloj de los comandos que sí tienen monitores.
El monitor del ensamblador no se atribuye a los casos históricos. Los segmentos
nuevos conservan reservas de 2 GiB de RAM, 1 GiB de disco y guard de reloj de 1 s;
no se afirma cobertura completa de esas evidencias para el intervalo histórico r6.

Cleanup nativo, cierre del observador y liberación de la solicitud propia de
actividad: **PASS**. [Cierre nativo](native-closure.json) acredita que no se
cambió la configuración del reloj del host. W32Time y políticas globales de
energía/pantalla intactos. Se verificaron **{len(prior)} archivos históricos** y
los cambios ajenos sin diferencias. [Preservación](preservation-of-prior-work.json).
La liberación y restauración API acreditadas corresponden a los auxiliares
actuales. Los auxiliares r6/r7 terminados por reinicio no tienen restauración API
observada; no se les atribuye la restauración ni el exit de los auxiliares nuevos.

[Matriz R01–R15/I01–I14](candidate-decision.json), con activación
**PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado, E/P/UX y requisitos
operativos/privacidad separados. Sin commits, push, despliegue ni activación.

[Recuperación y selección de evidencia](README.md). La aprobación técnica, si
corresponde, se limita al árbol y contrato fijo evaluados; no acredita capacidad
comercial, carga máxima, estabilidad de cola o fairness fuerte.
'''
    if not profiles:
        start=report.index('Los [recibos PROFILE]')
        end=report.index('## Orquestación de la suite completa',start)
        profile_states=', '.join(s+': '+temporal_states[s] for s in scenario_names)
        report=report[:start]+f'''No hay recibos PROFILE completos en esta campaña.
Estados actuales: {profile_states}. El [índice de cobertura temporal](profile-results-index.json)
conserva las variantes sin recibo; no se transfieren métricas históricas.

'''+report[end:]
    (HERE/'REPORT.md').write_text(report,encoding='utf-8',newline='\n')
    (HERE/'README.md').write_text('''# Conservación B9 compuesto

[Reporte](REPORT.md) · [Decisión](candidate-decision.json) · [Bloques](block-status.json) ·
[Índice](artifact-index.json) · [Manifest](preservation-manifest.json) ·
[Prueba de recuperación](preservation-verification.json) · [Entrega](delivery-verification.json).

El paquete conserva logs nuevos, el diff de cuatro tests sobre la base y las copias originales
referenciadas bajo `referenced-evidence/`. El [manifiesto](reuse-manifest.json)
identifica su procedencia y SHA-256; esas copias no son ejecuciones nuevas.
Los journals parciales r6/r7 y su procedencia se conservan en `referenced-case-evidence/r6/` y `referenced-case-evidence/r7/`
y [case-resumption-manifest.json](case-resumption-manifest.json). La aceptación
es condicionada por la limitación histórica de disco/reloj aceptada; el exit del
ensamblador actual no representa un exit 0 de la invocación original interrumpida.
Los recibos que sustentan este cierre se recuperan dentro del mismo paquete.
Recuperar en una
carpeta ausente o vacía desde este expediente:

```powershell
rtk proxy python -B restore_native.py --destination C:/ruta/nueva/b9-recuperado
```

Se validan SHA-256 de partes, archivo y miembros. El empaquetador verifica
una recuperación interna y otra por CLI. No inicia pruebas ni PostgreSQL.
Las cuatro correcciones staged coinciden con el árbol actual evaluado según
[code-selection.json](code-selection.json); los paths de evidencia son explícitos.
Los bloques referenciados conservan el SHA del árbol anterior; su aceptación
para el árbol actual se limita a las excepciones autorizadas de reloj en un fixture y dos listas de snapshots,
verificada en [reuse-validation.json](reuse-validation.json).
Los logs se conservan dentro del ZIP sin normalización Git. No hay commit o push.
''',encoding='utf-8',newline='\n')
    acta=REPO/'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
    before=acta.read_bytes();acta_marker=f'B9 Windows compuesto r8 {candidate["candidate_tree"][:7]}'
    assert acta_marker.encode() not in before
    addition=f'''\n\n## {acta_marker} — {classification['date_local']} — aceptación {decision_label}

Base 1947726 y árbol actual {candidate['candidate_tree']}, cuatro tests corregidos; runtime/locks/aserciones/cargas intactos. Decisión **{decision_label}**; decision de máquina {classification['decision']}, accepted_historical_evidence_limitation=true. Los {len(references)} bloques PASS se ejecutaron sobre {previous_tree} (369 IDs completos, full 118), aceptados bajo la excepción autorizada de fixture. General combina 2483 PASS y 2 SKIP r6, 405 PASS r7 y 323 casos nuevos (321 sin resultado más 2 snapshots corregidos); conserva los dos FAIL r7 y no repite PASS: {len(current_suite_observations)} observaciones backend nuevas completas y {len(referenced_suite_observations)} de bloques referenciados. La cobertura histórica de disco/reloj monotónico del prefijo no está acreditada y el usuario aceptó esa limitación; el exit original r6 sigue UNKNOWN, sin convertirlo en exit 0. El comando de general es un ensamblador actual, sin ejecución adicional de tests. No se afirma corrida continua. {classification['cause']} Full lógico compuesto: {statuses['full']['state']}. Cleanup y cierre nativo de auxiliares actuales PASS; sin restauración API observada de los auxiliares r6 terminados por reinicio. {len(prior)} archivos históricos y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. Sin commits, push, despliegue o activación. [Reporte](../b9-correction-20261020-native-r8/REPORT.md), [matriz](../b9-correction-20261020-native-r8/candidate-decision.json).\n'''.encode()
    acta.write_bytes(before+addition);assert acta.read_bytes()[:len(before)]==before
    save('acta-update.json',{'state':'PASS','append_only':True,'prior_prefix_bytes':len(before),
        'prior_prefix_sha256':digest(before),'appended_sha256':digest(addition),'final_sha256':digest(acta.read_bytes())})
    save('closure-reporting.json',{'state':'PASS','decision':classification['decision'],
        'acceptance_label':decision_label,'accepted_historical_evidence_limitation':True,
        'historical_disk_and_monotonic_evidence_verified':False,
        'case_resumption_manifest':'case-resumption-manifest.json',
        'evidence_mode':'COMPOSITE_ACCEPTANCE','continuous_single_campaign':False,
        'accepted_candidate_tree':candidate['candidate_tree'],'previous_candidate_tree':previous_tree,
        'authorized_cross_candidate_exceptions':['fixture-clock-authorization.json','snapshot-resumption-authorization.json'],
        'historical_failed_attempts_preserved':2,'previous_PASS_cases_rerun':0,
        'reference_count':len(references),'historical_receipts_copied_as_current_execution':False,
        'formal_evaluator_sealed':(HERE/'evaluation-seal.json').exists(),
        'formal_controller_invoked':not preparation_only,
        'sealed_evaluator_changed':False,'reporting_script_sha256':digest(Path(__file__).read_bytes())})
    print('ACCEPTANCE_REPORTING_PASS')

if __name__=='__main__':main()
