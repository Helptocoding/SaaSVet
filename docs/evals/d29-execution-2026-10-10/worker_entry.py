"""Private evaluation entry. Provider bytes and runtime remain unchanged."""
import argparse
import json
import os
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
from process_identity import creation
from evaluation_provider import installed as provider_installed
from native_witnesses import installed as witnesses_installed
from forecast_observer import installed as forecast_installed


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['worker'])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--job', type=Path, required=True)
    p.add_argument('--role', choices=['sender', 'planner_1', 'planner_2'], required=True)
    args = p.parse_args()
    from apps.agent.tests.scheduling_characterization import execution
    from apps.agent.tests.scheduling_characterization.runner import bootstrap
    job = json.loads(args.job.read_text(encoding='utf-8'))
    if job['phase'] != 'ACCREDITATION_SCENARIO' or job['case_id'] not in ('R1-06', 'R2-09', 'R2-04', 'R1-04'):
        raise ValueError('PROSPECTIVE_SINGLE_SCENARIO_ONLY')
    bootstrap()
    recorder = execution.Recorder
    original_capture = recorder.capture
    @contextmanager
    def capture(instance,role):
        with original_capture(instance,role) as journal:
            journal.emit('participant_identity',parent_pid=os.getppid(),
                         process_creation_filetime=creation(os.getpid()))
            yield journal
    with provider_installed(execution), witnesses_installed(), forecast_installed(args.output,job,args.role), patch.object(recorder,'capture',capture):
        execution.worker(args.output, args.role, job)


if __name__ == '__main__':
    main()
