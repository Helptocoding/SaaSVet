"""Complete the actual native cleanup interface, then reuse every R104 gate."""
import json
import os
import sys
from pathlib import Path
from lab_control import HERE,ROOT,lab
from native_cleanup import validate


if __name__=='__main__':
    folder=Path(sys.argv[1]).resolve();d=folder/'capture'
    read=lambda p:json.loads(p.read_text())
    job=read(folder/'job.json');archive=read(folder/'execution-source-archive.json')
    assert archive==job['evaluation_source_hashes']
    assert all(lab.sha(folder/'execution-sources'/name)==sha for name,sha in archive.items())
    task,state=lab.session()
    os.environ.update(lab.environment(state['config'],Path(state['copy'])))
    sys.path[:0]=[str(HERE),str(Path(state['copy'])/'backend'),str(ROOT/'docs/evals/d29-offline-preparation-2026-10-09')]
    from apps.agent.tests.scheduling_characterization.execution import read_lines,digest
    from apps.agent.tests.scheduling_characterization.runner import bootstrap,write_json
    from apps.agent.claim_diagnostic_report import read_journal
    assert digest({k:v for k,v in job.items() if k!='job_sha256'})==job['job_sha256']
    journals=[read_journal(d/(r+'.jsonl')) for r in ('planner_1','planner_2','sender')]
    after=[r for r in read_lines(folder/'resources.jsonl') if r['stage']=='after']
    cleanup=validate(read(d/'participant-exits.json'),[j[0]['os_pid'] for j in journals],after,read(folder/'execution-receipt.json'))
    assert cleanup['all_reaped'],cleanup
    write_json(d/'participants-cleanup.json',cleanup)
    bootstrap()
    from r104_verification import verify
    result=verify(folder)
    write_json(d/'finite-verification-v2.json',result)
    receipt=dict(status=result['status'],case_id='R1-04',variant='forecasts',errors=result['errors'],
        original_provisional_result='physical-verification.json',physical_attempts=1,execution_archive_verified=True,
        counts=result['counts'],clock_gate=result['clock_gate'],original_base_gates=result['original_base_gates'],
        prequeries=result['prequeries'],forecast_yields=len(result['native_forecast_yields']),cleanup=cleanup,
        verification_source_hashes={n:lab.sha(HERE/n) for n in ['reverify_r104.py','native_cleanup.py','test_native_cleanup.py','r104_verification.py']})
    write_json(folder/'physical-verification-v2.json',receipt)
    from django.db import connections
    connections.close_all()
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('clock_gate','original_base_gates','verification_source_hashes')}),flush=True)
