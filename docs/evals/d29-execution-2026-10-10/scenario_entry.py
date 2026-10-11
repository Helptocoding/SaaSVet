"""One sealed R106 or R209 job. No retry, matrix or tuning commands."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import load_case
from guarded import guarded
import prospective_execution
from apps.agent.tests.scheduling_characterization import execution
from apps.agent.tests.scheduling_characterization.runner import bootstrap, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--job', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    job = json.loads(args.job.read_text())
    if job['phase'] != 'ACCREDITATION_SCENARIO' or job['case_id'] not in ('R1-06', 'R2-09'):
        raise ValueError('SINGLE_PROSPECTIVE_JOB_ONLY')
    if job['case_id'] == 'R2-09' and job['variant'] not in ('uncertain_meta', 'slow_meta'):
        raise ValueError('SEPARATE_DECLARED_META_VARIANT_REQUIRED')
    original, ordinal = execution.offer, 0
    def offer(recorder, fixture, slot, schedule_slot=None, phase='ORDINARY'):
        nonlocal ordinal
        if phase == 'ORDINARY':
            slot = ordinal % 3
            ordinal += 1
        row = original(recorder, fixture, slot, schedule_slot, phase)
        execution.append(recorder.directory / 'population-slots.jsonl', dict(message_id=row.pk if row else None,
            slot=slot, phase=phase, organization_id=fixture[0].pk,
            scenario_only=job['case_id'] == 'R1-06' and slot == 3,
            schedule_id=schedule_slot['id'] if schedule_slot else None))
        return row
    try:
        with guarded(args.output), patch.object(execution, 'execute_job', prospective_execution.execute_job), \
                patch.object(execution, 'offer', offer):
            load_case.run(args.job, args.output)
    finally:
        bootstrap()
        from apps.agent.tests.scheduling_characterization.physical import independent
        write_json(args.output / 'full-durable-final.json', independent())


if __name__ == '__main__':
    main()
