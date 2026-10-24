"""Verify only the added SDK dependency closure, without refreshing other pins."""
from importlib import metadata
import json
from pathlib import Path

from packaging.requirements import Requirement

out = Path(__file__).resolve().parent
root = out.parents[2]
target = out / 'dependencies.json'
assert not target.exists()
names = ['boto3', 'botocore', 's3transfer', 'jmespath', 'python-dateutil', 'six']
lock = (root / 'backend/requirements.lock').read_text(encoding='utf-8').lower()
versions, checks = {}, []
for name in names:
    version = metadata.version(name)
    versions[name] = version
    assert f'{name}=={version}' in lock
    for value in metadata.requires(name) or []:
        requirement = Requirement(value)
        if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
            continue
        installed = metadata.version(requirement.name)
        assert installed in requirement.specifier, (name, requirement.name, installed)
        checks.append(dict(parent=name, dependency=requirement.name, installed=installed, satisfied=True))
target.write_text(json.dumps(dict(status='PASS', installed=versions, checks=checks,
    network_used=False, existing_pins_refreshed=False), indent=2), encoding='utf-8')
print(target.read_text(encoding='utf-8'))
