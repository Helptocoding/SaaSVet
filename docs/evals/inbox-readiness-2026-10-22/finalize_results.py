"""Post-process retained results and seal the public delivery; never execute a profile."""
import hashlib
import json
from pathlib import Path
import socket
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    (OUT/name).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def decide():
    assert not (OUT/'RESULTS.json').exists()
    stop = json.loads((OUT/'b9-STOP.json').read_text())
    assert stop['state'] == 'FAIL' and stop['phase'] == 'profile-base'
    raw = json.loads((OUT/'blocks/profile-base.json').read_text())
    command = json.loads((OUT/'blocks/profile-base.command.json').read_text())
    assert command['exit_code'] == 0 and command['invalidating_incident'] is None
    assert raw['gates']['healthy_claim_p95_le_10'] is False
    assert raw['warmup_seconds'] == 30 and raw['measurement_seconds'] == 300 and raw['smoke_only'] is False
    seal = json.loads((OUT/'b9-evaluation-seal.json').read_text())
    bad = [p for p,h in seal['files'].items() if not Path(p).is_file() or digest(Path(p)) != h]
    assert not bad, bad[:5]
    monitor = json.loads((OUT/'monitor-profile-base.json').read_text())
    observations = dict(samples=len(monitor), min_ram_bytes=min(r['host']['physical_available'] for r in monitor),
        min_disk_bytes=min(r['host']['disk_available'] for r in monitor),
        max_wall_minus_monotonic_seconds=max(abs(r['wall_minus_monotonic_seconds']) for r in monitor))
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1',35591)) != 0, 'Private cluster still listening'
    assert json.loads((OUT/'b9-cleanup.json').read_text())['state'] == 'PASS'
    result = dict(state='CLOSED_WITH_PENDING_ITEMS',
        migrations='PASS_LOCAL_ONLY', b2='DEFERRED_BY_USER', privacy='PREPARED_FOR_REVIEW_NOT_ACCEPTED',
        meta_reception='EXCLUDED_BY_USER', security='PASS_NEW_HISTORICAL_AND_CORRECTION_VERIFICATION',
        b9='FAIL_BASE', activation='NOT_EXECUTED', original_r12_fail_preserved=True,
        metrics={k:raw[k] for k in ('healthy_claim','safety_dispatch','outbox_dispatch')},
        b9_source_integrity=dict(state='PASS', files=len(seal['files']), mismatches=[]),
        monitor=observations,
        profiles=dict(base='FAIL',blocked_llm='NOT_EXECUTED',meta_slow='NOT_EXECUTED',
                      duplicate='NOT_EXECUTED',saturation='NOT_EXECUTED'),
        original_evaluator_limitation='Metrics aggregate healthy organizations; no per-organization SLO certification claimed',
        future_acceptance_requires_per_organization_reporting=True,
        acceptance_granted=False, product_root_cause_determined=False,
        cleanup='PASS_PRIVATE_POSTGRESQL_STOPPED',
        dependency_audits=dict(classification='ADVISORY',python_findings=162,python_packages=11,
            pnpm_summary=dict(low=8,moderate=39,high=38,critical=0),remediation='OPEN'),
        formal_profile_runs=1, formal_profile_retries=0, automatic_new_campaigns=0,
        deployment=False, commits_created=0, pushes_performed=0)
    save('RESULTS.json',result)
    print(json.dumps(dict(state=result['state'], b9=result['b9'], cleanup=result['cleanup'])), flush=True)


def seal_delivery():
    assert (OUT/'RESULTS.json').exists() and not (OUT/'MANIFEST.json').exists()
    public = [p for p in OUT.rglob('*') if p.is_file()
              and 'runtime' not in p.relative_to(OUT).parts and '__pycache__' not in p.parts]
    review = ROOT/'docs/compliance/inbox-privacy-review-2026-10-22'
    public += [p for p in review.rglob('*') if p.is_file()]
    public += [ROOT/p for p in ('.gitignore','.gitleaksignore','.gitleaks.toml',
        'docs/CIERRE-INBOX-WHATSAPP.md','docs/compliance/arco.md','docs/runbooks/inbox-media.md')]
    paths = sorted(set(public))
    manifest = dict(schema='inbox-readiness-delivery/1', files={p.relative_to(ROOT).as_posix():
        dict(sha256=digest(p), bytes=p.stat().st_size) for p in paths},
        private_runtime_excluded=True, original_historical_evidence_modified=False)
    save('MANIFEST.json',manifest)
    bad = [p for p,r in manifest['files'].items() if digest(ROOT/p) != r['sha256']]
    assert not bad
    print(json.dumps(dict(state='PASS',sealed_files=len(paths),mismatches=bad,
                         manifest_sha256=digest(OUT/'MANIFEST.json'))), flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--decision']:
        decide()
    elif sys.argv[1:] == ['--seal']:
        seal_delivery()
    else:
        raise SystemExit('Use --decision or --seal; no execution/retry mode exists')
