"""Stop only the owned full-suite process group after a proven precondition failure."""
import json
import os
from pathlib import Path
import signal
import sys
import time

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from prepare_wsl import WORK,RTK,PYTHON,save

def command(pid):
    return [s.decode() for s in (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0') if s]

def main():
    assert WORK.resolve()==Path('/home/lap/b9i-correction-20261014-r3')
    assert not (HERE/'manual-stop-request.json').exists()
    receipt=json.loads((HERE/'blocks/full.command.json').read_text())
    assert receipt['state']=='RUNNING' and receipt['label']=='full'
    assert not (HERE/'blocks/full.results.json').exists()
    failures=[json.loads(line) for line in (HERE/'blocks/full.ids.jsonl').read_text().splitlines()
        if json.loads(line)['outcome'] in ('FAIL','ERROR')]
    relevant=[r for r in failures if 'Child exited before barrier' in (r.get('traceback') or '')
        and 'B8B workers require isolated test_b8b_ PostgreSQL' in r['traceback']]
    assert relevant
    expected=[str(PYTHON),'-B',str(HERE/'recorded_suite.py'),'full','test_b9i_full']
    matches=[]
    for directory in Path('/proc').glob('[0-9]*'):
        try:
            if command(int(directory.name))==expected:matches.append(int(directory.name))
        except (FileNotFoundError,ProcessLookupError,PermissionError):pass
    assert len(matches)==1,matches
    pid=matches[0];group=os.getpgid(pid)
    expected_leader=[str(RTK),'proxy',*expected]
    assert command(group)==expected_leader,(group,command(group))
    assert receipt['argv']==expected_leader
    save('manual-stop-request.json',{'state':'PENDING_HARNESS_INCOMPATIBILITY',
        'reason':'B8B children rejected the isolated full database name before READY; concurrency scenario not reached',
        'required_database_prefix':'test_b8b_','actual_full_database':'test_b9i_full',
        'failed_ids_at_request':[r['id'] for r in relevant],
        'evidence':'blocks/full.ids.jsonl','owned_child_pid':pid,'owned_process_group':group,
        'verified_child_argv':expected,'verified_group_leader_argv':expected_leader,
        'sources_dependencies_or_evaluator_modified':False,'formal_reruns':0,
        'request_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
    os.killpg(group,signal.SIGTERM)
    start=time.monotonic();escalated=False
    while time.monotonic()-start<10:
        if not (Path('/proc')/str(pid)).exists():break
        time.sleep(.1)
    if (Path('/proc')/str(pid)).exists():
        assert command(group)==expected_leader
        os.killpg(group,signal.SIGKILL);escalated=True
    save('manual-stop-signal.json',{'state':'OWNED_SUITE_STOP_REQUESTED',
        'owned_process_group':group,'sigterm_sent':True,'sigkill_sent':escalated,
        'foreign_processes_signaled':False,'formal_controller_left_running_to_record_receipts':True})
    print('OWNED_FULL_SUITE_STOP_REQUESTED',flush=True)

if __name__=='__main__':main()
