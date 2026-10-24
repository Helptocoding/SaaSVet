"""Verify private locked Windows interpreters and hash dependencies without tests."""
import json
from pathlib import Path
import re
import subprocess
from native_support import EVIDENCE, WORK, TREE, PYTHON, PORT, RTK, environment, save, sha256

PROBE=r'''
import importlib.metadata as metadata,json,sys,sysconfig
import django
django.setup()
import apps.agent.durable as durable
import apps.agent.worker as worker
import psycopg
from django.conf import settings
db=settings.DATABASES['default']
print(json.dumps(dict(state='DEPENDENCY_PREFLIGHT_READY',executable=sys.executable,
    base_executable=sys._base_executable,prefix=sys.prefix,base_prefix=sys.base_prefix,
    python_version=sys.version,site_packages=sysconfig.get_path('purelib'),
    django_file=django.__file__,psycopg_file=psycopg.__file__,durable_file=durable.__file__,worker_file=worker.__file__,
    database={key:str(db.get(key,'')) for key in ('ENGINE','NAME','HOST','PORT')},
    packages=sorted([dict(name=dist.metadata['Name'],version=dist.version,
        location=str(dist.locate_file(''))) for dist in metadata.distributions()],key=lambda row:row['name'].lower()))))
'''


def normalize(name):
    return re.sub(r'[-_.]+','-',name).lower()


def locked_versions(path):
    pins={}
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):
            continue
        match=re.fullmatch(r'([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s;]+)',line)
        assert match is not None, 'Unsupported locked requirement: '+line
        name,version=normalize(match[1]),match[2]
        assert name not in pins, 'Duplicate locked requirement: '+name
        pins[name]=version
    # The exact candidate lock has 34 pins; installed tooling is not counted as a requirement.
    assert len(pins)==34, 'Frozen requirement denominator differs from the candidate lock'
    return pins


def package_versions(row):
    packages={}
    for package in row['packages']:
        name=normalize(package['name'])
        assert name not in packages, 'Duplicate installed distribution: '+name
        packages[name]=package['version']
        assert Path(package['location']).resolve().is_relative_to((WORK/'python').resolve())
    return packages


def main():
    assert not (EVIDENCE/'evaluation-seal.json').exists()
    for name in ('interpreter-preflight.json','python-environment.json','base-python-environment.json','dependency-files.json'):
        assert not (EVIDENCE/name).exists(), name
    private=(WORK/'python').resolve()
    assert PYTHON.is_file() and PYTHON.resolve().is_relative_to(private)
    assert PORT==35487
    lock=TREE/'backend/requirements.lock'
    pins=locked_versions(lock)
    config=environment()
    base_result=subprocess.run([str(RTK),'proxy',str(PYTHON),'-B','-X','utf8','-c',
        'import sys; print(sys._base_executable)'],cwd=TREE/'backend',env=config,
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
    save('interpreter-base-location.json',{'exit_code':base_result.returncode,
        'stdout':base_result.stdout,'stderr':base_result.stderr,'application_tests_executed':False})
    assert base_result.returncode==0
    base=Path(base_result.stdout.strip())
    assert base.is_file() and base.resolve().is_relative_to(private)
    rows={}
    installed={}
    for label,executable in [('primary',PYTHON),('legacy_base',base)]:
        argv=[str(RTK),'proxy',str(executable),'-B','-X','utf8','-c',PROBE]
        result=subprocess.run(argv,cwd=TREE/'backend',env=config,stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW)
        receipt={'argv':argv,'cwd':str(TREE/'backend'),'exit_code':result.returncode,
            'stdout':result.stdout,'stderr':result.stderr}
        save('interpreter-probe-'+label+'.json',receipt)
        assert result.returncode==0, receipt
        row=json.loads(result.stdout)
        assert row['state']=='DEPENDENCY_PREFLIGHT_READY'
        for key in ('executable','base_executable','prefix','base_prefix','site_packages'):
            assert Path(row[key]).resolve().is_relative_to(private), key
        assert Path(row['executable']).resolve()==executable.resolve()
        assert row['database']['ENGINE']=='django.db.backends.postgresql'
        assert row['database']['HOST']=='127.0.0.1' and row['database']['PORT']==str(PORT)
        assert row['database']['NAME']=='test_b9i_control'
        for key in ('django_file','psycopg_file'):
            assert Path(row[key]).resolve().is_relative_to(WORK.resolve()), key
        for key in ('durable_file','worker_file'):
            assert Path(row[key]).resolve().is_relative_to(TREE.resolve()), key
        versions=package_versions(row)
        differences={name:{'expected':version,'actual':versions.get(name)}
            for name,version in pins.items() if versions.get(name)!=version}
        row['required_lock_versions']=pins
        row['lock_differences']=differences
        row['required_pin_count']=len(pins)
        row['additional_distributions']={name:version for name,version in versions.items() if name not in pins}
        rows[label]=row
        installed[label]=versions
        assert not differences, differences
    assert installed['primary']==installed['legacy_base'], 'Private primary/base distribution versions differ'
    roots=[WORK/'python',TREE/'frontend/node_modules',WORK/'pnpm']
    excluded={'__pycache__','.cache','.vite','.vite-temp'}
    files={}
    for root in roots:
        assert root.is_dir(), root
        for file in sorted(root.rglob('*')):
            if file.is_file() and not excluded.intersection(file.relative_to(root).parts):
                assert file.resolve().is_relative_to(WORK.resolve()), file
                files[str(file)]=sha256(file.read_bytes())
    lock_hash=sha256(lock.read_bytes())
    for label,name in [('primary','python-environment.json'),('legacy_base','base-python-environment.json')]:
        save(name,dict(rows[label],state='PASS',requirements_sha256=lock_hash,
            installed_distribution_count=len(installed[label]),private_prefix_verified=True,
            application_tests_executed=False))
    save('dependency-files.json',{'files':files,'roots':[str(root) for root in roots],
        'requirements_sha256':lock_hash,'excludes':sorted(excluded),
        'installed_files_modified':False})
    save('interpreter-preflight.json',{'state':'PASS','interpreters':rows,
        'required_lock_versions':'PASS','required_pin_count':len(pins),
        'application_package_parity':'PASS','hashed_dependency_files':len(files),
        'application_tests_executed':False,'legacy_B3_entrypoint_executed':False,
        'sys_base_executable_redirected':False,'base_prefix_private':True,
        'global_python_environment_used':False})
    print('DUAL_INTERPRETER_PREFLIGHT_PASS',len(files),flush=True)


if __name__=='__main__':
    main()
