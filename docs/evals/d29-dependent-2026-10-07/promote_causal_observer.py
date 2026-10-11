"""Freeze evaluation-only pre-query observation for fresh final matrix jobs."""
import ast
import json
import runpy
import shutil
from pathlib import Path

HERE=Path(__file__).resolve().parent
lab=runpy.run_path(str(HERE/'orchestration/lab.py'))
task,state=lab['session']()
target=task/'orchestration-v3'
target.mkdir()
sources={}
for source in (HERE/'orchestration-v3').glob('*.py'):
    ast.parse(source.read_text(encoding='utf-8'))
    shutil.copy2(source,target/source.name)
    sources[source.name]=lab['sha'](source)
lab['write'](HERE/'orchestration-v3-seal.json',sources)
lab['write'](HERE/'causal-observer-revision.json',dict(
    change='READONLY_PRE_QUERY_AND_POST_QUERY_CUTS_AROUND_ACTUAL_SELECTIONS',
    reason='CONCURRENT_LOAD_NEEDS_OBSERVATIONS_BEFORE_NATIVE_SELECTION_NOT_LATER_CENSUS',
    worker_loop_changed=False,workers_held=False,added_ingress=False,
    source_runtime_changed=False,base_modified=False,prior_attempts_rewritten=False,
    original_orchestration=state['orchestration'],new_orchestration=str(target),sources=sources,
    limitation='Pre-query coexistence alone is not the full causal forecast/supersession sequence',
    new_run_ids_required=True))
state['orchestration']=str(target)
(task/'session.json').write_text(json.dumps(state),encoding='utf-8')
print('Observer v3 sealed; no production source, worker loop or base parameter changed',flush=True)
