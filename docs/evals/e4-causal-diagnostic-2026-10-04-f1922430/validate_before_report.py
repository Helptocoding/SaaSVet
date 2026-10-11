"""Validate every new capture before any causal report is generated."""
import json
import sys
import infra
sys.path.insert(0,str(infra.ROOT/'backend'))
from apps.agent.claim_diagnostic_report import read_journal, reconstruct


def main():
    paths=[infra.OUT/(name+'.jsonl') for name in ('ingress','planner-1','planner-2','sender')]
    paths += [p for p in sorted((infra.OUT/'functional-artifacts').glob('*.jsonl'))
              if not p.name.endswith('-waits.jsonl')]
    checks=[]
    sessions=set()
    for path in paths:
        rows=read_journal(path)
        assert rows[-1]['failed_writes']==0 and not rows[-1]['open_transaction']
        assert rows[0]['session_id'] not in sessions
        sessions.add(rows[0]['session_id'])
        run_id=rows[0]['run_id']
        assert run_id=='causal-'+infra.KEY or run_id.startswith('f-'+infra.KEY+'-')
        reconstruct([rows])
        checks.append(dict(path=path.relative_to(infra.OUT).as_posix(),events=len(rows),
            query_count=rows[-1]['query_count'],footer_complete=True,failed_writes=0,
            transactions_closed=True,session_id=rows[0]['session_id'],run_id=run_id))
    observer=json.loads((infra.OUT/'waits.summary.json').read_text(encoding='utf-8'))
    assert observer['complete'] and observer['partial_journal_lines']==0
    count=0
    for line in (infra.OUT/'waits.jsonl').open(encoding='utf-8'):
        item=json.loads(line)
        assert item['run_id']=='causal-'+infra.KEY
        count+=1
    assert count==observer['samples']
    infra.write('integrity-before-report.json',dict(classification='DIAGNOSTIC_ONLY',run_id='causal-'+infra.KEY,
        validated_before_causal_report=True,journals=checks,observer=observer,observer_parsed_samples=count,
        result='COMPLETE',causal_interpretation_performed=False))
    print(json.dumps(dict(integrity='COMPLETE',journals=len(checks),observer_samples=count)))


if __name__=='__main__':
    main()
