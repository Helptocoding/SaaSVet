"""Close r5 after cleanup, preserving its fixture ERROR and awake interruption.

This post-run helper does not edit any sealed evaluator, test, receipt or patch.
It classifies the retained facts before invoking the existing report generator,
so the same classification reaches REPORT.md, candidate-decision.json and ACTA.
"""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
from datetime import datetime, timedelta, timezone


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
DIAGNOSTICS = HERE / 'diagnostics'
TEST_ID = 'apps.notifications.tests.test_notifications.DerivedFeedTests.test_upcoming_window'
AWAKE_CAUSE = 'Owned awake request unavailable: RuntimeError: Awake heartbeat stale or clock mismatch'
MEXICO_CITY = timezone(timedelta(hours=-6))
GIB = 1024 ** 3
NEW_PASS = ('full-b8d', 'full-b8e')


def require(condition, message):
    if not condition:
        raise RuntimeError('r5 closure: ' + message)


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def save_new(name, value):
    with (HERE / name).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def jsonl(name):
    return [json.loads(line) for line in (HERE / name).read_text(encoding='utf-8').splitlines()
            if line.strip()]


def gaps(rows, host_nested=False):
    def host(row):
        return row['host'] if host_nested else row
    pairs = []
    for first, second in zip(rows, rows[1:]):
        a, b = host(first), host(second)
        interval = b['utc_epoch_seconds'] - a['utc_epoch_seconds']
        if interval > 10:
            pairs.append({'seconds': interval, 'from_utc': a['utc'], 'to_utc': b['utc']})
    return sorted(pairs, key=lambda row: row['seconds'], reverse=True)


def windows_events(started_utc):
    """Read only the relevant System records; retain localized text and raw XML."""
    start = datetime.fromisoformat(started_utc.replace('Z', '+00:00')) - timedelta(hours=1)
    end = datetime.now(timezone.utc) + timedelta(minutes=5)
    command = """[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$evtStart=[DateTime]::Parse('%s').ToLocalTime()
$evtEnd=[DateTime]::Parse('%s').ToLocalTime()
try {
$events=@(Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$evtStart;EndTime=$evtEnd;Id=1,42,107,506,507} -ErrorAction Stop | Where-Object {$_.ProviderName -in @('Microsoft-Windows-Kernel-Power','Microsoft-Windows-Power-Troubleshooter','Microsoft-Windows-Kernel-General')} | Select-Object @{Name='utc';Expression={$_.TimeCreated.ToUniversalTime().ToString('o')}},Id,ProviderName,RecordId,Message,@{Name='xml';Expression={$_.ToXml()}})
[PSCustomObject]@{state='READ_ONLY_CAPTURED';events=$events} | ConvertTo-Json -Depth 5 -Compress
} catch { [PSCustomObject]@{state='UNAVAILABLE';error=$_.Exception.Message} | ConvertTo-Json -Compress }
""" % (start.isoformat(), end.isoformat())
    argv = ['rtk', 'proxy', 'powershell.exe', '-NoProfile', '-Command', command]
    try:
        result = subprocess.run(argv, capture_output=True, timeout=45, check=False)
        payload = json.loads(result.stdout.decode('utf-8-sig'))
        payload['exit_code'] = result.returncode
        payload['stderr'] = result.stderr.decode('utf-8', errors='replace')
        payload['read_only'] = True
        return payload
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {'state': 'UNAVAILABLE', 'read_only': True,
                'error': type(exc).__name__ + ': ' + str(exc)}


