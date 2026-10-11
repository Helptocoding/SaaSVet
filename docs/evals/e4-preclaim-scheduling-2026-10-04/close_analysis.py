"""Validate and close the offline analysis; no database connection or runtime execution."""
import json
import shutil
import socket
import subprocess
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import derive

ROOT, OUT, RUNS = derive.ROOT, derive.OUT, derive.RUNS


def rtk(*args):
    result = subprocess.run([shutil.which('rtk'), *args], cwd=ROOT, check=True,
                            capture_output=True, encoding='utf-8')
    return result.stdout.strip()


def main():
    head = rtk('proxy', 'git', 'rev-parse', 'HEAD')
    branch = rtk('proxy', 'git', 'symbolic-ref', '--short', 'HEAD')
    assert head == derive.HEAD and branch == 'codex/e4-capacity-scheduling'
    verified = derive.integrity()
    assert verified == derive.load(OUT/'input-integrity.json')
    journals, equivalence, cleanup, misses = [], [], [], []
    for run, port in zip(RUNS, (35449, 35451, 35453)):
        prepared = derive.load(run/'prepared.json')
        data = Path(tempfile.gettempdir()) / ('vet-e4-causal-'+prepared['run_id'])
        with socket.socket() as probe:
            probe.settimeout(0.5)
            closed = probe.connect_ex(('127.0.0.1',port)) != 0
        prior = derive.load(run/'cleanup.json')
        assert closed and not data.exists() and prior['status'] == 'CLEANED'
        assert prior['clients'] == prior['waiting_locks'] == prior['prepared_transactions'] == 0
        assert set(prior['dropped_databases']) == set(prepared['databases'])
        cleanup.append({'source_run_id': prepared['run_id'], 'port': port, 'port_closed_now': closed,
                        'data_directory': str(data), 'data_directory_absent_now': not data.exists(),
                        'original_cleanup_sha256': derive.sha(run/'cleanup.json'),
                        'original_cleanup': prior,
                        'new_postgresql_or_workers_started_by_this_analysis': False})
        eq = derive.load(run/'functional-comparison.json')
        assert eq['result'] == 'EQUIVALENT'
        assert eq['tests']['tests'] == 6
        assert all(eq['tests'][k] == 0 for k in ('failures','errors','skips','xfail'))
        assert all(c['on_off_equal'] for c in eq['comparisons'])
        equivalence.append({'run_id': eq['run_id'], 'result': eq['result'], 'tests': eq['tests'],
                            'verified_contracts': eq['verified_contracts'], 'scope': eq['scope'],
                            'receipt_sha256': derive.sha(run/'functional-comparison.json')})
        for f in eq['functional_journals']:
            rows = derive.read_journal(run/f['path'])
            assert rows[-1]['event'] == 'capture_end' and rows[-1]['failed_writes'] == 0
            assert not rows[-1]['open_transaction'] and len(rows) == f['events']
            assert derive.sha(run/f['path']) == f['sha256']
            journals.append({'run_id': eq['run_id'], 'path': str(run/f['path']),
                             'events': len(rows), 'footer_complete': True, 'failed_writes': 0,
                             'sha256': f['sha256']})
        state = derive.load(run/'durable-state.json')
        conv_org = {m['conversation_id']:m['organization_id'] for m in state['messages']}
        pending = [m for m in state['messages'] if m['status'] == 'pending']
        assert all(m['turn_work_id'] is None and m['process_attempts'] == 0 for m in pending)
        attempts = derive.load(run/'per-attempt.json')
        for a in attempts['attempts_without_binding']:
            assert a['outcome'] == 'miss'
            misses.append({'run_id': state['run_id'], 'attempt_id': a['attempt_id'],
                           'session_id': a['session_id'], 'worker': a['worker'],
                           'conversation_id': a['conversation_id'], 'organization_id': conv_org[a['conversation_id']],
                           'outcome': a['outcome'], 'duration_ms': a['duration_ms'],
                           'query_count': a['query_count'],
                           'query_ids': [q['query_id'] for q in a['sql_timings']],
                           'reason': 'No explicit branch reason in journal; do not relabel all misses SATURATED.'})
    derive.save('misses.json', misses)
    files = [
        'docs/contrato-concurrencia-b9c.md',
        'docs/decisions/2026-09-27-b9c-turnwork-concurrency.md',
        'docs/implementacion-b9c-agente-whatsapp-2026-09-27.md',
        'docs/contrato-beta-release-b9d.md',
        'docs/decisions/2026-09-28-b9d-beta-release-gates.md',
        'docs/contrato-execution-guard-b8amd',
        'docs/contrato-presupuesto-turnwork-b9b.md',
        'docs/contrato-elegibilidad-preclaim-b3-c4-w1-v1.md',
        'docs/diagnostico-e4-eligible-claim-2026-09-30.md',
        'docs/plan-implementacion-auditoria-agente-whatsapp-2026-09md',
        'docs/evals/b9c-acceptance-results.json',
        'docs/evals/b9d-acceptance-results.json',
        'docs/evals/e4-claim/final.json',
        'docs/evals/e4-claim/regression-summary.json',
        'backend/apps/agent/tests/test_b9c_concurrency.py',
        'backend/apps/agent/tests/test_b9c_processes.py',
        'backend/apps/agent/tests/test_e4_claim_yield.py',
        'backend/apps/agent/tests/test_e4_yield_processes.py',
        'backend/apps/agent/tests/test_e4_selection.py',
        'backend/apps/agent/worker.py',
        'backend/apps/agent/durable.py',
        'backend/apps/agent/services.py',
        'backend/apps/agent/management/commands/run_agent_worker.py',
        *[(run.relative_to(ROOT)/'run.py').as_posix() for run in RUNS],
    ]
    derive.save('contract-evidence.json', {
        'head': head, 'source_sha256': {f:derive.sha(ROOT/f) for f in files},
        'contract_adjudication': {'B9C_violation_demonstrated':False, 'B9D_violation_demonstrated':False,
            'B8A_violation_demonstrated':False, 'tenant_isolation_violation_demonstrated':False,
            'documented_fairness_violation_demonstrated':False, 'bounded_yield_violation_demonstrated':False,
            'global_bounded_starvation_guarantee_exists':False, 'individual_READY_claim_SLA_exists':False,
            'contract_gap_for_this_analysis':False,
            'new_requirement_would_need_contract_decision':'Bounded waiting for every READY org or sustained noisy 1/s.'},
        'test_evidence_scope':'Existing source inspected and prior immutable receipts validated; no new tests or PROFILE run.',
        'questions': {
            'A': 'Another org can be claimed by the other planner on its eligible poll if capacity/selection/locks allow; no immediate wakeup SLA. Existing blocked-LLM tests and controlled diagnostic equivalence.',
            'B': 'One candidate/org and N=1 prevent noisy monopoly of both authoritative planners. f192 noisy 129/173 ordinary claims; healthy all complete.',
            'C': 'Least-recently-claimed org ranking plus conversation last_activity/id and bounded forecast; no round-robin, quota-share or global starvation bound.',
            'D': 'Configured pauses and observed gaps reconstructed independently per worker. Work195 has 124 complete 1s pauses on admitting worker; overlaps prohibit summing across workers.',
            'E': 'High latency also occurs with free org capacity: healthy f123 W165 and 94.7844987s of noisy f192 W195 interval.',
            'F': 'Saturation/defer is expected, preserves durable input/attempts/budget and returns to polling. Finite right-censoring does not prove infinite starvation.'}})
    summary = derive.load(OUT/'output-summary.json')
    historical = derive.load(ROOT/'docs/evals/e4-claim/final.json')
    assert historical['historical_b9e'] == historical['historical_profile'] == 'FAIL'
    assert historical['b9'] == 'IN_PROGRESS'
    closure = {'analysis_id': 'preclaim-analysis-'+uuid.uuid4().hex,
        'closed_at_utc': datetime.now(timezone.utc).isoformat(),
        'classification': 'OFFLINE_PRECLAIM_SCHEDULING_ANALYSIS',
        'source_execution_classification': 'DIAGNOSTIC_ONLY',
        'exit': 'CAPACITY_LIMIT_CONFIRMED', 'next_action': 'STOP_BEFORE_TUNING',
        'baseline_head': head, 'final_head': head, 'branch': branch, 'new_commits': [],
        'source_integrity': verified, 'existing_functional_comparison': equivalence,
        'functional_journals_revalidated': journals, 'cleanup': cleanup,
        'per_attempt_rows': len(derive.load(OUT/'scheduling-evidence.json')['per_attempt']),
        'misses': len(misses), 'misses_by_run_and_org': dict(Counter(str((m['run_id'],m['organization_id'])) for m in misses)),
        'key_attempts': summary['key_attempts'],
        'historical_turnwork_86_root_cause': 'ROOT_CAUSE_NOT_CONFIRMED',
        'historical_b9e': 'FAIL', 'historical_profile_beta_1': 'FAIL', 'b9': 'IN_PROGRESS',
        'later_2026_10_02_evaluation': 'PRESERVED_UNCHANGED; neither erases nor reclassifies historical FAIL',
        'runtime_changes': False, 'selector_changes': False, 'new_instrumentation': False,
        'new_load_or_synthetic_tests': False, 'profile_runner_invoked': False,
        'deploy': False, 'activation': False, 'production_changes': False,
        'minimal_runtime_fix_candidate': None,
        'conclusion_scope': 'Structural overload under the controlled workload plus observed occupancy/batch/cadence; exact yield share remains unmeasured.',
        'missing_evidence': ['Actual SELECT snapshot predicate values/reasons for excluded organizations to apportion free-capacity yield.',
                             'Explicit sleep entry/exit events to separate overhead inside observed inter-poll gaps.',
                             'Equivalent phase/worker evidence from the historical runtime/run to attribute TurnWork86.'],
        'git_status_after_analysis': rtk('git','status','--short')}
    assert closure['per_attempt_rows'] == 490 and closure['misses'] == 79
    assert len(journals) == 15
    derive.save('closure.json', closure)
    derive.save('preclaim-analysis.json', {
        'schema': 'e4-preclaim-scheduling-conclusion-v1', 'analysis_id': closure['analysis_id'],
        'classification': closure['classification'], 'source_execution_classification': 'DIAGNOSTIC_ONLY',
        'baseline_head': head, 'exit': closure['exit'], 'next_action': closure['next_action'],
        'causes': [
            {'mechanism':'ORGANIZATION_CAPACITY_AND_SERVICE_DEMAND', 'level':'CONFIRMED', 'contract_violation':False,
             'offered_turns_per_second':1, 'controlled_service_lower_bound_seconds':1.1,
             'ideal_capacity_upper_bound_turns_per_second':1/1.1},
            {'mechanism':'OLDER_CONVERSATIONS_WITH_ONE_CANDIDATE_PER_ORG','level':'CONFIRMED','contract_violation':False,
             'f192_work195_older_messages_admitted_during_wait':82},
            {'mechanism':'SEQUENTIAL_WORKER_OCCUPANCY_BATCH_ONE_AND_POLL_PAUSE','level':'CONFIRMED','contract_violation':False},
            {'mechanism':'FREE_CAPACITY_YIELD_RULE','level':'CONFIRMED_RULE_LIKELY_UNQUANTIFIED_LOAD_CONTRIBUTION','contract_violation':False},
            {'mechanism':'SQL_OR_LOCKS_EXPLAIN_MINUTES','level':'NOT_SUPPORTED_FOR_CURRENT_RUNS'},
            {'mechanism':'IMPROPER_STARVATION_OR_NOISY_MONOPOLY','level':'NOT_SUPPORTED_FOR_CURRENT_RUNS'},
            {'mechanism':'INFINITE_WAIT_UNDER_SUCCESSIVE_FUTURE_FORECASTS','level':'POSSIBLE_NOT_OBSERVED'}],
        'run_summaries':summary['run_summaries'], 'key_attempts':summary['key_attempts'],
        'historical_turnwork_86_root_cause':'ROOT_CAUSE_NOT_CONFIRMED',
        'minimal_runtime_fix_candidate':None, 'stop':True,
        'missing_evidence':closure['missing_evidence'],
        'artifact_index':{name: str(OUT/name) for name in ('report.md','scheduling-evidence.json','capacity-intervals.json',
                        'selector-observations.json','provider-proof.json','per-attempt-scheduling.csv','misses.json',
                        'input-integrity.json','contract-evidence.json','closure.json')}})
    files = {p.name:{'sha256':derive.sha(p),'bytes':p.stat().st_size}
             for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'manifest.sha256.json'}
    derive.save('manifest.sha256.json', {'analysis_id':closure['analysis_id'], 'head':head,
                'classification':closure['classification'], 'exit':closure['exit'], 'self_excluded':True,'files':files})
    print(json.dumps({'analysis_id':closure['analysis_id'], 'exit':closure['exit'], 'next_action':closure['next_action'],
                      'protected_head_files':verified['protected_head_files'], 'prior_artifacts':243,
                      'load_journals_revalidated':12,'functional_journals_revalidated':len(journals),
                      'per_attempt_rows':490, 'misses':79, 'cleanup_current_checks':cleanup,
                      'new_manifest_files':len(files)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
