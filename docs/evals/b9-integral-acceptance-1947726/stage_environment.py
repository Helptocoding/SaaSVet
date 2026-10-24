"""Finish controlled environment setup before the first formal block."""
import base64
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import zipfile
from prepare_campaign import EVIDENCE, REPO, TREE, WORK, PYTHON, PG, save, sha256, resources, download

ASSEMBLY = json.loads((EVIDENCE / 'assembly.json').read_text())
NODE = Path(ASSEMBLY['node'])
PNPM = Path(ASSEMBLY['pnpm'])
DATA = WORK / 'pgdata'
PORT = 35459


def environment():
    keep = ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA',
            'LOCALAPPDATA', 'PROGRAMDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
            'COMSPEC', 'PATHEXT', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'HOMEDRIVE', 'HOMEPATH')
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env.update(PATH=str(NODE.parent) + os.pathsep + str(PYTHON.parent) + os.pathsep + env.get('PATH', ''),
        DJANGO_SETTINGS_MODULE='config.settings', SECRET_KEY='b9i-disposable-test-only',
        ENVIRONMENT='dev', DEBUG='False', DATABASE_URL=f'postgresql://b9e@127.0.0.1:{PORT}/test_b9i_control',
        DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='', DISCORD_WEBHOOK_URL='',
        HEALTHCHECK_AGENT_WORKER_URL='', HEALTHCHECK_AGENT_SENDER_URL='',
        AGENT_LLM_API_KEY='', AGENT_LLM_BASE_URL='', WHATSAPP_ACCESS_TOKEN='',
        WHATSAPP_APP_SECRET='', WHATSAPP_VERIFY_TOKEN='',
        PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
        VITE_API_URL='http://127.0.0.1:8000/api', CI='true')
    return env


def command(name, args, cwd=WORK):
    log = EVIDENCE / (name + '.log')
    if log.exists():
        raise RuntimeError('Refusing to repeat preparation command ' + name)
    start = time.monotonic()
    with log.open('wb') as stream:
        result = subprocess.run(['rtk', 'proxy', *map(str, args)], cwd=cwd, env=environment(),
                                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    save(name + '.exit.json', {'argv': list(map(str, args)), 'cwd': str(cwd),
        'seconds': time.monotonic() - start, 'exit_code': result.returncode, 'preparation_only': True})
    if result.returncode:
        raise RuntimeError(name + ' failed during preparation; see log')


def integrity(label):
    sources = json.loads((EVIDENCE / 'candidate-sources.json').read_text())['files']
    mismatches = [name for name, info in sources.items() if not (TREE / name).is_file()
                  or sha256((TREE / name).read_bytes()) != info['sha256']]
    save('integrity-' + label + '.json', {'candidate_sha': ASSEMBLY['candidate_sha'],
        'checked_files': len(sources), 'mismatches': mismatches, 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    if mismatches:
        raise RuntimeError('Candidate integrity mismatch: ' + label)


def main():
    assert ASSEMBLY['phase'] == 'ASSEMBLED_NOT_EXECUTED'
    resume = '--resume-after-pg' in sys.argv
    if resume:
        assert (DATA / 'postmaster.pid').is_file()
        save('pg-start-wrapper-incident.json', {'preparation_only': True, 'tests_executed': False,
            'cause': 'pg_ctl exited and reported ready; RTK proxy retained descendant handles. Stopped only wrapper PID 26268; resume with existing owned cluster after SQL verification.',
            'postgresql_start_repeated': False})
    else:
        assert not DATA.exists()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', PORT))
        command('initdb', [PG / 'initdb.exe', '-D', DATA, '-U', 'b9e', '-A', 'trust', '-E', 'UTF8', '--locale=C'])
        with (DATA / 'postgresql.conf').open('a', encoding='utf-8') as stream:
            stream.write("\n# B9I private evaluation only\nlisten_addresses = '127.0.0.1'\nport = 35459\nfsync = on\nsynchronous_commit = on\nfull_page_writes = on\n")
        command('pg-start', [PG / 'pg_ctl.exe', '-D', DATA, '-l', EVIDENCE / 'postgresql.log', '-w', '-t', '60', 'start'])
    import psycopg
    with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute('CREATE DATABASE test_b9i_control')
            cur.execute("SELECT version(), current_user, current_setting('data_directory'), current_setting('port'), current_setting('listen_addresses'), current_setting('fsync'), current_setting('synchronous_commit'), current_setting('full_page_writes'), pg_backend_pid()")
            values = cur.fetchone()
            save('postgresql-preflight.json', dict(zip(('version', 'user', 'data_directory', 'port', 'listen_addresses', 'fsync', 'synchronous_commit', 'full_page_writes', 'observer_pid'), values)) | {'postmaster_pid': int((DATA / 'postmaster.pid').read_text().splitlines()[0]), 'owned_databases': ['test_b9i_control'], 'private_cluster': True})
            assert values[2].replace('\\', '/') == str(DATA).replace('\\', '/')
            assert values[3:8] == ('35459', '127.0.0.1', 'on', 'on', 'on')
    # CI's blocking scanner version; download is preparation, scan is block 2.
    filename = 'gitleaks_8.18.4_windows_x64.zip'
    release = 'https://github.com/gitleaks/gitleaks/releases/download/v8.18.4/'
    sums = download(release + 'gitleaks_8.18.4_checksums.txt').decode()
    expected = next(line.split()[0] for line in sums.splitlines() if line.split()[-1] == filename)
    data = download(release + filename)
    assert sha256(data) == expected
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(WORK / 'gitleaks')
    command('gitleaks-version', [WORK / 'gitleaks/gitleaks.exe', 'version'])
    save('gitleaks-toolchain.json', {'version': '8.18.4', 'archive_sha256': expected,
        'executable_sha256': sha256((WORK / 'gitleaks/gitleaks.exe').read_bytes()),
        'url': release + filename, 'history_scan_executed': False})
    integrity('before-install')
    command('frontend-install', [NODE, PNPM, 'install', '--frozen-lockfile', '--store-dir', WORK / 'pnpm-store'], cwd=TREE / 'frontend')
    integrity('after-install')
    save('environment-ready.json', {'state': 'READY_FOR_PREFLIGHT_SEAL', 'tests_executed': False,
        'resources': resources(), 'controlled_environment': environment(),
        'postgresql_config_sha256': sha256((DATA / 'postgresql.conf').read_bytes()),
        'postgresql_hba_sha256': sha256((DATA / 'pg_hba.conf').read_bytes())})
    print('Environment staged; no application tests executed.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        save('environment-incident.json', {'type': type(exc).__name__, 'message': str(exc), 'tests_executed': False})
        raise
