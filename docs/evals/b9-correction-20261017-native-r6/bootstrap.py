"""Prepare the authorized fixture-only successor without changing product gates."""
import ast
import hashlib
import json
from pathlib import Path
import socket
import subprocess

HERE = Path(__file__).resolve().parent
PRIOR = HERE.with_name('b9-correction-20261017-native-r5')
OLD_TREE = '196aceb4f5f234c086b96d8e8af93787613f3c25'
NEW_TREE = '68dffd746793700071f577a58528b0f9636930db'
USER = 'Sí, corregir y continuar conservando lo válido'

SETUP = r'''def setup():
    assert not WORK.exists() and not (EVIDENCE / 'authorization.json').exists()
    assert resources()['disk_available'] >= 3 * GIB
    assert json.loads((EVIDENCE / 'candidate-input.json').read_text(encoding='utf-8'))['candidate_tree'] == SHA
    WORK.mkdir()
    for name in ('downloads', 'rtk-config', 'tool-data', 'tool-config', 'cache', 'pnpm-home'):
        (WORK / name).mkdir()
    for name in ('empty.npmrc', 'empty-global.npmrc'):
        (WORK / name).write_text('', encoding='utf-8')
    for name in ('PLAN.md', 'scope-manifest.json', 'resource-policy.json', 'prior-focused-verification.json'):
        (EVIDENCE / name).write_bytes((NATIVE_PRIOR / name).read_bytes())
    for target, source in (('candidate.json', 'candidate-input.json'), ('correction.diff', 'correction-input.diff')):
        (EVIDENCE / target).write_bytes((EVIDENCE / source).read_bytes())
    scope = json.loads((EVIDENCE / 'scope-manifest.json').read_text(encoding='utf-8'))
    for key in ('candidate_sha', 'candidate_tree'):
        if scope.get(key) == '196aceb4f5f234c086b96d8e8af93787613f3c25':
            scope[key] = SHA
    scope['fixture_clock_equivalence'] = 'fixture-clock-authorization.json'
    save('scope-manifest.json', scope)
    with (EVIDENCE / 'PLAN.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n\n## Corrección temporal y reuso acotado autorizados, 2026-10-17\n\n'
            'El usuario autorizó «Sí, corregir y continuar conservando lo válido». '
            'El candidato 68dffd746793700071f577a58528b0f9636930db difiere del '
            '196aceb4f5f234c086b96d8e8af93787613f3c25 únicamente en '
            'backend/apps/notifications/tests/test_notifications.py: imports estándar '
            'y un decorador mock que fija mediodía UTC solo durante test_upcoming_window. '
            'El cuerpo, los IDs, assertions, validadores y constraint siguen idénticos. '
            'Los otros 3331 blobs, producto, dependencias y locks no cambian. '
            'Esta autorización sustituye exclusivamente la exigencia de mismo SHA para '
            'trece bloques PASS cuya selección no ejecuta ese método y cuya equivalencia '
            'se verifica antes del sello; no permite otros cambios ni omisiones. '
            'Se conservan once bloques ya referenciados y full-b8d/full-b8e de native-r5 '
            '(369 IDs únicos; 118 IDs de full), con su candidato probado y el candidato '
            'aceptado explícitos. El grupo general parcial y su ERROR temporal e incidente '
            'de vigilia permanecen como evidencia no aprobada. Se ejecutan completos los '
            '3213 IDs de general y luego frontend, seguridad, auditorías y cinco perfiles '
            'con sus migraciones, cargas, tiempos 30/300/20 y gates originales. '
            'Antes del sello se permite una comprobación de desarrollo del método '
            'corregido, sin crédito formal y sin sustituir el grupo general completo. '
            'La aceptación es compuesta; no se afirma una campaña continua. '
            'Referencias: fixture-clock-authorization.json, fixture-resumption-amendment.json, '
            'reuse-manifest.json y reuse-validation.json. Reservas 2 GiB RAM/1 GiB disco, '
            'reloj 1s, auxiliares acotados 12h/13h sin renovación adaptativa y restauración '
            'explícita. No se autorizan commits, push, despliegue ni activación.\n')
    policy = json.loads((EVIDENCE / 'resource-policy.json').read_text(encoding='utf-8'))
    policy.update(resumption_instruction='Sí, corregir y continuar conservando lo válido',
                  fixture_clock_authorization='fixture-clock-authorization.json')
    save('resource-policy.json', policy)
    save('authorization.json', {'user': 'Sí, corregir y continuar conservando lo válido',
        'date_local': '2026-10-17', 'scope': 'Fixture-only successor with bounded verified reuse',
        'candidate_tree': SHA, 'previous_candidate_tree': '196aceb4f5f234c086b96d8e8af93787613f3c25',
        'prior_campaign': NATIVE_PRIOR.name, 'prior_decision': 'PENDING_FIXTURE_AND_AWAKE_INCIDENT',
        'maximum_formal_runs_per_block': 1, 'maximum_formal_runs_per_profile_variant': 1,
        'authorized_fixture_correction': 'fixture-clock-authorization.json',
        'further_test_or_product_changes': False, 'product_runtime_changes': False,
        'commits_push_deploy_activation_authorized': False})
    contract = json.loads((NATIVE_PRIOR / 'full-partition-contract.json').read_text(encoding='utf-8'))
    assert contract['candidate_tree'] == '196aceb4f5f234c086b96d8e8af93787613f3c25'
    contract['candidate_tree'] = SHA
    save('full-partition-contract.json', contract)
    for name in ('recorded_suite.py', 'full_partition.py', 'awake_guard.py', 'awake_status.py',
                 'host_resources.py', 'host_observer.py'):
        (EVIDENCE / name).write_text((NATIVE_PRIOR / name).read_text(encoding='utf-8'),
                                    encoding='utf-8', newline='\n')
    source = (PRIOR / 'discover_candidate.py').read_text(encoding='utf-8')
    begin = source.index('os.environ.update(')
    end = source.index('\nimport django', begin)
    source = source[:begin] + 'from native_support import environment\nos.environ.update(environment())' + source[end:]
    source = source.replace("encoding='utf-8')\n\n\nscope", "encoding='utf-8', newline='\\n')\n\n\nscope")
    source = source.replace('196aceb4f5f234c086b96d8e8af93787613f3c25', SHA)
    (EVIDENCE / 'discover_candidate.py').write_text(source, encoding='utf-8', newline='\n')
    prior = {}
    for folder in EVIDENCE.parent.iterdir():
        if folder.is_dir() and folder != EVIDENCE and (folder.name.startswith('b9-correction-') or folder.name.startswith('b9-integral-acceptance-1947726')):
            prior.update({p.relative_to(REPO).as_posix(): sha256(p.read_bytes())
                          for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts})
    save('prior-evidence-before.json', prior)
    assemble_native()
'''


