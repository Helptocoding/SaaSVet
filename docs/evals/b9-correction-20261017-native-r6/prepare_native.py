"""Prepare the fixed candidate on Windows, with no application test execution."""
import base64
import difflib
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from native_support import EVIDENCE, REPO, OLD, WORK, TREE, PYTHON, PG, NODE, PNPM, DATA, PORT, SHA, RTK, GIB, save, sha256, resources, environment, run, command, integrity

PRIOR = EVIDENCE.with_name('b9-correction-20261014-r4')
NATIVE_PRIOR = EVIDENCE.with_name('b9-correction-20261017-native-r5')
BASE = Path('C:/Users/LAP/AppData/Local/Programs/Python/Python313')
LOCKED = Path('C:/Users/LAP/AppData/Local/Temp/vet-b8b-locked')


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'B9-native-evaluation'}), timeout=60) as response:
        return response.read()


def download(url, name, expected=None):
    data = fetch(url)
    actual = sha256(data)
    if expected:
        assert actual == expected, name
    path = WORK / 'downloads' / name
    path.write_bytes(data)
    records = json.loads((EVIDENCE / 'downloads.json').read_text()) if (EVIDENCE / 'downloads.json').exists() else []
    records.append({'url': url, 'name': name, 'sha256': actual, 'expected_sha256': expected, 'bytes': len(data)})
    save('downloads.json', records)
    return data