def new_complete_pass(label, expected_count, candidate_tree):
    command = read('blocks/' + label + '.command.json')
    gate = read('blocks/' + label + '.gate.json')
    result = read('blocks/' + label + '.results.json')
    selected = read(label + '-selected.json')
    journal = jsonl('blocks/' + label + '.ids.jsonl')
    require(command['state'] == 'COMPLETED' and command['exit_code'] == 0 and
            command.get('invalidating_incident') is None and gate['state'] == 'PASS',
            'new group is not a valid complete PASS: ' + label)
    require(command['candidate_sha'] == result['candidate_sha'] == candidate_tree and
            result['tests'] == expected_count == len(selected) == len(set(selected)) and
            sorted(result['test_ids']) == selected and len(result['test_ids']) == expected_count,
            'new group candidate/inventory mismatch: ' + label)
    require(not any(result.get(key) for key in
                    ('failures', 'errors', 'skips', 'xfail', 'xpass', 'failed_ids', 'exit_code')) and
            len(journal) == expected_count and sorted(row['id'] for row in journal) == selected and
            all(row['outcome'] == 'PASS' for row in journal),
            'new group outcomes incomplete: ' + label)
    return {'label': label, 'state': 'PASS', 'tests': expected_count,
            'origin': 'CURRENT_EXECUTION', 'campaign': HERE.name,
            'command_sha256': sha(HERE / 'blocks' / (label + '.command.json')),
            'results_sha256': sha(HERE / 'blocks' / (label + '.results.json')),
            'journal_sha256': sha(HERE / 'blocks' / (label + '.ids.jsonl'))}


