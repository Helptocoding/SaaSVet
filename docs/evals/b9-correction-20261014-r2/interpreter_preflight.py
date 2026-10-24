"""Check locked imports in both actual interpreters without executing tests."""
import json
from pathlib import Path
import subprocess
from prepare_wsl import EVIDENCE, WORK, TREE, PYTHON, RTK, environment, save, sha256

PROBE = r'''
import importlib.metadata as m,json,sys,sysconfig
import django
django.setup()
import apps.agent.durable as durable
import apps.agent.worker as worker
import psycopg
from django.conf import settings
db=settings.DATABASES['default']
print(json.dumps(dict(state='DEPENDENCY_PREFLIGHT_READY',executable=sys.executable,
    base_executable=sys._base_executable,prefix=sys.prefix,site_packages=sysconfig.get_path('purelib'),
    django_file=django.__file__,psycopg_file=psycopg.__file__,durable_file=durable.__file__,worker_file=worker.__file__,
    database={k:str(db.get(k,'')) for k in ('ENGINE','NAME','HOST','PORT')},
    packages=sorted([dict(name=d.metadata['Name'],version=d.version) for d in m.distributions()],key=lambda x:x['name'].lower()))))
'''

def main():
    assert not (EVIDENCE/'evaluation-seal.json').exists()
    assert not (EVIDENCE/'interpreter-preflight.json').exists()
    base=Path(subprocess.check_output([str(RTK),'proxy',str(PYTHON),'-B','-c',
        'import sys; print(sys._base_executable)'],env=environment(),text=True).strip())
    assert base.resolve().is_relative_to((WORK/'python').resolve())
    rows={}
    for label, executable in [('primary',PYTHON),('legacy_base',base)]:
        argv=[str(RTK),'proxy',str(executable),'-B','-X','utf8','-c',PROBE]
        result=subprocess.run(argv,cwd=TREE/'backend',env=environment(),stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        receipt={'argv':argv,'cwd':str(TREE/'backend'),'exit_code':result.returncode,
            'stdout':result.stdout,'stderr':result.stderr}
        save('interpreter-probe-'+label+'.json',receipt)
        assert result.returncode==0, receipt
        rows[label]=json.loads(result.stdout)
        row=rows[label]
        assert row['state']=='DEPENDENCY_PREFLIGHT_READY'
        assert row['database']['HOST']=='127.0.0.1' and row['database']['PORT']=='35482'
        assert row['database']['NAME']=='test_b9i_control'
        for key in ('django_file','psycopg_file'):
            assert Path(row[key]).resolve().is_relative_to(WORK.resolve())
        for key in ('durable_file','worker_file'):
            assert Path(row[key]).resolve().is_relative_to(TREE.resolve())
    def application_packages(row):
        return {x['name'].lower().replace('_','-'):x['version'] for x in row['packages'] if x['name'].lower()!='pip'}
    assert application_packages(rows['primary'])==application_packages(rows['legacy_base'])
    files={}
    for row in rows.values():
        site=Path(row['site_packages']).resolve()
        assert site.is_relative_to(WORK.resolve())
        for file in sorted(site.rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts:
                files[str(file)]=sha256(file.read_bytes())
    save('dependency-files.json',{'files':files,'roots':[r['site_packages'] for r in rows.values()],
        'requirements_sha256':sha256((TREE/'backend/requirements.lock').read_bytes()),'excludes':['__pycache__']})
    save('interpreter-preflight.json',{'state':'PASS','interpreters':rows,
        'application_package_parity':'PASS','hashed_dependency_files':len(files),
        'application_tests_executed':False,'legacy_B3_entrypoint_executed':False,
        'sys_base_executable_redirected':False,'base_prefix_private':True})
    print('DUAL_INTERPRETER_PREFLIGHT_PASS',len(files),flush=True)

if __name__=='__main__':
    main()
