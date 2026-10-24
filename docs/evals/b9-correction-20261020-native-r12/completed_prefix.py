"""Read-only validation of the completed r11 frontend prefix for r12."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
import backend_resumption as backend

HERE=Path(__file__).resolve().parent
CAMPAIGN='b9-correction-20261020-native-r11'
TREE='f5f18d71847a46d66644775cd90d30268f072e3b'
MANIFEST='completed-prefix-manifest.json'
VALIDATION='completed-prefix-validation.json'
EXCLUDED={'referenced-completed-evidence','referenced-selector-evidence','__pycache__'}
LABELS={'frontend-test','frontend-smoke-urls','frontend-lint'}
TARGET_FILE='src/pages/inbox/index.test.jsx'
TARGET_NAME='Inbox — aislamiento del borrador un éxito antiguo A→B→A no borra un draft nuevo aunque tenga el mismo texto'
_CACHE=None


def require(ok,message):
    if not ok:raise RuntimeError('Completed r11 prefix: '+message)


def sha(path):
    return backend.sha(path)


def read(root,name):
    return json.loads(backend.safe(root,name).read_text(encoding='utf-8'))


def source_root():
    return backend.safe(HERE,'referenced-prefix-evidence/r11')


def inventory(root):
    require(root.is_dir() and not root.is_symlink() and not root.is_junction(),'missing/linked prefix source')
    names=set()
    for path in root.rglob('*'):
        relative=path.relative_to(root)
        if any(part in EXCLUDED for part in relative.parts):continue
        require(not path.is_symlink() and not path.is_junction(),'linked prefix artifact')
        if path.is_file():names.add(relative.as_posix())
    return names


def manifest():
    data=read(HERE,MANIFEST)
    require(data['schema']=='b9-completed-r11-prefix/1' and data['source_campaign']==CAMPAIGN and
        data['source_candidate_tree']==data['candidate_tree']==TREE and
        data['bundle_relative']=='referenced-prefix-evidence/r11','prefix manifest identity changed')
    require(isinstance(data['files'],dict) and bool(data['files']),'empty prefix manifest')
    return data


def validate_files():
    data=manifest();bundle=source_root();original=HERE.with_name(CAMPAIGN)
    require(inventory(bundle)==set(data['files']),'prefix bundle inventory changed')
    if original.exists():require(inventory(original)==set(data['files']),'original prefix inventory changed')
    for name,item in data['files'].items():
        require(set(item)=={'sha256','bytes'} and isinstance(item['bytes'],int) and item['bytes']>=0,
            'invalid prefix artifact descriptor')
        for root in (bundle,original) if original.exists() else (bundle,):
            path=backend.safe(root,name)
            require(path.is_file() and path.stat().st_size==item['bytes'] and sha(path)==item['sha256'],
                'prefix artifact changed '+str(root/name))
    return data


def finite(value):
    return isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value)


def guard(label,exit_code=0,advisory=False):
    root=source_root();command=read(root,'blocks/'+label+'.command.json')
    require(command['state']=='COMPLETED' and command['exit_code']==exit_code and
        command['candidate_sha']==TREE and command['formal_run_number']==1 and
        command['advisory'] is advisory and command.get('invalidating_incident') is None,
        'invalid original completed command '+label)
    rows=read(root,'monitor-'+label+'.json')
    require(bool(rows),'missing original monitor '+label)
    epochs=[]
    for row in rows:
        host=row['host'];awake=row['awake'];skew=row['wall_minus_monotonic_seconds']
        require(host['physical_available']>=2*1024**3 and host['disk_available']>=1024**3 and
            finite(skew) and abs(skew)<=1,'original resource/clock incident '+label)
        require(awake['state']=='ACTIVE_CONFIRMED' and finite(awake['sample_age_seconds']) and
            0<=awake['sample_age_seconds']<=10,'original awake witness invalid '+label)
        epochs.append(host['utc_epoch_seconds'])
    require(all(0<=b-a<=10 for a,b in zip(epochs,epochs[1:])),'original monitor gap '+label)
    for when in ('before','after'):
        host=command['resources_'+when]['host']
        require(host['physical_available']>=2*1024**3 and host['disk_available']>=1024**3,
            'original endpoint resource incident '+label)
        for prefix,field,count in [('integrity','checked_files',3332),
            ('dependency-check','checked',len(read(root,'dependency-files.json')['files'])),
            ('seal-check','checked',len(read(root,'evaluation-seal.json')['files']))]:
            receipt=read(root,prefix+'-'+when+'-'+label+'.json')
            require(receipt[field]==count and receipt['mismatches']==[],'original byte guard incomplete '+label)
    require(command['resources_after']['awake']['state']=='ACTIVE_CONFIRMED','original awake unavailable after '+label)
    return dict(state='PASS_GUARDS',exit_code=exit_code,advisory=advisory,monitor_samples=len(rows),
        min_ram_bytes=min(r['host']['physical_available'] for r in rows),
        min_disk_bytes=min(r['host']['disk_available'] for r in rows),
        max_clock_skew_seconds=max(abs(r['wall_minus_monotonic_seconds']) for r in rows))


def identities_from_raw(result,tree):
    rows=[]
    frontend=(Path(tree)/'frontend').resolve()
    for file in result['testResults']:
        path=Path(file['name']).resolve()
        require(path.is_relative_to(frontend),'raw Vitest file outside original private frontend')
        relative=path.relative_to(frontend).as_posix()
        for row in file['assertionResults']:
            rows.append(dict(identity={'file':relative,'fullName':row['fullName']},
                status=row['status']))
    return rows


def key(identity):
    require(set(identity)=={'file','fullName'} and all(isinstance(v,str) for v in identity.values()),
        'invalid frontend identity')
    return identity['file'],identity['fullName']


def validate_frontend():
    root=source_root();old=backend.source_root()
    original=read(old,'blocks/frontend-tests.json')
    old_tree=read(old,'assembly.json')['tree']
    original_rows=identities_from_raw(original,old_tree)
    require(len(original_rows)==355 and Counter(r['status'] for r in original_rows)=={'passed':354,'failed':1},
        'r9 frontend observations changed')
    retained={key(row['identity']) for row in original_rows if row['status']=='passed'}
    target=(TARGET_FILE,TARGET_NAME)
    require([key(row['identity']) for row in original_rows if row['status']=='failed']==[target],
        'r9 timeout identity changed')
    selected=read(root,'frontend-remainder-selected.json')
    require(selected==[dict(file=TARGET_FILE,fullName=TARGET_NAME)],'r11 selected more than original failed identity')
    require({key(row) for row in read(root,'frontend-retained-pass-selected.json')}==retained and
        len(read(root,'frontend-retained-pass-selected.json'))==354,'r11 retained PASS selection changed')
    selection=read(root,'frontend-remainder-selection.json');argv=selection['argv'];index=argv.index('--testNamePattern')
    require(selection['identity']==selected[0] and selection['previous_PASS_cases_selected']==0 and
        selection['test_timeout_override'] is False and selection['retries_added'] is False and
        selection['pool_or_concurrency_changed'] is False and selection['default_timeout_preserved_ms']==5000 and
        argv[index+1]=='^'+TARGET_NAME+'$' and argv[4:7]==['run','test',TARGET_FILE],
        'r11 selection/timeouts/concurrency changed')
    raw=read(root,'blocks/frontend-test-remainder.json')
    require(raw['success'] is True and raw['numTotalTests']==26 and raw['numPassedTests']==1 and
        raw['numFailedTests']==0 and raw['numPendingTests']==25 and raw['numTodoTests']==0,
        'r11 raw result not one PASS plus 25 filtered metadata')
    actual=identities_from_raw(raw,read(root,'assembly.json')['tree'])
    require(len(actual)==26 and len({key(r['identity']) for r in actual})==26 and
        all(r['identity']['file']==TARGET_FILE for r in actual),'r11 raw inventory changed')
    require([key(r['identity']) for r in actual if r['status']=='passed']==[target] and
        all(r['status'] in ('passed','pending','skipped') for r in actual),'r11 actual case failure or rerun')
    filtered={key(r['identity']) for r in actual if r['status']!='passed'}
    require(len(filtered)==25 and filtered<=retained,'filtered cases are not retained metadata')
    result=read(root,'blocks/frontend-tests.json')
    require(result['schema']=='b9-frontend-logical-aggregate/1' and result['state']=='PASS' and
        result['candidate_tree']==TREE and result['exit_scope']=='aggregate' and result['exit_code']==0 and
        result['logical_aggregate'] is True and result['continuous_single_campaign'] is False and
        result['case_counts']==dict(total=355,passed=355,failed=0,skipped=0,pending=0,todo=0),
        'r11 logical frontend aggregate changed')
    cases=result['cases'];ids=[key(row['identity']) for row in cases]
    require(len(ids)==len(set(ids))==355 and set(ids)==retained|{target} and
        all(row['status']=='passed' for row in cases),'frontend 354+1 union changed')
    require(read(root,'frontend-full-selected.json')==[row['identity'] for row in cases],
        'full frontend selection differs from aggregate')
    require(result['retained_pass']==354 and result['current_pass']==1 and
        result['previous_PASS_cases_rerun']==0 and result['original_command_exit_code']==1 and
        result['original_outcome']=='PENDING_TIMEOUT','original timeout was hidden')
    for row in cases:
        source=row['provenance']
        if key(row['identity'])==target:
            require(source['origin']=='CURRENT_EXECUTION' and source['campaign']==CAMPAIGN and
                source['candidate_tree']==TREE and source['artifact']=='blocks/frontend-test-remainder.json' and
                source['sha256']==sha(root/'blocks/frontend-test-remainder.json'),
                'actual r11 case provenance differs')
        else:
            require(source['origin']=='REFERENCED_PASS' and source['campaign']==backend.CAMPAIGN and
                source['candidate_tree']==backend.OLD and source['accepted_candidate_tree']==TREE and
                source['sha256']==sha(old/'blocks/frontend-tests.json'),'old frontend PASS provenance differs')
    require(result['current_remainder_command_sha256']==sha(root/'blocks/frontend-test-remainder.command.json') and
        result['current_remainder_json_sha256']==sha(root/'blocks/frontend-test-remainder.json'),
        'actual r11 command/result binding changed')
    metadata=result['filtered_case_metadata']
    require(metadata['count']==25 and metadata['counted_as_acceptance_skips'] is False and
        {key(row) for row in metadata['cases']}==filtered,'filtered metadata counted as acceptance skip')
    gate=read(root,'blocks/frontend-test.gate.json')
    require(gate['state']=='PASS' and gate['tests']==355 and gate['retained_PASS']==354 and
        gate['new_PASS']==1 and gate['command_reference']=='frontend-test-assemble.command.json',
        'frontend gate not original 355 PASS')
    require(read(root,'blocks/frontend-smoke-urls.gate.json')==
        dict(label='frontend-smoke-urls',state='PASS',exit_code=0),'smoke URL gate not original PASS')
    require(read(root,'blocks/frontend-lint.gate.json')==
        dict(label='frontend-lint',state='ADVISORY_NONZERO',exit_code=1),'lint advisory changed')
    front_manifest=read(root,'frontend-resumption-manifest.json')
    require(front_manifest['schema']=='b9-frontend-resumption/1' and front_manifest['candidate_tree']==TREE and
        front_manifest['source_candidate_tree']==backend.OLD and front_manifest['previous_PASS_cases_rerun']==0,
        'frontend source manifest changed')
    require(all(sha(backend.safe(root,name))==wanted for name,wanted in front_manifest['local_inputs'].items()),
        'frontend sealed input changed')
    require(all(sha(backend.safe(old,name))==wanted for name,wanted in front_manifest['original_artifacts'].items()),
        'original frontend failure artifact changed')
    selector=read(root,'diagnostics/selector-discovery-check.json')
    require(selector['state']=='PASS' and selector['actual_tests_executed']==0 and
        selector['static_collected']==26 and selector['matched_runtime_identity']==1,'r11 selector preflight invalid')
    return dict(state='PASS',total_cases=355,retained_pass=355,retained_PASS=355,new_selected_ids=0,
        source_campaign=CAMPAIGN,source_candidate_tree=TREE,candidate_tree=TREE,
        original_command_exit_code=1,original_outcome='PENDING_TIMEOUT',timeout_ms=5000,
        logical_aggregate=True,remainder_command='blocks/frontend-test-remainder.command.json',
        remainder_result='blocks/frontend-test-remainder.json',assembler_command='blocks/frontend-test-assemble.command.json',
        logical_result='blocks/frontend-tests.json',historical_r9_retained_pass=354,historical_r11_new_pass=1,
        frontend_manifest='frontend-resumption-manifest.json',completed_prefix_manifest=MANIFEST,
        current_test_runs=0,current_frontend_test_runs=0,current_selected_ids=0,
        filtered_metadata_count=25,filtered_metadata_counted_as_acceptance_skips=False,
        frontend_smoke='PASS',frontend_lint='ADVISORY_NONZERO',previous_PASS_cases_rerun=0,
        original_timeout_and_exit_preserved=True,source_actual_case_execution_count=1)


def validate_completed_prefix():
    global _CACHE
    data=validate_files();root=source_root()
    require(read(root,'candidate.json')['candidate_tree']==TREE and
        read(HERE,'candidate.json')['candidate_tree']==TREE,'prefix/current candidate tree changed')
    invocation=read(root,'invocation-formal.json');stop=read(root,'STOP.json')
    require(invocation['state']=='COMPLETED' and invocation['exit_code']==2 and
        stop['state']=='PENDING_CLASSIFICATION' and stop['phase']=='security' and stop['exit_code']==2,
        'original r11 stop/exit changed')
    security=read(root,'security-scopes.json')
    require(security['state']=='PENDING' and security['scans']==[] and
        security['cause']=='Sealed Git history changed or could not be verified' and
        security['product_finding_attributed'] is False,'original pre-scan security guard changed')
    require(not (root/'blocks/security.gate.json').exists(),'security gate must not be fabricated')
    commands={label:guard(label,1,True) if label=='frontend-lint' else guard(label)
        for label in ('frontend-test-remainder','frontend-test-assemble','frontend-lint','frontend-smoke-urls')}
    commands['security_pre_scan_guard']=guard('security',2)
    summary=validate_frontend()
    seal=read(root,'evaluation-seal.json');require(seal['candidate_sha']==TREE,'source seal candidate changed')
    marker='/docs/evals/'+CAMPAIGN+'/'
    retained_sealed=0
    for name,wanted in seal['files'].items():
        normalized=name.replace('\\','/')
        if marker not in normalized:continue
        relative=normalized.split(marker,1)[1]
        if any(part in EXCLUDED for part in Path(relative).parts):continue
        require(relative in data['files'] and data['files'][relative]['sha256']==wanted,
            'source sealed prefix artifact differs '+relative)
        retained_sealed+=1
    require(retained_sealed>0,'source seal contains no retained evaluator inputs')
    _CACHE=dict(state='PASS',candidate_tree=TREE,source_candidate_tree=TREE,source_campaign=CAMPAIGN,
        manifest=MANIFEST,manifest_sha256=sha(HERE/MANIFEST),reference_files=len(data['files']),
        sealed_files=len(seal['files']),retained_sealed_evaluator_files=retained_sealed,
        frontend=summary,source_commands=commands,source_formal_exit_code=2,source_stop_phase='security',
        source_gitleaks_scans=[],source_gitleaks_executed=False,original_security_guard_preserved=True,
        current_test_runs=0,application_tests_executed=False,accepted_historical_evidence_limitation=True)
    return dict(_CACHE)


def frontend_summary():
    if _CACHE is None:validate_completed_prefix()
    return dict(_CACHE['frontend'])


def prepare():
    require(not (HERE/'evaluation-seal.json').exists() and not (HERE/'invocation-formal.json').exists(),
        'prefix preparation must precede current seal')
    path=HERE/VALIDATION;require(not path.exists(),'refusing prefix validation receipt overwrite')
    result=validate_completed_prefix()
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print('COMPLETED_R11_PREFIX_VALIDATED_NO_TESTS',flush=True)


if __name__=='__main__':
    require(len(sys.argv)==2 and sys.argv[1]=='prepare','only explicit prepare is supported')
    prepare()

