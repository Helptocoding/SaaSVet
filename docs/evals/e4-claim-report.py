"""Summarize preserved evidence without rerunning or altering measurements."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/evals/e4-claim'
BASELINE = 'f051c27002986193772ced0fb1e00e19822d26ef'


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def epoch(value):
    return datetime.fromisoformat(value).timestamp() if value else None


def summarize(label):
    receipt = read(label+'.json')
    analysis = read(label+'.analysis.json')
    orgs = receipt['fixture_organization_ids']
    ordinary = [t for t in analysis['timelines'] if t['route']=='planner']
    works = receipt['claim_diagnostic']['works']
    near = analysis['noisy_selected_with_healthy_due_within_existing_poll']
    # Durable interval sweep, end before start when timestamps coincide.
    active = Counter(); maximum = Counter()
    intervals = [(epoch(w['claimed_at']),1,w['organization_id']) for w in works if
        w['status'] != 'COMPLETED' or w['outcome_code']!='safety_handoff']
    intervals += [(epoch(w['completed_at']),-1,w['organization_id']) for w in works if
        w['completed_at'] and w['outcome_code']!='safety_handoff']
    for at, delta, org in sorted(t for t in intervals if t[0] is not None):
        active[org] += delta
        maximum[org] = max(maximum[org], active[org])
    fields = {key:receipt.get(key) for key in ('scenario','window_utc','inbound_count',
        'outbound_count','healthy_claim','safety_dispatch','outbox_dispatch','gates',
        'technical_pass','critical_violations','monotonic_diagnostic','e4_overrides',
        'warmup_seconds','measurement_seconds','postgresql_process_ids')}
    fields.update(classification='DIAGNOSTIC_ONLY', acceptance_run=False,
        margin=analysis['margin'], organizations=analysis['organizations'],
        planners=analysis['planners'], selector_sql=analysis['selector_sql'],
        selector_explain_execution_ms=receipt['claim_diagnostic']['selector_plan'][0]['Execution Time'],
        locks_sql_upper_bounds=analysis['locks_sql_upper_bounds'],
        misses=len(analysis['duplicated_misses']),
        misses_by_org=dict(Counter(m['org'] for m in analysis['duplicated_misses'])),
        misses_with_subsequent_claim=sum(bool(m['subsequent_claims']) for m in analysis['duplicated_misses']),
        noisy_first_with_healthy_ready=analysis['noisy_first_with_healthy_ready'],
        near_ready_noisy_selected=len(near),
        near_ready_noisy_applicable=sum(n['guard_applicable_by_request_time'] for n in near),
        near_ready_noisy_applicable_claims=sum(n['guard_applicable_by_request_time'] and n['claimed'] for n in near),
        both_healthy_ready_snapshots=sum(set(c['healthy_ready'])=={0,1} for c in analysis['candidate_cases']),
        global_starts_before_claim_by_org={i:dict(Counter(len(t['opportunities']) for t in ordinary if t['org']==i)) for i in (0,1)},
        joined_after_observation=sum(t['joined_after_candidate_observation'] for t in ordinary),
        maximum_durable_ordinary_processing_by_org={orgs.index(org):n for org,n in maximum.items()},
        scope_or_membership_violations=receipt['claim_diagnostic']['cross_tenant_or_membership'],
        max_sampled_processing=max((a['count'] for s in receipt['queue_samples'] for a in s['active_work']),default=0),
        max_sampled_pending_inbound=max(s['pending_inbound'] for s in receipt['queue_samples']),
        max_sampled_pending_outbound=max(s['pending_outbound'] for s in receipt['queue_samples']),
        ordinary_llm_admissions=sorted(set(w['llm_calls_admitted'] for w in works if w['outcome_code']!='safety_handoff')))
    return fields


def regression():
    inventory = set(read('regression-final-inventory.json'))
    first_inventory = set(read('regression-inventory.json'))
    refinement = read('refinement.json')
    first_passed = set(); final_passed = set(); executions = []; receipts = []; coverage = {}
    first_failures = []
    labels = [f'regression-{i}' for i in range(3)]+[f'regression-final-{i}' for i in range(3)]
    for label in labels:
        path = OUT/(label+'.results.json')
        if not path.exists():
            journal = OUT/(label+'.results.passed.jsonl')
            rows = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
            print('IN_PROGRESS',label,'passed journal rows',len(rows),'last',rows[-1] if rows else None)
            return None
        result = read(path.name)
        selected = set(read(label+'-selected.json'))
        assert set(result['test_ids'])==selected and result['tests']==len(selected)
        receipts.append(dict(label=label,**result))
        journal = OUT/(label+'.results.passed.jsonl')
        rows = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
        assert all(row['status']=='ok' for row in rows)
        assert result['errors']==result['skips']==result['xfail']==0, result
        assert read(label+'.exit.json')['exit_code']==result['exit_code']
        passed_ids = {row['test_id'] for row in rows}
        failed_ids = set(result['failed_ids'])
        assert len(rows)==len(passed_ids) and passed_ids==selected-failed_ids
        is_final = label.startswith('regression-final-')
        if is_final:
            assert result['exit_code']==0 and result['failures']==0 and not failed_ids
            assert not final_passed.intersection(passed_ids)
            final_passed.update(passed_ids)
        else:
            assert not first_passed.intersection(passed_ids)
            first_passed.update(passed_ids)
            first_failures.extend(result['failed_ids'])
            assert result['failures']==len(failed_ids)
            assert result['exit_code']==int(bool(failed_ids))
        for identifier in passed_ids:
            coverage[identifier]=dict(receipt=label+'.results.json',
                source_version='final pending-safety exemption' if is_final else 'initial forecast prototype',
                hash_projection='raw checkout bytes' if is_final else refinement['prototype_worker_hash_projection'],
                worker_sha256=refinement['final_source_sha256']['backend/apps/agent/worker.py'] if is_final else refinement['prototype_worker_sha256'])
        executions.extend(result['test_ids'])
    assert first_failures==[refinement['initial_regression']['failed_id']]
    assert first_passed==first_inventory-set(first_failures)
    assert final_passed==set(refinement['revalidation']['ids'])
    passed=first_passed | final_passed
    assert passed==inventory==set(coverage), (len(passed),len(inventory),sorted(inventory-passed))
    assert len(executions)==len(first_inventory)+len(final_passed)
    for source, expected in refinement['final_source_sha256'].items():
        assert digest(ROOT/source)==expected, source
    for label in ('safety-edge-before','safety-edge-before-v2'):
        probe=read(label+'.results.json')
        assert probe['tests']==probe['failures']==probe['exit_code']==1
        assert probe['errors']==probe['skips']==probe['xfail']==0
    assert read('safety-edge-after.results.json')['exit_code']==0
    result = dict(status='PASS', selected=len(inventory), executed=len(executions), passed=len(passed),
        failures=0, errors=0, skips=0, xfail=0,
        ids=sorted(inventory), shard_receipts=receipts, coverage_by_id=coverage,
        all_ids_on_final_source=False, final_source_revalidated=len(final_passed),
        prototype_only_passed=len(passed-final_passed),
        preserved_first_attempt=dict(executed=len(first_inventory),passed=len(first_passed),failures=1,
            failed_ids=first_failures,classification='FIXTURE_SETUP_FAILURE_RECOVERED_IN_FINAL_REVALIDATION'),
        accepted_failures_definition='No unresolved failing ID; preserved first-attempt and probe failures remain in original receipts',
        new_ids=sorted(t for t in inventory if 'test_e4_claim_yield.' in t or 'test_e4_yield_processes.' in t))
    return result


def main():
    labels = ['baseline-base-v2','baseline-blocked','ablation-no-noisy','ablation-no-pause',
              'ablation-batch-three','ablation-fast-provider','candidate-bounded-yield','postfix-base','postfix-blocked',
              'postfix-final-base','postfix-final-blocked']
    summary = dict(baseline=BASELINE, classification='DIAGNOSTIC_ONLY', root_cause='ROOT_CAUSE_CONFIRMED',
        measurements={label:summarize(label) for label in labels},
        formal_profile_rerun=False, profile_integral_result='NOT_RUN', historical_profile='FAIL',
        b9e='FAIL_HISTORICAL', b9='IN_PROGRESS', production_activation=False)
    reg = regression()
    if reg:
        (OUT/'regression-summary.json').write_text(json.dumps(reg,indent=2)+'\n',encoding='utf-8')
        summary['regression'] = {k:v for k,v in reg.items() if k not in ('ids','shard_receipts','coverage_by_id')}
    summary['refinement']=read('refinement.json')
    summary['final_measurements']=['postfix-final-base','postfix-final-blocked']
    summary['performance_state']='DIAGNOSTIC_GATE_GREEN' if all(summary['measurements'][s]['healthy_claim']['p95_seconds']<=10 for s in summary['final_measurements']) else 'PERFORMANCE_STOP'
    summary['prototype_measurements_not_final']=['postfix-base','postfix-blocked']
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    preflight = read('preflight.json')
    sources = {}
    for file, before in preflight['source_sha256'].items():
        actual = digest(ROOT/file)
        sources[file] = dict(baseline_sha256=before, final_sha256=actual, unchanged=actual==before)
        assert (actual!=before) == (file=='backend/apps/agent/worker.py'), file
    # Verify complete protected runtime/profile tree against Git, not just sampled hashes.
    # RTK's human diff filter adds headings to --name-only; proxy for machine parsing.
    changed = subprocess.check_output(['rtk','proxy','git','diff',BASELINE,'--name-only','--',
        'backend/apps/agent','backend/apps/channels','backend/apps/organizations',
        'backend/config','docs/evals/profile-beta-1-v1.json','docs/evals/profile-beta-1-methodology.md'],
        cwd=ROOT,text=True).splitlines()
    runtime_changes = [p for p in changed if '/tests/' not in p]
    assert runtime_changes==['backend/apps/agent/worker.py'], runtime_changes
    logs = sorted(OUT.glob('*.log'))
    private_artifacts = sorted({*logs,*OUT.glob('*.json'),*OUT.glob('*.jsonl')})
    # Closed technical event vocabulary may include words like response; forbid payload identifiers.
    leaks = []
    for path in private_artifacts:
        content = path.read_text(encoding='utf-8',errors='replace')
        for pattern in (r'\b52155\d{8,10}\b',r'(?i)authorization\s*[:=]\s*bearer\s+\S+',
                        r'\bsk-[A-Za-z0-9_-]{20,}\b',r'Mi perro está convulsionando',r'Otra consulta'):
            if re.search(pattern,content):
                leaks.append(dict(file=path.name, pattern=pattern))
    validation = dict(protected_sources=sources, runtime_changed_paths=runtime_changes,
        source_hash_projection='raw checkout bytes; protected baseline/final compared on same host',
        privacy=dict(log_files_scanned=len(logs),total_artifacts_scanned=len(private_artifacts),matches=leaks,
            scope='log/JSON/JSONL fixture phone, credential and content sentinels; no production metrics or payload traces'),
        diagnostic_gate_eligible_for_optional_profile=summary['performance_state']=='DIAGNOSTIC_GATE_GREEN' and bool(reg),
        formal_profile_rerun=False, migrations_added=False)
    assert not leaks, leaks
    (OUT/'validation.json').write_text(json.dumps(validation,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(measurements={k:{field:v[field] for field in ('healthy_claim','margin','gates',
        'near_ready_noisy_applicable','near_ready_noisy_applicable_claims','ordinary_llm_admissions',
        'max_sampled_pending_inbound','maximum_durable_ordinary_processing_by_org')} for k,v in summary['measurements'].items()},
        regression=summary.get('regression'),validation=validation),indent=2))


if __name__=='__main__':
    main()
