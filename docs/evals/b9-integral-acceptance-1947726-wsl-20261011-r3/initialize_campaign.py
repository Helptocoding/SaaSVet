"""Prepare the conditionally authorized campaign after clock isolation passes."""
import hashlib
import json
from pathlib import Path
import shutil
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIOR = HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r2')
ISOLATION = Path('C:/Users/LAP/AppData/Local/Temp/b9-clock-isolation-gp1mngqo')
BASELINE = Path('C:/Users/LAP/AppData/Local/Temp/b9-clock-diagnostic-ry8snt_d')

def save(name, data):
    (HERE / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def main():
    if (HERE / 'authorization.json').exists():
        raise RuntimeError('Already initialized')
    result = json.loads((ISOLATION / 'summary.json').read_text(encoding='utf-8'))
    assert result['exit_codes'] == {'windows': 0, 'wsl': 0}
    assert all(v['elapsed_seconds'] >= 120 and v['max_absolute_wall_minus_monotonic_seconds'] <= 1
               for v in result['surfaces'].values())
    assert json.loads((ISOLATION / 'service-paused.json').read_text(encoding='utf-8'))['state'] == 'PASS'
    assert not (ISOLATION / 'service-restored.json').exists()
    save('authorization.json', {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'user_instruction': 'procede',
        'authorized_scope': 'Temporarily pause Ubuntu/WSL time synchronizer; compare clocks; run a new campaign only if stable and adequately resourced; restore service at closure',
        'clock_observation_condition': 'PASS; 120 seconds, original 1-second discontinuity limit retained',
        'candidate_sha': '194772677ca4e9fe1a1dec7f4dafa48396a6c583',
        'Windows_W32Time_or_host_clock_configuration_changes_authorized': False,
        'product_fixtures_load_timings_or_gate_changes_authorized': False,
        'commit_push_deploy_activation_authorized': False})
    folders = [HERE.with_name(name) for name in ('b9-integral-acceptance-1947726',
        'b9-integral-acceptance-1947726-wsl-20261011', 'b9-integral-acceptance-1947726-wsl-20261011-r2')]
    save('prior-evidence-before.json', {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in folders for p in folder.rglob('*') if p.is_file()})
    for name in ('prepare_wsl.py', 'stage_wsl.py', 'host_resources.py', 'discover_candidate.py',
                 'recorded_suite.py', 'run_campaign.py', 'launch_campaign.py', 'restore_wsl.py',
                 'cleanup_linux.py', 'capture_wsl.py', 'preseal.py'):
        source = (PRIOR / name).read_text(encoding='utf-8')
        source = source.replace('/home/lap/b9i-wsl-1947726-20261011-r2', '/home/lap/b9i-wsl-1947726-20261011-r3')
        if name == 'preseal.py':
            source = source.replace("'b9-integral-acceptance-1947726-wsl-20261011'", "'b9-integral-acceptance-1947726-wsl-20261011-r2'")
        if name == 'run_campaign.py':
            source = source.replace("'frontend-smoke:urls'", "'frontend-smoke-urls'")
            source = source.replace("label='frontend-'+task", "label='frontend-'+task.replace(':','-')")
            source = source.replace("EVIDENCE/'adapter-lineage.json',", "EVIDENCE/'adapter-lineage.json',EVIDENCE/'clock-control.json',")
            source = source.replace("def verify(label):\n    integrity(label)",
                "def verify(label):\n    validate_clock_control()\n    integrity(label)")
            source = source.replace('class StopCampaign(Exception):', '''def validate_clock_control():
    config=json.loads((EVIDENCE/'clock-control.json').read_text())
    process=Path('/proc')/str(config['guard_pid'])/'cmdline'
    if not process.exists() or config['guard_source_linux'].encode() not in process.read_bytes():
        stop('PENDING','clock-control','Clock service guardian unavailable')
    current=subprocess.check_output([str(RTK),'proxy','systemctl','show','systemd-timesyncd.service',
        '--property=ActiveState,UnitFileState'],stdin=subprocess.DEVNULL,text=True)
    if 'ActiveState=inactive' not in current or 'UnitFileState='+config['initial_enabled'] not in current:
        stop('PENDING','clock-control','Approved temporary clock service configuration changed')

class StopCampaign(Exception):''')
        (HERE / name).write_text(source, encoding='utf-8', newline='\n')
    for label, folder in (('baseline', BASELINE), ('paused', ISOLATION)):
        target = HERE / 'clock-diagnostics' / label
        target.mkdir(parents=True)
        for name in ('probe.py', 'observe.py', 'windows.jsonl', 'wsl.jsonl', 'summary.json'):
            shutil.copy2(folder / name, target / name)
        if label == 'paused':
            for name in ('guard.py', 'service-before.json', 'service-stop-command.json', 'service-paused.json'):
                shutil.copy2(folder / name, target / name)
    before = json.loads((ISOLATION / 'service-before.json').read_text(encoding='utf-8'))
    save('clock-control.json', {'guard_pid': before['pid'],
        'guard_source_linux': '/mnt/c/Users/LAP/AppData/Local/Temp/b9-clock-isolation-gp1mngqo/guard.py',
        'guard_source_sha256': hashlib.sha256((ISOLATION / 'guard.py').read_bytes()).hexdigest(),
        'initial_active': before['initial_active'], 'initial_enabled': before['initial_enabled'],
        'authorized_temporary_state': 'systemd-timesyncd.service inactive; enabled state unchanged',
        'restoration_required': True, 'windows_W32Time_untouched': True,
        'isolation_summary_sha256': hashlib.sha256((ISOLATION / 'summary.json').read_bytes()).hexdigest(),
        'baseline_max_skew_seconds': 1.511376911,
        'paused_max_skew_seconds': result['surfaces']['wsl']['max_absolute_wall_minus_monotonic_seconds'],
        'observation_limit': 'Two-minute observation; ongoing original clock monitor remains authoritative'})
    plan = (folders[0] / 'PLAN.md').read_text(encoding='utf-8')
    (HERE / 'PLAN.md').write_text('# B9E — campaña WSL2 r3 con aislamiento horario autorizado\n\n'
        'Autorización: «procede», después de la propuesta de pausar temporalmente el sincronizador de Ubuntu/WSL, '
        'comprobar estabilidad y ejecutar una campaña nueva solo si pasa y hay recursos. '
        'La comparación de 120 segundos pasó. El servicio se restaurará al cierre. '
        'W32Time y la configuración horaria de Windows permanecen intactos. '
        'Mismo SHA, alcance, fixtures, cargas, tiempos, gates y límites. Las tres campañas anteriores se preservan.\n\n'
        + plan[plan.index('## Objetivo y alcance acordado'):], encoding='utf-8')
    save('assembly-adaptations.json', {'new_workspace': '/home/lap/b9i-wsl-1947726-20261011-r3',
        'clock_configuration': 'Explicitly authorized temporary Ubuntu/WSL service pause; original monitor and 1-second limit retained',
        'receipt_path_portability': 'Frontend smoke task stays smoke:urls; evidence label uses frontend-smoke-urls to avoid NTFS colon filename',
        'conservation': 'Independent inventory and recovery; batch Git blob verification; preserve unified diff context spaces',
        'product_test_fixture_timing_load_or_gate_changes': False})
    print('INITIALIZED_NEW_AUTHORIZED_CAMPAIGN_R3')

if __name__ == '__main__':
    main()
