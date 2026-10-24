"""Continue only unexecuted security/audits/profiles on the unchanged candidate."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parents[1]
PRIOR = HERE.with_name('b9-correction-20261020-native-r11')
REPO = HERE.parents[2]
TREE = 'f5f18d71847a46d66644775cd90d30268f072e3b'
RTK = Path('C:/Users/LAP/.local/bin/rtk.exe')


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(name, data):
    p = HERE / name
    assert not p.exists(), p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def copy_inputs():
    assert read(PRIOR / 'invocation-formal.json')['exit_code'] == 2
    assert read(PRIOR / 'STOP.json')['phase'] == 'security'
    assert read(PRIOR / 'security-scopes.json')['scans'] == []
    assert read(PRIOR / 'candidate.json')['candidate_tree'] == TREE
    assert read(PRIOR / 'awake-request/closure.json')['matches_original_thread_state'] is True
    assert read(PRIOR / 'resource-observer-closure.json')['state'] == 'PASS'
    oldseal = read(PRIOR / 'evaluation-seal.json')
    assert all(Path(p).is_file() and sha(Path(p)) == h for p, h in oldseal['files'].items())
    for label in ('frontend-test-remainder', 'frontend-test-assemble', 'frontend-lint', 'frontend-smoke-urls', 'security'):
        assert read(PRIOR / ('integrity-after-' + label + '.json'))['mismatches'] == []
        assert read(PRIOR / ('dependency-check-after-' + label + '.json'))['mismatches'] == []
        assert read(PRIOR / ('seal-check-after-' + label + '.json'))['mismatches'] == []
    excluded = {'composite_evidence.py', 'run_campaign.py', 'retire_previous_cluster.py', 'handoff_runtime.py'}
    for p in PRIOR.glob('*.py'):
        if p.name in excluded:
            continue
        target = HERE / p.name
        assert not target.exists(), target
        text = p.read_text(encoding='utf-8')
        if p.name == 'deliver_native.py':
            text = text.replace('native-r11', 'native-r12').replace('native-20261020-r11', 'native-20261020-r12')
            anchor = "        f'docs/evals/{HERE.name}/referenced-selector-evidence/**/*.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\\n'"
            assert anchor in text
            text = text.replace(anchor, anchor + "\n        f'docs/evals/{HERE.name}/referenced-prefix-evidence/**/*.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\\n'")
        if p.name == 'finalize_preflight.py':
            text = text.replace('b9-correction-20261020-native-r10', PRIOR.name).replace('native-r10/', 'native-r11/')
        target.write_text(text, encoding='utf-8', newline='\n')
    derived = {'launcher-validation.json', 'postgresql-preflight.json', 'campaign-adaptation.json',
        'clock-preflight.json', 'native-preflight.json', 'environment-ready.json', 'receipt-adapter.diff',
        'adapter-validation.json', 'backend-reference-validation.json', 'security-history.json'}
    for name in oldseal['files']:
        source = Path(name)
        if not source.is_relative_to(PRIOR):
            continue
        relative = source.relative_to(PRIOR)
        if len(relative.parts) != 1 or source.suffix == '.py' or relative.name in derived:
            continue
        target = HERE / relative
        assert not target.exists(), target
        shutil.copy2(source, target)
    extra = ['checkout-before.json', 'discovery-skip-annotations.json',
        'private-postgresql/postgresql.conf', 'private-postgresql/pg_hba.conf',
        'diagnostics/fixture-clock-focused-check.json', 'diagnostics/verify_preserved_contract.py',
        'diagnostics/verify_evidence_contract.py', 'diagnostics/verify_frontend_equivalence.py',
        'diagnostics/verify_frontend_equivalence.cjs', 'diagnostics/frontend-fixture-ast-check.json',
        'diagnostics/frontend-fixture-original.jsx', 'diagnostics/verify_selector.py',
        'diagnostics/verify_selector.cjs', 'diagnostics/selector-discovery-check.json',
        'diagnostics/selection-discovery.json', 'diagnostics/selector-static-discovery.json',
        'diagnostics/planned-selector.json', 'selector-history-manifest.json']
    for name in extra:
        target = HERE / name
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PRIOR / name, target)
    original = read(PRIOR / 'security-history.json')
    observed = read(PRIOR / 'security-history-before.json')['current']
    assert original['head'] == observed['head'] == '194772677ca4e9fe1a1dec7f4dafa48396a6c583'
    assert original['is_shallow'] is observed['is_shallow'] is False
    removed = sorted(set(original['refs']) - set(observed['refs']))
    added = sorted(set(observed['refs']) - set(original['refs']))
    assert removed and added and all(p.startswith('refs/codex/turn-diffs/captures/') for p in removed + added)
    from_environment = dict(__import__('os').environ)
    def git(*args):
        return subprocess.check_output([str(RTK), 'proxy', 'git', *args], cwd=REPO,
            env=from_environment, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW).decode('utf-8').strip()
    current = {'head': git('rev-parse', 'HEAD'),
        'refs': sorted(git('for-each-ref', '--format=%(refname) %(objectname)').splitlines()),
        'is_shallow': git('rev-parse', '--is-shallow-repository') == 'true'}
    assert current == observed, 'Git history changed again during preparation'
    save('security-history.json', current)
    save('security-history-prior.json', original)
    save('security-history-resumption-decision.json', {'state': 'HARNESS_ONLY_HISTORY_REFRESH',
        'candidate_tree': TREE, 'source_candidate_tree': TREE, 'source_campaign': PRIOR.name,
        'no_source_change': True, 'no_PASS_reruns': True, 'user_request': 'continua donde te quedaste y no repitas test que ya pasaron',
        'reason': 'Only an internal Codex capture ref changed since the inherited snapshot; HEAD and all other refs are unchanged.',
        'refs_removed': removed, 'refs_added': added, 'HEAD_unchanged': True,
        'prior_scan_commands_executed': 0, 'prior_scans': [], 'original_STOP_preserved': True,
        'history_guard_unchanged': 'Exact complete HEAD/refs/shallow comparison before and after scanning remains mandatory.',
        'scan_arguments_and_security_gates_unchanged': True, 'current_history_frozen_before_new_seal': current,
        'frontend_cases_retained': 355, 'new_frontend_cases': 0, 'smoke_retained': True,
        'remaining': ['security', 'pip-audit', 'pnpm-audit', 'profile-base', 'profile-blocked_llm',
            'profile-meta_slow', 'profile-duplicate', 'profile-saturation'],
        'historical_evidence_limitation_accepted': True, 'continuous_campaign_claimed': False})
    save('completed-prefix-live-reference.json', {
        'state': 'PASS', 'candidate_tree': TREE, 'source_campaign': PRIOR.name,
        'guard_after_security': {name: sha(PRIOR / name) for name in (
            'integrity-after-security.json', 'dependency-check-after-security.json', 'seal-check-after-security.json')},
        'sources_and_dependencies_unchanged_after_last_formal_command': True,
        'new_seal_will_repeat_all_original_integrity_checks': True, 'application_tests_executed_here': False})
    save('resumption-current.json', {'state': 'REMAINING_SECURITY_AND_PROFILES_ONLY', 'candidate_tree': TREE,
        'source_campaign': PRIOR.name, 'retained_backend_ids': 3331, 'retained_frontend_PASS': 355,
        'new_frontend_cases': 0, 'runtime_reinstalled': False, 'no_PASS_reruns': True,
        'decision': 'security-history-resumption-decision.json'})
    with (HERE / 'PLAN.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n\n## Continuación limitada tras guard de referencias internas\n\n'
            'r11 conserva frontend 355 PASS (354 referenciados y un caso nuevo aprobado), '
            'smoke PASS y lint advisory. El guard de seguridad se detuvo antes de ejecutar '
            'Gitleaks porque cambió una captura interna de Codex desde el snapshot heredado; '
            'HEAD, referencias restantes y candidato permanecen iguales. Esta decisión congela '
            'el historial actual completo antes del nuevo sello y mantiene sin cambios el guard '
            'exacto previo/posterior y los argumentos del escáner. Solo se ejecutan seguridad, '
            'auditorías y los cinco perfiles pendientes, sin repetir ningún PASS. Se conserva '
            'la parada original y toda la limitación histórica aceptada. Sin activación ni commits.\n')
    print('R12_CURRENT_INPUTS_READY_NO_TESTS', flush=True)


def freeze():
    retired = read(HERE / 'previous-cluster-retirement.json')
    assert retired['state'] == 'PASS' and retired['previous_campaign'] == PRIOR.name
    assert sha(Path(retired['previous_log']['path'])) == retired['previous_log']['sha256']
    for name in ('referenced-completed-evidence', 'referenced-selector-evidence'):
        assert not (HERE / name).exists()
        shutil.copytree(PRIOR / name, HERE / name)
    bundle = HERE / 'referenced-prefix-evidence/r11'
    assert not bundle.exists()
    files = {}
    for source in sorted(PRIOR.rglob('*')):
        if not source.is_file() or '__pycache__' in source.parts:
            continue
        relative = source.relative_to(PRIOR)
        if relative.parts[0] in ('referenced-completed-evidence', 'referenced-selector-evidence'):
            continue
        target = bundle / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        wanted = sha(source)
        assert sha(target) == wanted
        files[relative.as_posix()] = {'sha256': wanted, 'bytes': source.stat().st_size}
    save('completed-prefix-manifest.json', {'schema': 'b9-completed-r11-prefix/1',
        'source_campaign': PRIOR.name, 'source_candidate_tree': TREE, 'candidate_tree': TREE,
        'bundle_relative': 'referenced-prefix-evidence/r11', 'files': files})
    prior = {}
    for folder in HERE.parent.iterdir():
        if folder.is_dir() and folder != HERE and (folder.name.startswith('b9-correction-') or
                folder.name.startswith('b9-integral-acceptance-1947726')):
            prior.update({p.relative_to(REPO).as_posix(): sha(p) for p in folder.rglob('*')
                if p.is_file() and '__pycache__' not in p.parts})
    save('prior-evidence-before.json', prior)
    print('R12_PREFIX_FROZEN', len(files), 'prior_files', len(prior), flush=True)


if __name__ == '__main__':
    {'copy': copy_inputs, 'freeze': freeze}[sys.argv[1]]()
