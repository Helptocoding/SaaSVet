"""Install the CI-pinned scanner locally; verify publisher checksums first."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

import requests

out = Path(__file__).resolve().parent
target = out / 'scanner-toolchain.json'
assert not target.exists()
version = '8.18.4'
base = 'https://github.com/gitleaks/gitleaks/releases/download/v' + version + '/'
archive_name = 'gitleaks_' + version + '_windows_x64.zip'
response = requests.get(base + 'gitleaks_' + version + '_checksums.txt', timeout=30)
response.raise_for_status()
expected = next(line.split()[0] for line in response.text.splitlines() if line.split()[-1] == archive_name)
response = requests.get(base + archive_name, timeout=30)
response.raise_for_status()
archive = response.content
assert len(archive) < 8*1024*1024 and hashlib.sha256(archive).hexdigest() == expected
folder = out / 'runtime' / 'gitleaks'
folder.mkdir(parents=True, exist_ok=True)
binary = folder / 'gitleaks.exe'
assert not binary.exists()
with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
    data = zipped.read('gitleaks.exe')
binary.write_bytes(data)
probe = subprocess.run(['rtk', 'proxy', str(binary), 'version'], capture_output=True, text=True, check=True)
assert version in probe.stdout
result = dict(version=version, source=base + archive_name, archive_sha256=expected,
    binary_sha256=hashlib.sha256(data).hexdigest(), binary=str(binary), checksum_verified=True)
target.write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