def setup():
    assert not WORK.exists() and not (EVIDENCE / 'authorization.json').exists()
    assert resources()['disk_available'] >= 3 * GIB
    assert json.loads((EVIDENCE / 'candidate-input.json').read_text(encoding='utf-8'))['candidate_tree'] == SHA
    WORK.mkdir()
    for name in ('downloads', 'rtk-config', 'tool-data', 'tool-config', 'cache', 'pnpm-home'):
        (WORK / name).mkdir()
    for name in ('empty.npmrc', 'empty-global.npmrc'):
        (WORK / name).write_text('', encoding='utf-8')
    for name in ('PLAN.md', 'scope-manifest.json', 'resource-policy.json', 'prior-focused-verification.json'):
        (EVIDENCE / name).write_bytes((NATIVE_PRIOR / name).read_bytes())
    for target, source in (('candidate.json', 'candidate-input.json'), ('correction.diff', 'correction-input.diff')):
        (EVIDENCE / target).write_bytes((EVIDENCE / source).read_bytes())
    scope = json.loads((EVIDENCE / 'scope-manifest.json').read_text(encoding='utf-8'))
    for key in ('candidate_sha', 'candidate_tree'):
        if scope.get(key) == '196aceb4f5f234c086b96d8e8af93787613f3c25':
            scope[key] = SHA
    scope['fixture_clock_equivalence'] = 'fixture-clock-authorization.json'
    save('scope-manifest.json', scope)
    with (EVIDENCE / 'PLAN.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n\n## Corrección temporal y reuso acotado autorizados, 2026-10-17\n\n'
            'El usuario autorizó «Sí, corregir y continuar conservando lo válido». '
            'El candidato 68dffd746793700071f577a58528b0f9636930db difiere del '
            '196aceb4f5f234c086b96d8e8af93787613f3c25 únicamente en '
            'backend/apps/notifications/tests/test_notifications.py: imports estándar '
            'y un decorador mock que fija mediodía UTC solo durante test_upcoming_window. '
            'El cuerpo, los IDs, assertions, validadores y constraint siguen idénticos. '
            'Los otros 3331 blobs, producto, dependencias y locks no cambian. '
            'Esta autorización sustituye exclusivamente la exigencia de mismo SHA para '
            'trece bloques PASS cuya selección no ejecuta ese método y cuya equivalencia '
            'se verifica antes del sello; no permite otros cambios ni omisiones. '
            'Se conservan once bloques ya referenciados y full-b8d/full-b8e de native-r5 '
            '(369 IDs únicos; 118 IDs de full), con su candidato probado y el candidato '
            'aceptado explícitos. El grupo general parcial y su ERROR temporal e incidente '
            'de vigilia permanecen como evidencia no aprobada. Se ejecutan completos los '
            '3213 IDs de general y luego frontend, seguridad, auditorías y cinco perfiles '
            'con sus migraciones, cargas, tiempos 30/300/20 y gates originales. '
            'Antes del sello se permite una comprobación de desarrollo del método '
            'corregido, sin crédito formal y sin sustituir el grupo general completo. '
            'La aceptación es compuesta; no se afirma una campaña continua. '
            'Referencias: fixture-clock-authorization.json, fixture-resumption-amendment.json, '
            'reuse-manifest.json y reuse-validation.json. Reservas 2 GiB RAM/1 GiB disco, '
            'reloj 1s, auxiliares acotados 12h/13h sin renovación adaptativa y restauración '
            'explícita. No se autorizan commits, push, despliegue ni activación.\n')
    policy = json.loads((EVIDENCE / 'resource-policy.json').read_text(encoding='utf-8'))
    policy.update(resumption_instruction='Sí, corregir y continuar conservando lo válido',
                  fixture_clock_authorization='fixture-clock-authorization.json')
    save('resource-policy.json', policy)
    save('authorization.json', {'user': 'Sí, corregir y continuar conservando lo válido',
        'date_local': '2026-10-17', 'scope': 'Fixture-only successor with bounded verified reuse',
        'candidate_tree': SHA, 'previous_candidate_tree': '196aceb4f5f234c086b96d8e8af93787613f3c25',
        'prior_campaign': NATIVE_PRIOR.name, 'prior_decision': 'PENDING_FIXTURE_AND_AWAKE_INCIDENT',
        'maximum_formal_runs_per_block': 1, 'maximum_formal_runs_per_profile_variant': 1,
        'authorized_fixture_correction': 'fixture-clock-authorization.json',
        'further_test_or_product_changes': False, 'product_runtime_changes': False,
        'commits_push_deploy_activation_authorized': False})
    contract = json.loads((NATIVE_PRIOR / 'full-partition-contract.json').read_text(encoding='utf-8'))
    assert contract['candidate_tree'] == '196aceb4f5f234c086b96d8e8af93787613f3c25'
    contract['candidate_tree'] = SHA
    save('full-partition-contract.json', contract)
    for name in ('recorded_suite.py', 'full_partition.py', 'awake_guard.py', 'awake_status.py',
                 'host_resources.py', 'host_observer.py'):
        (EVIDENCE / name).write_text((NATIVE_PRIOR / name).read_text(encoding='utf-8'),
                                    encoding='utf-8', newline='\n')
    source = (PRIOR / 'discover_candidate.py').read_text(encoding='utf-8')
    begin = source.index('os.environ.update(')
    end = source.index('\nimport django', begin)
    source = source[:begin] + 'from native_support import environment\nos.environ.update(environment())' + source[end:]
    source = source.replace("encoding='utf-8')\n\n\nscope", "encoding='utf-8', newline='\\n')\n\n\nscope")
    source = source.replace('196aceb4f5f234c086b96d8e8af93787613f3c25', SHA)
    (EVIDENCE / 'discover_candidate.py').write_text(source, encoding='utf-8', newline='\n')
    prior = {}
    for folder in EVIDENCE.parent.iterdir():
        if folder.is_dir() and folder != EVIDENCE and (folder.name.startswith('b9-correction-') or folder.name.startswith('b9-integral-acceptance-1947726')):
            prior.update({p.relative_to(REPO).as_posix(): sha256(p.read_bytes())
                          for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts})
    save('prior-evidence-before.json', prior)
    assemble_native()