def write_json(name, value):
    (HERE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n',
                             encoding='utf-8', newline='\n')


def main():
    assert not (HERE / 'native_support.py').exists()
    assert json.loads((PRIOR / 'native-closure.json').read_text(encoding='utf-8'))['state'] == 'PASS'
    assert json.loads((PRIOR / 'delivery-verification.json').read_text(encoding='utf-8'))['state'] == 'PASS'
    decision = json.loads((PRIOR / 'final-classification.json').read_text(encoding='utf-8'))
    assert decision['decision'] == 'PENDING' and not decision['product_failure_established']
    assert not Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6').exists()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 35490))
    candidate = json.loads((HERE / 'candidate-input.json').read_text(encoding='utf-8'))
    assert candidate['candidate_tree'] == NEW_TREE
    copied = []
    for source in sorted(PRIOR.glob('*.py')):
        if source.name in ('bootstrap.py', 'composite_evidence.py'):
            continue
        target = HERE / source.name
        assert not target.exists(), target
        text = source.read_text(encoding='utf-8')
        for old, new in [('20261017-native-r5', '20261017-native-r6'),
                         ('b9-native-20261017-r5', 'b9-native-20261017-r6'),
                         ('35489', '35490'), (OLD_TREE, NEW_TREE),
                         ('nativo r5', 'nativo r6'), ('nativa r5', 'nativa r6')]:
            text = text.replace(old, new)
        if source.name == 'prepare_native.py':
            tree = ast.parse(text)
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'setup')
            lines = text.splitlines(True)
            text = ''.join(lines[:node.lineno - 1]) + SETUP + '\n' + ''.join(lines[node.end_lineno:])
            text = text.replace("NATIVE_PRIOR = EVIDENCE.with_name('b9-correction-20261016-native-r3')",
                                "NATIVE_PRIOR = EVIDENCE.with_name('b9-correction-20261017-native-r5')")
        elif source.name == 'finalize_preflight.py':
            text = text.replace("prior = EVIDENCE.with_name('b9-correction-20261016-native-r3')",
                                "prior = EVIDENCE.with_name('b9-correction-20261017-native-r5')")
            text = text.replace("fromfile='native-r3/'", "fromfile='native-r5/'")
            text = text.replace('../b9-correction-20261016-native-r3/native-preflight.json',
                                '../b9-correction-20261017-native-r5/native-preflight.json')
            text = text.replace("'referenced_pass_blocks': 11", "'referenced_pass_blocks': 13")
        elif source.name == 'run_campaign.py':
            text = text.replace("'historical_pass_blocks_referenced':11", "'historical_pass_blocks_referenced':13")
            text = text.replace("'composite-amendment.json','reuse-manifest.json','reuse-validation.json',",
                                "'composite-amendment.json','reuse-manifest.json','reuse-validation.json',\n"
                                "        'fixture-clock-authorization.json','fixture-resumption-amendment.json',\n"
                                "        'diagnostics/verify_fixture_clock.py','diagnostics/fixture-clock-focused-check.json',")
            text = text.replace("    validate_clock_control()\n    discovery=", "    validate_clock_control()\n"
                "    assert json.loads((EVIDENCE/'diagnostics/fixture-clock-focused-check.json').read_text(encoding='utf-8'))['state']=='PASS'\n"
                "    discovery=")
        ast.parse(text, filename=str(target))
        compile(text, str(target), 'exec')
        assert all(line == line.rstrip() for line in text.splitlines()), target
        target.write_text(text, encoding='utf-8', newline='\n')
        copied.append({'path': source.name,
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    write_json('resumption.json', {'state': 'AUTHORIZED_FIXTURE_ONLY_COMPOSITE_SUCCESSOR',
        'user': USER, 'date_local': '2026-10-17', 'previous_campaign': PRIOR.name,
        'previous_decision': decision, 'source_candidate_tree': OLD_TREE,
        'candidate_tree': NEW_TREE, 'authorized_fixture': 'fixture-clock-authorization.json',
        'product_runtime_changes': False, 'reused_blocks': 13,
        'reused_unique_ids': 369, 'reused_full_ids': 118,
        'prior_formal_results_copied_as_current': False, 'continuous_campaign_claimed': False,
        'general_partial_reused_as_PASS': False, 'wsl_invoked': False,
        'new_workspace': 'C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6',
        'private_postgresql_port': 35490, 'copied_helpers': copied})
    write_json('fixture-resumption-amendment.json', {'state': 'USER_AUTHORIZED_BEFORE_SEAL',
        'user': USER, 'date_local': '2026-10-17', 'source_candidate_tree': OLD_TREE,
        'candidate_tree': NEW_TREE, 'exception': 'Only the exact authorized fixture-clock patch',
        'proof': 'fixture-clock-authorization.json', 'reused_blocks': 13,
        'reused_unique_ids': 369, 'reused_full_ids': 118,
        'entire_general_required': 3213, 'test_assertions_ids_guards_changed': False,
        'product_runtime_locks_changes': False, 'no_valid_FAIL_discarded': True,
        'all_profile_variants_and_original_gates_required': True,
        'continuous_campaign_claimed': False})
    amendment = {
        'state': 'USER_AUTHORIZED_BEFORE_FORMAL_SEAL', 'date_local': '2026-10-17',
        'user': USER, 'evidence_mode': 'COMPOSITE_ACCEPTANCE',
        'continuous_campaign_claimed': False, 'candidate_tree': NEW_TREE,
        'source_candidate_tree': OLD_TREE,
        'supersedes': 'Only the same-candidate requirement for the exact approved fixture patch and the existing composite restart exception',
        'historical_pass_source_plan': {
            'b9-correction-20261016-native-r4': ['directed', 'django-check', 'migration-drift', 'migrate', 'billing-schema'],
            'b9-correction-20261016-native-r3': ['b0', 'b3', 'b4', 'b5', 'full-b8b', 'full-b8c'],
            'b9-correction-20261017-native-r5': ['full-b8d', 'full-b8e']},
        'reference_validation': 'reuse-manifest.json and reuse-validation.json',
        'reference_copies_are_current_executions': False, 'reference_scope': 'Backend only',
        'frontend_all_checks_executed_here': True,
        'valid_failure_can_be_discarded_or_retried': False,
        'interrupted_block_resume': 'Whole block, distinct new receipt, after environment revalidation',
        'fixture_clock_exception': 'fixture-clock-authorization.json',
        'other_app_sources_tests_fixtures_locks_gates_loads_changed': False,
        'profile_warmup_measurement_drain_seconds': [30, 300, 20],
        'referenced_pass_blocks': 13, 'reused_unique_ids': 369, 'reused_full_ids': 118,
        'full_general_partial_reused_as_PASS': False,
        'prior_amendment': '../' + PRIOR.name + '/composite-amendment.json',
        'superseding_authorization': 'fixture-resumption-amendment.json'}
    write_json('composite-amendment.json', amendment)
    write_json('operational-lifetime-amendment.json', {
        'state': 'USER_AUTHORIZED_BEFORE_FORMAL_SEAL', 'user': USER,
        'date_local': '2026-10-17', 'awake_maximum_seconds': 43200,
        'observer_maximum_seconds': 46800, 'heartbeat_seconds': 1,
        'maximum_sample_age_seconds': 10, 'adaptive_renewal': False,
        'explicit_restoration_required': True, 'global_power_policy_changes': False,
        'reference': 'fixture-resumption-amendment.json',
        'helper_sha256': {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                          for name in ('awake_guard.py', 'host_observer.py')}})
    print('FIXTURE_ONLY_NATIVE_SUCCESSOR_PREPARED', len(copied), NEW_TREE, flush=True)


if __name__ == '__main__':
    main()
