"""Classify retained traces and specify a compatible, non-executed partition."""
import collections
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
REPO=HERE.parents[2]

def save(name,data):
    assert not (HERE/name).exists(),name
    (HERE/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    rows=[json.loads(line) for line in (HERE/'blocks/full.ids.jsonl').read_text().splitlines()]
    bad=[r for r in rows if r['outcome'] in ('FAIL','ERROR')]
    rejected=[r for r in bad if 'B8B workers require isolated test_b8b_ PostgreSQL' in (r.get('traceback') or '')]
    interrupted=[r for r in bad if r not in rejected]
    assert len(rejected)==7 and len(interrupted)==1
    stop=json.loads((HERE/'manual-stop-request.json').read_text())
    assert interrupted[0]['utc']==stop['request_utc']
    assert interrupted[0]['traceback'].endswith('AssertionError: Child exited before barrier: \n')
    selected=json.loads((HERE/'full-selected.json').read_text())
    seen={r['id'] for r in rows}
    save('failure-classification.json',{'decision':'PENDING','primary_cause':'Full database prefix conflicts with B8B child precondition before READY',
        'confirmed_precondition_rejections':rejected,'recorded_during_owned_stop':interrupted,
        'raw_outcomes':dict(collections.Counter(r['outcome'] for r in rows)),
        'scenario_validly_reached_for_failed_ids':False,'product_failure_attributed':False,
        'selected_ids':len(selected),'observed_ids':len(seen),'unobserved_ids':sorted(set(selected)-seen),
        'full_suite_complete':False,'raw_journal_modified':False})
    groups={};restricted=set();guards={}
    for family in ('b8b','b8c','b8d','b8e'):
        module='apps.agent.tests.test_'+family+'_processes.'
        ids=[name for name in selected if name.startswith(module)]
        assert ids
        required='test_'+family+'_'
        source=REPO/'backend/apps/agent/tests'/(family+'_process.py')
        text=source.read_text(encoding='utf-8')
        assert "config['NAME'].startswith('"+required+"')" in text
        guards[family]={'path':source.relative_to(REPO).as_posix(),
            'required_prefix':required,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'matching_lines':[(n,line) for n,line in enumerate(text.splitlines(),1) if 'startswith' in line]}
        groups[family]={'database':required+'b9i_full','ids':ids,'count':len(ids)}
        restricted.update(ids)
    others=[name for name in selected if name not in restricted]
    groups['general']={'database':'test_b9i_full_general','ids':others,'count':len(others)}
    flattened=[name for group in groups.values() for name in group['ids']]
    assert sorted(flattened)==selected and len(flattened)==len(set(flattened))==3331
    save('next-assembly-remediation.json',{'state':'STATIC_SPECIFICATION_ONLY_NOT_EXECUTED',
        'candidate_tree':'196aceb4f5f234c086b96d8e8af93787613f3c25',
        'cause':'Mutually exclusive database-prefix preconditions in B8B/B8C/B8D/B8E worker helpers',
        'guards':guards,'full_selection_sha256':hashlib.sha256((HERE/'full-selected.json').read_bytes()).hexdigest(),
        'groups':groups,'total_ids':len(flattened),'duplicate_ids':0,'missing_ids':[],
        'minimum_assembly_change':['Partition the discovered full inventory into these five sequential native-runner groups; one execution per ID',
            'Fresh compatible owned PostgreSQL base for each group; preserve local-host, durability, prefix and all other worker guards',
            'Capture per-group receipts and aggregate exact union/counts with the original critical-skip and failure gates',
            'Seal grouping, configuration and adapter before any new invocation; explicitly allow only these additional owned bases in cleanup'],
        'candidate_product_or_test_source_changes_required':False,'guards_disabled':False,
        'assertions_locks_loads_timings_or_thresholds_changed':False,'new_application_tests_added':False,
        'further_formal_campaign_started':False,'historical_results_to_be_transferred':False})
    print(json.dumps({'classification':'PENDING_HARNESS','precondition_failures':len(rejected),
        'interrupted_during_stop':len(interrupted),'counts':dict(collections.Counter(r['outcome'] for r in rows)),
        'missing_ids':len(set(selected)-seen),'proposed_partition_counts':{k:v['count'] for k,v in groups.items()}}))

if __name__=='__main__':main()
