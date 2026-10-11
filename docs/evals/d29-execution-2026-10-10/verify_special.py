"""Status envelope around the byte-preserved special scenario verifier."""
import json
import hashlib
import sys
from pathlib import Path
from apps.agent.tests.scheduling_characterization.runner import write_json
from verify_r204 import verify


def main(folder):
    job = json.loads((folder/'job.json').read_text())
    try:
        from apps.agent.tests.scheduling_characterization.execution import digest
        if digest({k:v for k,v in job.items() if k!='job_sha256'})!=job['job_sha256']:
            raise ValueError('JOB_SEAL_CHANGED')
        for name,expected in job['evaluation_source_hashes'].items():
            if hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()!=expected:
                raise ValueError('EVALUATION_OVERLAY_CHANGED:'+name)
        if job['case_id']=='R1-04':
            from r104_verification import verify as verify_forecast
            result=verify_forecast(folder)
            status=result['status']
            write_json(folder/'capture/finite-verification.json',result)
        else:
            result = verify(job,folder/'capture')
            write_json(folder/'capture/authorized-verification-v2.json',result)
            status = 'ACCREDITED' if result['status']=='PASS' and not result['errors'] else 'PENDING'
        errors = result.get('errors',[])
    except Exception as exc:
        status,errors = 'PENDING',['VERIFICATION_INCOMPLETE']
        result = dict(error_type=type(exc).__name__,error=str(exc))
    receipt = dict(status=status,case_id=job['case_id'],variant=job['variant'],errors=errors,
        original_verifier_result=result,physical_execution=True,synthetic_evidence=[],
        host_service_mutation=False)
    write_json(folder/'physical-verification.json',receipt)
    print(json.dumps(dict(status=status,errors=errors)),flush=True)


if __name__=='__main__':main(Path(sys.argv[1]))
