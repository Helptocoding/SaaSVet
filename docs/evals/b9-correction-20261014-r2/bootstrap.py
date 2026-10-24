"""Prepare a distinct fixed campaign without modifying historical evidence."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
PRIOR=HERE.with_name('b9-correction-20261013')
WORK='/home/lap/b9i-correction-20261014-r2'

def save(name,data):
    assert not (HERE/name).exists(),name
    (HERE/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def adapt(source):
    return source.replace('/home/lap/b9i-correction-20261013',WORK).replace('35481','35482').replace('corrected-20261013','corrected-20261014-r2')

def main():
    assert not (HERE/'authorization.json').exists()
    helpers=['prepare_wsl.py','stage_wsl.py','capture_wsl.py','discover_candidate.py','recorded_suite.py',
        'launch_campaign.py','interpreter_preflight.py','host_resources.py','host_observer.py',
        'awake_guard.py','awake_status.py','clock_setup.py','preseal.py','preseal_prepare.py',
        'run_campaign.py','scan_security.py','cleanup_linux.py','restore_wsl.py','deliver_wsl.py']
    for name in helpers:
        (HERE/name).write_text(adapt((PRIOR/name).read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
    for name in ['PLAN.md','scope-manifest.json','candidate.json','correction.diff','resource-policy.json']:
        (HERE/name).write_bytes((PRIOR/name).read_bytes())
    save('authorization.json',{'user':'hazlo','date_local':'2026-10-14',
        'scope':'New single fixed B9 acceptance campaign on the same corrected immutable tree after prior memory-reserve STOP',
        'prior_campaign':'b9-correction-20261013','prior_decision':'PENDING',
        'candidate_tree':'196aceb4f5f234c086b96d8e8af93787613f3c25','further_candidate_corrections':False,
        'maximum_formal_runs_per_block':1,'maximum_formal_runs_per_profile_variant':1,
        'product_tests_gates_loads_and_times_changed':False,'commits_push_deploy_activation_authorized':False})
    save('prior-focused-verification.json',{'source':'../b9-correction-20261013/focused-verification.json',
        'sha256':hashlib.sha256((PRIOR/'focused-verification.json').read_bytes()).hexdigest(),
        'receipt':json.loads((PRIOR/'focused-verification.json').read_text()),
        'executed_in_this_campaign':False,'substitutes_current_acceptance':False})
    # Keep exact dependency/bootstrap versions, replacing only ownership and paths.
    setup=adapt((PRIOR/'prepare_diagnostic.py').read_text(encoding='utf-8'))
    setup=setup[:setup.index('\ndef postgres():')]
    setup=setup.replace("'purpose': '11-test diagnostic, no integral campaign'", "'phase':'PREPARING','purpose':'New fixed integral acceptance, no focused test rerun'")
    setup=setup.replace("folder.name.startswith('b9-integral-acceptance-1947726')", "(folder.name.startswith('b9-integral-acceptance-1947726') or folder.name.startswith('b9-correction-'))")
    setup=setup.replace("assert 'not found' not in linkage, linkage", "assert 'not found' not in linkage, linkage\n        (EVIDENCE/('ldd-'+binary+'.txt')).write_text(linkage,encoding='utf-8')")
    frontend=(PRIOR/'complete_preparation.py').read_text(encoding='utf-8')
    frontend=frontend[frontend.index("    name='node-v20"):frontend.index('    import psycopg')]
    setup+='\n\ndef frontend():\n    import base64\n'+frontend+'\n    integrity("after-frontend-install")\n    print("FRONTEND_PREPARATION_PASS",flush=True)\n'
    setup+='\n\nif __name__=="__main__":\n    {"setup":setup,"frontend":frontend}[sys.argv[1]]()\n'
    (HERE/'prepare_campaign.py').write_text(setup,encoding='utf-8',newline='\n')
    capture=(HERE/'capture_wsl.py').read_text()
    capture=capture.replace("    args = {", "    args = {\n        'setup': ['/usr/bin/python3','-B',LINUX+'/prepare_campaign.py','setup'],\n        'frontend': [WORK+'/tools/rtk','proxy',WORK+'/venv/bin/python','-B',LINUX+'/prepare_campaign.py','frontend'],")
    (HERE/'capture_wsl.py').write_text(capture,encoding='utf-8',newline='\n')
    stage=(HERE/'stage_wsl.py').read_text()
    needle="    command('audit-venv',[PYTHON,'-m','venv',WORK/'audit-venv'])"
    addition="""    changes=json.loads((EVIDENCE/'candidate.json').read_text())['changed_paths']
    for name in changes:
        target=WORK/'security-patch'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(TREE/name,target)
    save('security-history.json',{'head':'194772677ca4e9fe1a1dec7f4dafa48396a6c583','full_history':True,
        'candidate_tree':SHA,'additional_current_tree_paths':changes,'patch_scan_source':str(WORK/'security-patch')})
