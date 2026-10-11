"""Seal methodology and new provider evidence. No execution entry point."""
import ast
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name,value):
    with (HERE/name).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')


def main():
    integrity=read(HERE/'complete-final-integrity.json')
    first=read(HERE/'complete-initial-integrity.json')
    cleanup=read(HERE/'lab-cleanup.json')
    processes=read(HERE/'process-cleanup.json')
    verification=read(HERE/'independent-provider-verification.json')
    assert integrity['intact'] and first==integrity
    assert all(cleanup.values()) and processes['passed']
    assert verification['status']=='PROVIDER_INFRASTRUCTURE_VALIDATED' and not verification['errors']
    for name,digest in verification['evidence_sha256'].items():
        assert sha(HERE/'provider-validation-03'/name)==digest, name
    for revision in ('orchestration','orchestration-v2','orchestration-v3'):
        for name,digest in read(HERE/(revision+'-seal.json')).items():
            assert sha(HERE/revision/name)==digest, revision+'/'+name
    for name,entry in read(HERE/'approved-overlay-provenance.json').items():
        assert sha(HERE/'orchestration-v3'/name)==entry['sha256'], name
    syntax={}
    for path in HERE.rglob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
        syntax[path.relative_to(HERE).as_posix()]=sha(path)
    write('source-syntax-verification.json',dict(passed=True,source_sha256=syntax,scope='STATIC_PARSE_ONLY'))
    write('phase-receipt.json',dict(schema='d29-methodology-and-minimal-provider-validation-v1',
        global_status='CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY',
        base_status='CONFIRMED_BASE_ESTABLISHED',base_sha256=integrity['base_sha256'],baseline=integrity['baseline'],
        full_matrix_runs=0,scenario_accreditation_runs=0,characterization_runs=0,
        provider_infrastructure_attempts=3,attempts_before_any_input=2,finite_physical_provider_cohorts=1,
        provider_status=verification['status'],provider_independent_receipt=dict(path='independent-provider-verification.json',
            sha256=sha(HERE/'independent-provider-verification.json')),
        proposals=dict(R104='SEPARATE_FINITE_CAUSAL_SCENARIO_EXTENSION; NOT_APPROVED_OR_IMPLEMENTED',
            R106='RECOMMEND_B_FOURTH_SCENARIO_CONVERSATION; NOT_APPLIED',
            R202='RECOMMEND_INPUT_EPISODE_CONVERSATION_WORK_RECONCILIATION; NOT_APPLIED',
            R204='PRELUDE_PLUS_UNCHANGED_BASE_WINDOW_ANCHORED_BEFORE_NATURAL_EXPIRY; NOT_EXECUTED'),
        R103='PREPARED_NOT_EXECUTED',R209_slow_meta='PENDING_NATURAL_READY_QUEUE_NOT_FORCED',
        base_changes=False,contract_changes=False,runtime_changes=False,commits=0,
        old_runs_reclassified=False,failed_attempts_preserved=True,prior_provider_runs_used_as_new_evidence=False,
        protected_sources=integrity['protected_source_count'],historical_artifacts=sum(v['count'] for v in integrity['historical_indexes'].values())+integrity['preparation_artifact_count'],
        cleanup=cleanup,process_cleanup_passed=processes['passed'],next_execution_requires_user_authorization=True,
        stop_after_delivery=True,capacity_claim=None,sustainable_envelope=None,
        modified_scope=str(HERE)))
    index={p.relative_to(HERE).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(HERE.rglob('*'))
           if p.is_file() and p.name!='artifact-index.json'}
    write('artifact-index.json',index)
    assert all(sha(HERE/name)==entry['sha256'] for name,entry in read(HERE/'artifact-index.json').items())
    print(json.dumps(dict(sealed_artifacts=len(index),provider_infrastructure=verification['status'],
        scenario_runs=0,integrity=True,cleanup=True,commits=0)))


if __name__=='__main__':
    main()
