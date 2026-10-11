"""Read-only reconciliation of existing B9/E4/D29 acceptance evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROFILE = ROOT / 'docs/evals/profile-beta-1-e4-sql-2026-10-02'


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify_map(base, mapping):
    mismatches = []
    for name, value in mapping.items():
        expected = value['sha256'] if isinstance(value, dict) else value
        path = base / name
        if not path.is_file() or sha(path) != expected:
            mismatches.append(name)
    return {'count': len(mapping), 'mismatches': mismatches}


def main():
    profile = read(PROFILE / 'evaluation-summary.json')
    corpus = read(PROFILE / 'corpus-decision.json')
    instrumentation = read(ROOT / 'docs/evals/e4-instrumentation-2026-10-03/closure.json')
    old_b9d = read(ROOT / 'docs/evals/b9d-acceptance-results.json')
    profile_artifacts = verify_map(PROFILE, read(PROFILE / 'manifest.sha256.json')['files'])
    frozen = verify_map(ROOT, profile['frozen_hashes'])
    hooks = verify_map(ROOT, instrumentation['runtime_sha256'])
    profile_sources = read(PROFILE / 'corpus-canonical.results.sources.json')
    current_deltas = verify_map(ROOT, profile_sources)
    expected_hooks = {'backend/apps/agent/durable.py', 'backend/apps/agent/services.py', 'backend/apps/agent/worker.py'}
    unexpected = sorted(set(current_deltas['mismatches']) - expected_hooks)
    by_id = {key: row for group in corpus['by_canonical_id'].values() for key, row in group.items()}
    test_ids = sorted({row['test_id'] for row in by_id.values()})
    historical_ids = set(test_id for run in old_b9d['runs'].values() for test_id in run.get('passed_ids', []))
    historical_negatives = sorted(test_id for test_id in historical_ids if
        test_id.startswith('apps.agent.tests.test_b2_results.') or
        test_id.endswith('.test_question_never_confirms') or
        test_id.endswith('.test_indirect_question_never_confirms'))
    negative_coverage = [{
        'test_id': test_id, 'passed_in_b9d_historical_receipt': True,
        'in_profile_46_selected_ids': test_id in test_ids,
        'current_execution_claimed': False,
    } for test_id in historical_negatives]
    witnesses = [
        'docs/evals/b9a-acceptance-results.json', 'docs/evals/b9b-acceptance-results.json',
        'docs/evals/b9c-acceptance-results.json', 'docs/evals/b9d-acceptance-results.json',
        'docs/evals/profile-beta-1-requirements-matrix.md',
        'docs/evals/profile-beta-1-e4-sql-2026-10-02/evaluation-summary.json',
        'docs/evals/profile-beta-1-e4-sql-2026-10-02/corpus-decision.json',
        'docs/evals/profile-beta-1-e4-sql-2026-10-02/manifest.sha256.json',
        'docs/evals/e4-instrumentation-2026-10-03/closure.json',
        'docs/evals/e4-preclaim-scheduling-2026-10-04/closure.json',
        'docs/evals/d29-phase-closure-2026-10-10/CIERRE.md',
        'docs/evals/d29-phase-closure-2026-10-10/r204-duration-audit.json',
        'docs/evals/d29-r104-decision-2026-10-10.md',
        'docs/evals/profile-beta-1-operational-readiness.md',
    ]
    result = {
        'schema': 'b9-acceptance-reconciliation-v1', 'date': '2026-10-11',
        'scope': 'Consolidation of existing receipts, no new acceptance execution',
        'technical_delivery': 'CONSOLIDATED',
        'profile_candidate_result': profile['profile_result'],
        'profile_candidate_sha': profile['profile_baseline_sha'],
        'current_head_reference': '825db75df68bf076929fa787e77beefe96803350',
        'current_integral_candidate_acceptance': 'PENDING_NOT_INFERRED_FROM_COMPOSITE_HISTORY',
        'activation': 'PENDING_ACTIVATION_REQUIREMENTS',
        'profile_artifact_integrity': profile_artifacts,
        'frozen_profile_inputs': frozen,
        'instrumentation_runtime_integrity': hooks,
        'profile_source_comparison': current_deltas,
        'unexpected_profile_source_deltas': unexpected,
        'instrumentation_equivalence': {
            'kind': 'FUNCTIONAL_NOT_TEMPORAL',
            'existing_receipt_unique_ids': instrumentation['total_unique_tests'],
            'functional_ast_after_removing_named_hooks': instrumentation['functional_ast_after_removing_named_hooks'],
            'selector_ast_identical': instrumentation['selector_ast_identical'],
            'no_fresh_profile_at_current_head': True,
        },
        'profile_corpus': {'selected_unique': len(test_ids), 'canonical_id_references': len(by_id),
                           'status': corpus['status'], 'failures': corpus['failures'], 'errors': corpus['errors'],
                           'skips': corpus['skips'], 'xfail': corpus['xfail']},
        'profile_scenario_gates': {name: row['gates'] for name, row in profile['scenarios'].items()},
        'profile_base_claim_p95_seconds': profile['scenarios']['base']['healthy_global']['p95'],
        'profile_blocked_claim_p95_seconds': profile['scenarios']['blocked_llm']['healthy_global']['p95'],
        'historical_b9d_accepted_unique': old_b9d['accepted_unique_total'],
        'historical_b9d_negative_evidence': negative_coverage,
        'explicit_limits': [
            'I04/I07 negative history is not represented as a fresh exact rerun of every negative on the current candidate.',
            'The 2384 historical IDs, 216 composite instrumentation IDs and 192 D29 IDs are separate scopes, not a full current acceptance run.',
            'PROFILE_PASS belongs to 0831046; functional hook equivalence does not transfer latency measurements to 825db75.',
            'No real model/Meta promotion evaluation, human/clinical approval or privacy approval is created by this act.',
            'D29 remains closed administratively with R1-04 PENDING; no new attempts or full matrix are authorized.',
        ],
        'witnesses': [{'path': p, 'sha256': sha(ROOT / p)} for p in witnesses],
        'application_tests_executed': False, 'runtime_changed': False, 'commit_created': False,
    }
    (HERE / 'acceptance-reconciliation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('profile_artifact_integrity', 'frozen_profile_inputs',
        'instrumentation_runtime_integrity', 'profile_source_comparison', 'unexpected_profile_source_deltas', 'profile_corpus')}, indent=2))
    assert not profile_artifacts['mismatches'] and not frozen['mismatches'] and not hooks['mismatches'] and not unexpected
    assert len(test_ids) == 46 and len(by_id) == 47 and corpus['status'] == 'PASS'
    assert not any(corpus[k] for k in ('failures', 'errors', 'skips', 'xfail'))
    assert all(value is True for row in result['profile_scenario_gates'].values() for value in row.values())


if __name__ == '__main__':
    main()
