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
from backend_resumption import source_root, case_summary
from frontend_resumption import validate_frontend_references, summary as frontend_summary

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
    aliases={'full-general':'full-general-assemble','frontend-test':'frontend-test-assemble'}
    filename=aliases.get(label,label)+suffix if suffix=='.command.json' else label+suffix
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
    return [path] if path.exists() else []


def journal_entries(label):
    path=journal_path(label)
    if not path.exists():return []
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if label=='directed' and path.name.endswith('.passed.jsonl'):
        assert all(row['status']=='ok' for row in rows)
        return [{'id':row['test_id'],'outcome':'PASS'} for row in rows]
    return rows


def historical_read(name):
    return json.loads((source_root()/name).read_text(encoding='utf-8'))


def validate_selector_history():
    manifest=read('selector-history-manifest.json')
    decision=read('selector-repair-decision.json')
    campaign='b9-correction-20261020-native-r10'
    tree=read('candidate.json')['candidate_tree']
    assert tree=='f5f18d71847a46d66644775cd90d30268f072e3b'
    assert manifest['schema']=='b9-zero-case-selector-history/1'
    assert manifest['source_campaign']==campaign
    assert manifest['source_candidate_tree']==manifest['candidate_tree']==tree
    assert manifest['bundle_relative']=='referenced-selector-evidence/r10'
    assert manifest['files']
    bundle=HERE/'referenced-selector-evidence/r10'
    original=HERE.with_name(campaign)
    def inventory(root):
        assert root.is_dir() and not root.is_symlink() and not root.is_junction()
        names=set();pending=[root]
        while pending:
            directory=pending.pop()
            for path in directory.iterdir():
                assert not path.is_symlink() and not path.is_junction()
                if path.name=='__pycache__' or (directory==root and path.name=='referenced-completed-evidence'):
                    continue
                if path.is_dir():pending.append(path)
                elif path.is_file():names.add(path.relative_to(root).as_posix())
        return names
    for root in (bundle,original) if original.exists() else (bundle,):
        assert inventory(root)==set(manifest['files'])
        for name,item in manifest['files'].items():
            assert name and ':' not in name and '\\' not in name and not name.startswith('/')
            parts=name.split('/')
            assert all(part not in ('','.','..') for part in parts)
            path=root.joinpath(*parts)
            assert path.resolve().is_relative_to(root.resolve())
            assert set(item)=={'sha256','bytes'}
            content=path.read_bytes()
            assert len(content)==item['bytes'] and digest(content)==item['sha256'],name
    required={'candidate.json','blocks/frontend-test-remainder.json',
        'blocks/frontend-test-remainder.command.json','blocks/frontend-test-assemble.command.json',
        'invocation-formal.json','STOP.json','frontend-remainder-selection.json'}
    assert required<=set(manifest['files'])
    def historical(name):return json.loads((bundle/name).read_text(encoding='utf-8'))
    assert historical('candidate.json')['candidate_tree']==tree
    raw=historical('blocks/frontend-test-remainder.json')
    rows=[row for suite in raw['testResults'] for row in suite['assertionResults']]
    identities=[(suite['name'],row['fullName']) for suite in raw['testResults'] for row in suite['assertionResults']]
    assert raw['numTotalTests']==raw['numPendingTests']==len(rows)==len(set(identities))==26
    assert raw['numPassedTests']==raw['numFailedTests']==raw['numTodoTests']==0
    assert all(row['status'] in ('skipped','pending') and row.get('duration') in (None,0) for row in rows)
    command=historical('blocks/frontend-test-remainder.command.json')
    assembler=historical('blocks/frontend-test-assemble.command.json')
    controller=historical('invocation-formal.json');stop=historical('STOP.json')
    assert command['state']=='COMPLETED' and command['exit_code']==0 and command['invalidating_incident'] is None
    assert assembler['state']=='COMPLETED' and assembler['exit_code']==1 and assembler['invalidating_incident'] is None
    assert controller['state']=='COMPLETED' and controller['exit_code']==2
    assert stop['state']=='PENDING' and stop['phase']=='frontend-test-assemble' and stop['exit_code']==1
    assert command['candidate_sha']==assembler['candidate_sha']==tree
    assert decision['state']=='HARNESS_ONLY_REPAIR_APPROVED'
    assert decision['source_campaign']==campaign
    assert decision['source_candidate_tree']==decision['candidate_tree']==tree
    assert decision['no_application_source_or_fixture_change'] is True
    assert decision['original_case_authorization']=='frontend-resumption-authorization.json'
    assert decision['application_test_cases_executed_in_r10']==0
    assert decision['previous_PASS_cases_rerun'] is False
    assert decision['exact_one_case_discovery_required'] is True
    return {'state':'PENDING_SELECTOR_NO_CASE_EXECUTED','source_campaign':campaign,
        'source_candidate_tree':tree,'candidate_tree':tree,'application_test_cases_executed':0,
        'passed_cases':0,'failed_cases':0,'filtered_case_metadata':26,'test_duration_ms':0,
        'filtered_metadata_is_acceptance_SKIP':False,'original_command_exit_code':0,
        'original_assembler_exit_code':1,'original_controller_exit_code':2,
        'original_stop_state':'PENDING','no_application_source_or_fixture_change':True,
        'previous_PASS_cases_rerun':False,'manifest':'selector-history-manifest.json',
        'manifest_sha256':digest((HERE/'selector-history-manifest.json').read_bytes()),
        'repair_decision':'selector-repair-decision.json','repair_decision_sha256':digest((HERE/'selector-repair-decision.json').read_bytes()),
        'repair_state':'HARNESS_ONLY_REPAIR_APPROVED','exact_one_case_discovery_required':True,
        'source_artifacts':{name:'referenced-selector-evidence/r10/'+name for name in sorted(required)},
        'original_receipts_changed':False}


