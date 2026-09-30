"""Close E4 evidence without promoting the historical B9E/PROFILE decision."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

BASELINE = '52e1663881653efe6dcaf1d264aaac224c89a7ac'
SCENARIOS = ('base', 'blocked_llm', 'meta_slow', 'duplicate', 'saturation')
SOURCE = ('backend/apps/agent/worker.py',
    'backend/apps/agent/tests/test_e4_selection.py',
    'backend/apps/agent/tests/test_e4_processes.py',
    'backend/apps/agent/tests/e4_selection_process.py')


def validate(repository, output):
    root = repository/'docs/evals'
    errors, runs, accepted = [], {}, set()
    historical = set(json.loads((root/'e4-historical-selected.json').read_text()))
    expected_target = set(json.loads((root/'e4-new-selected.json').read_text())) | {
        i for i in historical if i.startswith(('apps.agent.tests.test_b9c_concurrency.',
            'apps.agent.tests.test_b9c_processes.'))}
    selections = {'targeted': expected_target}
    selections.update({f'regression-{n}':set(json.loads((root/f'e4-regression-{n}-selected.json').read_text()))
        for n in range(1,4)})
    for name, expected in selections.items():
        data = json.loads((root/f'e4-{name}.results.json').read_text())
        exits = json.loads((root/f'e4-{name}.exit.json').read_text())
        passed = {json.loads(line)['test_id'] for line in
            (root/f'e4-{name}.results.passed.jsonl').read_text().splitlines() if line}
        inventory = set(data['test_ids'])
        run_errors = []
        if inventory != expected or passed != expected or data['tests'] != len(expected):
            run_errors.append('inventory/passed mismatch')
        if any(data[k] for k in ('failures','errors','skips','xfail','exit_code')) or exits['exit_code']:
            run_errors.append('non-green validation')
        sources = json.loads((root/f'e4-{name}.results.sources.json').read_text())
        for path in SOURCE:
            if sources.get(path) != hashlib.sha256((repository/path).read_bytes()).hexdigest():
                run_errors.append('candidate source mismatch: '+path)
        if accepted & passed: run_errors.append('overlapping shards')
        accepted |= passed
        runs[name] = dict(data, passed_ids=sorted(passed), pending=sorted(expected-passed),
            validation_errors=run_errors)
        errors.extend(name+': '+e for e in run_errors)
    profiles={}
    for scenario in SCENARIOS:
        receipt_path=root/f'e4-postfix-{scenario}.json'
        analysis_path=root/f'e4-postfix-{scenario}.analysis.json'
        if not receipt_path.exists() or not analysis_path.exists():
            profiles[scenario]=dict(status='NOT_EVALUATED',validation_errors=['missing closed receipt/collection'])
            errors.append(scenario+': missing closed receipt/collection')
            continue
        receipt=json.loads(receipt_path.read_text())
        analysis=json.loads(analysis_path.read_text())
        profile_errors=[]
        processes=receipt['postgresql_process_ids']
        if (len(processes) != 3 or len({p['pid'] for p in processes}) != 3
                or len({p['backend_pid'] for p in processes}) != 3
                or {p['role'] for p in processes} != {'planner-1','planner-2','sender'}):
            profile_errors.append('process topology mismatch')
        if (receipt['profile_version'] != 'profile-beta-1-v1' or receipt['warmup_seconds'] != 30
                or receipt['measurement_seconds'] != 300 or receipt['smoke_only']):
            profile_errors.append('profile changed')
        if not receipt['technical_pass']: profile_errors.append('variant failed')
        if any(analysis['critical'][k] for k in ('cross_tenant','cross_tenant_work',
                'cross_tenant_call','budget_violations','failed','unclaimed_healthy')):
            profile_errors.append('critical violation')
        if receipt['max_active_per_org_observed'] > 1: profile_errors.append('capacity exceeded')
        profiles[scenario]=dict(gates=receipt['gates'], healthy_claim=receipt['healthy_claim'],
            distributions=analysis['distributions'], critical=analysis['critical'],
            query_ms=analysis['query_plan'][0]['Execution Time'],
            validation_errors=profile_errors)
        errors.extend(scenario+': '+e for e in profile_errors)
    checks=json.loads((root/'e4-checks.exit.json').read_text())
    if checks['exit_code']: errors.append('checks failed')
    frozen = ['docs/evals/profile-beta-1-v1.json','docs/evals/profile-beta-1-methodology.md',
        'backend/apps/agent/tests/b9e_profile.py', *[str(p.relative_to(repository)).replace('\\','/')
            for p in root.glob('b9e-*') if p.is_file()]]
    comparison=subprocess.run(['rtk','git','diff','--exit-code',BASELINE,'--',*frozen],
        cwd=repository,capture_output=True)
    if comparison.returncode: errors.append('historical B9E/profile changed')
    privacy=[]
    patterns={'phone':r'(?<!\d)52155\d{8,}(?!\d)',
        'conversation':r'Mi perro está convulsionando ahora|Consulta sobre servicios|¿Qué servicios ofrecen\?',
        'content_field':r'"(?:prompt|response|phone|clinical_text)"\s*:'}
    for path in root.glob('e4-*'):
        if path.suffix not in ('.json','.jsonl','.log'): continue
        raw=path.read_bytes()
        text=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf8',errors='replace')
        for category,pattern in patterns.items():
            count=len(re.findall(pattern,text))
            if count: privacy.append(dict(file=path.name,category=category,count=count))
    if privacy: errors.append('privacy findings')
    corpus=set(json.loads((root/'e4-b9e-corpus-selected.json').read_text()))
    if corpus-accepted: errors.append('inherited E4 corpus missing IDs')
    candidate=subprocess.check_output(['rtk','proxy','git','rev-parse','HEAD'],cwd=repository,text=True).strip()
    result=dict(schema='e4-candidate-validation-v1', baseline=BASELINE,
        candidate_runtime_commit=candidate,
        e4_status='PARTIAL' if errors else 'COMPLETED', root_cause='ROOT_CAUSE_CONFIRMED',
        canonical_b9_status='IN_PROGRESS', historical_b9e_status='FAIL',
        integral_profile_beta_1_status='FAIL', formal_b9e_rerun=False,
        historical_reference_count=len(historical), regression_count=len(accepted),
        inherited_corpus_count=len(corpus), inherited_corpus_accepted=len(corpus & accepted),
        runs=runs, profiles=profiles, checks=checks, historical_preserved=comparison.returncode==0,
        privacy_findings=privacy, validation_errors=errors,
        candidate_source_sha256={p:hashlib.sha256((repository/p).read_bytes()).hexdigest() for p in SOURCE})
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(status=result['e4_status'],regression=len(accepted),errors=errors)))
    return bool(errors)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): raise RuntimeError('Refusing to overwrite validation')
    return validate(args.repository,args.output)


if __name__ == '__main__': raise SystemExit(main())
