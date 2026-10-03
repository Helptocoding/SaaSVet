"""Validate the final receipts and consolidate metrics without changing runtime."""
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def write(name,value):
    path=OUT/name
    assert not path.exists(),path
    path.write_text(json.dumps(value,indent=2,default=str)+'\n',encoding='utf-8')


def plan_summary(path):
    document=read(path)[0]
    nodes=[]
    def visit(node):
        if node.get('Relation Name'):
            nodes.append(dict(relation=node['Relation Name'],type=node['Node Type'],
                loops=node['Actual Loops'],hits=node.get('Shared Hit Blocks',0),
                reads=node.get('Shared Read Blocks',0),
                removed_per_loop=node.get('Rows Removed by Filter',0),
                total_time_times_loops=node['Actual Total Time']*node['Actual Loops']))
        for child in node.get('Plans',[]):
            visit(child)
    visit(document['Plan'])
    root=document['Plan']
    return dict(execution_ms=document['Execution Time'],planning_ms=document['Planning Time'],
        hits=root.get('Shared Hit Blocks',0),reads=root.get('Shared Read Blocks',0),
        temp_read=root.get('Temp Read Blocks',0),temp_written=root.get('Temp Written Blocks',0),
        message_nodes=[n for n in nodes if n['relation']=='channels_message'],
        dominant_relation_by_time_times_loops=max(nodes,key=lambda n:n['total_time_times_loops']),
        nodes=nodes)