def assemble_native():
    candidate = json.loads((EVIDENCE / 'candidate.json').read_text())
    assert run('git', 'rev-parse', 'HEAD').decode().strip() == candidate['base_commit']
    assert run('git', 'diff', '--name-only', candidate['base_commit'], SHA).decode().splitlines() == candidate['changed_paths']
    hashes = {}
    for name in candidate['changed_paths']:
        blob = run('git', 'show', SHA + ':' + name)
        assert run('git', 'show', ':' + name) == blob
        assert (REPO / name).read_bytes().replace(b'\r\n', b'\n') == blob
        hashes[name] = sha256(blob)
    save('code-selection.json', {'state': 'PASS', 'explicit_paths': candidate['changed_paths'],
        'staged_code_equals_frozen_candidate_tree': True, 'staged_sha256': hashes,
        'commits_created': 0, 'pushes_performed': 0})
    save('checkout-before.json', {'head': run('git', 'rev-parse', 'HEAD').decode().strip(),
        'branch': run('git', 'branch', '--show-current').decode().strip(),
        'unrelated': {n: {'exists': (REPO / n).exists(), 'sha256': sha256((REPO / n).read_bytes()) if (REPO / n).exists() else None}
                      for n in ('DEPLOY_VPS_PLAN.md', 'DEPLOY_VPS_STATUS.md', 'skills-lock.json')}})
    save('assembly.json', {'candidate_sha': SHA, 'workspace': WORK.as_posix(), 'tree': TREE.as_posix(),
        'python': PYTHON.as_posix(), 'pg_bin': PG.as_posix(), 'port': PORT,
        'phase': 'PREPARING', 'platform': 'Windows native', 'wsl_invoked': False})
    archive = run('git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'archive', '--format=tar', SHA)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(TREE, filter='data')
    files = []
    for record in filter(None, run('git', 'ls-tree', '-r', '-z', SHA).split(b'\0')):
        meta, name = record.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        name = name.decode()
        data = (TREE / name).read_bytes()
        assert kind == 'blob' and hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == oid
        files.append({'path': name, 'git_blob': oid, 'mode': mode, 'sha256': sha256(data), 'bytes': len(data)})
    assert len(files) == 3332
    save('candidate-sources.json', {'candidate_sha': SHA, 'archive_sha256': sha256(archive),
         'files': files, 'mismatches': []})
    del archive
    integrity('after-export')
    print('EXACT_NATIVE_CANDIDATE_PASS 3332 blobs', flush=True)
    runtime = WORK / 'python'
    runtime.mkdir()
    origins = {}
    def copy_file(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        target.write_bytes(data)
        origins[target.relative_to(runtime).as_posix()] = {'source': str(source), 'sha256': sha256(data)}
    for source in BASE.iterdir():
        if source.is_file() and (source.suffix.lower() in ('.exe', '.dll') or source.name in ('LICENSE.txt', 'LICENSE')):
            copy_file(source, runtime / source.name)
    for name in ('DLLs', 'Lib', 'tcl'):
        folder = BASE / name
        if folder.exists():
            for source in folder.rglob('*'):
                relative = source.relative_to(folder)
                if source.is_file() and '__pycache__' not in relative.parts and 'site-packages' not in relative.parts:
                    copy_file(source, runtime / name / relative)
    for source in (LOCKED / 'Lib/site-packages').rglob('*'):
        relative = source.relative_to(LOCKED / 'Lib/site-packages')
        if source.is_file() and '__pycache__' not in relative.parts:
            copy_file(source, runtime / 'Lib/site-packages' / relative)
    save('private-python-copy.json', {'state': 'COPIED_BEFORE_PREFLIGHT', 'files': origins,
        'shared_installations_modified': False, 'excluded': ['__pycache__', 'global third-party site-packages'],
        'dependency_source': str(LOCKED / 'Lib/site-packages')})
    assert run(PYTHON, '--version').decode().strip() == 'Python 3.13.2'
    name = 'node-v20.20.2-win-x64.zip'
    expected = 'dc3700fdd57a63eedb8fd7e3c7baaa32e6a740a1b904167ff4204bc68ed8bf77'
    data = download('https://nodejs.org/dist/v20.20.2/' + name, name, expected)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(WORK)
    meta = json.loads(fetch('https://registry.npmjs.org/pnpm/9.15.9'))
    package = download(meta['dist']['tarball'], 'pnpm-9.15.9.tgz')
    actual = 'sha512-' + base64.b64encode(hashlib.sha512(package).digest()).decode()
    original = json.loads((OLD / 'toolchain.json').read_text())
    assert actual == meta['dist']['integrity'] == original['pnpm_integrity']
    with tarfile.open(fileobj=io.BytesIO(package), mode='r:gz') as tf:
        tf.extractall(WORK / 'pnpm', filter='data')
    save('toolchain.json', {'node': run(NODE, '--version').decode().strip(),
        'pnpm': run(NODE, PNPM, '--version').decode().strip(),
        'python': run(PYTHON, '--version').decode().strip(),
        'postgres': run(PG / 'postgres.exe', '--version').decode().strip(),
        'node_archive_sha256': expected, 'pnpm_integrity': actual,
        'node_executable': str(NODE), 'pnpm_script': str(PNPM), 'wsl_invoked': False})
    assert json.loads((EVIDENCE / 'toolchain.json').read_text())['postgres'] == 'postgres (PostgreSQL) 16.15'
    print('NATIVE_TOOLS_PREPARED', flush=True)


def frontend():
    integrity('before-frontend-install')
    command('frontend-install', [NODE, PNPM, 'install', '--frozen-lockfile',
        '--node-linker=hoisted', '--package-import-method=copy', '--store-dir', WORK / 'pnpm-store'], cwd=TREE / 'frontend')
    integrity('after-frontend-install')
    save('frontend-layout.json', {'state': 'PASS', 'node_linker': 'hoisted',
        'package_import_method': 'copy', 'frozen_lockfile': True,
        'product_and_lock_files_changed': False,
        'reason': 'Native installation without package-store symbolic links'})
    print('NATIVE_FRONTEND_INSTALL_PASS', flush=True)


def stage():
    assert json.loads((EVIDENCE / 'frontend-layout.json').read_text())['state'] == 'PASS'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', PORT))
    command('initdb', [PG / 'initdb.exe', '-D', DATA, '-U', 'b9e', '-A', 'trust', '-E', 'UTF8', '--locale=C'])
    with (DATA / 'postgresql.conf').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write("\n# Native B9 private cluster\nlisten_addresses='127.0.0.1'\nport=" + str(PORT)
            + "\nfsync=on\nsynchronous_commit=on\nfull_page_writes=on\nmax_connections=40\n")
    argv = [str(RTK), 'proxy', str(PG / 'postgres.exe'), '-D', str(DATA)]
    with (WORK / 'postgresql.log').open('wb') as log:
        server = subprocess.Popen(argv, cwd=WORK, env=environment(), stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
    save('postgresql-start.json', {'mode': 'Owned foreground server under RTK with private log',
         'argv': argv, 'wrapper_pid': server.pid, 'port': PORT, 'data_directory': str(DATA)})
    import psycopg
    start = time.monotonic()
    while True:
        if server.poll() is not None:
            raise RuntimeError('Owned PostgreSQL exited before readiness')
        try:
            conn = psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True, connect_timeout=2)
            break
        except psycopg.OperationalError:
            if time.monotonic() - start > 60:
                raise
            time.sleep(.5)
    with conn:
        values = conn.execute("SELECT version(),current_setting('data_directory'),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes')").fetchone()
        assert Path(values[1]).resolve() == DATA.resolve() and values[2:] == ('on', 'on', 'on')
        conn.execute('CREATE DATABASE test_b9i_control')
    save('postgresql-preflight.json', {'state': 'PASS', 'values': values, 'port': PORT,
         'postmaster_pid': int((DATA / 'postmaster.pid').read_text().splitlines()[0]), 'private_cluster': True})
    (EVIDENCE / 'private-postgresql').mkdir()
    for name in ('postgresql.conf', 'pg_hba.conf'):
        shutil.copy2(DATA / name, EVIDENCE / 'private-postgresql' / name)
    command('discovery', [PYTHON, '-B', EVIDENCE / 'discover_candidate.py'], cwd=TREE / 'backend')
    from full_partition import build_partition
    build_partition()
    sources = ['backend/apps/agent/tests/b9e_profile.py', 'backend/apps/agent/tests/b9a_harness.py',
               'backend/apps/agent/tests/test_b9a_e2e.py']
    assert not run('git', 'diff', '--exit-code', '08310461337a284386299ec47c54125f2139bf7f', SHA, '--', *sources)
    save('profile-compatibility.json', {'state': 'PASS', 'candidate_sha': SHA,
        'historical_candidate': '08310461337a284386299ec47c54125f2139bf7f',
        'identical_git_sources': sources, 'warmup_seconds': 30, 'measurement_seconds': 300,
        'drain_seconds': 20, 'smoke': False, 'actual_read_llm_calls': 2, 'no_workload_or_gate_changes': True})
    archive = 'gitleaks_8.18.4_windows_x64.zip'
    base = 'https://github.com/gitleaks/gitleaks/releases/download/v8.18.4/'
    sums = fetch(base + 'gitleaks_8.18.4_checksums.txt').decode()
    digest = next(s.split()[0] for s in sums.splitlines() if s.split()[-1] == archive)
    data = download(base + archive, archive, digest)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(WORK / 'gitleaks')
    command('gitleaks-version', [WORK / 'gitleaks/gitleaks.exe', 'version'])
    assert run('git', 'rev-parse', '--is-shallow-repository').strip() == b'false'
    save('security-history.json', {'head': run('git', 'rev-parse', 'HEAD').decode().strip(),
        'refs': sorted(run('git', 'for-each-ref', '--format=%(refname) %(objectname)').decode().splitlines()),
        'is_shallow': False, 'full_history': True,
        'source': str(REPO), 'mode': 'Read-only Git history scan as original native controller',
        'candidate_tree': SHA})
    for name in json.loads((EVIDENCE / 'candidate.json').read_text())['changed_paths']:
        target = WORK / 'security-patch' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TREE / name, target)
    command('audit-venv', [PYTHON, '-m', 'venv', WORK / 'audit-venv'])
    command('audit-tool-install', [WORK / 'audit-venv/Scripts/python.exe', '-m', 'pip', 'install',
        '--no-cache-dir', 'pip-audit'])
    save('audit-toolchain.json', json.loads(run(WORK / 'audit-venv/Scripts/python.exe', '-m', 'pip', 'list', '--format=json')))
    command('interpreters', [PYTHON, '-B', EVIDENCE / 'interpreter_preflight.py'], cwd=TREE / 'backend')
    integrity('ready')
    save('native-preflight.json', {'state': 'PASS', 'python_and_base_private': True,
        'frontend_install': 'PASS', 'postgresql_private_durable': True,
        'full_partition_total': 3331, 'wsl_invoked': False, 'application_tests_executed': False,
        'resources': resources()})
    save('environment-ready.json', {'state': 'READY_FOR_SEAL', 'candidate_sha': SHA,
        'platform': 'Windows native', 'wsl_invoked': False, 'application_tests_executed': False})
    print('NATIVE_ENVIRONMENT_READY_FOR_SEAL', flush=True)


if __name__ == '__main__':
    try:
        {'setup': setup, 'frontend': frontend, 'stage': stage}[sys.argv[1]]()
    except Exception as exc:
        name = 'preparation-incident-' + sys.argv[1] + '.json'
        assert not (EVIDENCE / name).exists()
        save(name, {'type': type(exc).__name__, 'message': str(exc), 'tests_executed': False,
                    'resources': resources()})
        raise
