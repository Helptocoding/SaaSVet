"""Prepare a new authorized namespace without reusing any formal results."""
import hashlib
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIOR = HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r6')
WORK = '/home/lap/b9i-wsl-1947726-20261011-r7'

def save(name, value):
    target = HERE / name
    assert not target.exists(), name
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def main():
    assert not (HERE / 'authorization.json').exists()
    assert json.loads((PRIOR / 'cleanup.json').read_text())['state'] == 'PASS'
    assert json.loads((PRIOR / 'delivery-verification.json').read_text())['state'] == 'PASS'
    save('authorization.json', {
        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'user_instruction': 'continua, estara despierto',
        'host_awake_assurance': 'User confirms host will remain awake during execution',
        'inherited_resource_authorization': 'procede con lo disponible actual, no puedo liberar mas aun',
        'authorized_scope': 'New campaign of the same candidate and fixed scope; retain all previous stops. Same amended 2 GiB admission/execution reserve, original disk and clock gates, no formal retries within this campaign.',
        'candidate_sha': '194772677ca4e9fe1a1dec7f4dafa48396a6c583',
        'Windows_W32Time_changes_authorized': False,
        'product_workload_assertion_changes_authorized': False,
        'commit_push_deploy_activation_authorized': False})
    names = ['b9-integral-acceptance-1947726', 'b9-integral-acceptance-1947726-wsl-20261011']
    names += ['b9-integral-acceptance-1947726-wsl-20261011-r' + str(i) for i in range(2, 7)]
    save('prior-evidence-before.json', {
        file.relative_to(REPO).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for name in names for file in HERE.with_name(name).rglob('*') if file.is_file()})
    for file in sorted(PRIOR.glob('*.py')):
        if file.name == 'initialize_campaign.py':
            continue
        source = file.read_text(encoding='utf-8').replace('/home/lap/b9i-wsl-1947726-20261011-r6', WORK)
        if file.name in ('preseal.py', 'preseal_prepare.py'):
            source = source.replace("'b9-integral-acceptance-1947726-wsl-20261011-r5'", repr(PRIOR.name))
            source = source.replace('diff_from_r5', 'diff_from_r6')
        if file.name in ('deliver_wsl.py', 'clock_setup.py'):
            source = source.replace('r6-', 'r7-').replace('WSL r6:', 'WSL r7:')
        compile(source, str(HERE / file.name), 'exec')
        (HERE / file.name).write_text(source, encoding='utf-8', newline='\n')
    policy = json.loads((PRIOR / 'resource-policy.json').read_text(encoding='utf-8'))
    policy.update(resumption_instruction='continua, estara despierto', host_awake_assurance=True)
    save('resource-policy.json', policy)
    adaptations = json.loads((PRIOR / 'assembly-adaptations.json').read_text(encoding='utf-8'))
    adaptations.update(new_workspace=WORK, host_awake_assurance='User confirms awake host; global power policy unchanged',
        evaluator_changes_from_r6='Namespace and evidence lineage only; same persistent observer and guards')
    save('assembly-adaptations.json', adaptations)
    previous_plan = (PRIOR / 'PLAN.md').read_text(encoding='utf-8')
    body = previous_plan[previous_plan.index('Autorización:'):]
    body = body.replace('Las seis campañas anteriores se conservan.', 'Las siete campañas anteriores se conservan.')
    (HERE / 'PLAN.md').write_text(
        '# B9E — campaña WSL2 r7, continuación autorizada\n\n'
        'Nueva instrucción: «continua, estara despierto». Se conservan las siete campañas anteriores. '
        'El usuario confirma que el host permanecerá despierto; la política global de energía y W32Time no cambian. '
        'Se mantienen el mismo candidato, alcance fijo, recursos autorizados y todos los gates de contrato. '
        'El evaluador conserva las adaptaciones previas de r6: ambos intérpretes privados con el mismo lock, '
        'observador persistente de memoria Windows y captura Git sin refresco opcional del índice. '
        'No se transfieren resultados anteriores ni se permiten reintentos formales después de un STOP.\n\n'
        + body, encoding='utf-8')
    print('INITIALIZED_AUTHORIZED_CAMPAIGN_R7', flush=True)

if __name__ == '__main__':
    main()
