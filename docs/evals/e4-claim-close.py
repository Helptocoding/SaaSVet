"""Close evidence with exact ID equality, cleanup guards and byte hashes."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'docs/evals/e4-claim'
BASELINE = 'f051c27002986193772ced0fb1e00e19822d26ef'
RUNTIME = ['backend/apps/agent/worker.py','backend/apps/agent/tests/e4_yield_process.py',
           'backend/apps/agent/tests/test_e4_claim_yield.py','backend/apps/agent/tests/test_e4_yield_processes.py']


def git(*args):
    return subprocess.check_output(['rtk','proxy','git',*args],cwd=ROOT,text=True).strip()


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def write(name,value):
    (OUT/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def capture_runtime():
    commit = git('rev-parse','HEAD')
    assert git('rev-parse','HEAD^')==BASELINE
    assert set(git('diff-tree','--no-commit-id','--name-only','-r',commit).splitlines())==set(RUNTIME)
    write('runtime-commit.json',dict(commit=commit,parent=BASELINE,paths=RUNTIME,
        source_sha256={p:sha((ROOT/p).read_bytes()) for p in RUNTIME}))
    print('RUNTIME COMMIT',commit)


def inspect():
    for index in range(3):
        journal=OUT/f'regression-{index}.results.passed.jsonl'
        rows=[json.loads(line) for line in journal.read_text().splitlines()]
        result=OUT/f'regression-{index}.results.json'
        closed=read(result.name) if result.exists() else None
        print('shard',index,'passed',len(rows),'last',rows[-1]['test_id'] if rows else None,
              'result',{key:closed[key] for key in ('tests','failures','errors','skips','xfail','exit_code','seconds')} if closed else 'RUNNING')


def coverage():
    print(json.dumps(dict(Counter(identifier.rsplit('.',2)[0] for identifier in
        read('regression-inventory.json'))),indent=2))


def close():
    summary=read('summary.json'); reg=read('regression-summary.json'); cleanup=read('cleanup.json')
    assert reg['status']=='PASS' and reg['passed']==reg['selected']==775
    assert reg['executed']==898 and reg['final_source_revalidated']==124
    assert reg['preserved_first_attempt']['passed']==773 and reg['preserved_first_attempt']['failures']==1
    assert reg['failures']==reg['errors']==reg['skips']==reg['xfail']==0
    assert len(reg['new_ids'])==11
    assert cleanup['status']=='CLEANED' and cleanup['port_closed'] and cleanup['data_directory_absent'] and cleanup['log_absent']
    assert not cleanup['other_clients'] and cleanup['waiting_locks']==cleanup['prepared_transactions']==0
    assert read('checks.exit.json')['exit_code']==0
    assert read('validation.json')['runtime_changed_paths']==['backend/apps/agent/worker.py']
    for label in ('postfix-final-base','postfix-final-blocked'):
        m=summary['measurements'][label]
        assert m['e4_overrides']=={} and m['warmup_seconds']==30 and m['measurement_seconds']==300
        assert m['healthy_claim']['count']==60 and m['healthy_claim']['missing']==0
        assert m['scope_or_membership_violations']==0
        assert m['max_sampled_processing']==1
        assert max(m['maximum_durable_ordinary_processing_by_org'].values())==1
        assert m['near_ready_noisy_applicable']==0
    report=ROOT/'docs/diagnostico-e4-eligible-claim-2026-09-30.md'
    assert 'Regresión en curso' not in report.read_text(encoding='utf-8')
    assert 'Pendiente del commit runtime' not in report.read_text(encoding='utf-8')
    inventory=read('regression-final-inventory.json')
    modules=dict(Counter(identifier.rsplit('.',2)[0] for identifier in inventory))
    new_hashes={p:dict(raw=sha((ROOT/p).read_bytes()),lf=sha((ROOT/p).read_bytes().replace(b'\r\n',b'\n')))
        for p in RUNTIME}
    final=dict(status='E4_IMPLEMENTED_VERIFIED_'+summary['performance_state'],baseline=BASELINE,
        runtime_commit=read('runtime-commit.json')['commit'],diagnostic_only=True,root_cause='ROOT_CAUSE_CONFIRMED',
        improvement_count=1,formal_profile_rerun=False,profile_candidate_integral='NOT_RUN',
        historical_b9e='FAIL',historical_profile='FAIL',b9='IN_PROGRESS',
        healthy_p95_base=summary['measurements']['postfix-final-base']['healthy_claim']['p95_seconds'],
        healthy_p95_blocked=summary['measurements']['postfix-final-blocked']['healthy_claim']['p95_seconds'],
        regression=dict(selected=775,passed=775,executed=898,final_source_revalidated=124,
            prototype_only_passed=651,all_ids_on_final_source=False,
            preserved_first_attempt_failures=1,unresolved_failures=0,errors=0,skips=0,xfail=0,modules=modules,new_ids=reg['new_ids']),
        checks='PASS',migrations=0,cleanup='CLEANED',
        production=dict(state='PENDING_ACTIVATION_REQUIREMENTS',B0='CLOSED',B7B=False,
            execution_flags={},release_grants=[],active_clinics=0,deploy=False,
            evidence='Preserved user baseline; no productive DB was contacted or activated'),
        source_hashes=new_hashes,environment=dict(python=platform.python_version(),platform=platform.platform(),
            postgresql='16.15; fsync=on; synchronous_commit=on',django='6.0.5'),
        closed_utc=datetime.now(timezone.utc).isoformat(),next_step='STOP; formal review/profile v1 integral later, no second tuning')
    write('final.json',final)
    files=sorted(p for p in OUT.iterdir() if p.is_file() and p.name!='manifest.sha256.json')
    files += [ROOT/'.gitattributes',report]
    files += sorted(ROOT.glob('docs/evals/e4-claim-*.py'))
    files += [ROOT/p for p in RUNTIME]
    files += [ROOT/'backend/apps/agent/tests/e4_claim_diagnostic.py',ROOT/'backend/apps/agent/tests/e4_claim_candidate.py']
    write('manifest.sha256.json',dict(schema='e4-claim-byte-manifest-v1',self_excluded=True,
        evidence_policy='Raw evidence bytes preserved by -text; code includes LF projection for autocrlf checkouts',
        files={str(path.relative_to(ROOT)).replace('\\','/'):dict(bytes=path.stat().st_size,sha256=sha(path.read_bytes()),
            sha256_lf=sha(path.read_bytes().replace(b'\r\n',b'\n'))) for path in files}))
    print('CLOSED evidence files',len(files),'IDs',len(inventory),'runtime',final['runtime_commit'])


def verify_index():
    entries=read('manifest.sha256.json')['files']
    # Keep Windows/RTK process command lines small; the full 216-path argv
    # intermittently fails CreateProcess with WinError 5 on this host.
    paths=list(entries)
    lines=[]
    for offset in range(0,len(paths),30):
        lines.extend(git('ls-files','-s','--',*paths[offset:offset+30]).splitlines())
    indexed={line.split('\t',1)[1]:line.split()[1] for line in lines}
    assert set(indexed)==set(entries)
    for name,entry in entries.items():
        content=(ROOT/name).read_bytes()
        normalized=content.replace(b'\r\n',b'\n')
        if name.startswith('docs/evals/e4-claim/'):
            assert sha(content)==entry['sha256'], name
        else:
            assert sha(content)==entry['sha256'] or sha(normalized)==entry['sha256_lf'], name
        raw_blob=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        lf_blob=hashlib.sha1(b'blob '+str(len(normalized)).encode()+b'\0'+normalized).hexdigest()
        if name.startswith('docs/evals/e4-claim/'):
            assert indexed[name]==raw_blob, ('Evidence byte normalization',name)
        else:
            assert indexed[name] in (raw_blob,lf_blob), name
    print('INDEX VERIFIED',len(entries),'manifested files; raw evidence bytes preserved')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('inspect','coverage','capture-runtime','close','verify-index'))
    action=parser.parse_args().action
    {'inspect':inspect,'coverage':coverage,'capture-runtime':capture_runtime,'close':close,'verify-index':verify_index}[action]()
