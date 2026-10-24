"""Native Windows assembly support; candidate tests and runtime stay unchanged."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

EVIDENCE = Path(__file__).resolve().parent
REPO = EVIDENCE.parents[2]
OLD = EVIDENCE.with_name('b9-integral-acceptance-1947726')
WORK = Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6')
TREE = WORK / 'src'
PYTHON = WORK / 'python/python.exe'
PG = Path('C:/Users/LAP/AppData/Local/Temp/vet-b8b-pg16-bin/pgsql/bin')
NODE = WORK / 'node-v20.20.2-win-x64/node.exe'
PNPM = WORK / 'pnpm/package/bin/pnpm.cjs'
DATA = WORK / 'pgdata'
PORT = 35490
SHA = 'b271e314817da51e99811cb18921fd7c9f59e58a'
RTK = Path('C:/Users/LAP/.local/bin/rtk.exe')
GIB = 1024 ** 3


def save(name, value):
    path = EVIDENCE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n',
                    encoding='utf-8', newline='\n')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Memory(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                *[(name, ctypes.c_ulonglong) for name in (
                    'total', 'available', 'page_total', 'page_available',
                    'virtual_total', 'virtual_available', 'extended')]]


def resources():
    mem = Memory()
    mem.length = ctypes.sizeof(mem)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
        raise OSError('GlobalMemoryStatusEx failed')
    return {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'utc_epoch_seconds': time.time(), 'physical_total': mem.total,
            'physical_available': mem.available, 'page_available': mem.page_available,
            'disk_available': shutil.disk_usage(REPO).free, 'platform': 'Windows native'}


def environment():
    keep = {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA',
            'LOCALAPPDATA', 'PROGRAMDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
            'COMSPEC', 'PATHEXT', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE',
            'HOMEDRIVE', 'HOMEPATH'}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env.update(PATH=os.pathsep.join(map(str, [NODE.parent, PYTHON.parent, PG, RTK.parent]))
               + os.pathsep + env.get('PATH', ''),
        CLAUDE_CONFIG_DIR='C:/Users/LAP/.claude', XDG_DATA_HOME=str(WORK / 'tool-data'),
        XDG_CONFIG_HOME=str(WORK / 'tool-config'), XDG_CACHE_HOME=str(WORK / 'cache'),
        PNPM_HOME=str(WORK / 'pnpm-home'), NPM_CONFIG_USERCONFIG=str(WORK / 'empty.npmrc'),
        NPM_CONFIG_GLOBALCONFIG=str(WORK / 'empty-global.npmrc'),
        NPM_CONFIG_REGISTRY='https://registry.npmjs.org',
        DJANGO_SETTINGS_MODULE='config.settings', SECRET_KEY='b9i-native-disposable-test-only',
        ENVIRONMENT='dev', DEBUG='False',
        DATABASE_URL=f'postgresql://b9e@127.0.0.1:{PORT}/test_b9i_control',
        DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='', DISCORD_WEBHOOK_URL='',
        HEALTHCHECK_AGENT_WORKER_URL='', HEALTHCHECK_AGENT_SENDER_URL='',
        AGENT_LLM_API_KEY='', AGENT_LLM_BASE_URL='', WHATSAPP_ACCESS_TOKEN='',
        WHATSAPP_APP_SECRET='', WHATSAPP_VERIFY_TOKEN='',
        PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONNOUSERSITE='1',
        PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1',
        VITE_API_URL='http://127.0.0.1:8000/api', CI='true')
    return env


def run(*args, cwd=REPO, env=None):
    return subprocess.check_output([str(RTK), 'proxy', *map(str, args)], cwd=cwd,
        env=env or environment(), stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW)


def command(label, args, cwd=None):
    target = EVIDENCE / (label + '.command.json')
    assert not target.exists(), label
    argv = [str(RTK), 'proxy', *map(str, args)]
    start = time.monotonic()
    info = {'state': 'RUNNING', 'argv': argv, 'cwd': str(cwd or WORK),
            'preparation_only': True, 'resources_before': resources()}
    save(target.name, info)
    with (EVIDENCE / (label + '.log')).open('wb') as log:
        result = subprocess.run(argv, cwd=cwd or WORK, env=environment(),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
    info.update(state='COMPLETED', exit_code=result.returncode,
                seconds=time.monotonic() - start, resources_after=resources())
    save(target.name, info)
    if result.returncode:
        raise RuntimeError(label + ' failed; see retained log')
    print(label + ': PASS', flush=True)


def integrity(label):
    manifest = json.loads((EVIDENCE / 'candidate-sources.json').read_text(encoding='utf-8'))
    bad = [row['path'] for row in manifest['files']
           if not (TREE / row['path']).is_file()
           or sha256((TREE / row['path']).read_bytes()) != row['sha256']]
    save('integrity-' + label + '.json', {'checked_files': len(manifest['files']), 'mismatches': bad})
    if bad:
        raise RuntimeError('Candidate source changed')
