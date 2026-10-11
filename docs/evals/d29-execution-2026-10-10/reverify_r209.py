"""Read-only versioned reconciliation; the original attempt is never rewritten."""
import json
import os
import sys
from unittest.mock import patch
from pathlib import Path
from lab_control import HERE,ROOT,lab


if __name__=='__main__':
    folder=Path(sys.argv[1]).resolve()
    task,state=lab.session()
    os.environ.update(lab.environment(state['config'],Path(state['copy'])))
    sys.path[:0]=[str(HERE),str(Path(state['copy'])/'backend'),str(ROOT/'docs/evals/d29-offline-preparation-2026-10-09')]
    from apps.agent.tests.scheduling_characterization.execution import digest
    from apps.agent.tests.scheduling_characterization.runner import bootstrap,write_json
    from native_verifier_bridge import installed
    from r209_verification_v3 import verify
    bootstrap()
    job=json.loads((folder/'job.json').read_text())
    archive=json.loads((folder/'execution-source-archive.json').read_text())
    assert digest({k:v for k,v in job.items() if k!='job_sha256'})==job['job_sha256']
    assert archive==job['evaluation_source_hashes']
    assert all(lab.sha(folder/'execution-sources'/name)==sha for name,sha in archive.items())
    clock=json.loads((folder/'capture-clock/clock-receipt.json').read_text())
    assert clock['gate_passed']
    exits=json.loads((folder/'capture/participant-exits.json').read_text())
    assert len(exits)==3 and all(p['exit_code']==0 for p in exits)
    from load_case import validate_base
    validate_base(job['confirmed_base_reference'])
    from apps.channels.models import Message
    from sealed_census import output_row
    census=json.loads((folder/'capture/full-durable-final.json').read_text())
    with installed(),patch.object(Message.objects,'get',lambda **kwargs:output_row(census,**kwargs)):
        result=verify(folder/'capture',job)
    write_json(folder/'capture/prospective-reconciliation-v3.json',result)
    receipt=dict(status='PENDING' if result['errors'] else 'ACCREDITED',case_id=job['case_id'],variant=job['variant'],
        errors=result['errors'],clock_gate=clock,physical_execution=True,physical_run_repeated=False,
        gates=result['gates'],counts=result['reconciliation']['counts'],native_ancestry=result['native_ancestry'],
        original_provisional_result='physical-verification.json',execution_source_archive_verified=True,
        verification_source_hashes={name:lab.sha(HERE/name) for name in
            ['reverify_r209.py','r209_verification_v3.py','native_ancestry.py','test_native_ancestry.py','native_verifier_bridge.py','sealed_census.py','test_sealed_census.py']})
    write_json(folder/'physical-verification-v3.json',receipt)
    from django.db import connections
    connections.close_all()
    print(json.dumps(dict(status=receipt['status'],errors=receipt['errors'],counts=receipt['counts'])),flush=True)
