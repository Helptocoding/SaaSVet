"""Run authorized regression/check stages against the retained isolated template."""
import json
import subprocess
import sys

import psycopg
from psycopg import sql

from benchmark import OUT, ROOT, PY, PREFIX, environment


def regression(port, resume=False):
    ids=json.loads((ROOT/'docs/evals/e4-claim/regression-final-inventory.json').read_text())
    assert len(ids)==775 and not any('.test_b9e_' in x for x in ids)
    if resume:
        partial=json.loads((OUT/'regression-partial.json').read_text())
        assert partial['tests']==659 and partial['source_hashes_verified']
        ids=sorted(set(ids)-set(partial['test_ids']))
        assert len(ids)==116
    groups={}
    for identifier in ids:
        groups.setdefault(identifier.rsplit('.',2)[0],[]).append(identifier)
    shards=[[],[]]
    for group in sorted(groups.values(),key=len,reverse=True):
        min(shards,key=len).extend(group)
    inventory='regression-resume-ids.json' if resume else 'regression-ids.json'
    assert resume or not (OUT/inventory).exists()
    (OUT/inventory).write_text(json.dumps(ids,indent=2)+'\n',encoding='utf-8')
    processes=[]
    for index,selected in enumerate(shards):
        stage=('regression-resume-' if resume else 'regression-')+str(index)
        database='test_b8b_e4sql20261001_'+stage.replace('-','_')
        assert not (OUT/(stage+'.results.inventory.json')).exists()
        path=OUT/(stage+'-ids.json')
        path.write_text(json.dumps(sorted(selected),indent=2)+'\n',encoding='utf-8')
        with psycopg.connect(f'postgresql://e4bench@127.0.0.1:{port}/postgres',autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                sql.Identifier(database),sql.Identifier(PREFIX+'template')))
        command=['rtk','proxy',str(PY),'-X','utf8','-m','apps.agent.tests.run_b9a_acceptance',
            '--suite','targeted','--database',database,'--output',str(OUT/stage),
            '--ids-file',str(path)]
        log=(OUT/(stage+'-launcher.log')).open('w',encoding='utf-8')
        proc=subprocess.Popen(command,cwd=ROOT/'backend',env=environment(port,PREFIX+'template'),
                              stdout=log,stderr=subprocess.STDOUT)
        processes.append((stage,proc,log))
        print(json.dumps(dict(stage=stage,selected=len(selected),pid=proc.pid)),flush=True)
    codes=[]
    for stage,proc,log in processes:
        code=proc.wait()
        log.close()
        codes.append(code)
        print(json.dumps(dict(stage=stage,exit_code=code)),flush=True)
    raise SystemExit(max(codes))


def main(stage):
    receipt = json.loads((OUT/'environment-full.json').read_text())
    port = receipt['port']
    if stage in ('regression','regression-resume'):
        return regression(port,resume=stage=='regression-resume')
    if stage in ('oracle-final','oracle-classified'):
        database=PREFIX+stage.replace('-','_')
        assert not (OUT/(stage+'.json')).exists()
        uri=f'postgresql://e4bench@127.0.0.1:{port}/postgres'
        with psycopg.connect(uri,autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                sql.Identifier(database),sql.Identifier(PREFIX+'template')))
        proc=subprocess.run(['rtk','proxy',str(PY),'-X','utf8',str(OUT/'oracle.py'),'--post'],
            cwd=ROOT/'backend',env=environment(port,database),capture_output=True,text=True)
        (OUT/(stage+'-stderr.log')).write_text(proc.stderr,encoding='utf-8')
        assert proc.returncode==0,proc.stderr[-2000:]
        (OUT/(stage+'.json')).write_text(proc.stdout,encoding='utf-8')
        with psycopg.connect(uri,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
        print(stage.upper()+'_PASS',flush=True)
        return
    uri = f'postgresql://e4bench@127.0.0.1:{port}/postgres'
    database = 'test_b8b_e4sql20261001_'+stage.replace('-','_')
    assert stage in ('new','new-final','regression','checks') or stage.startswith('repair-')
    with psycopg.connect(uri,autocommit=True) as conn:
        assert conn.execute("SELECT current_setting('data_directory')").fetchone()[0].replace('\\','/').endswith('/vet-e4-sql-redesign-2026-10-01-data')
        conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
            sql.Identifier(database),sql.Identifier(PREFIX+'template')))
    ids = (['apps.agent.tests.test_e4_sql_selector','apps.agent.tests.test_e4_sql_processes']
           if stage.startswith('new') else json.loads((ROOT/'docs/evals/e4-claim/regression-final-inventory.json').read_text())
           if stage == 'regression' else [])
    path = OUT/(stage+'-ids.json')
    if not path.exists():
        path.write_text(json.dumps(ids,indent=2)+'\n',encoding='utf-8')
    command = ['rtk','proxy',str(PY),'-X','utf8','-m','apps.agent.tests.run_b9a_acceptance',
        '--suite','checks' if stage=='checks' else 'targeted','--database',database,
        '--output',str(OUT/stage),'--ids-file',str(path)]
    print('RUN '+stage+' '+database,flush=True)
    result = subprocess.run(command,cwd=ROOT/'backend',env=environment(port,PREFIX+'template'),
                            capture_output=True,text=True)
    (OUT/(stage+'-launcher.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
    print(json.dumps(dict(stage=stage,returncode=result.returncode)),flush=True)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main(sys.argv[1])
