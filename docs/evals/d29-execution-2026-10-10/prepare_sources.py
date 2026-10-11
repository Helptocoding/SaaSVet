"""Create a reviewable evaluation copy; never edits protected source files."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = ROOT / 'docs/evals/d29-authorized-probes-2026-10-07/revision2'


def main():
    source = ROOT / 'backend/apps/agent/tests/scheduling_characterization/execution.py'
    text = source.read_text(encoding='utf-8')
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'execute_job')
    body = '\n'.join(text.splitlines()[node.lineno-1:node.end_lineno]) + '\n'
    old = "                if not [m for m in snap['messages'] if m['turn_work_id'] is None and m['status'] == 'pending']:\n                    break\n"
    assert body.count(old) == 1
    body = body.replace(old, '')
    marker = '      with participants(directory, job) as processes:\n'
    initial = '''      if not finite and job['case_id'] == 'R2-09':
        from .runner import wait_ready
        initial_rows = []
        for fixture in fixtures:
            for slot in range(3):
                row = offer(recorder, fixture, slot, phase='INITIAL_READY')
                if row is None:
                    raise RuntimeError('INITIAL_READY_INGRESS_UNRESOLVED')
                initial_rows.append(row)
        for row in initial_rows:
            wait_ready(row)
        recorder.snapshot('initial_ready_before_workers')
'''.replace('from .runner', 'from apps.agent.tests.scheduling_characterization.runner')
    assert body.count(marker) == 1
    body = body.replace(marker, initial + marker)
    body = body.replace('from .', 'from apps.agent.tests.scheduling_characterization.')
    header = '''"""Evaluation copy of execute_job: natural R209 initial cohort and full followup.
Original gates and analysis remain in use. See adaptation-seal.json.
"""
from apps.agent.tests.scheduling_characterization.execution import *
from apps.agent.tests.scheduling_characterization import execution
from launch_bridge import participants

def offer(*args, **kwargs):
    return execution.offer(*args, **kwargs)

def health(processes):
    return execution.health(processes)

'''
    target = HERE / 'prospective_execution.py'
    with target.open('x', encoding='utf-8') as f:
        f.write(header + body)
    sources = {source.as_posix(): hashlib.sha256(source.read_bytes()).hexdigest()}
    for name in ('evaluation_provider.py', 'clock_guard.py', 'guarded.py', 'prepared_probe.py',
                 'host-event-cut.ps1', 'load_case.py', 'verify_case.py'):
        src, dst = PRIOR / name, HERE / name
        with dst.open('xb') as f:
            f.write(src.read_bytes())
        sources[src.as_posix()] = hashlib.sha256(src.read_bytes()).hexdigest()
    with (HERE / 'adaptation-seal.json').open('x', encoding='utf-8') as f:
        json.dump(dict(original_sources=sources, executor_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            changes=['R209 six ordinary initial READY inputs', 'sender prepared before planners for R209',
                     'complete 240 second followup', 'evaluation-only native witnesses']), f, indent=2)


if __name__ == '__main__':
    main()
