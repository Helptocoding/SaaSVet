"""Install the original pip-audit version into a private directory, not the app runtime."""
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

out = Path(__file__).resolve().parent
target = out/'runtime/b9/audit-site'
assert not target.exists()
env = {k:v for k,v in os.environ.items() if k.upper() in
       {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'COMSPEC'}}
env.update(PIP_CONFIG_FILE=os.devnull, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
args = [shutil.which('rtk'), 'proxy', sys.executable, '-m', 'pip', 'install',
        '--target', str(target), '--no-compile', '--disable-pip-version-check',
        '--index-url', 'https://pypi.org/simple', 'pip-audit==2.10.1']
with (out/'audit-install.log').open('wb') as log:
    result = subprocess.run(args, env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
packages = sorted([dict(name=d.metadata['Name'], version=d.version)
                   for d in metadata.distributions(path=[str(target)])], key=lambda x:x['name'].lower())
receipt = dict(state='PASS' if result.returncode == 0 else 'PENDING', exit_code=result.returncode,
               original_auditor_version='2.10.1', packages=packages, product_dependencies_changed=False)
(out/'audit-toolchain.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
print(json.dumps(dict(state=receipt['state'], packages=len(packages))), flush=True)
raise SystemExit(result.returncode)
