"""Evaluation-only host/clock containment; preserves original intersections."""
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from clock_guard import JournalMonitor, prevent_idle_sleep, verify_host_cuts
from prepared_probe import host_cut

@contextmanager
def guarded(directory):
    from apps.agent.tests.scheduling_characterization import execution
    directory = Path(directory)
    side = directory.with_name(directory.name + '-clock')
    side.mkdir(parents=True, exist_ok=False)
    monitor = JournalMonitor(directory)
    original_health = execution.health
    def health(processes):
        monitor.check()
        original_health(processes)
    def hidden(command, **kwargs):
        kwargs.pop('creationflags', None)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        return subprocess.Popen(command, startupinfo=si, **kwargs)
    launch = SimpleNamespace(Popen=hidden, STDOUT=subprocess.STDOUT,
        TimeoutExpired=subprocess.TimeoutExpired, check_output=subprocess.check_output)
    receipt = dict(status='NOT_ACCREDITED', gate_passed=False)
    try:
        with prevent_idle_sleep() as acquired:
            receipt['idle_guard'] = acquired
            before = host_cut(side/'host-before.json')
            if before.get('error'):
                raise RuntimeError('HOST_EVENTS_UNAVAILABLE')
            monitor.start()
            try:
                with patch.object(execution, 'MODULE', 'worker_entry'), patch.object(execution, 'health', health), patch.object(execution, 'subprocess', launch):
                    yield monitor
            finally:
                try:
                    receipt['journals'] = monitor.close()
                finally:
                    after = host_cut(side/'host-after.json', before['last_record_id'])
                    receipt['host'] = verify_host_cuts(before, after)
            receipt.update(status='CLOCK_CHECKS_PASSED', gate_passed=True)
        receipt['idle_guard_restored'] = True
    except Exception as exc:
        receipt.update(status='INVALID_RUN', error_class=type(exc).__name__, error=str(exc))
        raise
    finally:
        with (side/'clock-receipt.json').open('x', encoding='utf-8') as f:
            json.dump(receipt, f, indent=2)

