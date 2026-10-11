"""Deterministic launch-order controls; never physical evidence."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import launch_bridge


class LaunchControls(unittest.TestCase):
    def run_launch(self, case, fail_sender=False):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            started = []
            class Process:
                def __init__(self, command, **kwargs):
                    self.role = command[command.index('--role') + 1]
                    started.append(self.role)
                    self.pid = len(started)
                    self.returncode = 1 if fail_sender and self.role == 'sender' else None
                    if self.returncode is None:
                        (folder / (self.role + '.ready')).write_text('ready')
                def poll(self):
                    return self.returncode
                def wait(self, timeout):
                    self.returncode = self.returncode or 0
                def terminate(self):
                    self.returncode = -1
            error = None
            with patch.object(launch_bridge.execution.subprocess, 'Popen', Process), \
                    patch.object(launch_bridge,'creation',lambda pid:100000+pid):
                try:
                    with launch_bridge.participants(folder, dict(case_id=case)):
                        pass
                except RuntimeError as exc:
                    error = str(exc)
            rows = [json.loads(x) for x in (folder / 'process-launch.jsonl').read_text().splitlines()]
            return started, rows, error, (folder / 'stop').exists()

    def test_meta_sender_ready_precedes_both_planner_launches(self):
        started, rows, error, stopped = self.run_launch('R2-09')
        self.assertEqual(started, ['sender', 'planner_1', 'planner_2'])
        self.assertEqual([(r['event'], r['role']) for r in rows[:2]], [('launch','sender'),('ready_observed','sender')])
        self.assertLess(rows[1]['monotonic_ns'], rows[2]['start_monotonic_bounds'][0])
        self.assertIsNone(error)
        self.assertTrue(stopped)

    def test_sender_failure_never_starts_a_planner(self):
        started, rows, error, stopped = self.run_launch('R2-09', fail_sender=True)
        self.assertEqual(started, ['sender'])
        self.assertIsNotNone(error)
        self.assertTrue(stopped)

    def test_r106_preserves_existing_launch_topology(self):
        started, rows, error, stopped = self.run_launch('R1-06')
        self.assertEqual(started, ['planner_1', 'planner_2', 'sender'])
        self.assertIsNone(error)


if __name__ == '__main__':
    unittest.main()
