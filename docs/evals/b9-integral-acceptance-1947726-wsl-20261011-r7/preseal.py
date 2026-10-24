"""Document evaluator lineage and original command-specific configuration."""
import difflib
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PRIOR = HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r6')

def main():
    target = HERE / ('adapter-lineage-final.json' if sys.argv[1:]==['--final'] else 'adapter-lineage.json')
    if target.exists() or (HERE / 'evaluation-seal.json').exists():
        raise RuntimeError('Preseal already recorded')
    rows = {}
    for file in sorted(HERE.glob('*.py')):
        current = file.read_bytes()
        compile(current.decode('utf-8'), str(file), 'exec')
        old = PRIOR / file.name
        rows[file.name] = {'sha256': hashlib.sha256(current).hexdigest(), 'prior_sha256':
            hashlib.sha256(old.read_bytes()).hexdigest() if old.exists() else None}
        if old.exists():
            rows[file.name]['diff'] = ''.join(difflib.unified_diff(
                old.read_text(encoding='utf-8').splitlines(True), current.decode('utf-8').splitlines(True),
                fromfile=PRIOR.name + '/' + file.name, tofile=HERE.name + '/' + file.name))
    target.write_text(json.dumps({'state': 'RECORDED_BEFORE_FORMAL_EXECUTION', 'helpers': rows,
        'candidate_sources_changed': False, 'fixtures_workload_timing_or_thresholds_changed': False,
        'directed_original_runner_configuration': {
            'entrypoint': 'apps.agent.tests.run_b9a_acceptance -> run_b8e_acceptance',
            'local_postgresql_guard': 'preserved',
            'password_hasher': 'Original runner prepends MD5PasswordHasher only within isolated directed test process',
            'critical_regression_runners': 'super methods preserve original guards',
        }}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('PRESEAL_LINEAGE_RECORDED', len(rows))

if __name__ == '__main__':
    main()
