"""Seal this review, preserve historical receipts, and record the accepted debt."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not (OUT/'summary.json').exists() and not (OUT/'MANIFEST.json').exists()
    build = json.loads((OUT/'landing-build.json').read_text())
    assert build['state'] == 'PASS' and len(build['built_pages']) == 18
    assert build['original_landing_notice_unchanged'] and not build['published']
    inventory = json.loads((OUT/'source-inventory.json').read_text())
    assert not inventory['retained_phase3_source_comparison']['mismatches']
    current_mismatches = [r['path'] for r in inventory['files'] if digest(Path(r['path'])) != r['digest']]
    assert not current_mismatches, current_mismatches
    old = ROOT/'docs/evals/inbox-readiness-2026-10-22'
    previous = json.loads((old/'MANIFEST.json').read_text())
    protected = {p:r for p,r in previous['files'].items() if p.startswith((
        'docs/evals/inbox-readiness-2026-10-22/', 'docs/compliance/inbox-privacy-review-2026-10-22/'))}
    old_mismatches = [p for p,r in protected.items() if digest(ROOT/p) != r['sha256']]
    assert not old_mismatches, old_mismatches
    sample_paths = ['docs/evals/inbox-b2-guarantees-2026-10-22/runtime/opaque.bin',
                    'backend/private-media/opaque.bin', 'backend/saaslyvet-inbox-media-spool/wa-opaque.spool']
    check = subprocess.run([shutil.which('rtk'),'proxy','git','check-ignore','--no-index',*sample_paths],
                           cwd=ROOT,capture_output=True,text=True,check=True)
    assert sorted(check.stdout.splitlines()) == sorted(sample_paths)
    result = dict(state='REVIEW_COMPLETE_EXTERNAL_GATES_PENDING',
        b9_latency=dict(state='ACCEPTED_DEBT_NON_BLOCKING', observed_p95_seconds=11.57264,
                       original_target_seconds=10, original_FAIL_preserved=True, current_B9_runs=0),
        checklist=dict(complete=0,total=6),
        declared_country='United States',actual_media_bucket_region_proven=False,
        landing_env_relevant_key_names={'.env':[],'.env.example':[]},
        prior_phase3_sources_checked=16,prior_phase3_mismatches=[],new_product_test_runs=0,
        landing_build=dict(state='PASS',pages=18,source_repo_modified=False,published=False),
        historical_public_outputs_checked=len(protected),historical_output_mismatches=old_mismatches,
        git_exclusions_verified=sample_paths,docker_private_directories_excluded=True,
        real_B2_tests=False,restore_media_drill=False,legal_version_promoted=False,
        production_activated=False,commits_created=0,pushes_performed=0)
    (OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    public = [p for p in OUT.iterdir() if p.is_file()]
    public += [ROOT/p for p in ('.gitignore','backend/.dockerignore','docs/CIERRE-INBOX-WHATSAPP.md',
        'docs/runbooks/RUNBOOK-RESTORE.md','docs/compliance/cierre-b2-whatsapp-2026-10-22.md',
        'docs/decisions/2026-10-22-b9-base-latency-accepted-debt.md')]
    manifest = dict(schema='inbox-b2-guarantees-review/1',private_runtime_excluded=True,
        historical_delivery_manifest_digest=digest(old/'MANIFEST.json'),
        files=[dict(path=p.relative_to(ROOT).as_posix(),digest=digest(p),bytes=p.stat().st_size)
               for p in sorted(public)])
    (OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    assert all(digest(ROOT/r['path']) == r['digest'] for r in manifest['files'])
    print(json.dumps(dict(state='PASS',sealed_files=len(public),historical_outputs_unchanged=len(protected),
                         build_pages=18,b9_latency='ACCEPTED_DEBT_NON_BLOCKING')),flush=True)


if __name__ == '__main__':
    main()
