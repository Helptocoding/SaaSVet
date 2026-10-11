"""Future isolated worker entry: corrected provider installed in every process."""
import argparse
import json
from pathlib import Path
from evaluation_provider import installed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['worker'])
    parser.add_argument('--output', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--role', required=True, choices=['planner_1', 'planner_2', 'sender'])
    args = parser.parse_args()
    from apps.agent.tests.scheduling_characterization import execution
    job = json.loads(Path(args.job).read_text(encoding='utf-8'))
    if job['phase'] != 'ACCREDITATION_SCENARIO' or job['case_id'] not in ('R1-03', 'R1-04', 'R2-04', 'R2-09'):
        raise ValueError('PREPARED_ACCREDITATION_WORKER_ONLY')
    with installed(execution):
        execution.worker(Path(args.output), args.role, job)


if __name__ == '__main__':
    main()
