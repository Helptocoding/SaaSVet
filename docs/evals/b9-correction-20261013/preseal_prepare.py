"""Retire spent bootstrap archives and record final helper lineage before seal."""
import difflib
import json
from pathlib import Path
import shutil
from prepare_wsl import EVIDENCE,WORK,save,sha256,resources,integrity

def main():
    assert WORK.resolve()==Path('/home/lap/b9i-correction-20261013')
    assert not (EVIDENCE/'evaluation-seal.json').exists()
    assert not (EVIDENCE/'preseal-preparation-cleanup.json').exists()
    rows=[]
    for name in ('downloads','rtk-archive','uv-archive','uv-cache'):
        directory=WORK/name
        assert directory.resolve().parent==WORK.resolve() and not directory.is_symlink()
        if directory.exists():
            files=[p for p in directory.rglob('*') if p.is_file()]
            rows.append({'path':str(directory),'files':len(files),'bytes':sum(p.stat().st_size for p in files)})
            shutil.rmtree(directory)
    integrity('after-bootstrap-cleanup')
    save('preseal-preparation-cleanup.json',{'state':'PASS','retired':rows,'resources':resources(),
        'candidate_or_installed_dependencies_removed':False,'foreign_processes_terminated':False,'application_tests_executed':False})
    prior=EVIDENCE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r8')
    helpers={}
    for file in sorted(EVIDENCE.glob('*.py')):
        source=file.read_text(encoding='utf-8');compile(source,str(file),'exec')
        old=prior/file.name
        helpers[file.name]={'sha256':sha256(file.read_bytes()),'diff_from_r8':''.join(difflib.unified_diff(
            old.read_text(encoding='utf-8').splitlines(True) if old.exists() else [],source.splitlines(True),
            fromfile=prior.name+'/'+file.name,tofile=EVIDENCE.name+'/'+file.name))}
    save('preseal-environment-amendments.json',{'state':'FINAL_BEFORE_SEAL','helpers':helpers,
        'authorized_admission_policy_amended':True,'workload_timing_or_thresholds_changed':False,'authorized_test_corrections':'candidate.json','further_changes_after_seal_permitted':False,'application_tests_executed':False})
    print('PRESEAL_PREPARATION_PASS',flush=True)

if __name__=='__main__':
    main()
