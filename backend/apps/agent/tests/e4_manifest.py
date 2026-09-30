"""Hash closed E4 artifacts and attest preserved historical bytes."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path
from .e4_validate import BASELINE, SOURCE


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): raise RuntimeError('Refusing to overwrite manifest')
    root=args.repository/'docs/evals'
    frozen=list(root.glob('profile-beta-1-*')) + [root/name for name in (
        'b9e-first-base.json','b9e-first-blocked.json','b9e-first-meta.json',
        'b9e-first-duplicate.json','b9e-first-saturation.json','b9e-load-summary.json',
        'b9e-first-run-analysis.md')]
    frozen += [args.repository/'backend/apps/agent/tests/b9e_profile.py',
               args.repository/'docs/reporte-aceptacion-b9-profile-beta-1-2026-09-29.md']
    preserved={}
    for file in frozen:
        relative=str(file.relative_to(args.repository)).replace('\\','/')
        original=subprocess.check_output(['rtk','proxy','git','cat-file','blob',BASELINE+':'+relative],cwd=args.repository)
        preserved[relative]=dict(baseline_sha256=hashlib.sha256(original).hexdigest(),
            current_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
            byte_identical=original==file.read_bytes())
    files=sorted(p for p in root.glob('e4-*') if p.is_file() and p!=args.output)
    files += [args.repository/p for p in SOURCE]
    files += sorted((args.repository/'backend/apps/agent/tests').glob('e4*.py'))
    files += [args.repository/'docs/diagnostico-e4-capacidad-scheduling-2026-09-30.md',
              args.repository/'.gitattributes']
    hashes={str(p.relative_to(args.repository)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files}
    candidate=subprocess.check_output(['rtk','proxy','git','rev-parse','HEAD'],cwd=args.repository,text=True).strip()
    source_representations={}
    for relative in SOURCE:
        blob=subprocess.check_output(['rtk','proxy','git','cat-file','blob',candidate+':'+relative],cwd=args.repository)
        executed=(args.repository/relative).read_bytes()
        source_representations[relative]=dict(
            executed_worktree_sha256=hashlib.sha256(executed).hexdigest(),
            runtime_commit_blob_sha256=hashlib.sha256(blob).hexdigest(),
            byte_identical=executed==blob,
            transformation='IDENTICAL' if executed==blob else 'CRLF_TO_LF',
            equivalent_after_crlf_normalization=executed.replace(b'\r\n',b'\n')==blob.replace(b'\r\n',b'\n'))
    source_equivalent=all(v['equivalent_after_crlf_normalization'] for v in source_representations.values())
    result=dict(schema='e4-manifest-v2',baseline=BASELINE,candidate_runtime_commit=candidate,
        environment=dict(python=platform.python_version(),django=importlib.metadata.version('Django'),
            psycopg=importlib.metadata.version('psycopg'),requirements_lock_sha256=hashlib.sha256(
                (args.repository/'backend/requirements.lock').read_bytes()).hexdigest()),
        historical_bytes=preserved,historical_byte_identical=all(v['byte_identical'] for v in preserved.values()),
        runtime_source_representations=source_representations,runtime_source_equivalent=source_equivalent,
        closed_artifact_sha256=hashes,includes_self=False)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(files=len(hashes),historical_byte_identical=result['historical_byte_identical'])))
    return not result['historical_byte_identical'] or not source_equivalent


if __name__ == '__main__': raise SystemExit(main())
