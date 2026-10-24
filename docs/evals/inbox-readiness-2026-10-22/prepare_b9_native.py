"""Private PostgreSQL16 and fixed 120-second clock observation before formal acceptance."""
import ctypes
import json
import socket
import time
from b9_runtime import *


def main():
    assert not (OUT/'b9-native-preflight.json').exists()
    assert json.loads((OUT/'b9-preparation.json').read_text())['state'] == 'PREPARED'
    host = resources()
    assert host['physical_available'] >= 2*GIB and host['disk_available'] >= GIB
    # Resume only the identified preparation pipe incident, never a formal run.
    incident = OUT/'b9-launcher-incident.json'
    if DATA.exists():
        assert incident.exists() and not (OUT/'b9-start.json').exists()
        assert int((DATA/'postmaster.pid').read_text().splitlines()[0]) == 28828
    else:
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', PORT)) != 0, 'Dedicated port already occupied'
        run(PG/'initdb.exe', '-D', DATA, '--username=b9e', '--auth=trust', '--encoding=UTF8', '--locale=C')
        # A file, instead of PIPE, prevents an inherited server handle from
        # keeping the Windows RTK wrapper open after pg_ctl has already exited.
        import subprocess
        with (WORK/'pg-start.log').open('wb') as log:
            subprocess.run([str(RTK),'proxy',str(PG/'pg_ctl.exe'),'-D',str(DATA),'-l',str(WORK/'postgres.log'),
                '-o',f'-p {PORT} -h 127.0.0.1','-w','start'],env=environment(),stdout=log,stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=60,check=True)
    save('b9-owned-cluster.json', dict(state='STARTED', data=str(DATA), port=PORT,
         ordinary_database_touched=False, pid=int((DATA/'postmaster.pid').read_text().splitlines()[0])))
    import psycopg
    with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True) as conn:
        row = conn.execute("SELECT version(), current_setting('data_directory'), current_setting('fsync'), current_setting('synchronous_commit'), current_setting('full_page_writes')").fetchone()
    assert row[0].startswith('PostgreSQL 16.15') and row[2:] == ('on','on','on')
    assert Path(row[1]).resolve() == DATA.resolve()
    save('b9-postgresql-preflight.json', dict(state='PASS', values=row, private_cluster=True, port=PORT))
    code = 'import sys,site,json,importlib.metadata as m; import django,psycopg; print(json.dumps(dict(version=sys.version,executable=sys.executable,base_executable=sys._base_executable,prefix=sys.prefix,site=site.getsitepackages(),django=django.__file__,psycopg=psycopg.__file__,packages={d.metadata["Name"].lower().replace("_","-"):d.version for d in m.distributions()})))'
    info = json.loads(run(PYTHON, '-c', code))
    expected = json.loads((OLD/'python-environment.json').read_text())
    assert info['version'] == expected['python_version']
    for name, version in expected['required_lock_versions'].items():
        assert info['packages'][name] == version, name
    assert all(Path(info[k]).resolve().is_relative_to((WORK/'python').resolve())
               for k in ('executable','base_executable','prefix','django','psycopg'))
    save('b9-interpreter-preflight.json', dict(state='PASS', **info))
    assert ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    origin, wall = time.monotonic(), time.time()
    samples = []
    try:
        while time.monotonic()-origin < 120:
            now, current = time.monotonic(), time.time()
            skew = abs((current-wall)-(now-origin))
            samples.append(skew)
            assert skew <= 1, 'Clock discontinuity'
            assert ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
            time.sleep(.5)
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    save('b9-clock-preflight.json', dict(state='PASS', elapsed_seconds=time.monotonic()-origin,
         samples=len(samples), max_absolute_wall_minus_monotonic_seconds=max(samples),
         host_clock_configuration_changed=False, W32Time_changed=False, observation_only=True))
    save('b9-native-preflight.json', dict(state='PASS', private_postgresql=True, durable=True,
         private_python=True, resources=resources(), formal_blocks_executed=False))
    print('NATIVE_PREFLIGHT_PASS', flush=True)


if __name__ == '__main__':
    main()