def main():
    environment=read('environment-post.json')
    worker_hash=hashlib.sha256((ROOT/'backend/apps/agent/worker.py').read_bytes()).hexdigest()
    assert worker_hash==environment['worker_sha256']
    matrices={}
    metrics=[]
    for kind in ('messages','conversations'):
        rows=read('matrix-post-'+kind+'.json')
        assert len(rows)==14
        matrices[kind]=rows
        for i in range(0,len(rows),2):
            old,new=rows[i:i+2]
            assert old['variant']=='OLD' and new['variant']=='NEW' and old['x']==new['x']
            for key in ('pending_messages','conversations','ready_messages','future_messages','selected_conversation_ids'):
                assert old[key]==new[key],(kind,key)
            assert old['query_count']==new['query_count']==1
            assert old['execution_ms']['n']==new['execution_ms']['n']==30
            new_message=[n for group in new['nodes'] for n in group if n['relation']=='channels_message']
            assert new_message and max(n['loops'] for n in new_message)==1
            metrics.append(dict(kind=kind,x=new['x'],
                old=old['execution_ms'],new=new['execution_ms'],
                p95_ratio=old['execution_ms']['p95']/new['execution_ms']['p95'],
                old_max_message_loops=max(n['loops'] for g in old['nodes'] for n in g if n['relation']=='channels_message'),
                new_max_message_loops=1,old_hits=old['nodes'][0][0]['hits'],
                new_hits=new['nodes'][0][0]['hits'],old_planning_ms=old['planning_ms'],
                new_planning_ms=new['planning_ms']))
    oracle=read('oracle-final.json')
    assert oracle['states_tested']==321 and oracle['decision_mismatches']==0
    assert read('oracle.json')['decision_mismatches']==0
    assert read('oracle-post.json')['decision_mismatches']==0
    classified=read('oracle-classified.json')
    assert classified['states_tested']==321 and classified['decision_mismatches']==0
    no_eligible=next(row for row in classified['manual'] if row['case']=='no_eligible_candidate')
    assert no_eligible['selection_empty_old'] and no_eligible['selection_empty_new']
    assert not no_eligible['yield_old'] and not no_eligible['yield_new']
    assert all(row['yield_old']==row['yield_new'] for row in classified['manual'])
    historical=[]
    resumed=(OUT/'regression-partial.json').exists()
    if resumed:
        partial=read('regression-partial.json')
        assert partial['tests']==659 and partial['source_hashes_verified']
        retained=[]
        for index in range(2):
            for line in (OUT/f'regression-{index}.results.passed.jsonl').read_text().splitlines():
                row=json.loads(line)
                assert row['status']=='ok'
                retained.append(row['test_id'])
            sources=read(f'regression-{index}.results.sources.json')
            for filename,digest in sources.items():
                assert hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()==digest
        assert sorted(retained)==partial['test_ids'] and len(set(retained))==659
        historical.extend(retained)
    for index in range(2):
        stage=('regression-resume-' if resumed else 'regression-')+str(index)
        result=read(stage+'.results.json')
        assert result['exit_code']==0
        assert all(result[k]==0 for k in ('failures','errors','skips','xfail'))
        historical.extend(result['test_ids'])
        assert read(stage+'.results.sources.json')['backend/apps/agent/worker.py']==worker_hash
    expected=json.loads((ROOT/'docs/evals/e4-claim/regression-final-inventory.json').read_text())
    assert sorted(historical)==sorted(expected) and len(set(historical))==775
    unit=[]
    for line in (OUT/'new-final.results.passed.jsonl').read_text().splitlines():
        row=json.loads(line)
        if '.test_e4_sql_selector.' in row['test_id']:
            assert row['status']=='ok'
            unit.append(row['test_id'])
    assert len(unit)==3
    unit_sources=read('new-final.results.sources.json')
    for source in ('backend/apps/agent/worker.py','backend/apps/agent/tests/test_e4_sql_selector.py',
                   'backend/apps/agent/tests/e4_sql_oracle.py'):
        assert unit_sources[source]==hashlib.sha256((ROOT/source).read_bytes()).hexdigest()
    processes=read('repair-processes.results.json')
    assert processes['tests']==5 and processes['exit_code']==0
    assert all(processes[k]==0 for k in ('failures','errors','skips','xfail'))
    process_sources=read('repair-processes.results.sources.json')
    for source in ('backend/apps/agent/worker.py','backend/apps/agent/tests/test_e4_sql_processes.py',
                   'backend/apps/agent/tests/e4_sql_process.py'):
        assert process_sources[source]==hashlib.sha256((ROOT/source).read_bytes()).hexdigest()
    journal=[json.loads(line) for line in (OUT/'repair-processes.results.b9c-processes.jsonl').read_text().splitlines()]
    admissions=[row['admissions'] for row in journal if 'admissions' in row]
    active=[n for row in journal for n in row.get('active',{}).values()]
    assert admissions and max(admissions)==0 and active and max(active)<=1
    assert read('checks.exit.json')['exit_code']==0
    passed=sorted(historical+unit+processes['test_ids'])
    assert len(passed)==len(set(passed))==783
    write('passed-ids.json',passed)
    write('metrics-summary.json',dict(points=metrics,
        stress_old=plan_summary('explain/post/OLD-conversations-1000.json'),
        stress_new=plan_summary('explain/post/NEW-conversations-1000.json')))
    write('verification-summary.json',dict(status='OPTIMIZATION_VERIFIED',
        baseline='1d04e72f69e9c1576ac1be901624db127b879bf4',old_runtime='83ee3b24c84b170e22e401cb09a34da5320ae0a3',
        worker_sha256=worker_hash,optimization_count=1,migrations=0,new_indexes=0,new_persistence=False,
        historical_passed=775,new_selector_passed=3,new_process_passed=5,unique_passed=783,
        regression_retained_after_interruption=659 if resumed else 0,
        regression_resumed_passed=116 if resumed else 0,
        failures_final=0,errors_final=0,skips=0,xfail=0,
        design_oracle_states=320,design_alternative_comparisons=640,
        post_oracle_states=320,final_oracle_states=321,generated_states_per_oracle=300,
        additional_generated_unit_states=160,seed=20261001,decision_mismatches=0,
        query_count_old=1,query_count_new=1,structural_points_passed=14,
        max_processing_per_org=max(active),observation_and_miss_admissions=max(admissions),
        safety='PASS',monotonic_ready='PASS',B3='PASS',B5='PASS',B9B='PASS',B9C='PASS',
        PROFILE_run=False,B9E_run=False,PROFILE_historical_status='FAIL',B9E='FAIL',B9='IN_PROGRESS',
        B0='CLOSED',B7B=False,flags={},release_grants=[],active_clinics=0,deploy=False,
        activation_status='PENDING_ACTIVATION_REQUIREMENTS',
        limits='PostgreSQL 16.15 synthetic cardinality experiment with three controlled organizations; host scheduling noise remains. No SQL SLO introduced.'))
    print('OPTIMIZATION_VERIFIED: 783 unique tests, 14 paired structural points, zero oracle mismatches')


if __name__=='__main__':
    main()
