"""Prepare the approved case-only continuation using the existing frozen runtime."""
import ast
import hashlib
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
PRIOR = HERE.with_name('b9-correction-20261017-native-r6')
REPO = HERE.parents[2]
SHA = '68dffd746793700071f577a58528b0f9636930db'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    target = HERE / name
    assert not target.exists(), target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def main():
    assert not (HERE / 'native_support.py').exists()
    proposal = HERE / 'RESUMPTION-PROPOSAL.md'
    proof = PRIOR / 'diagnostics/resumption-20261019/prefix-validation.json'
    assert digest(proof) == '51bed99c98bc8683f2764c841076f6ea47288fe339608fd122c4b405ba9e21db'
    save('case-resumption-authorization.json', {
        'state': 'USER_AUTHORIZED_BEFORE_FORMAL_SEAL',
        'recorded_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'user_reply': 'Sí, continuar con esa limitación',
        'question': '¿Autorizas la propuesta de continuar solo con los 728 casos pendientes y las etapas restantes, conservando los 2483 PASS, con una limitación explícita de cierre por el monitor histórico de disco/reloj perdido? Las nuevas ejecuciones mantendrán todos los guards; el informe no afirmará que ese registro ausente existe.',
        'candidate_tree': SHA, 'proposal_sha256': digest(proposal),
        'prefix_validation_sha256': digest(proof),
        'accepted_historical_evidence_limitation': True,
        'retained_pass': 2483, 'retained_expected_skips': 2, 'remaining': 728,
        'source_invocation_exit_code': None,
        'missing_historical_disk_clock_monitor_is_claimed': False,
        'all_new_resource_clock_awake_guards_required': True,
        'assertions_workload_gates_concurrency_changes': False,
        'product_runtime_lock_changes': False,
        'commits_push_deploy_activation_authorized': False})
    copied = []
    excluded = {'bootstrap.py', 'composite_evidence.py'}
    for source in sorted(PRIOR.glob('*.py')):
        if source.name in excluded:
            continue
        target = HERE / source.name
        assert not target.exists(), target
        raw = source.read_bytes()
        target.write_bytes(raw)
        copied.append({'path': source.name, 'source': '../' + PRIOR.name + '/' + source.name,
                       'source_sha256': digest(source), 'sha256': digest(target)})
    # Historical preparation metadata is explicitly referenced, never rerun or relabeled.
    names = ['PLAN.md', 'scope-manifest.json', 'resource-policy.json', 'prior-focused-verification.json',
        'candidate-input.json', 'candidate.json', 'correction-input.diff', 'correction.diff',
        'candidate-sources.json', 'toolchain.json', 'python-environment.json', 'base-python-environment.json',
        'dependency-files.json', 'interpreter-preflight.json', 'private-python-copy.json', 'frontend-layout.json',
        'security-history.json', 'install-cache-retirement.json', 'fixture-clock-authorization.json',
        'fixture-resumption-amendment.json', 'downloads.json', 'audit-toolchain.json',
        'profile-compatibility.json', 'effective-configuration.json', 'code-selection.json', 'checkout-before.json',
        'full-partition-contract.json', 'full-partition.json', 'discovery.json', 'discovery-skip-annotations.json',
        'diagnostics/verify_fixture_clock.py', 'diagnostics/fixture-clock-focused-check.json',
        'diagnostics/verify_preserved_contract.py', 'diagnostics/composite-validator-checks.json']
    names += [p.name for p in PRIOR.glob('*-selected.json')]
    names += ['private-postgresql/postgresql.conf', 'private-postgresql/pg_hba.conf']
    metadata = {}
    for name in dict.fromkeys(names):
        source, target = PRIOR / name, HERE / name
        assert source.is_file() and not target.exists(), name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        metadata[name] = {'source': '../' + PRIOR.name + '/' + name, 'sha256': digest(source),
                          'application_tests_executed_here': False}
    save('prepared-runtime-references.json', {'state': 'REFERENCED_PREPARATION',
        'runtime_reinstalled': False, 'source_reexported': False,
        'current_integrity_proof': '../' + PRIOR.name + '/diagnostics/resumption-20261019/prefix-validation.json',
        'proof_sha256': digest(proof), 'files': metadata})
    assembly = json.loads((PRIOR / 'assembly.json').read_text(encoding='utf-8'))
    assembly.update(phase='PREPARING_CASE_CONTINUATION',
        runtime_handoff_from='../' + PRIOR.name, runtime_reinstalled=False)
    save('assembly.json', assembly)
    save('authorization.json', {'user': 'Sí, continuar con esa limitación', 'candidate_tree': SHA,
        'scope': 'Only 728 missing cases and remaining original stages; accepted historical monitor limitation',
        'proof': 'case-resumption-authorization.json', 'product_runtime_changes': False,
        'maximum_formal_runs_per_new_selection': 1, 'commits_push_deploy_activation_authorized': False})
    save('resumption.json', {'state': 'AUTHORIZED_CASE_ONLY_COMPOSITE_SUCCESSOR', 'candidate_tree': SHA,
        'source_campaign': PRIOR.name, 'accepted_historical_evidence_limitation': True,
        'authorization': 'case-resumption-authorization.json', 'retained_pass': 2483,
        'retained_skips': 2, 'remaining_cases': 728, 'reused_complete_blocks': 13,
        'workspace': assembly['workspace'], 'runtime_reinstalled': False,
        'source_reexported': False, 'wsl_invoked': False, 'copied_helpers': copied,
        'continuous_campaign_claimed': False})
    amendment = json.loads((PRIOR / 'composite-amendment.json').read_text(encoding='utf-8'))
    amendment.update(user='Sí, continuar con esa limitación',
        case_resumption_authorization='case-resumption-authorization.json',
        interrupted_block_resume='Only 728 IDs without outcome; 2483 PASS and 2 expected skips retained under accepted historical evidence limitation',
        full_general_partial_reused_as_PASS=True,
        accepted_historical_evidence_limitation=True,
        prior_amendment='../' + PRIOR.name + '/composite-amendment.json')
    save('composite-amendment.json', amendment)
    policy = json.loads((HERE / 'resource-policy.json').read_text(encoding='utf-8'))
    policy.update(case_resumption_authorization='case-resumption-authorization.json')
    (HERE / 'resource-policy.json').write_text(json.dumps(policy, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    with (HERE / 'PLAN.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n\n## Continuación de casos autorizada con limitación histórica\n\n'
            'El usuario aprobó «Sí, continuar con esa limitación» a RESUMPTION-PROPOSAL.md. '
            'Se conservan 2483 PASS y dos skips previstos de r6 y se ejecutan solamente '
            'los 728 IDs sin resultado. Se conserva el estado interrumpido y el exit code '
            'desconocido de r6; su monitor histórico de disco/reloj no existe. Esta carencia '
            'se acepta expresamente como condición de evidencia enmendada. No se afirma '
            'una ejecución continua del grupo ni la existencia de ese registro. Todos los '
            'bloques restantes, cinco perfiles y guards nuevos mantienen su contrato. '
            'El monitor nuevo persiste RAM, disco y reloj cada segundo. Referencia: '
            'case-resumption-authorization.json. Producto, assertions, locks y cargas sin cambios.\n')
    controller = HERE / 'run_campaign.py'
    text = controller.read_text(encoding='utf-8')
    text = text.replace('    validate_references()\n    integrity(label)',
        '    validate_references()\n    from case_resumption import validate_case_references\n    validate_case_references()\n    integrity(label)')
    text = text.replace("'authorization.json','candidate.json'", "'case-resumption-authorization.json','case-resumption-manifest.json','case-resumption-validation.json',\n        'RESUMPTION-PROPOSAL.md','prepared-runtime-references.json','authorization.json','candidate.json'")
    needle = "        code = execute(label, [PYTHON, '-B', EVIDENCE/'recorded_suite.py', label, group['database']],"
    replacement = """        if label == 'full-general':
            tail = 'full-general-remainder'
            code = execute(tail, [PYTHON, '-B', EVIDENCE/'run_remainder.py'],
                env={'B9I_SUITE': tail, 'B9I_ID_JOURNAL': str(BLOCKS/(tail+'.ids.jsonl')),
                     'B9I_SUITE_RECEIPT': str(BLOCKS/(tail+'.results.json'))})
            check_suite(tail, code)
            code = execute('full-general-assemble', [PYTHON, '-B', EVIDENCE/'case_resumption.py', 'assemble'])
            if code:
                stop('PENDING', label, 'Case evidence assembly invalid', exit_code=code)
            check_suite(label, 0)
            continue
""" + needle
    assert text.count(needle) == 1
    text = text.replace(needle, replacement)
    text = text.replace("'activation':'PENDING_ACTIVATION_REQUIREMENTS'", "'accepted_historical_evidence_limitation':True,\n        'acceptance_label':'PASS_BAJO_CONDICION_DE_EVIDENCIA_ENMENDADA',\n        'activation':'PENDING_ACTIVATION_REQUIREMENTS'")
    controller.write_text(text, encoding='utf-8', newline='\n')
    finalize = HERE / 'finalize_preflight.py'
    text = finalize.read_text(encoding='utf-8').replace('b9-correction-20261017-native-r5', PRIOR.name)
    text = text.replace("'native-r5/'", "'native-r6/'")
    finalize.write_text(text, encoding='utf-8', newline='\n')
    # The original eight protected controller/partition functions remain byte-equivalent ASTs.
    protected = {'run_campaign.py': ('execute', 'check_suite', 'budget', 'gate', 'create_db'),
                 'full_partition.py': ('build_partition', 'projected_groups', 'validate_partition')}
    for name, functions in protected.items():
        def nodes(path):
            return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef)}
        original, current = nodes(PRIOR / name), nodes(HERE / name)
        assert all(original[n] == current[n] for n in functions), name
    save('operational-lifetime-amendment.json', {'state': 'AUTHORIZED_BOUNDED_FRESH_SEGMENT',
        'authorization': 'case-resumption-authorization.json', 'awake_maximum_seconds': 43200,
        'observer_maximum_seconds': 46800, 'heartbeat_seconds': 1,
        'maximum_sample_age_seconds': 10, 'adaptive_renewal': False,
        'explicit_restoration_required': True, 'global_power_policy_changes': False})
    prior = {}
    for folder in HERE.parent.iterdir():
        if folder.is_dir() and folder != HERE and (folder.name.startswith('b9-correction-') or folder.name.startswith('b9-integral-acceptance-1947726')):
            prior.update({p.relative_to(REPO).as_posix(): digest(p) for p in folder.rglob('*')
                          if p.is_file() and '__pycache__' not in p.parts})
    save('prior-evidence-before.json', prior)
    print('CASE_RESUMPTION_PREPARED_NO_TESTS', len(copied), len(prior), flush=True)


if __name__ == '__main__':
    main()
