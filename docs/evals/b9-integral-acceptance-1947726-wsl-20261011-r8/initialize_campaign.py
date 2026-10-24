"""Prepare the authorized r8 namespace, retaining all earlier evidence."""
import hashlib
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIOR = HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r7')
WORK = '/home/lap/b9i-wsl-1947726-20261011-r8'

def save(name, value):
    target = HERE / name
    assert not target.exists(), name
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def main():
    assert not (HERE / 'authorization.json').exists()
    assert json.loads((PRIOR / 'cleanup.json').read_text())['state'] == 'PASS'
    assert json.loads((PRIOR / 'delivery-verification.json').read_text())['state'] == 'PASS'
    save('authorization.json', {
        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'user_instruction': 'prosigue',
        'authorized_scope': 'New campaign of the same candidate and fixed scope, incorporating the previously proposed bounded own-thread Windows awake request before seal. All previous stops retained; no formal retries within this campaign.',
        'inherited_resource_authorization': 'procede con lo disponible actual, no puedo liberar mas aun',
        'resource_policy': 'Same amended 2 GiB admission/execution reserve; original disk and clock gates',
        'candidate_sha': '194772677ca4e9fe1a1dec7f4dafa48396a6c583',
        'temporary_owned_awake_request_authorized': True,
        'global_power_policy_changes_authorized': False,
        'Windows_W32Time_changes_authorized': False,
        'product_workload_assertion_changes_authorized': False,
        'commit_push_deploy_activation_authorized': False})
    names = ['b9-integral-acceptance-1947726', 'b9-integral-acceptance-1947726-wsl-20261011']
    names += ['b9-integral-acceptance-1947726-wsl-20261011-r' + str(i) for i in range(2, 8)]
    save('prior-evidence-before.json', {
        file.relative_to(REPO).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for name in names for file in HERE.with_name(name).rglob('*') if file.is_file()})
    for file in sorted(PRIOR.glob('*.py')):
        if file.name == 'initialize_campaign.py':
            continue
        source = file.read_text(encoding='utf-8').replace('/home/lap/b9i-wsl-1947726-20261011-r7', WORK)
        if file.name in ('preseal.py', 'preseal_prepare.py'):
            source = source.replace("'b9-integral-acceptance-1947726-wsl-20261011-r6'", repr(PRIOR.name))
            source = source.replace('diff_from_r6', 'diff_from_r7')
        if file.name in ('deliver_wsl.py', 'clock_setup.py'):
            source = source.replace('r7-', 'r8-').replace('WSL r7:', 'WSL r8:')
        compile(source, str(HERE / file.name), 'exec')
        (HERE / file.name).write_text(source, encoding='utf-8', newline='\n')
    awake = (PRIOR / 'diagnostics/awake_guard.py').read_text(encoding='utf-8')
    awake = awake.replace('Prepared after r7 STOP for a future campaign.', 'Prepared before the r8 seal for this authorized campaign.')
    (HERE / 'awake_guard.py').write_text(awake, encoding='utf-8', newline='\n')
    policy = json.loads((PRIOR / 'resource-policy.json').read_text(encoding='utf-8'))
    policy.update(resumption_instruction='prosigue', host_awake_assurance='Bounded own-thread request, live heartbeat checked before and during formal blocks')
    save('resource-policy.json', policy)
    adaptations = json.loads((PRIOR / 'assembly-adaptations.json').read_text(encoding='utf-8'))
    adaptations.pop('evaluator_changes_from_r6', None)
    adaptations.update(new_workspace=WORK,
        host_awake_assurance='Bounded SetThreadExecutionState request with heartbeat, checked before and during blocks, released on closure; global power policy unchanged',
        evaluator_changes_from_r7='Namespace/lineage, owned awake-request liveness check, and fail-closed observer exception handling. Original product/test workloads, gates and time limits retained.')
    save('assembly-adaptations.json', adaptations)
    previous_plan = (PRIOR / 'PLAN.md').read_text(encoding='utf-8')
    body = previous_plan[previous_plan.index('Autorización:'):]
    body = body.replace('Las siete campañas anteriores se conservan.', 'Las ocho campañas anteriores se conservan.')
    (HERE / 'PLAN.md').write_text(
        '# B9E — campaña WSL2 r8, continuación con protección temporal\n\n'
        'Nueva instrucción: «prosigue», después de proponer la integración de una protección temporal. '
        'Se conservan las ocho campañas anteriores. Antes del sello se adquiere una solicitud propia de '
        'SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED), con límite de seis horas y cierre explícito. '
        'Un heartbeat de un segundo confirma la solicitud en su hilo; su vigencia se comprueba antes de cada bloque '
        'y cada cinco segundos durante su ejecución, con antigüedad máxima de diez segundos. '
        'La política global de energía, pantalla y W32Time permanecen intactas. La solicitud no garantiza evitar '
        'suspensión manual/tapa/botón ni overrides de política. Los gates originales de reloj, memoria e integridad '
        'siguen siendo la autoridad; si una sonda deja de estar disponible, se detiene el grupo propio y se conserva PENDING. '
        'No se cambian producto, tests, fixtures, cargas, tiempos ni aserciones. No se transfieren resultados anteriores.\n\n'
        + body, encoding='utf-8')
    print('INITIALIZED_AUTHORIZED_CAMPAIGN_R8', flush=True)

if __name__ == '__main__':
    main()
