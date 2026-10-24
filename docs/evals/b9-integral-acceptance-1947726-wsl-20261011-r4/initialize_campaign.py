"""Initialize the newly authorized campaign without touching prior evidence."""
import hashlib
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIOR = HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r3')
WORK = '/home/lap/b9i-wsl-1947726-20261011-r4'

def save(name, data):
    (HERE / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def main():
    if (HERE / 'authorization.json').exists():
        raise RuntimeError('Already initialized')
    save('authorization.json', {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'user_instruction': 'hazlo',
        'authorized_scope': 'Prepare identical locked application dependencies for private venv and its private base Python, validate both before sealing, then execute a new fixed campaign with previously authorized temporary WSL clock isolation and restoration',
        'candidate_sha': '194772677ca4e9fe1a1dec7f4dafa48396a6c583',
        'Windows_W32Time_or_host_clock_configuration_changes_authorized': False,
        'product_fixtures_load_timings_or_gate_changes_authorized': False,
        'commit_push_deploy_activation_authorized': False})
    folders = [HERE.with_name(name) for name in ('b9-integral-acceptance-1947726',
        'b9-integral-acceptance-1947726-wsl-20261011',
        'b9-integral-acceptance-1947726-wsl-20261011-r2', PRIOR.name)]
    save('prior-evidence-before.json', {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in folders for p in folder.rglob('*') if p.is_file()})
    for name in ('prepare_wsl.py', 'stage_wsl.py', 'host_resources.py', 'discover_candidate.py',
                 'recorded_suite.py', 'run_campaign.py', 'launch_campaign.py', 'restore_wsl.py',
                 'cleanup_linux.py', 'capture_wsl.py', 'preseal.py', 'deliver_wsl.py'):
        source = (PRIOR / name).read_text(encoding='utf-8')
        source = source.replace('/home/lap/b9i-wsl-1947726-20261011-r3', WORK)
        if name == 'preseal.py':
            source = source.replace("'b9-integral-acceptance-1947726-wsl-20261011-r2'", repr(PRIOR.name))
        if name == 'capture_wsl.py':
            source = source.replace("args = {", "args = {\n        'assemble': ['/usr/bin/python3', '-B', LINUX + '/prepare_wsl.py', 'assemble'],\n        'interpreters': [WORK + '/tools/rtk', 'proxy', WORK + '/venv/bin/python', '-B', LINUX + '/interpreter_preflight.py'],")
        if name == 'prepare_wsl.py':
            needle = "    command('pip-check',[PYTHON,'-m','pip','check'])"
            assert source.count(needle) == 1
            source = source.replace(needle, needle + '''
    # Legacy process tests select sys._base_executable. Prepare that private prefix
    # from the identical lock before sealing; no candidate or interpreter redirect.
    prefix = base.resolve().parent.parent
    assert prefix.is_relative_to((WORK/'python').resolve()) and prefix != (WORK/'python').resolve()
    command('base-python-dependencies',[PYTHON,'-m','pip','install','--prefix',prefix,
        '--ignore-installed','--no-cache-dir','-r',TREE/'backend/requirements.lock'])
    command('base-python-pip-check',[WORK/'uv/uv','pip','check','--python',base])
    metadata_code = "import importlib.metadata as m,json,sys,sysconfig; print(json.dumps(dict(executable=sys.executable,base_executable=sys._base_executable,prefix=sys.prefix,site_packages=sysconfig.get_path('purelib'),packages=sorted([dict(name=d.metadata['Name'],version=d.version) for d in m.distributions()],key=lambda x:x['name'].lower()))))"
    save('base-python-environment.json',json.loads(run(base,'-B','-c',metadata_code)))
''')
        if name == 'run_campaign.py':
            needle = "def verify(label):\n    validate_clock_control()\n    integrity(label)"
            assert source.count(needle) == 1
            source = source.replace(needle, needle + '''
    dependencies=json.loads((EVIDENCE/'dependency-files.json').read_text())
    changed=[p for p,h in dependencies['files'].items() if not Path(p).is_file() or sha256(Path(p).read_bytes())!=h]
    save('dependency-check-'+label+'.json',{'checked':len(dependencies['files']),'mismatches':changed})
    if changed:
        stop('PENDING',label,'Sealed application dependencies changed',mismatches=changed)
''')
            needle = "    assert json.loads((EVIDENCE/'environment-ready.json').read_text())['state']=='READY_FOR_SEAL'"
            source = source.replace(needle, needle + "\n    assert json.loads((EVIDENCE/'interpreter-preflight.json').read_text())['state']=='PASS'")
            needle = "EVIDENCE/'adapter-lineage.json',EVIDENCE/'clock-control.json',"
            source = source.replace(needle, needle + "\n        EVIDENCE/'dependency-files.json',EVIDENCE/'interpreter-preflight.json',EVIDENCE/'base-python-environment.json',")
        (HERE / name).write_text(source, encoding='utf-8', newline='\n')
        compile(source, str(HERE / name), 'exec')
    plan = (folders[0] / 'PLAN.md').read_text(encoding='utf-8')
    (HERE / 'PLAN.md').write_text('# B9E — campaña WSL2 r4 con dependencias privadas corregidas\n\n'
        'Autorización: «hazlo», tras la decisión de preparar los dos intérpretes privados con las mismas dependencias congeladas, '
        'validarlos antes del sello y ejecutar una campaña nueva. Las cuatro campañas anteriores se conservan. '
        'La validación previa comprueba importaciones y configuración, sin ejecutar tests ni el contrato B3. '
        'Se mantiene la pausa temporal autorizada del sincronizador de WSL, con observación previa de 120 s y restauración al cierre. '
        'El guardián tiene una concesión máxima de 6 h para restaurar el servicio si el controlador desaparece; '
        'no cambia las duraciones de tests ni el límite de discontinuidad de 1 s. Windows W32Time permanece intacto. '
        'Mismo candidato, selección, fixtures, tasas, concurrencia, tiempos y gates.\n\n'
        + plan[plan.index('## Objetivo y alcance acordado'):], encoding='utf-8')
    save('assembly-adaptations.json', {'new_workspace': WORK,
        'dependency_remediation': 'Identical requirements.lock installed into private venv and its private base Python prefix before sealing; neither candidate code nor sys._base_executable redirected',
        'preseal_validation': 'Django setup, durable/worker/psycopg imports and package parity in both interpreters; no test execution or B3 claims/crashes/timeouts',
        'dependency_integrity': 'Both application site-packages hashed before seal and checked before/after every block',
        'clock_configuration': 'Authorized temporary WSL synchronization pause; 120-second observation and original continuous 1-second guard retained; guardian restoration lease 21600 seconds',
        'receipt_path_portability': 'Original smoke:urls task, frontend-smoke-urls evidence filename',
        'conservation': 'Independent inventory and recovery; batch Git blob verification; preserve prior staged files',
        'product_test_fixture_timing_load_or_gate_changes': False})
    print('INITIALIZED_NEW_AUTHORIZED_CAMPAIGN_R4')

if __name__ == '__main__':
    main()
