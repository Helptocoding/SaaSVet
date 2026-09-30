"""Collect completed receipts only; preserve failures and historical evidence."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/evals/w1-mono'
BASELINE = '623a80930883fd0473ac6fe4697a417f763dad4c'
source_fallback = {}


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def verify_source(path, sources):
    current = (ROOT/path).read_bytes()
    if path in sources:
        assert hashlib.sha256(current).hexdigest() == sources[path], path
        return
    if path in source_fallback:
        assert hashlib.sha256(current).hexdigest() == source_fallback[path]['current_raw_sha256'], path
        return
    # The inherited runner hashes the agent tree. Domain test modules outside
    # that tree are instead required to remain identical to both Git cuts.
    assert not path.startswith('backend/apps/agent/'), path
    normalized = current.replace(b'\r\n', b'\n')
    hashes = {}
    for revision in (BASELINE, '83285eb096a568dbeb1d67a5c98001dc0bee8352'):
        blob = subprocess.run(['rtk', 'proxy', 'git', 'cat-file', 'blob', revision+':'+path],
            cwd=ROOT, capture_output=True, check=True).stdout.replace(b'\r\n', b'\n')
        assert blob == normalized, path
        hashes[revision] = hashlib.sha256(blob).hexdigest()
    source_fallback[path] = dict(current_raw_sha256=hashlib.sha256(current).hexdigest(),
        current_lf_sha256=hashlib.sha256(normalized).hexdigest(), git_cut_lf_sha256=hashes)


def main():
    runs = {}
    accepted = set()
    for stem in ('targeted-v3', 'supplemental-v4', 'recovery-0', 'recovery-1', 'recovery-2'):
        result = read(stem + '.results.json')
        passed = {json.loads(line)['test_id'] for line in
            (OUT / (stem + '.results.passed.jsonl')).read_text(encoding='utf-8').splitlines()}
        inventory = set(result['test_ids'])
        assert result['tests'] == len(inventory) == len(passed)
        assert passed == inventory
        assert not any(result[key] for key in ('errors', 'failures', 'skips', 'xfail', 'exit_code'))
        runs[stem] = result | dict(passed_ids=sorted(passed))
        accepted.update(passed)
        sources = read(stem + '.results.sources.json')
        for path in {'backend/apps/agent/services.py', *(
                'backend/' + '.'.join(case.split('.')[:4]).replace('.', '/') + '.py'
                for case in passed)}:
            verify_source(path, sources)
    partial = read('regression-partial.json')
    prior = set(partial['accepted_completed_ids'])
    recovered = {case for name, result in runs.items() if name.startswith('recovery-')
                 for case in result['passed_ids']}
    assert prior.isdisjoint(recovered)
    assert prior | recovered == set(partial['expected_ids'])
    assert 'Traceback (most recent call last)' not in (OUT/'regression.log').read_text(encoding='utf-8')
    partial_sources = read(partial['source_receipt'])
    for path in {'backend/apps/agent/services.py', *(
            'backend/' + '.'.join(case.split('.')[:4]).replace('.', '/') + '.py' for case in prior)}:
        verify_source(path, partial_sources)
    runs['regression-completed-journal'] = partial
    accepted.update(prior)
    assert len(accepted) == 758
    assert sum(run['tests'] for name, run in runs.items()
        if name != 'regression-completed-journal') + len(prior) == len(accepted)
    (OUT/'domain-source-validation.json').write_text(json.dumps(dict(
        reason='Inherited source receipts hash the agent tree; these unchanged historical domain tests are checked against both Git cuts, normalized LF.',
        files=source_fallback), indent=2)+'\n', encoding='utf-8')
    journals = [json.loads(line) for path in OUT.glob('*.mono-processes.jsonl')
        for line in path.read_text(encoding='utf-8').splitlines()]
    pids = sorted({r['pid'] for r in journals if 'pid' in r})
    backends = sorted({r['backend_pid'] for r in journals if 'backend_pid' in r})
    checks = read('checks-final.exit.json')
    assert checks['exit_code'] == 0
    result = dict(schema='w1-monotonic-v1', baseline='623a80930883fd0473ac6fe4697a417f763dad4c',
        amendment_commit='2f259f4d21802d00e705c3f7fc71e7e26f5694fa',
        runtime_commit=read('validation.json')['runtime_commit'],
        classification='TECHNICAL_CANDIDATE', acceptance_profile_runs=int(any(OUT.glob('candidate-profile-*.json'))),
        runs=runs, accepted_unique_total=len(accepted), accepted_ids=sorted(accepted),
        new_ids=sorted(x for x in accepted if '.test_w1_mono' in x),
        skipped=0, xfail=0, pending_required_ids=[], checks=checks,
        process_pids=pids, backend_pids=backends,
        blocking_observations=[r for r in journals if r['event'] == 'PG_BLOCKING'],
        causality=[r for r in journals if r['event'] == 'READY_CAUSALITY'],
        excluded_attempts=read('excluded-attempts.json'),
        diagnostics={name: read(name+'.json') for name in ('diagnostic-base', 'diagnostic-blocked')},
        diagnostic_decision=read('diagnostic-decision.json'),
        production=dict(B0='CLOSED', B7B=False, execution_flags={}, release_grants=[],
            activated_clinics=0, activation='PENDING_ACTIVATION_REQUIREMENTS', deployed=False),
        B9='IN_PROGRESS', B9E='FAIL', historical_PROFILE_BETA_1='FAIL')
    result['artifact_sha256'] = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in OUT.iterdir() if p.is_file() and p.name != 'acceptance-results.json'}
    (OUT / 'acceptance-results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(unique_ids=len(accepted), new_ids=len(result['new_ids']),
        process_pids=len(pids), backend_pids=len(backends))))


if __name__ == '__main__':
    main()
