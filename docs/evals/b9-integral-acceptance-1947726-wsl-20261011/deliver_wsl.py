"""Conserve and recover evidence, then stage only the explicit delivery paths."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from restore_wsl import restore

EVIDENCE=Path(__file__).resolve().parent
REPO=EVIDENCE.parents[2]

def digest(data):return hashlib.sha256(data).hexdigest()
def save(name,data):(EVIDENCE/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def run(*args):return subprocess.check_output(['rtk','proxy',*map(str,args)],cwd=REPO,stdin=subprocess.DEVNULL)

def main():
    if (EVIDENCE/'preservation-manifest.json').exists():
        raise RuntimeError('Evidence already conserved; refusing overwrite')
    head=run('git','rev-parse','HEAD').decode().strip()
    branch=run('git','branch','--show-current').decode().strip()
    original=json.loads((EVIDENCE/'checkout-before.json').read_text())
    if head!=original['head'] or branch!=original['branch']:
        raise RuntimeError('Shared checkout HEAD/branch changed')
    prior=json.loads((EVIDENCE/'preservation-of-prior-work.json').read_text())
    if prior['prior_campaign_mismatches'] or not prior['unrelated_unchanged']:
        raise RuntimeError('Prior work preservation failed')
    staged_names=run('git','diff','--cached','--name-only','-z').decode().split('\0')
    baseline={name:digest(run('git','show',':'+name)) for name in filter(None,staged_names)}
    save('index-before-delivery.json',baseline)
    for path in (REPO/'.gitattributes',REPO/'.gitignore'):
        lines=(
            '\n# B9E Linux/WSL2: preserve this campaign evidence byte for byte.\n'
            f'docs/evals/{EVIDENCE.name}/** -text whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\n'
            f'docs/evals/{EVIDENCE.name}/evidence-packages/* -diff\n'
            if path.name=='.gitattributes' else
            '\n# Raw Linux campaign logs are conserved inside its evidence package.\n'
            f'docs/evals/{EVIDENCE.name}/**/*.log\n'
            f'docs/evals/{EVIDENCE.name}/__pycache__/\n')
        if EVIDENCE.name in path.read_text(encoding='utf-8'):
            raise RuntimeError('Delivery attributes already present')
        with path.open('a',encoding='utf-8',newline='\n') as stream:stream.write(lines)
    save('checkout-final.json',{'head':head,'branch':branch,'status_before_staging':run('git','status','--porcelain=v1','-uall').decode(),
        'commits_created':0,'pushes_performed':0,'previous_staged_paths':len(baseline)})
    paths=sorted(p for p in EVIDENCE.rglob('*') if p.is_file() and '__pycache__' not in p.parts
        and 'evidence-packages' not in p.parts)
    inventory={p.relative_to(EVIDENCE).as_posix():{'sha256':digest(p.read_bytes()),'bytes':p.stat().st_size} for p in paths}
    save('artifact-index.json',inventory)
    paths.append(EVIDENCE/'artifact-index.json')
    files={p.relative_to(EVIDENCE).as_posix():{'sha256':digest(p.read_bytes()),'bytes':p.stat().st_size} for p in paths}
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for p in paths:archive.write(p,p.relative_to(EVIDENCE).as_posix())
    data=buffer.getvalue()
    package=EVIDENCE/'evidence-packages';package.mkdir()
    parts=[]
    for n,start in enumerate(range(0,len(data),40*1024**2),1):
        content=data[start:start+40*1024**2]
        p=package/('campaign.zip.part'+str(n).zfill(3));p.write_bytes(content)
        parts.append({'path':p.relative_to(EVIDENCE).as_posix(),'sha256':digest(content),'bytes':len(content)})
    save('preservation-manifest.json',{'schema':'b9i-wsl-preservation-v1','files':files,'parts':parts,'archive_sha256':digest(data)})
    with tempfile.TemporaryDirectory(prefix='b9i-wsl-recovery-') as temporary:
        proof=restore(EVIDENCE,Path(temporary)/'restored')
        command=['rtk','proxy',sys.executable,'-B',str(EVIDENCE/'restore_wsl.py'),'--destination',str(Path(temporary)/'cli-restored')]
        result=subprocess.run(command,cwd=REPO,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if result.returncode:raise RuntimeError('CLI recovery failed: '+result.stderr.decode(errors='replace'))
        cli=json.loads(result.stdout)
        if cli['state']!='PASS':raise RuntimeError('CLI recovery did not pass')
    save('preservation-verification.json',{'internal_restore':proof,'actual_cli_restore':cli,
        'package_sha256':digest(data),'raw_logs_preserved_without_git_normalization':True})
    selected=sorted(p.relative_to(REPO).as_posix() for p in EVIDENCE.rglob('*') if p.is_file()
        and p.suffix!='.log' and '__pycache__' not in p.parts)
    selected+=['.gitattributes','.gitignore','docs/evals/b9-consolidation-2026-10-11/ACTA.md']
    selection_path=(EVIDENCE/'git-selection.json').relative_to(REPO).as_posix()
    verification_path=(EVIDENCE/'delivery-verification.json').relative_to(REPO).as_posix()
    selected=sorted(set(selected+[selection_path,verification_path]))
    save('git-selection.json',{'paths':selected,'explicit':True,'raw_logs_excluded_from_git':True})
    # Save this preliminary receipt before staging; the final one replaces only itself.
    save('delivery-verification.json',{'state':'VERIFYING','selected_paths':len(selected)})
    run('git','add','--',*selected)
    raw=run('git','diff','--cached','--check')
    if raw:raise RuntimeError('Unexpected whitespace output')
    changed_prior=[name for name,h in baseline.items() if name not in
        ('.gitattributes','.gitignore','docs/evals/b9-consolidation-2026-10-11/ACTA.md')
        and digest(run('git','show',':'+name))!=h]
    mismatches=[];normalized_text=[]
    for name in selected:
        local=(REPO/name).read_bytes();staged=run('git','show',':'+name)
        if local!=staged:
            if name in ('.gitattributes','.gitignore') and local.replace(b'\r\n',b'\n')==staged.replace(b'\r\n',b'\n'):
                normalized_text.append(name)
            else:mismatches.append(name)
    if changed_prior or mismatches:raise RuntimeError('Staging integrity failed')
    artifact_drift=[name for name,row in files.items() if digest((EVIDENCE/name).read_bytes())!=row['sha256']]
    if artifact_drift:raise RuntimeError('Preserved files drifted')
    save('delivery-verification.json',{'state':'PASS','selected_paths':len(selected),
        'evidence_git_blobs_equal_local_bytes':True,'root_text_normalized_paths':normalized_text,
        'prior_staged_paths_checked':len(baseline),
        'prior_staged_drift_outside_three_delivery_files':changed_prior,'evidence_drift':artifact_drift,
        'cached_diff_check_exit_code':0,'commits_created':0,'pushes_performed':0})
    run('git','add','--',verification_path)
    if run('git','show',':'+verification_path)!=(REPO/verification_path).read_bytes():
        raise RuntimeError('Final delivery receipt differs in index')
    run('git','diff','--cached','--check')
    print(json.dumps({'state':'PASS','selected_paths':len(selected),'recovered_members':proof['recovered_members'],
        'previous_staged_paths_preserved':len(baseline),'commits':0,'pushes':0}))

if __name__=='__main__':main()