"""
    stage=stage.replace(needle,addition+needle)
    stage=stage.replace("    integrity('ready')", "    command('interpreters',[PYTHON,'-B',EVIDENCE/'interpreter_preflight.py'],cwd=TREE/'backend')\n    save('base-python-environment.json',json.loads((EVIDENCE/'interpreter-preflight.json').read_text())['interpreters']['legacy_base'])\n    integrity('ready')")
    (HERE/'stage_wsl.py').write_text(stage,encoding='utf-8',newline='\n')
    controller=(HERE/'run_campaign.py').read_text()
    start=controller.index('    paths=[*EVIDENCE.glob')
    end=controller.index('    paths=[p for p in paths',start)
    controller=controller[:start]+"""    paths=[*EVIDENCE.glob('*.py'),*[EVIDENCE/n for n in [
        'scope-manifest.json','PLAN.md','candidate-sources.json','assembly.json','authorization.json',
        'candidate.json','correction.diff','resource-policy.json','resource-observer-control.json',
        'adapter-lineage.json','adapter-lineage-final.json','clock-control.json',
        'awake-request/control.json','preseal-awake-validation.json','prior-focused-verification.json',
        'preseal-preparation-cleanup.json','preseal-environment-amendments.json',
        'dependency-files.json','interpreter-preflight.json','base-python-environment.json',
        'toolchain.json','python-environment.json','profile-compatibility.json','campaign-adaptation.json']],
        *[p for p in (EVIDENCE/'clock-diagnostics').rglob('*') if p.is_file()],
        Path(json.loads((EVIDENCE/'clock-control.json').read_text())['guard_source_linux']),
        Path(json.loads((EVIDENCE/'clock-control.json').read_text())['guard_rtk_linux']),
        *EVIDENCE.glob('*-selected.json'),PYTHON,Path(sys._base_executable),NODE,PNPM,
        WORK/'gitleaks/gitleaks',*PG.glob('*'),DATA/'postgresql.conf',DATA/'pg_hba.conf']
"""+controller[end:]
    controller=controller.replace("'focused_verification_recorded':True", "'prior_focused_verification_reference':'prior-focused-verification.json'")
    (HERE/'run_campaign.py').write_text(controller,encoding='utf-8',newline='\n')
    preseal=(HERE/'preseal.py').read_text().replace("PRIOR = HERE.with_name('b9-integral-acceptance-1947726-wsl-20261012-r9')","PRIOR = HERE.with_name('b9-correction-20261013')")
    (HERE/'preseal.py').write_text(preseal,encoding='utf-8',newline='\n')
    preseal_cleanup=(HERE/'preseal_prepare.py').read_text().replace("'b9-integral-acceptance-1947726-wsl-20261011-r8'","'b9-correction-20261013'")
    (HERE/'preseal_prepare.py').write_text(preseal_cleanup,encoding='utf-8',newline='\n')
    deliver=(HERE/'deliver_wsl.py').read_text()
    line="        f'docs/evals/{HERE.name}/receipt-adapter.diff whitespace=-blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\\n')"
    deliver=deliver.replace(line,"        f'docs/evals/{HERE.name}/receipt-adapter.diff whitespace=-blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\\n'\n        f'docs/evals/{HERE.name}/correction.diff whitespace=-blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\\n')")
    (HERE/'deliver_wsl.py').write_text(deliver,encoding='utf-8',newline='\n')
    (HERE/'diagnostics').mkdir()
    progress=adapt((PRIOR/'diagnostics/progress.py').read_text()).replace('b9-correction-20261013','b9-correction-20261014-r2')
    (HERE/'diagnostics/progress.py').write_text(progress,encoding='utf-8',newline='\n')
    reporting=adapt((PRIOR/'diagnostics/close_acceptance.py').read_text())
    reporting=reporting.replace("'focused-verification.json'","'prior-focused-verification.json'")
    reporting=reporting.replace('Verificación enfocada final:', 'Verificación enfocada de la campaña anterior, sin repetición actual:')
    reporting=reporting.replace('B9 corregido 196aceb','B9 corregido r2 196aceb').replace('../b9-correction-20261013/','../b9-correction-20261014-r2/')
    (HERE/'diagnostics/close_acceptance.py').write_text(reporting,encoding='utf-8',newline='\n')
    # Two selected product/test paths must still equal the already reviewed tree.
    candidate=json.loads((HERE/'candidate.json').read_text())
    def git(*args):return subprocess.check_output(['rtk','proxy','git',*args],cwd=REPO)
    assert git('rev-parse','HEAD').decode().strip()==candidate['base_commit']
    assert git('cat-file','-t',candidate['candidate_tree']).strip()==b'tree'
    assert git('diff','--name-only',candidate['base_commit'],candidate['candidate_tree']).decode().splitlines()==candidate['changed_paths']
    hashes={}
    for name in candidate['changed_paths']:
        frozen=git('show',candidate['candidate_tree']+':'+name)
        assert git('show',':'+name)==frozen
        assert (REPO/name).read_bytes().replace(b'\r\n',b'\n')==frozen
        hashes[name]=hashlib.sha256(frozen).hexdigest()
    save('code-selection.json',{'state':'PASS','explicit_paths':candidate['changed_paths'],
        'staged_code_equals_frozen_candidate_tree':True,'staged_sha256':hashes,'commits_created':0,'pushes_performed':0})
    lineage={}
    for file in HERE.glob('*.py'):
        text=file.read_text();compile(text,str(file),'exec');old=PRIOR/file.name
        lineage[file.name]={'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
            'prior_sha256':hashlib.sha256(old.read_bytes()).hexdigest() if old.exists() else None,
            'diff':''.join(difflib.unified_diff(old.read_text().splitlines(True) if old.exists() else [],text.splitlines(True),fromfile=str(old),tofile=str(file)))}
    save('campaign-adaptation.json',{'state':'PREPARED_BEFORE_SEAL','helpers':lineage,
        'reason':'Prior campaign closed PENDING on host memory; user now authorizes one new campaign',
        'candidate_changed':False,'assertions_gates_loads_and_times_changed':False,
        'changes':'New evidence/workspace/port ownership; reuse preparation without rerunning focused tests; full-history plus exact two-path security scan; preserve diff context whitespace'})
    print('NEW_CAMPAIGN_BOOTSTRAP_PASS')

if __name__=='__main__':main()
