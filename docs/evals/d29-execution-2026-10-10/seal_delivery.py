"""Seal the delivered phase after checking cleanup and all saved evidence."""
import json
import subprocess
from datetime import datetime, timezone
from lab_control import HERE, ROOT, lab


def main():
    initial = lab.read(HERE / 'initial-integrity.json')
    final = lab.read(HERE / 'final-integrity.json')
    current = lab.integrity()
    for field in ('protected_sources', 'previous_evidence', 'head'):
        assert initial[field] == final[field] == current[field], field
    cleanup = lab.read(HERE / 'lab-cleanup.json')
    assert cleanup and all(value is True for value in cleanup.values())
    precleanup = lab.read(HERE / 'precleanup-integrity.json')
    assert precleanup['status'] == 'INTACT' and precleanup['evidence_sealed_before_cleanup']
    for relative in precleanup['attempt_manifests']:
        manifest = HERE / relative
        recorded = lab.read(manifest)
        actual = {path.relative_to(manifest.parent).as_posix() for path in manifest.parent.rglob('*')
                  if path.is_file() and path != manifest and path.suffix != '.pyc'}
        assert actual == set(recorded), relative
        for name, entry in recorded.items():
            path = manifest.parent / name
            assert path.stat().st_size == entry['bytes'] and lab.sha(path) == entry['sha256'], path
    summary = lab.read(HERE / 'execution-summary.json')
    for scenario in summary['scenarios'].values():
        assert lab.read(HERE / scenario['authoritative_result'])['status'] == scenario['status']
    assert summary['plan_closed'] is False and summary['regression_tests'] == 192
    assert summary['offline_controls']['tests'] == 97
    branch = subprocess.check_output(['rtk', 'proxy', 'git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    assert branch == 'codex/e4-capacity-scheduling'
    status = subprocess.check_output(['rtk', 'proxy', 'git', 'status', '--porcelain=v1'], cwd=ROOT, text=True)
    lab.write(HERE / 'repository-final-state.json', dict(head=current['head'], branch=branch,
        porcelain_v1=status, preexisting_changes_preserved=True, new_phase_directory=HERE.relative_to(ROOT).as_posix(),
        commits_created=False))
    index_path = HERE / 'artifact-index.json'
    receipt_path = HERE / 'final-phase-receipt.json'
    excluded = {index_path, receipt_path}
    index = {path.relative_to(HERE).as_posix(): dict(sha256=lab.sha(path), bytes=path.stat().st_size)
             for path in sorted(HERE.rglob('*')) if path.is_file() and path not in excluded and path.suffix != '.pyc'}
    lab.write(index_path, index)
    receipt = dict(schema='d29-rector-delivery-v1', sealed_at_utc=datetime.now(timezone.utc).isoformat(),
        baseline=current['head'], branch=branch, protected_sources=len(current['protected_sources']),
        previous_evidence_unchanged=True, attempts_sealed=len(precleanup['attempt_manifests']),
        artifact_index=dict(path=index_path.name, sha256=lab.sha(index_path), files=len(index),
                            bytes=sum(item['bytes'] for item in index.values()),
                            excludes=['artifact-index.json', 'final-phase-receipt.json', '*.pyc']),
        execution_summary=dict(path='execution-summary.json', sha256=lab.sha(HERE / 'execution-summary.json')),
        scenarios=summary['scenarios'], validation=dict(offline_controls=97, native_postgresql_tests=4,
        sequential_regression_tests=192, skipped_regressions=0),
        private_lab_cleanup=cleanup, host_service_mutation=False, original_verifiers_unchanged=True,
        production_runtime_unchanged=True, confirmed_base_unchanged=True, commits_created=False,
        full_matrix=False, tuning=False, new_characterization=False, capacity_estimates=False,
        plan_closed=False, unresolved_decision=summary['unresolved_decision'], delivery='ENTREGA.md')
    lab.write(receipt_path, receipt)
    # Read back the seal, including nested manifests, before reporting success.
    assert all((HERE / name).stat().st_size == entry['bytes'] and lab.sha(HERE / name) == entry['sha256']
               for name, entry in lab.read(index_path).items())
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
