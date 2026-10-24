"""Path-only adaptation of the original B9 native environment/resource observer."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
OLD = OUT.with_name('b9-correction-20261020-native-r12')
WORK = OUT/'runtime/b9'
TREE = WORK/'src'
PYTHON = WORK/'python/python.exe'
NODE = WORK/'node-v20.20.2-win-x64/node.exe'
PNPM = WORK/'pnpm/package/bin/pnpm.cjs'
PG = Path('C:/Users/LAP/AppData/Local/Temp/vet-b8b-pg16-bin/pgsql/bin')
DATA = WORK/'pgdata'
PORT = 35591
RTK = Path(shutil.which('rtk'))
GIB = 1024**3
spec = importlib.util.spec_from_file_location('original_b9_native_support', OLD/'native_support.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
for name in ('WORK', 'TREE', 'PYTHON', 'NODE', 'PNPM', 'PG', 'DATA', 'PORT'):
    setattr(native, name, globals()[name])
environment = native.environment
resources = native.resources


def save(name, value):
    path = OUT/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str)+'\n', encoding='utf-8')


def run(*args, cwd=WORK, env=None):
    return subprocess.check_output([str(RTK), 'proxy', *map(str,args)], cwd=cwd,
        env=env or environment(), stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW)
