"""Reuse the previous fixed assembler in a separate, authorized campaign."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
PRIOR=HERE.with_name('b9-correction-20261014-r2')
OLD_WORK='/home/lap/b9i-correction-20261014-r2'
WORK='/home/lap/b9i-correction-20261014-r3'

def save(name,data):
    assert not (HERE/name).exists(),name
    (HERE/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def adapt(text):
    return text.replace(OLD_WORK,WORK).replace('35482','35483').replace('corrected-20261014-r2','corrected-20261014-r3')

def main():
    assert not (HERE/'authorization.json').exists()
    for file in PRIOR.glob('*.py'):
        if file.name!='bootstrap.py':
            (HERE/file.name).write_text(adapt(file.read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
    for name in ['PLAN.md','scope-manifest.json','candidate.json','correction.diff','resource-policy.json','prior-focused-verification.json']:
        (HERE/name).write_bytes((PRIOR/name).read_bytes())
    save('authorization.json',{'user':'continua','date_local':'2026-10-14',
        'scope':'One new fixed B9 acceptance campaign on the same corrected tree after prior host-memory STOP',
        'prior_campaign':PRIOR.name,'prior_decision':'PENDING',
        'candidate_tree':'196aceb4f5f234c086b96d8e8af93787613f3c25',
        'further_candidate_corrections':False,'maximum_formal_runs_per_block':1,
        'maximum_formal_runs_per_profile_variant':1,'product_assertions_gates_loads_and_times_changed':False,
        'commits_push_deploy_activation_authorized':False})
    # Reuse the final preparation imports; no focused verification is repeated.
    assert 'fetch, download, extract' in (HERE/'prepare_campaign.py').read_text()
    controller=(HERE/'run_campaign.py').read_text().replace("'effective-configuration.json','preparation-incident-frontend.json','code-selection.json'", "'effective-configuration.json','code-selection.json'")
    (HERE/'run_campaign.py').write_text(controller,encoding='utf-8',newline='\n')
    for name in ['preseal.py','preseal_prepare.py']:
        source=(HERE/name).read_text().replace("'b9-correction-20261013'","'b9-correction-20261014-r2'")
        (HERE/name).write_text(source,encoding='utf-8',newline='\n')
    (HERE/'diagnostics').mkdir()
    progress=adapt((PRIOR/'diagnostics/progress.py').read_text()).replace('b9-correction-20261014-r2','b9-correction-20261014-r3')
    (HERE/'diagnostics/progress.py').write_text(progress,encoding='utf-8',newline='\n')
    reporter=adapt((PRIOR/'diagnostics/close_acceptance.py').read_text()).replace('B9 corregido r2 196aceb','B9 corregido r3 196aceb').replace('../b9-correction-20261014-r2/','../b9-correction-20261014-r3/')
    reporter=reporter.replace('Verificación enfocada 155 PASS y un skip histórico,','Verificación enfocada anterior, sin repetición actual: 155 PASS y un skip histórico,')
    (HERE/'diagnostics/close_acceptance.py').write_text(reporter,encoding='utf-8',newline='\n')
    candidate=json.loads((HERE/'candidate.json').read_text())
    def git(*args):return subprocess.check_output(['rtk','proxy','git',*args],cwd=REPO)
    assert git('rev-parse','HEAD').decode().strip()==candidate['base_commit']
    assert git('cat-file','-t',candidate['candidate_tree']).strip()==b'tree'
    assert git('diff','--name-only',candidate['base_commit'],candidate['candidate_tree']).decode().splitlines()==candidate['changed_paths']
    hashes={}
    for name in candidate['changed_paths']:
        blob=git('show',candidate['candidate_tree']+':'+name)
        assert git('show',':'+name)==blob
        assert (REPO/name).read_bytes().replace(b'\r\n',b'\n')==blob
        hashes[name]=hashlib.sha256(blob).hexdigest()
    save('code-selection.json',{'state':'PASS','explicit_paths':candidate['changed_paths'],
        'staged_code_equals_frozen_candidate_tree':True,'staged_sha256':hashes,
        'commits_created':0,'pushes_performed':0})
    helpers={}
    for file in HERE.glob('*.py'):
        source=file.read_text();compile(source,str(file),'exec');old=PRIOR/file.name
        helpers[file.name]={'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
            'prior_sha256':hashlib.sha256(old.read_bytes()).hexdigest() if old.exists() else None,
            'diff':''.join(difflib.unified_diff(old.read_text().splitlines(True) if old.exists() else [],source.splitlines(True),fromfile=str(old),tofile=str(file)))}
    save('campaign-adaptation.json',{'state':'PREPARED_BEFORE_SEAL','helpers':helpers,
        'reason':'User continues after prior memory-reserve stop; current host memory 7.38 GiB and C: free disk 2.58 GiB',
        'candidate_changed':False,'assertions_gates_loads_and_times_changed':False,
        'changes':'Separate evidence/workspace/port ownership and prior-lineage references; final previous preparation imports reused; no historical preparation incident injected into current campaign'})
    print('NEW_CAMPAIGN_BOOTSTRAP_PASS')

if __name__=='__main__':main()
