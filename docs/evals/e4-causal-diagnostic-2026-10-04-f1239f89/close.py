"""Read-only closure checks plus final artifact manifests for this run."""
import json
import socket
import subprocess
from collections import Counter
from datetime import datetime, timezone

import infra
from finalize import read_journal, sha


def load(name):
    return json.loads((infra.OUT/name).read_text(encoding='utf-8'))


def git(*args):
    return subprocess.check_output(['rtk','proxy','git',*args],cwd=infra.ROOT).decode().strip()


def utc_ns(value):
    delta = datetime.fromisoformat(value)-datetime(1970,1,1,tzinfo=timezone.utc)
    return ((delta.days*86400+delta.seconds)*1000000+delta.microseconds)*1000


def assert_private(value):
    forbidden = {'sql','params','body','prompt','password','query_text','dsn','raw_sql'}
    if isinstance(value,dict):
        assert not forbidden.intersection(value)
        for item in value.values():
            assert_private(item)
    elif isinstance(value,list):
        for item in value:
            assert_private(item)


def main():
    report = load('causal-report.json')
    assert report['result_classification'] in ('CAUSE_CONFIRMED','CAUSE_NOT_CONFIRMED')
    assert report['classification'] == 'DIAGNOSTIC_ONLY' and not report['acceptance_run']
    assert git('rev-parse','HEAD') == infra.HEAD
    assert git('rev-parse','HEAD^') == report['baseline']['authorized_runtime_baseline']
    assert git('branch','--show-current') == report['baseline']['branch']
    assert infra.snapshot() == load('protected-sources-before.json') == load('protected-sources-after.json')
    assert not infra.DATA.exists()
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1',infra.PORT)) != 0
    assert all(row['exit_code'] == 0 for row in load('process-exits.json'))
    journal_checks = []
    first_ingest = load('load-inputs.json')['inputs'][0]['ingest_start_ns']
    for role in ('ingress','planner-1','planner-2','sender'):
        name = role+'.jsonl'
        rows = read_journal(infra.OUT/name)
        assert rows[0]['monotonic_ns'] < first_ingest
        assert_private(rows)
        journal_checks.append(dict(path=name,run_id=rows[0]['run_id'],session_id=rows[0]['session_id'],
            capture_before_ingestion=True,events=len(rows),queries=rows[-1]['query_count'],
            footer_complete=True,failed_writes=rows[-1]['failed_writes'],sha256=sha(infra.OUT/name)))
    functional_journal_checks = []
    for path in sorted((infra.OUT/'functional-artifacts').glob('*.jsonl')):
        if path.name.endswith('-waits.jsonl'):
            continue
        rows = read_journal(path)
        assert rows[0]['run_id'].startswith('f-'+infra.KEY+'-')
        assert_private(rows)
        functional_journal_checks.append(dict(path=path.relative_to(infra.OUT).as_posix(),
            run_id=rows[0]['run_id'],session_id=rows[0]['session_id'],events=len(rows),
            queries=rows[-1]['query_count'],footer_complete=True,failed_writes=rows[-1]['failed_writes'],sha256=sha(path)))
    sessions = [row['session_id'] for row in journal_checks+functional_journal_checks]
    assert len(sessions) == len(set(sessions))
    comparisons = []
    for scenario in ('concurrency','lock-wait','blocked-llm','rollback'):
        name = 'functional-artifacts/'+scenario+'-equivalence.json'
        receipt = load(name)
        assert receipt['on_off_equal'] and receipt['off'] == receipt['on']
        comparisons.append(dict(scenario=scenario,receipt=name,sha256=sha(infra.OUT/name),on_off_equal=True))
    functional = dict(classification='DIAGNOSTIC_ONLY',run_id=report['run_id'],result='EQUIVALENT',
        tests=load('functional-results.results.json'),comparisons=comparisons,
        verified_contracts=['selector decisions','SQL order/count/lock clauses',
            'normalized SQL parameters in new/retry/reclaim/busy/not-due test','membership','attempts',
            'lease authority','epoch/fencing','B9B admitted/reserved budget','claim result',
            'outer and savepoint rollback','READY join deadline','reconnection','controlled concurrent admissions',
            'separate readonly observer sees controlled locks','blocked LLM preserves other organization progress'],
        normalization=['auto-generated datetime SQL parameters; authority clocks/leases checked separately',
            'generated savepoint labels','process ordering in controlled concurrency receipts'],
        scope='Same HEAD, identical states and controlled barriers. No scheduling-equality assertion for independently timed concurrent full loads.',
        functional_journals=functional_journal_checks)
    infra.write('functional-comparison.json',functional)

    utc_checks, differences = [], []
    envelope_ms = max(item['range_ms'] for item in report['clock_observation']['utc_minus_monotonic_ranges'].values())
    for claim in report['claims']:
        if not claim['selection_start']:
            continue
        start = claim['selection_start']
        for metric in claim['message_timelines']:
            wall_eligible_s = (start['utc_ns']-utc_ns(metric['effective_inbound_eligible_at']))/1e9
            bounds = metric['eligible_to_selection_seconds_bounds']
            differences.append(wall_eligible_s-sum(bounds)/2)
            if metric['over_10_seconds']:
                wall_persisted_s = (start['utc_ns']-utc_ns(metric['persisted_at']))/1e9
                if report['result_classification']=='CAUSE_CONFIRMED': assert wall_persisted_s > 10
                # Sensitivity check against the largest observed UTC/monotonic offset range.
                # This is an empirical margin, not a clock-service guarantee or a fabricated timestamp.
                lower = metric['persisted_to_eligible_seconds']+bounds[0]-envelope_ms/1000
                if report['result_classification']=='CAUSE_CONFIRMED': assert lower > 10
                utc_checks.append(dict(attempt_id=claim['attempt_id'],message_id=metric['message_id'],
                    selection_utc_observed_ns=start['utc_ns'],persisted_at=metric['persisted_at'],
                    utc_observed_persisted_to_selection_s=wall_persisted_s,
                    utc_observed_eligible_to_selection_s=wall_eligible_s,
                    calibrated_lower_minus_observed_clock_offset_range_s=lower))
    assert len(utc_checks) == len(report['over_10_seconds'])
    queries = 0
    query_errors = Counter()
    with (infra.OUT/'query-timings.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            query = json.loads(line)
            assert_private(query)
            assert query['duration_ns'] == query['execute_end_ns']-query['execute_start_ns']
            queries += 1
            query_errors[query['error_class'] or 'NONE'] += 1
    assert queries == report['all_sql_query_count']
    assert sha(infra.OUT/'query-timings.jsonl') == report['query_timing_sha256']
    assert_private(report)
    original_pids = [row['ProcessId'] for row in load('process-inventory-observed.json')]
    filter_expression = ' OR '.join('ProcessId = '+str(pid) for pid in original_pids)
    command = 'Get-CimInstance Win32_Process -Filter "'+filter_expression+'" | Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json -Compress'
    remaining = subprocess.check_output(['rtk','proxy','powershell','-NoProfile','-Command',command]).decode().strip()
    assert not remaining, remaining
    closure = dict(classification='DIAGNOSTIC_ONLY',result_classification=report['result_classification'],head=infra.HEAD,
        baseline_parent=git('rev-parse','HEAD^'),branch=git('branch','--show-current'),
        protected_files_unchanged=load('protected-sources-before.json')['protected_files'],
        new_runtime_commits=0,tracked_changed_files=git('diff','--name-only').splitlines(),
        main_journals=journal_checks,functional_journals=functional_journal_checks,unique_sessions=True,
        query_timing_count=queries,query_errors=dict(query_errors),source_integrity=True,
        capture_before_first_ingestion=True,observer_complete=load('waits.summary.json')['complete'],
        original_process_ids_absent=True,port_closed=True,data_directory_absent=True,
        utc_crosscheck=dict(over_10_cases=utc_checks,
            min_utc_observed_persisted_to_selection_s=min((x['utc_observed_persisted_to_selection_s'] for x in utc_checks),default=None),
            max_observed_utc_monotonic_offset_range_ms=envelope_ms,
            min_clock_offset_sensitivity_lower_s=min((x['calibrated_lower_minus_observed_clock_offset_range_s'] for x in utc_checks),default=None),
            eligible_to_selection_utc_minus_calibrated_midpoint_ms=[min(differences)*1000,max(differences)*1000],
            limitation='Paired journal UTC observations provide corroboration; empirical offset sensitivity is not a guarantee against unobserved clock steps.'),
        report='causal-report.json',functional_comparison='functional-comparison.json')
    infra.write('closure-validation.json',closure)
    report['artifact_index']['functional_comparison'] = 'functional-comparison.json'
    report['artifact_index']['closure_validation'] = 'closure-validation.json'
    report['artifact_index']['manifest'] = 'manifest.sha256.json'
    report['clock_observation']['utc_crosscheck'] = dict(closure['utc_crosscheck'])
    report['clock_observation']['utc_crosscheck'].pop('over_10_cases')
    with (infra.OUT/'causal-report.json').open('w',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2);stream.write('\n')
    files = {}
    for path in sorted(infra.OUT.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.name != 'manifest.sha256.json':
            files[path.relative_to(infra.OUT).as_posix()] = dict(sha256=sha(path),bytes=path.stat().st_size)
    infra.write('manifest.sha256.json',dict(classification='DIAGNOSTIC_ONLY',result_classification=report['result_classification'],
        run_id=report['run_id'],head=infra.HEAD,self_excluded=True,files=files))
    print(json.dumps(dict(result_classification=report['result_classification'],manifest_files=len(files),
        journals=len(journal_checks),functional_journals=len(functional_journal_checks),
        main_events=sum(x['events'] for x in journal_checks),queries=queries,
        min_utc_persisted_to_selection_s=closure['utc_crosscheck']['min_utc_observed_persisted_to_selection_s'],
        min_clock_sensitivity_lower_s=closure['utc_crosscheck']['min_clock_offset_sensitivity_lower_s'],
        report_sha256=files['causal-report.json']['sha256']),indent=2))


if __name__ == '__main__':
    main()
