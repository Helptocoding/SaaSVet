"""Create the newly authorized campaign without changing earlier evidence."""
import hashlib
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIOR = HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011')

def save(name, value):
    (HERE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def main():
    if (HERE / 'authorization.json').exists():
        raise RuntimeError('Campaign already initialized')
    save('authorization.json', {
        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'user_instruction': 'procede',
        'decision': 'New WSL campaign with corrected bootstrap after prior preflight stop',
        'candidate_sha': '194772677ca4e9fe1a1dec7f4dafa48396a6c583',
        'prior_campaign_immutable': PRIOR.name,
        'same_scope_gates_resources_and_single_run_limits': True,
        'commit_push_deploy_activation_authorized': False,
    })
    save('prior-evidence-before.json', {
        str(p.relative_to(REPO)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in (PRIOR, HERE.with_name('b9-integral-acceptance-1947726'))
        for p in folder.rglob('*') if p.is_file()
    })
    for name in ('prepare_wsl.py', 'stage_wsl.py', 'host_resources.py', 'discover_candidate.py',
                 'recorded_suite.py', 'run_campaign.py', 'launch_campaign.py',
                 'restore_wsl.py', 'deliver_wsl.py'):
        source = (PRIOR / name).read_text(encoding='utf-8')
        if name == 'prepare_wsl.py':
            source = source.replace("WORK = Path('/home/lap/b9i-wsl-1947726-20261011')",
                                    "WORK = Path('/home/lap/b9i-wsl-1947726-20261011-r2')")
            start = source.index("    for name in ('discover_candidate.py','recorded_suite.py'):")
            end = source.index("    print('ASSEMBLED:", start)
            source = source[:start] + '    # Helpers and authorized plan are prepared before assembly, then sealed.\n' + source[end:]
        if name == 'run_campaign.py':
            source = source.replace("if not all(value is True for value in result['gates'].values()):",
                                    "if result.get('technical_pass') is not True or not all(value is True for value in result['gates'].values()):")
        if name == 'launch_campaign.py':
            source = source.replace('    from run_campaign import run_all',
                                    '    from run_campaign import run_all, StopCampaign')
            source = source.replace('    run_all()\n', '''    try:
        run_all()
    except StopCampaign:
        raise SystemExit(2)
    except Exception as exc:
        save('controller-incident.json', {'type': type(exc).__name__, 'message': str(exc)})
        if not (EVIDENCE / 'STOP.json').exists():
            save('STOP.json', {'state': 'PENDING', 'phase': 'controller', 'cause': str(exc), 'no_rerun': True})
        raise
''')
        (HERE / name).write_text(source, encoding='utf-8', newline='\n')
    plan = (HERE.with_name('b9-integral-acceptance-1947726') / 'PLAN.md').read_text(encoding='utf-8')
    (HERE / 'PLAN.md').write_text(
        '# B9E — campaña nueva WSL2, intento autorizado r2\n\n'
        'Autorización: «procede», después de explicar el cierre PENDING anterior y el requisito de una nueva decisión. '
        'Se usa launch_campaign.py con el entorno cargado antes de Django. Se preservan ambas campañas anteriores. '
        'Mismo candidato, alcance, gates, presupuesto y límites; sin commit, push, despliegue ni activación.\n\n'
        + plan[plan.index('## Objetivo y alcance acordado'):], encoding='utf-8')
    save('assembly-adaptations.json', {
        'new_workspace': '/home/lap/b9i-wsl-1947726-20261011-r2',
        'bootstrap': 'Environment loaded before importing Django; durable stop on exceptions',
        'profile_validation': 'Honor the original runner technical_pass, including generator errors',
        'product_test_fixture_timing_load_or_gate_changes': False,
        'helper_sources_preserved_in_prior_campaign': True,
    })
    print('INITIALIZED_NEW_AUTHORIZED_CAMPAIGN')

if __name__ == '__main__':
    main()