def main():
    require(not (HERE / 'final-classification.json').exists(), 'classification already exists; no overwrite')
    require(not (HERE / 'closure-reporting.json').exists(), 'reporting already completed; no rerun')
    require(not (DIAGNOSTICS / 'invalid-fixture-closure.json').exists(), 'closure already exists')
    require(read('cleanup.json')['state'] == 'PASS', 'private environment cleanup is incomplete')
    require(read('native-closure.json')['state'] == 'PASS', 'native closure is incomplete')
    require(read('resource-observer-closure.json')['state'] == 'PASS', 'observer is not closed')
    awake = read('awake-request/closure.json')
    require(awake['state'] == 'PASS_API_REQUEST_AND_RESTORATION' and
            awake['matches_original_thread_state'] is True, 'awake API restoration is incomplete')
    formal = read('invocation-formal.json')
    require(formal['state'] == 'COMPLETED' and formal['exit_code'] == 2,
            'formal controller is not the retained stopped invocation')
    stop = read('STOP.json')
    command = read('blocks/full-general.command.json')
    require(stop['state'] == 'PENDING' and stop['phase'] == 'full-general' and
            stop['cause'] == AWAKE_CAUSE and command['state'] == 'COMPLETED' and
            command['invalidating_incident'] == AWAKE_CAUSE,
            'retained formal stop differs from the expected awake interruption')
    require(not (HERE / 'blocks/full-general.results.json').exists() and
            not (HERE / 'blocks/full-general.gate.json').exists(),
            'unexpected complete general result/gate requires a fresh classification')
    require(not (HERE / 'supersession.json').exists(), 'unexpected supersession receipt')

    sys.path.insert(0, str(HERE))
    from composite_evidence import validate_references
    manifest = validate_references()
    candidate = read('candidate.json')
    diagnosis = read('diagnostics/notification-clock-classification.json')
    selected = read('full-general-selected.json')
    journal = jsonl('blocks/full-general.ids.jsonl')
    ids = [row['id'] for row in journal]
    errors = [row for row in journal if row['outcome'] == 'ERROR']
    counts = {name: sum(row['outcome'] == name for row in journal)
              for name in ('PASS', 'SKIP', 'ERROR', 'FAIL')}
    require(len(selected) == 3213 and len(ids) == len(set(ids)) == 2639 and
            set(ids).issubset(selected) and counts == {'PASS': 2636, 'SKIP': 2, 'ERROR': 1, 'FAIL': 0},
            'partial outcome inventory changed; reclassify explicitly')
    require(len(errors) == 1 and errors[0]['id'] == TEST_ID and
            errors[0] == diagnosis['error_row'] and diagnosis['test_id'] == TEST_ID and
            diagnosis['candidate_tree'] == candidate['candidate_tree'] and
            diagnosis['classification'] == 'HARNESS_FIXTURE_TIME_DEPENDENCE' and
            diagnosis['product_failure_established'] is False and
            'appointment_end_after_start' in errors[0]['traceback'],
            'fixture diagnosis is not backed by the retained ERROR')
    patch = HERE / diagnosis['proposal']['patch_file']
    require(sha(patch) == diagnosis['proposal']['patch_sha256'], 'approved fixture proposal bytes changed')
    require(diagnosis['proposal']['test_body_ast_identical'] is True and
            diagnosis['proposal']['production_constraint_changed'] is False,
            'fixture proposal changes the test body or product constraint')

    new_pass = [new_complete_pass(label, count, candidate['candidate_tree'])
                for label, count in zip(NEW_PASS, (27, 29))]
    reused = sorted(manifest['blocks'])
    require(len(reused) == 11, 'reference inventory changed')
    accepted = reused + list(NEW_PASS)
    monitor = read('monitor-full-general.json')
    heartbeat = jsonl('awake-request/heartbeat.jsonl')
    observer = jsonl('resource-observer/samples.jsonl')
    monitor_gaps = gaps(monitor, host_nested=True)
    require(bool(monitor_gaps) and monitor[-1]['awake']['state'] == 'UNAVAILABLE',
            'awake interruption is not supported by the monitor')
    events = windows_events(formal['utc_started'])
    event_rows = events.get('events') or []
    if isinstance(event_rows, dict):
        event_rows = [event_rows]
    suspend_corroborated = any(row.get('Id') == 42 and
                              row.get('ProviderName') == 'Microsoft-Windows-Kernel-Power'
                              for row in event_rows) and any(
        row.get('Id') == 107 and row.get('ProviderName') == 'Microsoft-Windows-Kernel-Power'
        for row in event_rows)
    minimum_ram = min(row['host']['physical_available'] for row in monitor)
    minimum_disk = min(row['host']['disk_available'] for row in monitor)
    snapshots = [command['resources_before']['host'], command['resources_after']['host']]
    reserves_met = minimum_ram >= 2 * GIB and minimum_disk >= GIB and all(
        row['physical_available'] >= 2 * GIB and row['disk_available'] >= GIB for row in snapshots)

    untouched = [HERE / name for name in (
        'candidate.json', 'STOP.json', 'invocation-formal.json',
        'blocks/full-general.command.json', 'blocks/full-general.ids.jsonl',
        'monitor-full-general.json', 'diagnostics/notification-clock-classification.json',
        'diagnostics/notification-clock-proposal.patch', 'evaluation-seal.json',
        'run_campaign.py', 'full_partition.py', 'composite_evidence.py',
        'diagnostics/close_acceptance.py')]
    before = {path.relative_to(HERE).as_posix(): sha(path) for path in untouched}
    now = datetime.now(timezone.utc)
    observation = {
        'state': 'CLASSIFIED_FROM_RETAINED_EVIDENCE', 'utc': now.isoformat(),
        'candidate_tree': candidate['candidate_tree'], 'formal_stop': stop,
        'fixture_diagnosis': 'diagnostics/notification-clock-classification.json',
        'fixture_error_utc': errors[0]['utc'], 'fixture_error_id': TEST_ID,
        'fixture_error_precedes_largest_monitor_gap': errors[0]['utc'] < monitor_gaps[0]['from_utc'],
        'partial_general': {'selected': len(selected), 'observed': len(ids), 'outcomes': counts,
                            'missing_ids': sorted(set(selected) - set(ids)),
                            'accepted_as_complete_pass': False},
        'accepted_complete_pass_gates': accepted, 'referenced_pass_count': 11,
        'new_complete_pass_groups': new_pass, 'accepted_complete_gate_count': 13,
        'monitor_gap_intervals': monitor_gaps,
        'awake_heartbeat_gap_intervals': gaps(heartbeat),
        'observer_gap_intervals': gaps(observer),
        'minimum_monitor_ram_bytes': minimum_ram, 'minimum_monitor_disk_bytes': minimum_disk,
        'recorded_monitor_and_before_after_reserves_met': reserves_met,
        'windows_system_events': events,
        'windows_suspend_and_resume_records_observed': suspend_corroborated,
        'interpretation': 'The invalid fixture ERROR is earlier than the awake interruption. '
                          'The formal controller stopped on its awake guard. Windows System '
                          'records, when available, corroborate suspension/resumption; their '
                          'reason fields do not identify a person or prove a resource cause.',
        'resource_shortage_cause_established': False, 'oom_established': False,
        'product_failure_established': False, 'supersession_performed': False,
        'sealed_candidate_fixture_patch_applied': False,
        'source_receipts_and_helpers_sha256': before}
    save_new('diagnostics/fixture-and-awake-observation.json', observation)
    cause = ('Se conservan 13 gates completos PASS: 11 referenciados y full-b8d/full-b8e '
             'nuevos (27/27 y 29/29). Full-general queda incompleto: 2639/3213 IDs, '
             '2636 PASS, 2 SKIP y 1 ERROR por fixture dependiente de la hora en '
             'test_upcoming_window, anterior a la interrupción. La parada formal '
             'corresponde a heartbeat de vigilia inválido tras una brecha de unas '
             '3 horas; los eventos System documentan suspensión/reanudación. '
             'No se establece fallo del producto ni escasez de RAM/disco como causa. '
             'La corrección propuesta del fixture no se aplicó al candidato sellado; '
             'los bloques pendientes necesitan ejecución válida. '
             '[Diagnóstico conjunto](diagnostics/fixture-and-awake-observation.json).')
    if not suspend_corroborated:
        cause = cause.replace('los eventos System documentan suspensión/reanudación',
                              'la captura adicional de eventos System no aporta confirmación independiente de suspensión')
    classification = {
        'decision': 'PENDING',
        'classification': 'HARNESS_FIXTURE_TIME_DEPENDENCE_AND_ENVIRONMENT_AWAKE_INTERRUPTION',
        'date_local': now.astimezone(MEXICO_CITY).date().isoformat(),
        'classified_utc': now.isoformat(), 'cause': cause,
        'evidence_mode': 'COMPOSITE_ACCEPTANCE', 'continuous_single_campaign': False,
        'candidate_tree': candidate['candidate_tree'], 'formal_invocations': 1, 'formal_reruns': 0,
        'accepted_complete_pass_gates': accepted, 'accepted_complete_gate_count': 13,
        'referenced_pass_gates': reused, 'new_complete_pass_groups': list(NEW_PASS),
        'full_general_selected_ids': 3213, 'full_general_observed_ids': 2639,
        'full_general_partial_outcomes': counts, 'full_general_missing_ids': 574,
        'full_general_complete_gate_accepted': False,
        'invalid_fixture_test_id': TEST_ID, 'fixture_error_utc': errors[0]['utc'],
        'formal_environment_stop': AWAKE_CAUSE, 'product_failure_established': False,
        'resource_shortage_cause_established': False, 'oom_established': False,
        'supersession_performed': False, 'sealed_candidate_fixture_patch_applied': False,
        'supporting_evidence': 'diagnostics/fixture-and-awake-observation.json'}
    save_new('final-classification.json', classification)
    reporter = DIAGNOSTICS / 'close_acceptance.py'
    runpy.run_path(str(reporter), run_name='__main__')
    require(read('candidate-decision.json')['decision'] == 'PENDING', 'candidate decision drift')
    require(read('block-status.json')['full-general']['state'] == 'PENDING_ENVIRONMENT_INTERRUPTION',
            'partial general was not retained as interrupted')
    require(all(read('block-status.json')[label]['state'] == 'PASS' for label in accepted),
            'a complete valid PASS was lost')
    report = (HERE / 'REPORT.md').read_text(encoding='utf-8')
    acta = (REPO / 'docs/evals/b9-consolidation-2026-10-11/ACTA.md').read_text(encoding='utf-8')
    require(cause in report and cause in acta, 'joint classification missing from report/ACTA')
    require(all(sha(HERE / name) == digest for name, digest in before.items()),
            'a retained source receipt/helper changed during reporting')
    save_new('diagnostics/invalid-fixture-closure.json', {
        'state': 'PASS', 'technical_acceptance_decision': 'PENDING',
        'classification': classification['classification'],
        'accepted_complete_gate_count': 13, 'product_failure_established': False,
        'formal_supersession_performed': False, 'sealed_candidate_modified': False,
        'reporter_executed': 'diagnostics/close_acceptance.py',
        'reporter_sha256': sha(reporter), 'report_sha256': sha(HERE / 'REPORT.md'),
        'classification_sha256': sha(HERE / 'final-classification.json'),
        'source_receipts_and_helpers_unchanged': True,
        'history_preservation': read('preservation-of-prior-work.json'),
        'application_tests_executed_by_this_helper': False})
    print('INVALID_FIXTURE_AND_AWAKE_CLOSURE_PASS technical_acceptance=PENDING retained_complete_gates=13')


if __name__ == '__main__':
    main()
