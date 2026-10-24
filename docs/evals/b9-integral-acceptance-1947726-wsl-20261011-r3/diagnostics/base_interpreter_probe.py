"""Post-stop import diagnostic only; never run a test or application entrypoint."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from prepare_wsl import TREE, RTK, environment, save

assert (HERE / 'STOP.json').exists()
assert not (HERE / 'base-interpreter-diagnostic.json').exists()
base = str(Path(sys._base_executable))
lookup = "import importlib.util,json,sys; print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'sys_path':sys.path,'django_spec':str(importlib.util.find_spec('django')),'psycopg_spec':str(importlib.util.find_spec('psycopg'))}))"
records = []
for label, binary, code in (
    ('venv_module_visibility', sys.executable, lookup),
    ('base_module_visibility', base, lookup),
    ('base_import_django_only', base, 'import django; print(django.get_version())'),
):
    argv = [str(RTK), 'proxy', binary, '-B', '-X', 'utf8', '-c', code]
    result = subprocess.run(argv, cwd=TREE / 'backend', env=environment(),
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    records.append({'label': label, 'argv': argv, 'cwd': str(TREE / 'backend'),
                    'exit_code': result.returncode,
                    'stdout': result.stdout.decode('utf-8', errors='replace'),
                    'stderr': result.stderr.decode('utf-8', errors='replace')})
sources = {}
for name in ('backend/apps/agent/tests/test_b3_processes.py', 'backend/apps/agent/tests/b3_process.py'):
    content = (TREE / name).read_bytes()
    sources[name] = {'sha256': hashlib.sha256(content).hexdigest(), 'source': content.decode('utf-8')}
save('base-interpreter-diagnostic.json', {
    'state': 'OBSERVED_AFTER_DURABLE_STOP', 'base_executable': base,
    'test_entrypoint_executed': False, 'application_entrypoint_executed': False,
    'django_setup_called': False, 'database_accessed': False,
    'dependencies_installed_or_changed': False, 'formal_rerun': False,
    'original_child_stderr_retained_by_candidate_test': False,
    'limitation': 'The original child stderr was discarded by candidate cleanup. This import-only probe diagnoses dependency visibility in the same interpreter, cwd and application environment; it is not an original child trace.',
    'probe_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'commands': records, 'candidate_sources': sources,
})
print(json.dumps({'base_executable': base, 'commands': [
    {'label': r['label'], 'exit_code': r['exit_code'], 'stdout': r['stdout'], 'stderr': r['stderr']}
    for r in records]}, ensure_ascii=False), flush=True)
