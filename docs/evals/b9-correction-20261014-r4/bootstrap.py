"""Prepare one new campaign; change only the previously incompatible assembly."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIOR = HERE.with_name('b9-correction-20261014-r3')
OLD_WORK = '/home/lap/b9i-correction-20261014-r3'
WORK = '/home/lap/b9i-correction-20261014-r4'


def save(name, data):
    target = HERE / name
    assert not target.exists(), name
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def adapt(source):
    return source.replace(OLD_WORK, WORK).replace('35483', '35484').replace(
        'corrected-20261014-r3', 'corrected-20261014-r4')


def replace_once(path, before, after):
    source = path.read_text(encoding='utf-8')
    assert source.count(before) == 1, (path.name, before)
    path.write_text(source.replace(before, after), encoding='utf-8', newline='\n')


def main():
    assert not (HERE / 'authorization.json').exists()
    for old in PRIOR.glob('*.py'):
        if old.name != 'bootstrap.py':
            target = HERE / old.name
            assert not target.exists(), target
            target.write_text(adapt(old.read_text(encoding='utf-8')), encoding='utf-8', newline='\n')
    for name in ('PLAN.md', 'scope-manifest.json', 'candidate.json', 'correction.diff',
                 'resource-policy.json', 'prior-focused-verification.json'):
        (HERE / name).write_bytes((PRIOR / name).read_bytes())
    with (HERE / 'PLAN.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n\n## Adaptación autorizada r4, 2026-10-14\n\n'
                     'El usuario pidió «procede a ajustar y ejecutar». Se conserva el árbol '
                     '196aceb4f5f234c086b96d8e8af93787613f3c25 y todo el contrato anterior. '
                     'La suite full se divide exhaustivamente en B8B (21), B8C (41), B8D (27), '
                     'B8E (29) y general (3213), en ese orden, con bases nuevas compatibles. '
                     'Cada ID se ejecuta una vez dentro de full; la unión debe ser exactamente '
                     'los 3331 IDs descubiertos. Se conservan runners nativos, procesos internos, '
                     'aserciones, guards, locks, cargas, tiempos, umbrales y reglas de skips. '
                     'La configuración y los inventarios se sellan antes de ejecutar. '
                     'El gate full exige todos los grupos completos y satisfactorios. '
                     'Sin reintentos formales ni transferencia de resultados históricos.\n')
    save('authorization.json', {
        'user': 'procede a ajustar y ejecutar', 'date_local': '2026-10-14',
        'scope': 'One fixed new campaign after correcting the full-suite database assembly',
        'prior_campaign': PRIOR.name, 'prior_decision': 'PENDING_HARNESS_INCOMPATIBILITY',
        'candidate_tree': '196aceb4f5f234c086b96d8e8af93787613f3c25',
        'further_candidate_corrections': False, 'maximum_formal_runs_per_block': 1,
        'maximum_formal_runs_per_profile_variant': 1,
        'product_assertions_gates_loads_and_times_changed': False,
        'commits_push_deploy_activation_authorized': False})
    specification = json.loads((PRIOR / 'next-assembly-remediation.json').read_text(encoding='utf-8'))
    assert specification['total_ids'] == 3331 and specification['duplicate_ids'] == 0
    assert not specification['missing_ids']
    save('full-partition-contract.json', {
        'candidate_tree': specification['candidate_tree'],
        'full_selection_sha256': specification['full_selection_sha256'],
        'guards': specification['guards'],
        'counts': {name: group['count'] for name, group in specification['groups'].items()},
        'order': ['b8b', 'b8c', 'b8d', 'b8e', 'general'],
        'sources_assertions_guards_loads_timings_thresholds_changed': False})
    for name in ('preseal.py', 'preseal_prepare.py'):
        replace_once(HERE / name, "'b9-correction-20261014-r2'", "'b9-correction-20261014-r3'")
    replace_once(HERE / 'stage_wsl.py',
                 "    files=['backend/apps/agent/tests/b9e_profile.py'",
                 "    from full_partition import build_partition\n    build_partition()\n"
                 "    files=['backend/apps/agent/tests/b9e_profile.py'")
    replace_once(HERE / 'recorded_suite.py',
                 "    runner = {'b0': RecordedB0Runner, 'b3': RecordedB3Runner,\n"
                 "              'b4': RecordedB4Runner, 'b5': RecordedB5Runner, 'full': RecordedFullRunner}[label]",
                 "    if label.startswith('full-'):\n"
                 "        from full_partition import validate_partition\n"
                 "        group = next(row for row in validate_partition()['groups'] if row['label'] == label)\n"
                 "        assert database == group['database']\n"
                 "        runner = RecordedFullRunner\n"
                 "    else:\n"
                 "        runner = {'b0': RecordedB0Runner, 'b3': RecordedB3Runner,\n"
                 "                  'b4': RecordedB4Runner, 'b5': RecordedB5Runner, 'full': RecordedFullRunner}[label]")
    controller = HERE / 'run_campaign.py'
    replace_once(controller, "    # Validate adapter syntax", 
                 "    from full_partition import validate_partition\n    validate_partition()\n"
                 "    # Validate adapter syntax")
    replace_once(controller, "'effective-configuration.json','code-selection.json'",
                 "'effective-configuration.json','code-selection.json',\n"
                 "        'full-partition-contract.json','full-partition.json'")
    replace_once(controller, "    if label!='full' and", 
                 "    full_family = label == 'full' or label.startswith('full-')\n"
                 "    if not full_family and")
    replace_once(controller, "    if label=='full':", "    if full_family:")
    replace_once(controller, "    for kind in ('b0','b3','b4','b5','full'):",
                 "    for kind in ('b0','b3','b4','b5'):")
    replace_once(controller, "    for task in ('build','test','lint','smoke:urls'):",
                 "    from full_partition import validate_partition, aggregate_full\n"
                 "    for group in validate_partition()['groups']:\n"
                 "        label = group['label']\n"
                 "        code = execute(label, [PYTHON, '-B', EVIDENCE/'recorded_suite.py', label, group['database']],\n"
                 "            env={'B9I_SUITE': label, 'B9I_ID_JOURNAL': str(BLOCKS/(label+'.ids.jsonl')),\n"
                 "                 'B9I_SUITE_RECEIPT': str(BLOCKS/(label+'.results.json'))})\n"
                 "        check_suite(label, code)\n"
                 "    aggregate_full()\n"
                 "    check_suite('full', 0)\n"
                 "    for task in ('build','test','lint','smoke:urls'):")
    replace_once(HERE / 'cleanup_linux.py',
                 "        assert all(n.startswith('test_b9i_') or n == 'test_b8b_b9i_directed' for n in names)",
                 "        from full_partition import validate_partition\n"
                 "        owned_full = {row['database'] for row in validate_partition()['groups']}\n"
                 "        assert all(n.startswith('test_b9i_') or n == 'test_b8b_b9i_directed' or n in owned_full for n in names)")
    # Diagnostics are separate from the frozen application and evaluator.
    (HERE / 'diagnostics').mkdir()
    for name in ('progress.py', 'close_acceptance.py'):
        source = adapt((PRIOR / 'diagnostics' / name).read_text(encoding='utf-8'))
        source = source.replace('B9 corregido r3 196aceb', 'B9 corregido r4 196aceb')
        source = source.replace('b9-correction-20261014-r3', 'b9-correction-20261014-r4')
        (HERE / 'diagnostics' / name).write_text(source, encoding='utf-8', newline='\n')
    candidate = json.loads((HERE / 'candidate.json').read_text(encoding='utf-8'))
    def git(*args):
        return subprocess.check_output(['rtk', 'proxy', 'git', *args], cwd=REPO)
    assert git('rev-parse', 'HEAD').decode().strip() == candidate['base_commit']
    assert git('cat-file', '-t', candidate['candidate_tree']).strip() == b'tree'
    assert git('diff', '--name-only', candidate['base_commit'], candidate['candidate_tree']).decode().splitlines() == candidate['changed_paths']
    hashes = {}
    for name in candidate['changed_paths']:
        blob = git('show', candidate['candidate_tree'] + ':' + name)
        assert git('show', ':' + name) == blob
        assert (REPO / name).read_bytes().replace(b'\r\n', b'\n') == blob
        hashes[name] = hashlib.sha256(blob).hexdigest()
    save('code-selection.json', {'state': 'PASS', 'explicit_paths': candidate['changed_paths'],
         'staged_code_equals_frozen_candidate_tree': True, 'staged_sha256': hashes,
         'commits_created': 0, 'pushes_performed': 0})
    helpers = {}
    for path in HERE.glob('*.py'):
        source = path.read_text(encoding='utf-8')
        compile(source, str(path), 'exec')
        old = PRIOR / path.name
        helpers[path.name] = {
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'prior_sha256': hashlib.sha256(old.read_bytes()).hexdigest() if old.exists() else None,
            'diff': ''.join(difflib.unified_diff(
                old.read_text(encoding='utf-8').splitlines(True) if old.exists() else [],
                source.splitlines(True), fromfile=str(old), tofile=str(path)))}
    save('campaign-adaptation.json', {'state': 'PREPARED_BEFORE_SEAL', 'helpers': helpers,
         'reason': 'Four mutually exclusive worker database-prefix guards in prior full assembly',
         'candidate_changed': False, 'assertions_gates_loads_and_times_changed': False,
         'changes': 'Five sequential native-runner full groups with compatible private bases; exact union and original gates; separate ownership and evidence'})
    print('NEW_CAMPAIGN_BOOTSTRAP_PASS')


if __name__ == '__main__':
    main()
