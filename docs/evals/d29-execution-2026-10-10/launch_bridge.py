"""Sequential preparation, then free workers; never holds a started planner."""
import os
import subprocess
import sys
import time
from process_identity import creation
from contextlib import contextmanager
from apps.agent.tests.scheduling_characterization import execution
from apps.agent.tests.scheduling_characterization.runner import write_json


@contextmanager
def participants(directory, job):
    processes, streams = [], []
    write_json(directory / 'participant-plan.json', job)
    def launch(role):
        stream = (directory / (role + '.log')).open('x', encoding='utf-8')
        streams.append(stream)
        before = time.perf_counter_ns()
        process = execution.subprocess.Popen(['rtk', 'proxy', sys.executable, '-B', '-X', 'utf8', '-m',
            'worker_entry', 'worker', '--output', str(directory), '--role', role,
            '--job', str(directory / 'participant-plan.json')],
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'),
            stdout=stream, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        processes.append(process)
        execution.append(directory / 'process-launch.jsonl', dict(event='launch', role=role,
            launcher_pid=process.pid, launcher_creation_filetime=creation(process.pid),
            start_monotonic_bounds=[before, time.perf_counter_ns()]))
        return process
    def ready(roles):
        end = time.monotonic() + 45
        while not all((directory / (role + '.ready')).exists() for role in roles):
            execution.health(processes)
            if time.monotonic() >= end:
                raise RuntimeError('PARTICIPANT_PREPARATION_TIMEOUT')
            time.sleep(.05)
        for role in roles:
            execution.append(directory / 'process-launch.jsonl', dict(event='ready_observed', role=role,
                monotonic_ns=time.perf_counter_ns()))
    try:
        if job['case_id'] == 'R2-09':
            launch('sender')
            ready(['sender'])
            launch('planner_1')
            launch('planner_2')
            ready(['planner_1', 'planner_2'])
        else:
            for role in ('planner_1', 'planner_2', 'sender'):
                launch(role)
            ready(['planner_1', 'planner_2', 'sender'])
        yield processes
    finally:
        (directory / 'stop').touch()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
        for stream in streams:
            stream.close()
        write_json(directory / 'participant-exits.json', [dict(pid=p.pid, exit_code=p.returncode) for p in processes])
