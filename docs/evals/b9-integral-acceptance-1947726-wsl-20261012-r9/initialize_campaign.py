"""Resume the unsealed r9 preparation after a new user instruction and resource recovery."""
import ctypes
import hashlib
import json
from pathlib import Path
import shutil
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIOR = HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r8')
WORK = '/home/lap/b9i-wsl-1947726-20261012-r9'


def save(name, value):
    target = HERE / name
    assert not target.exists(), name
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def main():
    for name in ('authorization.json', 'evaluation-seal.json', 'preflight.json', 'STOP.json',
                 'invocation-formal.json'):
        assert not (HERE / name).exists(), name
    assert json.loads((PRIOR / 'cleanup.json').read_text())['state'] == 'PASS'
    assert json.loads((PRIOR / 'delivery-verification.json').read_text())['state'] == 'PASS'
    history = HERE / 'preparation-history'
    history.mkdir()
    old_report = (HERE / 'REPORT.md').read_bytes()
    (history / 'REPORT-before-resumption.md').write_bytes(old_report)
    disk = shutil.disk_usage('C:/')._asdict()
    assert disk['free'] >= 2 * 1024**3, 'Preparation estimate and disk reserve unavailable'
    save('preparation-resumption.json', {
        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'user_instruction': 'prosige', 'disk_C': disk,
        'preserved_initial_readiness_report': 'preparation-history/REPORT-before-resumption.md',
        'preserved_initial_readiness_report_sha256': hashlib.sha256(old_report).hexdigest(),
        'earlier_stage': 'Read-only preparation blocked; no evaluator seal or formal execution',
        'readiness_rechecked_after_user_instruction': True,
        'formal_application_tests_executed': False, 'resource_guards_changed': False})
    save('authorization.json', {
        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'date_local': '2026-10-12', 'user_instruction': 'prosige',
        'authorized_scope': 'Resume previously unsealed r9 preparation after resources recovered, then one fixed-scope campaign of the same candidate. Preserve all previous stops and initial r9 readiness report.',
        'inherited_resource_authorization': 'procede con lo disponible actual, no puedo liberar mas aun',
        'resource_policy': 'Same 2 GiB admission/execution reserve, original 1 GiB backing disk reserve and 1-second clock guard',
        'candidate_sha': '194772677ca4e9fe1a1dec7f4dafa48396a6c583',
        'temporary_owned_awake_request_authorized': True,
        'global_power_policy_changes_authorized': False,
        'Windows_W32Time_changes_authorized': False,
        'product_workload_assertion_changes_authorized': False,
        'commit_push_deploy_activation_authorized': False})
    names = ['b9-integral-acceptance-1947726', 'b9-integral-acceptance-1947726-wsl-20261011']
    names += ['b9-integral-acceptance-1947726-wsl-20261011-r' + str(i) for i in range(2, 9)]
    save('prior-evidence-before.json', {
        file.relative_to(REPO).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for name in names for file in HERE.with_name(name).rglob('*') if file.is_file()})
    for file in sorted(PRIOR.glob('*.py')):
        if file.name == 'initialize_campaign.py':
            continue
        source = file.read_text(encoding='utf-8').replace('/home/lap/b9i-wsl-1947726-20261011-r8', WORK)
        if file.name in ('preseal.py', 'preseal_prepare.py'):
            source = source.replace("'b9-integral-acceptance-1947726-wsl-20261011-r7'", repr(PRIOR.name))
            source = source.replace('diff_from_r7', 'diff_from_r8')
        if file.name in ('deliver_wsl.py', 'clock_setup.py'):
            source = source.replace('r8-', 'r9-').replace('WSL r8:', 'WSL r9:')
        if file.name == 'awake_guard.py':
            source = source.replace('Prepared before the r8 seal', 'Prepared before the r9 seal')
        if file.name == 'run_campaign.py':
            source = source.replace("        EVIDENCE/'preseal-sleep-event-messages.json',",
                "        EVIDENCE/'preseal-sleep-event-messages.json',\n"
                "        EVIDENCE/'preparation-resumption.json',EVIDENCE/'preparation-history/REPORT-before-resumption.md',")
        compile(source, str(HERE / file.name), 'exec')
        assert not (HERE / file.name).exists(), file.name
        (HERE / file.name).write_text(source, encoding='utf-8', newline='\n')
    policy = json.loads((PRIOR / 'resource-policy.json').read_text(encoding='utf-8'))
    policy.update(resumption_instruction='prosige')
    save('resource-policy.json', policy)
    adaptations = json.loads((PRIOR / 'assembly-adaptations.json').read_text(encoding='utf-8'))
    adaptations.pop('evaluator_changes_from_r7', None)
    adaptations.update(new_workspace=WORK,
        evaluator_changes_from_r8='Namespace/lineage and sealed resumption provenance only. Same owned awake heartbeat and fail-closed resource monitor. No product, test, workload, timing, threshold or contract gate changes.')
    save('assembly-adaptations.json', adaptations)
    sleep = json.loads((PRIOR / 'preseal-sleep-event-messages.json').read_text(encoding='utf-8'))
    sleep.update(provenance='Preserved read-only diagnostic from r8; historical events, not a new query',
        source_campaign=PRIOR.name,
        source_sha256=hashlib.sha256((PRIOR / 'preseal-sleep-event-messages.json').read_bytes()).hexdigest())
    save('preseal-sleep-event-messages.json', sleep)
    previous_plan = (PRIOR / 'PLAN.md').read_text(encoding='utf-8')
    body = previous_plan[previous_plan.index('Autorización:'):]
    body = body.replace('Las ocho campañas anteriores se conservan.', 'Las nueve campañas anteriores se conservan.')
    (HERE / 'PLAN.md').write_text(
        '# B9E — campaña WSL2 r9 del 12-10-2026\n\n'
        'Nueva instrucción: «prosige», después de recuperar espacio real en C:. '
        'Se reanuda la preparación aún sin sellar; el reporte previo de falta de espacio se conserva '
        'en preparation-history/REPORT-before-resumption.md. Se preservan las nueve campañas anteriores. '
        'Antes del sello se adquiere una solicitud propia SetThreadExecutionState '
        '(ES_CONTINUOUS | ES_SYSTEM_REQUIRED), limitada a seis horas, con heartbeat de un segundo, '
        'comprobación antes de cada bloque y cada cinco segundos, antigüedad máxima de diez segundos '
        'y liberación explícita al cierre. No cambia política global, pantalla ni W32Time. '
        'No garantiza impedir suspensión manual, tapa, botón o políticas que prevalezcan. '
        'Todos los guards de reloj, recursos e integridad se conservan. '
        'No se cambian producto, tests, fixtures, tasas, tiempos, aserciones o gates; '
        'los resultados previos no se transfieren.\n\n' + body, encoding='utf-8')
    print('INITIALIZED_AUTHORIZED_CAMPAIGN_R9', flush=True)


if __name__ == '__main__':
    main()
