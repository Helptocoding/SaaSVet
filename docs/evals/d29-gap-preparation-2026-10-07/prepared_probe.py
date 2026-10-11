"""Explicit single-probe integration; no CLI and no invocation in this phase.

Wraps the existing fixed-base executor. It neither produces jobs/base nor loops
over scenarios. Future user authorization and an isolated lab are prerequisites.
"""
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch
from clock_guard import JournalMonitor, prevent_idle_sleep, verify_host_cuts

HERE = Path(__file__).resolve().parent


def host_cut(path, after=0):
    subprocess.run(['rtk', 'proxy', 'powershell', '-NoProfile', '-File', str(HERE/'host-event-cut.ps1'),
                    '-Output', str(path), '-AfterRecordId', str(after)], check=True,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return json.loads(path.read_text(encoding='utf-8'))


def r103(executor_module, job_path, output):
    """executor_module must be the preserved fixed-base load_case module.

    Existing source/base/demand gates still run. Clock sidecars cannot convert
    an invalid executor receipt to PASS. Supplemental gate and original
    verifier must both succeed after cleanup in the future attempt.
    """
    from apps.agent.tests.scheduling_characterization import execution
    job = json.loads(Path(job_path).read_text(encoding='utf-8'))
    if job['case_id'] != 'R1-03' or job['phase'] != 'ACCREDITATION_SCENARIO':
        raise ValueError('SINGLE_R103_PROBE_ONLY')
    output = Path(output)
    if output.exists():
        raise ValueError('FRESH_ATTEMPT_DIRECTORY_REQUIRED')
    sidecar = output.with_name(output.name + '-clock')
    sidecar.mkdir(parents=True, exist_ok=False)
    monitor = JournalMonitor(output)
    original_health = execution.health
    def health(processes):
        monitor.check()
        return original_health(processes)
    receipt = dict(status='NOT_ACCREDITED', clock_gate_passed=False, physical_accreditation=False,
                   runtime_changes=False, old_attempts_repaired=False)
    try:
        with prevent_idle_sleep() as acquired:
            receipt['idle_guard'] = acquired
            before = host_cut(sidecar/'host-before.json')
            if before.get('error'):
                raise RuntimeError('HOST_EVENTS_UNAVAILABLE')
            monitor.start()
            try:
                search_path = str(HERE) + os.pathsep + os.environ.get('PYTHONPATH', '')
                with patch.dict(os.environ, PYTHONPATH=search_path), patch.object(execution, 'MODULE', 'worker_entry'), \
                        patch.object(execution, 'health', health):
                    executor_module.run(job_path, output)
            finally:
                # The existing executor's participant context stops workers
                # before final capture completion; no force-pass on exception.
                try:
                    receipt['journals'] = monitor.close()
                finally:
                    after = host_cut(sidecar/'host-after.json', before['last_record_id'])
                    receipt['host'] = verify_host_cuts(before, after)
            receipt.update(status='CLOCK_CHECKS_PASSED_PENDING_SCENARIO_VERIFIERS', clock_gate_passed=True)
        receipt['idle_guard_restored'] = True
    except Exception as exc:
        receipt.update(status='NOT_ACCREDITED', error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        with (sidecar/'clock-receipt.json').open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, indent=2)
            stream.write('\n')
