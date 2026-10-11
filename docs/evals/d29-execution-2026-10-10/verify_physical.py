"""Physical admission uses raw journals, native gates and the host/clock gate.

No synthetic fixture is admitted by this entry point. Historical/offline
results remain components with their original provenance and terminology.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.append(str(ROOT / 'docs/evals/d29-offline-preparation-2026-10-09'))
from apps.agent.tests.scheduling_characterization.controller import digest
from apps.agent.tests.scheduling_characterization.runner import bootstrap, write_json
from apps.agent.tests.scheduling_characterization.execution import read_lines
from apps.agent.tests.scheduling_characterization.evidence import ClockMap, Interval, reconstruct, transactions
import r106_verifier


def verify(folder):
    d = folder / 'capture'
    job = json.loads((folder / 'job.json').read_text())
    errors = []
    unsigned = {k:v for k,v in job.items() if k != 'job_sha256'}
    if digest(unsigned) != job['job_sha256']:
        errors.append('JOB_SEAL_CHANGED')
    for name, expected in job['evaluation_source_hashes'].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != expected:
            errors.append('EVALUATION_OVERLAY_CHANGED:' + name)
    clock = json.loads((folder / 'capture-clock/clock-receipt.json').read_text())
    if not clock.get('gate_passed'):
        errors.append('CLOCK_OR_CAPTURE_INVALID')
    if not (d / 'job-result.json').exists():
        errors.append('EXECUTION_INCOMPLETE')
    exits = json.loads((d / 'participant-exits.json').read_text()) if (d / 'participant-exits.json').exists() else []
    if len(exits) != 3 or any(r['exit_code'] != 0 for r in exits):
        errors.append('PARTICIPANT_EXIT_NOT_CLEAN')
    result = None
    if not errors and job['case_id'] == 'R1-06':
        result = r106_verifier.verify_directory(d)
        errors += result['errors']
        write_json(d / 'prospective-reconciliation.json', result)
        # Native trigger cursor must agree with independently journaled ingress.
        participant = json.loads((d / 'participant-plan.json').read_text())
        if {k:v for k,v in participant.items() if k!='organization_ids'} != job:
            errors.append('PARTICIPANT_JOB_CHANGED')
        journals = [read_lines(d / (r + '.jsonl')) for r in r106_verifier.ROLES]
        sources = {str(e['message_id']):[e['created_at'],e['message_id']]
                   for journal in journals for e in journal if e['event']=='message_persisted'}
        for journal in journals:
            for event in journal:
                if event['event'] == 'new_input_guard':
                    if (event.get('capture_boundary') != 'NATIVE_EXISTENCE_QUERY'
                            or any(event.get('input_source_cursors',{}).get(str(mid)) != sources.get(str(mid))
                                   for mid in event['new_input_ids'])):
                        errors.append('NATIVE_GUARD_SOURCE_CURSOR_MISMATCH')
        sealed = json.loads((d / 'sealed-job.json').read_text())
        if sealed != job:
            errors.append('SEALED_EXECUTOR_JOB_CHANGED')
    elif not errors:
        bootstrap()
        from r209_verification_v3 import verify as verify_r209
        result = verify_r209(d,job)
        errors += result['errors']
        write_json(d / 'prospective-reconciliation.json',result)
    receipt = dict(status='PENDING' if errors else 'ACCREDITED', case_id=job['case_id'], variant=job['variant'],
        errors=sorted(set(errors)), clock_gate=clock, physical_execution=True,
        source_kind='PROSPECTIVE_PHYSICAL_POSTGRESQL', synthetic_evidence=[],
        full_followup_observed=bool(result and not errors),
        gates=result.get('gates') if result else None,
        counts=result.get('reconciliation',{}).get('counts') if result else None,
        next_step='STOP_AND_REVIEW' if errors else 'NEXT_SEQUENTIAL_REGRESSION_SUITE')
    write_json(folder / 'physical-verification.json', receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('clock_gate','gates')}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('folder', type=Path)
    args = p.parse_args()
    verify(args.folder)