def main():
    validate_references()
    validate_frontend_references()
    backend=source_root()
    case_proof=case_summary()
    front_proof=frontend_summary()
    selector_history=validate_selector_history()
    assert case_proof['accepted_historical_evidence_limitation'] is True
    assert case_proof['historical_disk_and_monotonic_evidence_verified'] is False
    assert front_proof['retained_pass']==354 and front_proof['new_selected_ids']==1 and front_proof['total_cases']==355
    assert front_proof['original_command_exit_code']==1 and front_proof['original_outcome']=='PENDING_TIMEOUT'
    assert front_proof['timeout_ms']==5000 and front_proof['logical_aggregate'] is True
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
    candidate=read('candidate.json');previous_tree=historical_read('candidate.json')['candidate_tree']
    assert candidate['previous_candidate_tree']==previous_tree==front_proof['source_candidate_tree']
    assert front_proof['candidate_tree']==candidate['candidate_tree']
    authorization=read('frontend-resumption-authorization.json');equivalence=read('frontend-equivalence.json')
    assert authorization['user_answer']=='Sí, ajustar ese armado y continuar sin repetir PASS'
    assert authorization['no_PASS_reruns'] is True and authorization['original_frontend_timeout_and_exit_1_preserved'] is True
    assert authorization['retained_backend_ids']==3331 and authorization['retained_frontend_PASS']==354
    assert equivalence['candidate_tree']==candidate['candidate_tree'] and equivalence['previous_candidate_tree']==previous_tree
    assert equivalence['only_two_input_setup_statements_changed'] is True
    assert equivalence['normalized_complete_module_AST_identical'] is True
    assert equivalence['eight_assertions_and_original_5000ms_timeout_unchanged'] is True
    assert equivalence['all_other_3331_blobs_identical'] is True
    prior=read('prior-evidence-before.json')
    drift=[n for n,h in prior.items() if not (REPO/n).is_file() or digest((REPO/n).read_bytes())!=h]
    original=read('checkout-before.json')['unrelated']
    current={n:{'exists':(REPO/n).exists(),'sha256':digest((REPO/n).read_bytes()) if (REPO/n).exists() else None} for n in original}
    assert not drift and current==original
    save('preservation-of-prior-work.json',{'prior_campaign_files_checked':len(prior),'prior_campaign_mismatches':drift,'unrelated_unchanged':True,'unrelated':current})
    integrity=[];integrity_mismatches={}
    for pattern in ('integrity-*.json','dependency-check-*.json','seal-check-*.json'):
        for file in HERE.glob(pattern):
            if file.name=='integrity-summary.json':continue
            receipt=read(file.name)
            if receipt.get('mismatches'):integrity_mismatches[file.name]=receipt['mismatches']
            integrity.append(file.name)
    if integrity_mismatches:assert classification['decision']=='PENDING'
    save('integrity-summary.json',{'state':'PENDING' if integrity_mismatches else 'PASS','receipts':integrity,'mismatches':integrity_mismatches})
    backend_labels=['directed','django-check','migration-drift','migrate','billing-schema','b0','b3','b4','b5',*FULL_GROUPS,'full']
    retained_labels=[*backend_labels,'frontend-build']
    assert not any((HERE/'blocks'/(label+'.command.json')).exists() for label in retained_labels)
    backend_full=read_block('full','.results.json')
    expected_full=historical_read('full-selected.json')
    full_rows=journal_entries('full')
    backend_counts=dict(Counter(row['outcome'] for row in full_rows))
    assert backend_full['tests']==3331 and sorted(backend_full['test_ids'])==expected_full
    assert len(full_rows)==len({row['id'] for row in full_rows})==3331
    assert sorted(row['id'] for row in full_rows)==expected_full
    assert backend_counts=={'PASS':3319,'SKIP':12}
    assert not backend_full['failures'] and not backend_full['errors'] and backend_full['exit_code']==0
    historical_failures=[];historical_source_counts={}
    for campaign,total,passes,skips,fails in [('r7',407,405,0,2),('r8',323,312,10,1)]:
        path=backend/('referenced-case-evidence/'+campaign+'/blocks/full-general-remainder.ids.jsonl')
        rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        assert len(rows)==total and Counter(row['outcome'] for row in rows)=={k:v for k,v in {'PASS':passes,'SKIP':skips,'FAIL':fails}.items() if v}
        historical_failures.extend(dict(row,source_campaign=campaign,source_journal=artifact_path(path)) for row in rows if row['outcome']=='FAIL')
        historical_source_counts[campaign]={'observations':total,'PASS':passes,'SKIP':skips,'FAIL':fails,'source':artifact_path(path)}
    assert len(historical_failures)==3
    for failure in historical_failures:
        accepted=[row for row in full_rows if row['id']==failure['id']]
        assert len(accepted)==1 and accepted[0]['outcome']=='PASS'
    old_r8=historical_read('referenced-case-evidence/r8/blocks/full-general-remainder.command.json')
    assert old_r8['state']=='COMPLETED' and old_r8['exit_code']==1
    save('historical-failed-attempts.json',{'state':'PRESERVED_HISTORICAL_FAIL','sources':historical_source_counts,'historical_FAIL':historical_failures,
        'original_r6_exit_code':None,'original_r7_exit_code':None,'original_r8_exit_code':1,'included_as_accepted_PASS':False,
        'corrected_PASS_sources':'Referenced complete r9 full receipt; original failures retained','no_PASS_reruns':True})
    old_frontend=historical_read('blocks/frontend-tests.json')
    timeout_failures=[dict(row,file=suite['name']) for suite in old_frontend['testResults'] for row in suite['assertionResults'] if row['status']=='failed']
    assert old_frontend['numTotalTests']==355 and old_frontend['numPassedTests']==354 and len(timeout_failures)==1
    old_front_command=historical_read('blocks/frontend-test.command.json')
    assert old_front_command['exit_code']==1 and old_front_command['invalidating_incident'] is None
    assert 'Test timed out in 5000ms.' in (backend/'blocks/frontend-test.command.log').read_text(encoding='utf-8')
    save('frontend-original-timeout.json',{'state':'PRESERVED_PENDING_TIMEOUT','source_campaign':backend.name,'original_command_exit_code':1,
        'original_outcome':'PENDING_TIMEOUT','timeout_ms':5000,'failures':timeout_failures,
        'original_result':artifact_path(backend/'blocks/frontend-tests.json'),'original_result_sha256':digest((backend/'blocks/frontend-tests.json').read_bytes()),
        'original_command':artifact_path(backend/'blocks/frontend-test.command.json'),'converted_to_original_PASS':False})
    save('selector-attempt-history.json',selector_history)
    current_frontend_result=read(front_proof['remainder_result']) if (HERE/front_proof['remainder_result']).exists() else None
    current_frontend_observed=sum(row.get('status') in ('passed','failed') for suite in (current_frontend_result or {}).get('testResults',[])
        for row in suite.get('assertionResults',[]))
    assert current_frontend_observed in (0,1)
    frontend_logical=read('blocks/frontend-tests.json') if (HERE/'blocks/frontend-tests.json').exists() else None
    if frontend_logical is not None:
        assert frontend_logical['schema']=='b9-frontend-logical-aggregate/1' and frontend_logical['exit_scope']=='aggregate'
        assert frontend_logical['original_command_exit_code']==1 and frontend_logical['original_outcome']=='PENDING_TIMEOUT'
        identities=[(row['identity']['file'],row['identity']['fullName']) for row in frontend_logical['cases']]
        assert len(identities)==len(set(identities))==355
    labels=[*retained_labels,'frontend-test','frontend-lint','frontend-smoke-urls','security','pip-audit','pnpm-audit',
        'profile-base','profile-blocked_llm','profile-meta_slow','profile-duplicate','profile-saturation']
    statuses={};references={}
    for label in labels:
        gate=optional_block_path(label,'.gate.json')
        if label=='full':
            assert gate.exists() and read_block(label,'.gate.json')['state']=='PASS'
            statuses[label]={'state':'PASS','formal_runs':0,'source_formal_runs':0,'logical_aggregate':True,
                'tests':3331,'outcomes':{k:backend_full.get(k) for k in ('failures','errors','skips','xfail','xpass')},
                'seconds':backend_full['seconds'],'seconds_scope':backend_full.get('seconds_scope'),
                'aggregate_receipt':artifact_path(block_path(label,'.results.json')),**block_origin(label)}
        else:
            command=optional_block_path(label,'.command.json')
            if not command.exists():
                statuses[label]={'state':'NOT_EXECUTED','formal_runs':0,'source_formal_runs':0,**block_origin(label)}
                continue
            c=read_block(label,'.command.json');assert c['state']=='COMPLETED'
            retained=label in retained_labels
            statuses[label]={'state':read_block(label,'.gate.json')['state'] if gate.exists() else 'INCOMPLETE',
                'exit_code':c['exit_code'],'seconds':c['seconds'],'formal_runs':0 if retained or label=='frontend-test' else 1,
                'source_formal_runs':1,'executed_candidate_tree':c['candidate_sha'],'accepted_candidate_tree':candidate['candidate_tree'],
                'invalidating_incident':c.get('invalidating_incident'),'command_receipt':artifact_path(command),**block_origin(label)}
            if c.get('invalidating_incident'):statuses[label]['state']='PENDING_ENVIRONMENT_INTERRUPTION'
            if label=='frontend-test':
                assert c['label']=='frontend-test-assemble'
                statuses[label].update(logical_aggregate=True,assembler_formal_runs=1,exit_scope='aggregate',
                    current_test_case_count=1,retained_test_case_count=354,original_command_exit_code=1,original_outcome='PENDING_TIMEOUT')
                if frontend_logical is not None:statuses[label].update(tests=355,outcomes=frontend_logical['case_counts'])
            elif label in backend_labels:
                result=optional_block_path(label,'.results.json')
                if result.exists():
                    receipt=read_block(label,'.results.json');statuses[label].update(tests=receipt['tests'],
                        outcomes={k:receipt.get(k) for k in ('failures','errors','skips','xfail','xpass')},failed_ids=receipt.get('failed_ids',[]))
        if label in retained_labels:
            assert statuses[label]['state']=='PASS' and statuses[label]['formal_runs']==0
            references[label]={'provenance':provenance(label),'command_receipt':statuses[label].get('command_receipt'),
                'aggregate_receipt':statuses[label].get('aggregate_receipt'),'accepted_candidate_tree':candidate['candidate_tree']}
    assert set(references)==set(retained_labels)
    validate_references();validate_frontend_references()
    save('block-status.json',statuses)
    save('composite-evidence-provenance.json',{'state':'PASS','evidence_mode':'COMPOSITE_ACCEPTANCE','continuous_single_campaign':False,
        'reference_manifest':'completed-reference-manifest.json','frontend_manifest':'frontend-resumption-manifest.json',
        'accepted_candidate_tree':candidate['candidate_tree'],'previous_candidate_tree':previous_tree,'retained_backend_and_build_blocks':references,
        'nested_original_PASS_blocks':13,'backend_case_summary':case_proof,'frontend_summary':front_proof,
        'accepted_historical_evidence_limitation':True,'historical_disk_and_monotonic_evidence_verified':False,
        'original_frontend_outcome':'PENDING_TIMEOUT','original_frontend_command_exit_code':1,'historical_backend_FAILs_preserved':3,
        'prior_zero_case_selector_attempt':selector_history,'selector_repair_decision':'selector-repair-decision.json'})
    save('execution-summary.json',{'candidate_tree':candidate['candidate_tree'],'acceptance_label':decision_label,
        'accepted_historical_evidence_limitation':True,'historical_disk_and_monotonic_evidence_verified':False,
        'evidence_mode':'COMPOSITE_ACCEPTANCE','continuous_single_campaign':False,
        'backend_unique_ids_in_complete_receipts':3331,'backend_PASS_retained':3319,'backend_SKIP_retained':12,
        'backend_application_test_cases_executed_current':0,'frontend_build_executed_current':False,'frontend_build_referenced_PASS':True,
        'frontend_cases_retained_PASS':354,'frontend_cases_selected_current':1,
        'frontend_test_case_outcomes_observed_current':current_frontend_observed,'frontend_logical_total_cases':355,
        'frontend_remainder_command':front_proof['remainder_command'],'frontend_assembler_command':front_proof['assembler_command'],
        'frontend_original_command_exit_code':1,'frontend_original_outcome':'PENDING_TIMEOUT','original_timeout_ms':5000,
        'backend_historical_failed_attempts':3,'original_backend_exits':{'r6':'UNKNOWN','r7':'UNKNOWN','r8':1},
        'prior_zero_case_selector_attempt':selector_history,
        'previous_PASS_cases_rerun':0,'frontend_filtered_metadata_not_counted_as_acceptance_skips':True,
        'logical_aggregates_counted_as_application_test_executions':False,'retained_blocks':references,
        'profile_variants_executed':sum(statuses['profile-'+s]['formal_runs'] for s in ['base','blocked_llm','meta_slow','duplicate','saturation']),
        'formal_controller_invocations':int((HERE/'invocation-formal.json').exists()),'formal_reruns':0})
    monitors={}
    for label in labels+['frontend-test-remainder']:
        command_label='frontend-test-assemble' if label=='frontend-test' else label
        file=Path(source_for(label))/('monitor-'+command_label+'.json')
        if label=='full-general':file=Path(source_for(label))/'monitor-full-general-assemble.json'
        if not file.exists():continue
        rows=json.loads(file.read_text(encoding='utf-8'))
        if rows:monitors[label]={'samples':len(rows),'source':artifact_path(file),**block_origin(label),
            'min_host_bytes':min(row['host']['physical_available'] for row in rows),
            'min_disk_bytes':min(row['host']['disk_available'] for row in rows),
            'max_clock_skew_seconds':max(abs(row['wall_minus_monotonic_seconds']) for row in rows),
            'monitor_scope':'ASSEMBLER_ONLY' if label in ('full-general','frontend-test') else 'CURRENT_OR_REFERENCED_COMMAND'}
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
        assert backend_full['tests']==3331 and backend_counts=={'PASS':3319,'SKIP':12}
        assert frontend_logical is not None and frontend_logical['state']=='PASS'
        assert frontend_logical['case_counts']=={'total':355,'passed':355,'failed':0,'skipped':0,'pending':0,'todo':0}
        assert frontend_logical['original_command_exit_code']==1 and frontend_logical['original_outcome']=='PENDING_TIMEOUT'
        assert sum(row['provenance']['origin']=='CURRENT_EXECUTION' for row in frontend_logical['cases'])==1
        assert sum(row['provenance']['origin']=='REFERENCED_PASS' for row in frontend_logical['cases'])==354
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
        'case_resumption_manifest':artifact_path(backend/'case-resumption-manifest.json'),'case_resumption_summary':case_proof,
        'frontend_resumption_manifest':'frontend-resumption-manifest.json','frontend_resumption_summary':front_proof,
        'previous_candidate_tree':previous_tree,
        'referenced_blocks_executed_on_previous_candidate':True,
        'cross_candidate_exception_authorization':'frontend-resumption-authorization.json',
        'selector_repair_decision':'selector-repair-decision.json','prior_zero_case_selector_attempt':selector_history,
        'historical_backend_authorizations_root':artifact_path(backend),
        'cross_candidate_equivalence_proof':'frontend-equivalence.json',
        'evidence_mode':'COMPOSITE_ACCEPTANCE','continuous_single_campaign':False,
        'reference_count':len(references),'reference_manifest':'completed-reference-manifest.json',
        'nested_historical_PASS_block_count':13,'backend_application_tests_executed_current':0,
        'decision':classification['decision'],'cause':classification['cause'],'R01_R15':R,'I01_I14':I,
        'temporal_variant_states':temporal_states,
        'activation':'PENDING_ACTIVATION_REQUIREMENTS','R1-04':'PENDING_WITH_ACCEPTED_LIMITATION; zero new physical attempts',
        'E_P_UX':'SEPARATE_UNCHANGED_SCOPES','operational_requirements':{
            'R06_real_promotion_eval':'PENDING_SEPARATE','R13_release_readiness':'PENDING_SEPARATE','R15_P_A_P_B':'PENDING_SEPARATE'},
        'production_runtime_changed':False,'locks_changed':False,'test_changes':candidate['changed_paths'],
        'commits_created':0,'pushes_performed':0,'production_activation_or_deployment':False})
    metrics=['window_utc','inbound_count','outbound_count','healthy_claim','safety_dispatch','outbox_dispatch',
        'max_active_per_org_observed','max_pending_inbound_observed','max_outbound_attempts','generator_events',
        'turnwork_status','outbound_status','llm_calls','llm_call_count','provider_calls']
    save('profile-results-index.json',{'variants':{s:{'path':'blocks/profile-'+s+'.json','technical_pass':value.get('technical_pass'),
        'gates':value.get('gates'),'measurements':{k:value[k] for k in metrics if k in value}} for s,value in profiles.items()},
        'not_executed':[s for s in scenario_names if statuses['profile-'+s]['state']=='NOT_EXECUTED'],
        'without_complete_receipt':[s for s in scenario_names if s not in profiles],'historical_metrics_transferred':False})
    table=[]
    for label,value in statuses.items():
        receipt=value.get('command_receipt',value.get('aggregate_receipt'))
        link='[recibo]('+receipt+')' if receipt else '—'
        scope='PASS referenciado' if label in retained_labels else 'ensamblador actual; un caso nuevo' if label=='frontend-test' else 'ejecución actual' if value['formal_runs'] else 'sin ejecución'
        table.append('| '+label+' | '+value['state']+' | '+str(value.get('tests','—'))+' | '+str(value.get('exit_code','—'))+' | '+scope+' | '+link+' |')
    table_text='\n'.join(table)
    profile_rows=[]
    for scenario in scenario_names:
        value=profiles.get(scenario,{})
        for boundary in ['healthy_claim','safety_dispatch','outbox_dispatch']:
            measurement=value.get(boundary,{})
            profile_rows.append('| '+scenario+' | '+boundary+' | '+str(measurement.get('count','—'))+' | '+str(measurement.get('missing','no field' if measurement else '—'))+' | '+str(measurement.get('p95_seconds','—'))+' | '+str(measurement.get('max_seconds','—'))+' |')
    profile_table='\n'.join(profile_rows)
    report=f"""# B9 Windows nativo r11 — {decision_label}

**Decisión técnica: {decision_label}.** {classification['cause']}

El candidato es `{candidate['candidate_tree']}`, sobre la base `{candidate['base_commit']}`.
La aceptación, si corresponde, mantiene la condición de evidencia enmendada aceptada
por el usuario: falta el monitor histórico de disco/reloj monotónico de r6. No se
inventan esas muestras ni los exits desconocidos de r6/r7. Esta aceptación compuesta
no declara una campaña continua. [Matriz R/I](candidate-decision.json).

Se conservan los **3331 IDs backend: 3319 PASS y 12 SKIP**, el build frontend PASS de
r9 y **354 PASS frontend**. En r11 se selecciona exclusivamente el caso frontend que
agotó los 5000 ms. Ningún PASS anterior se repite. Las pruebas de los cinco perfiles
son las cargas originales pendientes, con sus umbrales y concurrencia intactos.
[Referencias completas](completed-reference-manifest.json) ·
[Procedencia](composite-evidence-provenance.json) · [Ejecuciones](execution-summary.json).

El intento r10 permanece **PENDING por selector**: ejecutó cero casos,
con 0 PASS, 0 fallos y 26 metadatos filtrados de duración 0 ms. Su comando
terminó con exit 0; el ensamblador rechazó correctamente la ausencia del caso
con exit 1 y el controlador terminó con exit 2. Esos recibos se conservan;
no acreditan un PASS frontend ni un fallo de las aserciones del producto.
La decisión r11 permite reparar únicamente el patrón del selector, con el mismo
árbol f5, fixture, ocho aserciones y timeout de 5000 ms. Exige comprobar una
coincidencia exacta antes del primer intento real pendiente y no repite PASS.
[Intento de cero casos](selector-attempt-history.json) ·
[Manifest de historia](selector-history-manifest.json) ·
[Decisión de reparación](selector-repair-decision.json).

El frontend original r9 conserva **354 PASS, un timeout y exit 1**, clasificado
PENDING_TIMEOUT; no se convierte en un PASS original. El comando actual de la tabla
para frontend-test es el ensamblador: su exit es del agregado, no de una corrida
completa de Vitest. El agregado solo puede aprobar con 354 casos referenciados y un
caso nuevo aprobado, 355 identidades distintas y cero omisiones. Los metadatos de
casos excluidos por el filtro no son skips de aceptación.
[Timeout conservado](frontend-original-timeout.json) ·
[Manifiesto frontend](frontend-resumption-manifest.json) ·
[Caso nuevo](blocks/frontend-test-remainder.command.json) ·
[Ensamblador](blocks/frontend-test-assemble.command.json) ·
[Resultado lógico](blocks/frontend-tests.json).

La corrección adicional cambia solamente dos armados de texto del caso de
A→B→A en index.test.jsx: fireEvent.change invoca el onChange real para establecer
el mismo borrador completo. Conserva las ocho aserciones, navegación, clicks,
promesa tardía, IDs, imports y timeout de 5000 ms. Evita 62 pulsaciones ajenas al
objetivo de aislamiento causal del borrador. No cambia runtime productivo ni locks.
Los otros **3331 blobs** coinciden con el candidato r9.
[Autorización](frontend-resumption-authorization.json) ·
[Equivalencia](frontend-equivalence.json) · [Diff completo](correction.diff).

Los trece bloques históricos iniciales conservan su identidad anidada; los casos
backend r6/r7/r8 y el único caso corregido de r9 siguen en sus journals originales.
Los **tres FAIL backend históricos** permanecen visibles y sus correcciones tienen
PASS verificado dentro del backend completo r9. El exit original r8 sigue siendo 1;
r6/r7 siguen UNKNOWN. Los 12 SKIP identificados conservan sus motivos y no cubren
requisitos críticos. [Historial de fallos](historical-failed-attempts.json).
La nueva excepción frontend no vuelve a ejecutar las correcciones de reloj,
snapshots o baseline tenant ya aprobadas.

| Bloque | Estado | IDs | Exit | Alcance | Evidencia |
|---|---|---:|---:|---|---|
{table_text}

Los resultados del agregado no cuentan como ejecuciones adicionales. Los recibos
backend conservan sus candidatos originales y la cadena de equivalencias autorizadas;
su aceptación actual no los presenta como ejecuciones nuevas. Los monitores de los
ensambladores acreditan solo esos comandos. Los nuevos comandos conservan los guards
de 2 GiB RAM, 1 GiB disco y desviación máxima de reloj de 1 s.
[Monitores](monitor-summary.json) · [Integridad](integrity-summary.json).

Los cinco perfiles deben aprobar completos; no se transfieren métricas históricas.
El índice conserva denominadores, faltantes, percentiles, máximos, estados durables y
gates por variante. No se promedian percentiles entre organizaciones. Un campo ausente
no significa cero faltantes. [Recibos PROFILE](profile-results-index.json).

| Variante | Frontera | Muestras | Faltantes | p95 s | Máximo s |
|---|---|---:|---:|---:|---:|
{profile_table}

Cleanup del runtime privado y cierre de los auxiliares actuales: PASS. La restauración
API corresponde a los auxiliares actuales; no se atribuye a procesos históricos
terminados por reinicio. No se cambió la configuración del reloj del host ni políticas
globales de energía. Se verificaron {len(prior)} archivos históricos y los cambios ajenos.
[Cierre nativo](native-closure.json) · [Preservación](preservation-of-prior-work.json).

Activación **PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado, E/P/UX y
operación/privacidad separados. Sin commits, push, despliegue ni activación. El PASS
técnico bajo esta condición no acredita capacidad comercial ni fairness fuerte.
[Recuperación](README.md).
"""
    assert not (HERE/'REPORT.md').exists() and not (HERE/'README.md').exists()
    (HERE/'REPORT.md').write_text(report,encoding='utf-8',newline='\n')
    (HERE/'README.md').write_text("""# Conservación B9 r11

[Reporte](REPORT.md) · [Decisión](candidate-decision.json) · [Bloques](block-status.json) ·
[Índice](artifact-index.json) · [Manifest](preservation-manifest.json) ·
[Recuperación](preservation-verification.json) · [Entrega](delivery-verification.json).

El intento r10 de cero casos se preserva bajo referenced-selector-evidence/r10/,
con su manifest y la decisión de reparar solo el selector; no aporta PASS ni skips de aceptación.
El paquete contiene la referencia completa de r9 bajo referenced-completed-evidence/r9/,
con sus referencias anidadas y los fallos/timeout originales. No son ejecuciones r11.
El resultado frontend lógico conserva 354 PASS referenciados más un caso actual;
el exit del ensamblador no representa un exit 0 de la ejecución Vitest original.
La limitación histórica de disco/reloj r6 permanece explícitamente aceptada.

Recuperar en una carpeta ausente o vacía:

```powershell
rtk proxy python -B restore_native.py --destination C:/ruta/nueva/b9-recuperado
```

Se verifican SHA-256 de partes, archivo y miembros, con restauración interna y por CLI.
No inicia pruebas ni PostgreSQL. Los seis archivos de tests corregidos y la evidencia
staged se comprueban contra el candidato evaluado. Los logs se archivan sin normalización
Git. Sin commit ni push.
""",encoding='utf-8',newline='\n')
    acta=REPO/'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
    before=acta.read_bytes();marker=f'B9 Windows compuesto r11 {candidate["candidate_tree"][:7]}'
    assert marker.encode() not in before
    addition=f"""\n\n## {marker} — {classification['date_local']} — {decision_label}

Candidato {candidate['candidate_tree']}, base {candidate['base_commit']}. Decisión {decision_label}; {classification['cause']} Backend completo r9 conservado: 3331 IDs, 3319 PASS y 12 SKIP; build frontend r9 PASS. Frontend: 354 PASS conservados y un único caso actual, sin repetir PASS. Timeout original r9 de 5000 ms y exit 1 permanecen PENDING_TIMEOUT; los tres FAIL backend históricos y sus exits se conservan. La aceptación mantiene la limitación histórica de disco/reloj r6; no es campaña continua y los ensambladores no ejecutan tests. El intento r10 permanece PENDING por selector: cero casos, 26 metadatos filtrados, comando exit 0, ensamblador exit 1 y controlador exit 2; r11 repara solo el selector sobre el mismo f5 antes del primer intento real. Las ocho aserciones y timeout originales están intactos. Los 14 gates y cinco perfiles deben aprobar. Cleanup y auxiliares actuales PASS; historia y cambios ajenos preservados. Activación PENDING_ACTIVATION_REQUIREMENTS, R1-04 y E/P/UX/operación separados. Sin commits, push, despliegue ni activación. [Reporte](../b9-correction-20261020-native-r11/REPORT.md), [matriz](../b9-correction-20261020-native-r11/candidate-decision.json).
""".encode()
    acta.write_bytes(before+addition);assert acta.read_bytes()[:len(before)]==before
    save('acta-update.json',{'state':'PASS','append_only':True,'prior_prefix_bytes':len(before),'prior_prefix_sha256':digest(before),'appended_sha256':digest(addition),'final_sha256':digest(acta.read_bytes())})
    save('closure-reporting.json',{'state':'PASS','decision':classification['decision'],'acceptance_label':decision_label,
        'accepted_historical_evidence_limitation':True,'historical_disk_and_monotonic_evidence_verified':False,
        'evidence_mode':'COMPOSITE_ACCEPTANCE','continuous_single_campaign':False,'accepted_candidate_tree':candidate['candidate_tree'],
        'previous_candidate_tree':previous_tree,'backend_application_tests_executed_current':0,
        'frontend_cases_executed_current':current_frontend_observed,'frontend_cases_selected_current':1,
        'frontend_original_timeout_preserved':True,'frontend_original_command_exit_code':1,'historical_backend_failed_attempts_preserved':3,
        'prior_zero_case_selector_attempt':selector_history,'selector_repair_state':'HARNESS_ONLY_REPAIR_APPROVED',
        'previous_PASS_cases_rerun':0,'formal_evaluator_sealed':(HERE/'evaluation-seal.json').exists(),
        'formal_controller_invoked':(HERE/'invocation-formal.json').exists(),'sealed_evaluator_changed':False,
        'reporting_script_sha256':digest(Path(__file__).read_bytes())})
    print('ACCEPTANCE_REPORTING_PASS')


if __name__=='__main__':main()
