"""Supplement D29 R2-09 with real READY-queue/service interval overlap.

Later ordinary progress is insufficient. This reads original capture only;
it neither queries later database state nor invents a causal selector event.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
EPOCH=datetime(1970,1,1,tzinfo=timezone.utc)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value):
    delta=datetime.fromisoformat(value).astimezone(timezone.utc)-EPOCH
    return (delta.days*86400+delta.seconds)*1_000_000_000+delta.microseconds*1000


def inspect(directory):
    result=dict(run_id=directory.name,requirement='R2-09_ORDINARY_READY_QUEUE_DURING_AFFECTED_META_SERVICE',
                status='NOT_ACCREDITED',errors=[],overlaps=[],affected_calls=[],
                scope='SUPPLEMENTAL_PHYSICAL_REQUIREMENT; NOT_A_NEW_EXECUTION_OR_REPLAY')
    names=('job-result.json','independent-verification.json','participant-plan.json','sender.jsonl','sender-wire.jsonl')
    missing=[n for n in names if not (directory/n).exists()]
    if missing:
        result['errors']=['MISSING_CAPTURE:'+n for n in missing]
        return result
    result['evidence']={n:dict(path=str((directory/n).relative_to(HERE)),sha256=sha(directory/n)) for n in names}
    report=read(directory/'job-result.json')
    verification=read(directory/'independent-verification.json')
    job=read(directory/'participant-plan.json')
    if verification['status']!='PHYSICALLY_ACCREDITED' or report['issues']:
        result['errors'].append('ORIGINAL_CAPTURE_OR_VERIFICATION_NOT_VALID')
        return result
    calibration=[r for r in lines(directory/'sender.jsonl') if r['event']=='db_clock']
    if not calibration:
        result['errors'].append('SENDER_CLOCK_UNOBSERVED')
        return result
    offset_lo=max(timestamp(r['db_timestamp'])-r['end_ns'] for r in calibration)
    offset_hi=min(timestamp(r['db_timestamp'])-r['start_ns'] for r in calibration)
    if offset_lo>offset_hi:
        result['errors'].append('SENDER_CLOCK_CONTRADICTORY')
        return result
    wire=lines(directory/'sender-wire.jsonl')
    affected=job['organization_ids'][0]
    for dispatch in wire:
        if dispatch['event']!='dispatch' or dispatch['boundary']!='meta' or dispatch['organization_id']!=affected:
            continue
        endings=[r for r in wire if r['event']=='result' and r['boundary']=='meta'
                 and r['message_id']==dispatch['message_id']]
        if len(endings)!=1:
            result['errors'].append('META_RESULT_NOT_UNIQUE:'+str(dispatch['message_id']))
            continue
        end=endings[0]
        call=dict(message_id=dispatch['message_id'],result=end['result'],
                  dispatch_db_ns_bounds=[dispatch['monotonic_ns']+offset_lo,dispatch['monotonic_ns']+offset_hi],
                  result_db_ns_bounds=[end['monotonic_ns']+offset_lo,end['monotonic_ns']+offset_hi],
                  observed_elapsed_ns=end['elapsed_ns'])
        result['affected_calls'].append(call)
        # The accepted contained Meta fixture costs 200 ms; this is its
        # already-declared perturbation, not a new service SLA/tolerance.
        condition=(end['elapsed_ns']>=200_000_000*job['slow_multiplier']
                   if job['variant']=='slow_meta' else end['result']=='UNCERTAIN')
        if not condition:
            result['errors'].append('AFFECTED_META_CONDITION_NOT_OBSERVED:'+str(dispatch['message_id']))
            continue
        for episode in report['episodes']:
            ready=episode['ready_ns_bounds'];claim=episode['claim_commit_ns_bounds']
            if episode['issues'] or ready[1] is None or not claim or claim[0] is None:
                continue
            lo=max(ready[1],call['dispatch_db_ns_bounds'][1])
            hi=min(claim[0],call['result_db_ns_bounds'][0])
            if lo<hi:
                result['overlaps'].append(dict(message_id=dispatch['message_id'],episode_id=episode['episode_id'],
                    organization_id=episode['organization_id'],ready_ns_bounds=ready,
                    claim_commit_ns_bounds=claim,definitely_ready_unclaimed_during_service_ns=[lo,hi]))
    if not result['overlaps']:
        result['errors'].append('ORDINARY_READY_QUEUE_DURING_AFFECTED_META_NOT_OBSERVED')
    result['errors']=sorted(set(result['errors']))
    if not result['errors']:
        result['status']='PHYSICALLY_ACCREDITED'
    return result


def main():
    values=[inspect(HERE/'matrix-existing'/('matrix-existing-R209-'+v)) for v in ('slowmeta','uncertainmeta')]
    with (HERE/'sender-queue-overlap-verification.json').open('x',encoding='utf-8') as stream:
        json.dump(dict(schema='d29-sender-queue-overlap-v1',variants=values,synthetic_evidence=[],
                       verifier_sha256=sha(Path(__file__)),
                       prior_receipts_rewritten=False,base_changed=False),stream,indent=2)
        stream.write('\n')
    return values


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path);a=p.parse_args()
    print(json.dumps(inspect(a.directory.resolve()) if a.directory else main(),indent=2))
