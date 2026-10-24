"""Resume the authorized acceptance work in a fresh immutable namespace."""
import hashlib
import json
from pathlib import Path
import time

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
PRIOR=HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r5')
WORK='/home/lap/b9i-wsl-1947726-20261011-r6'

def save(name,data):
    (HERE/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    assert not (HERE/'authorization.json').exists()
    save('authorization.json',{'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'user_instruction':'reanuda','inherited_resource_authorization':'procede con lo disponible actual, no puedo liberar mas aun',
        'authorized_scope':'Resume the same candidate and scope as a new campaign; preserve all previous stops. Same explicitly amended admission and original 2 GiB execution reserve; no formal retries inside the new campaign.',
        'candidate_sha':'194772677ca4e9fe1a1dec7f4dafa48396a6c583',
        'Windows_W32Time_changes_authorized':False,'product_workload_assertion_changes_authorized':False,
        'commit_push_deploy_activation_authorized':False})
    folders=[HERE.with_name(n) for n in ('b9-integral-acceptance-1947726','b9-integral-acceptance-1947726-wsl-20261011',
        'b9-integral-acceptance-1947726-wsl-20261011-r2','b9-integral-acceptance-1947726-wsl-20261011-r3',
        'b9-integral-acceptance-1947726-wsl-20261011-r4',PRIOR.name)]
    save('prior-evidence-before.json',{p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in folders for p in folder.rglob('*') if p.is_file()})
    for name in ('prepare_wsl.py','stage_wsl.py','host_resources.py','discover_candidate.py','recorded_suite.py',
        'run_campaign.py','launch_campaign.py','restore_wsl.py','cleanup_linux.py','capture_wsl.py','preseal.py',
        'deliver_wsl.py','interpreter_preflight.py','clock_setup.py','preseal_prepare.py','prepare_sequence.py'):
        source=(PRIOR/name).read_text(encoding='utf-8')
        source=source.replace('/home/lap/b9i-wsl-1947726-20261011-r5',WORK)
        if name in ('preseal.py','preseal_prepare.py'):
            source=source.replace("'b9-integral-acceptance-1947726-wsl-20261011-r4'",repr(PRIOR.name)).replace('diff_from_r4','diff_from_r5')
        if name in ('deliver_wsl.py','clock_setup.py'):
            source=source.replace('r5-','r6-').replace('WSL r5:','WSL r6:')
        if name=='prepare_wsl.py':
            source=source.replace("run('git','status','--porcelain=v1','-uall')","run('git','--no-optional-locks','status','--porcelain=v1','-uall')")
        if name=='stage_wsl.py':
            begin=source.index('def host_resources():')
            end=source.index('\ndef main():',begin)
            source=source[:begin]+'''def host_resources():
    # Same Windows GlobalMemoryStatusEx API; persistent owned observer avoids
    # launching a fresh Windows interpreter for every resource sample.
    import time
    path=EVIDENCE/'resource-observer/samples.jsonl'
    with path.open('rb') as stream:
        stream.seek(0,2);size=stream.tell();stream.seek(max(0,size-8192))
        raw=stream.read()
    complete=raw.rsplit(b'\\n',1)[0].splitlines()
    if not complete:
        raise RuntimeError('Host resource observer has no complete sample')
    row=json.loads(complete[-1])
    if abs(time.time()-row['utc_epoch_seconds'])>10:
        raise RuntimeError('Host resource observer sample stale or clock mismatch')
    return row
''' +source[end:]
        if name=='run_campaign.py':
            source=source.replace("EVIDENCE/'assembly-adaptations.json',EVIDENCE/'resource-policy.json',", "EVIDENCE/'assembly-adaptations.json',EVIDENCE/'resource-policy.json',EVIDENCE/'resource-observer-control.json',")
        (HERE/name).write_text(source,encoding='utf-8',newline='\n')
        compile(source,str(HERE/name),'exec')
    policy=json.loads((PRIOR/'resource-policy.json').read_text(encoding='utf-8'))
    policy.update(resumption_instruction='reanuda',host_measurement='Same GlobalMemoryStatusEx API; persistent private Windows Python observer, 1-second samples; fail closed if latest sample is older than 10 seconds')
    save('resource-policy.json',policy)
    adaptations=json.loads((PRIOR/'assembly-adaptations.json').read_text(encoding='utf-8'))
    adaptations.update(new_workspace=WORK,
        host_probe='Persistent owned Windows Python 3.13.2, same host_resources.py/GlobalMemoryStatusEx via runpy, one-second samples and ten-second freshness limit; no assertion about cause of earlier memory fluctuations',
        git_snapshot='git status --no-optional-locks to avoid optional index refresh across Windows/WSL; same status inventory')
    save('assembly-adaptations.json',adaptations)
    prior_plan=(PRIOR/'PLAN.md').read_text(encoding='utf-8')
    body=prior_plan[prior_plan.index('Autorización:'):]
    (HERE/'PLAN.md').write_text('# B9E — campaña WSL2 r6, reanudación autorizada\n\n'
        'Nueva instrucción: «reanuda». Se conservan las seis campañas anteriores. '
        'Se hereda la excepción de memoria autorizada en r5, sin reducir nuevamente ningún límite. '
        'La sonda Windows consulta la misma API mediante un proceso privado persistente, con muestras cada segundo '
        'y rechazo de muestras con antigüedad mayor de 10 s. Esto reduce arranques repetidos de intérpretes, '
        'sin atribuirles la causa de la fluctuación observada. El estado Git se captura sin refrescar opcionalmente el índice. '
        'Ambas adaptaciones son previas al sello y no cambian producto, tests, fixtures, cargas, tiempos ni aserciones.\n\n'
        +body.replace('Las cinco campañas anteriores se conservan.','Las seis campañas anteriores se conservan.'),encoding='utf-8')
    print('INITIALIZED_AUTHORIZED_CAMPAIGN_R6')

if __name__=='__main__':
    main()
