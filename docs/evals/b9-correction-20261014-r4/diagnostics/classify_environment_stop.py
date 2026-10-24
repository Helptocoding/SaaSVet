"""Classify the retained resource stop; never run or retry application tests."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def save(name, data):
    target = HERE / name
    assert not target.exists(), target
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def main():
    stop = read('STOP.json')
    assert stop['state'] == 'PENDING' and stop['phase'] == 'directed'
    assert stop['cause'] == 'Memory reserve exhausted' and stop['no_rerun'] is True
    command = read('blocks/directed.command.json')
    assert command['state'] == 'COMPLETED'
    assert command['invalidating_incident'] == stop['cause'] and command['exit_code'] == -15
    assert read('invocation-formal.json')['exit_code'] == 2
    assert read('cleanup.json')['state'] == read('clock-restoration.json')['state'] == 'PASS'
    assert read('resource-observer-closure.json')['state'] == 'PASS'
    assert read('awake-request/closure.json')['state'] == 'PASS_API_REQUEST_AND_RESTORATION'
    passed = HERE / 'blocks/directed.results.passed.jsonl'
    assert not passed.read_text(encoding='utf-8').strip()
    assert not (HERE / 'blocks/directed.results.json').exists()
    assert len(list((HERE / 'blocks').glob('*.command.json'))) == 1
    partition = read('full-partition.json')
    assert partition['state'] == 'PASS' and partition['total_ids'] == 3331
    assert partition['duplicate_ids'] == 0 and partition['missing_ids'] == []
    assert all(not (HERE / 'blocks' / (row['label'] + '.command.json')).exists()
               for row in partition['groups'])
    monitor = read('monitor-directed.json')
    minimum_host = min(row['host']['physical_available'] for row in monitor)
    minimum_guest = min(row['guest']['physical_available'] for row in monitor)
    minimum_disk = min(row['guest']['disk_available'] for row in monitor)
    assert minimum_host < 2 * GIB <= minimum_guest and minimum_disk >= GIB
    raw = (HERE / 'resource-observer/samples.jsonl').read_bytes()
    samples = [json.loads(line) for line in raw.splitlines()]
    start = command['resources_before']['host']['utc_epoch_seconds']
    end = command['resources_after']['host']['utc_epoch_seconds']
    execution = [row for row in samples if start <= row['utc_epoch_seconds'] <= end]
    before = [row for row in samples if row['utc_epoch_seconds'] < start]
    after = [row for row in samples if row['utc_epoch_seconds'] > end]
    low = [row for row in execution if row['physical_available'] < 2 * GIB]
    assert execution and low
    save('resource-observation-validation.json', {
        'state': 'RESERVE_BREACH_CONFIRMED', 'classification': 'PENDING_ENVIRONMENT_INTERRUPTION',
        'windows_execution_epoch_interval': [start, end],
        'formal_commands_executed': 1, 'execution_windows_samples': len(execution),
        'execution_samples_below_two_GiB': len(low),
        'min_windows_bytes_execution_samples': min(row['physical_available'] for row in execution),
        'min_windows_bytes_command_monitor': minimum_host,
        'min_wsl_bytes_command_monitor': minimum_guest,
        'min_backing_disk_bytes_command_monitor': minimum_disk,
        'max_wsl_clock_skew_seconds': max(abs(row['wall_minus_monotonic_seconds']) for row in monitor),
        'pre_execution_samples_below_reserve': sum(row['physical_available'] < 2 * GIB for row in before),
        'post_execution_samples_below_reserve': sum(row['physical_available'] < 2 * GIB for row in after),
        'observer_file_bytes': len(raw), 'observer_file_sha256': hashlib.sha256(raw).hexdigest(),
        'observer_closed_before_validation': True,
        'limits': 'One-second Windows samples and native command monitor; no continuous sub-second guarantee',
        'oom_demonstrated': False, 'foreign_process_or_application_cause_attributed': False})
    save('assembly-adaptation-verification.json', {
        'state': 'PASS_PREFLIGHT_ONLY', 'candidate_tree': partition['candidate_tree'],
        'groups': partition['groups'], 'total_ids': 3331, 'duplicate_ids': 0, 'missing_ids': [],
        'guard_source_hashes_validated_before_seal': True,
        'sealed_grouping_and_inventories': True,
        'formal_partition_groups_executed': 0,
        'further_product_or_test_changes': False,
        'assertions_guards_locks_loads_times_thresholds_changed': False,
        'no_runtime_pass_claim_for_unexecuted_groups': True})
    candidate = read('candidate.json')
    cause = (
        'El ajuste del ensamblaje quedó implementado y validado antes del sello: '
        'los mismos 3331 IDs, cinco grupos compatibles, sin omisiones ni duplicados. '
        'La nueva campaña se detuvo en directed por RAM disponible en Windows '
        f'({minimum_host / GIB:.3f} GiB en el monitor, reserva fija de 2 GiB). '
        f'El disco conservó al menos {minimum_disk / GIB:.3f} GiB en ese monitor '
        'y WSL mantuvo su reserva. No se completó ningún ID dirigido con recibo. '
        'Los grupos full, los demás checks y PROFILE permanecen NOT_EXECUTED. '
        'La terminación SIGTERM fue la parada propia del guard; no demuestra OOM '
        'ni un fallo del producto. No hubo reintento formal ni transferencia de resultados históricos.')
    save('final-classification.json', {
        'decision': 'PENDING', 'date_local': '2026-10-14', 'phase': 'directed',
        'candidate_tree': candidate['candidate_tree'], 'base_commit': candidate['base_commit'],
        'cause': cause, 'primary_receipt': 'STOP.json',
        'resource_receipt': 'resource-observation-validation.json',
        'assembly_receipt': 'assembly-adaptation-verification.json',
        'formal_controller_invocations': 1, 'formal_reruns': 0,
        'completed_directed_ids_with_receipt': 0, 'full_groups_executed': 0,
        'product_failure_demonstrated': False, 'oom_demonstrated': False,
        'further_campaign_started': False})
    print('ENVIRONMENT_STOP_CLASSIFIED_PENDING', flush=True)


if __name__ == '__main__':
    main()
