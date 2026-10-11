"""One passive R104 investigation on the unchanged sealed base calendar."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
from guarded import guarded
import load_case
import prospective_execution
from apps.agent.tests.scheduling_characterization import execution
from apps.agent.tests.scheduling_characterization.runner import bootstrap,write_json


def main(job_path,d):
    job=json.loads(job_path.read_text())
    assert job['case_id']=='R1-04' and job['variant']=='forecasts'
    original=execution.offer
    ordinal=0
    def offer(recorder,fixture,slot,schedule_slot=None,phase='ORDINARY'):
        nonlocal ordinal
        assert phase=='ORDINARY' and schedule_slot is not None
        slot=ordinal%3
        ordinal+=1
        row=original(recorder,fixture,slot,schedule_slot,phase)
        execution.append(d/'population-slots.jsonl',dict(message_id=row.pk if row else None,
            slot=slot,phase=phase,organization_id=fixture[0].pk,schedule_id=schedule_slot['id']))
        return row
    error=None
    try:
        with guarded(d),patch.object(execution,'execute_job',prospective_execution.execute_job),patch.object(execution,'offer',offer):
            load_case.run(job_path,d)
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc))
        raise
    finally:
        bootstrap()
        from apps.agent.tests.scheduling_characterization.physical import independent
        write_json(d/'full-durable-final.json',independent())
        done=json.loads((d/'dependent-executor-receipt.json').read_text()) if (d/'dependent-executor-receipt.json').exists() else {}
        exits=json.loads((d/'participant-exits.json').read_text()) if (d/'participant-exits.json').exists() else []
        write_json(d/'finite-investigation.json',dict(status='PENDING',scope='ONE_PASSIVE_SEALED_BASE_INVESTIGATION',
            error=error or done.get('error'),planner_holds=False,selector_patch=False,deadline_patch=False,
            artificial_load=False,extra_fixture_inputs=0,full_base_window_executed=done.get('error') is None and bool(done),
            worker_exit_codes=[r['exit_code'] for r in exits]))
        if exits:
            from native_cleanup import capture
            capture(d,exits)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();main(args.job,args.output)
