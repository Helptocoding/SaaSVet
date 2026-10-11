"""Freeze setup-only sender verification repair for not-yet-started jobs."""
import ast
import json
import runpy
import shutil
from pathlib import Path

HERE=Path(__file__).resolve().parent
lab=runpy.run_path(str(HERE/'orchestration/lab.py'))
preflight=lab['read'](HERE/'sender-verifier-preflight.json')
if any(v['exit_code'] for v in preflight['results'].values()):
    raise RuntimeError('Required independent setup preflight did not pass')
task,state=lab['session']()
source=HERE/'orchestration-v3'
destination=HERE/'orchestration-v4'
frozen=task/'orchestration-v4'
destination.mkdir();frozen.mkdir()
anchor="    else:\n        events = observations(participant, report, journals, dispatches, read_lines, directory, final)"
replacement="    else:\n        if job['case_id'] == 'R2-09':\n            # This existing recipe reads the actual sender's durable witness.\n            # Initialize only this verifier process against its isolated DB.\n            from apps.agent.tests.scheduling_characterization.runner import bootstrap\n            bootstrap()\n        events = observations(participant, report, journals, dispatches, read_lines, directory, final)"
hashes={}
for path in sorted(source.glob('*.py')):
    text=path.read_text(encoding='utf-8')
    if path.name=='verify_case.py':
        if text.count(anchor)!=1:
            raise RuntimeError('Sender verifier anchor changed')
        text=text.replace(anchor,replacement)
    if path.name=='load_case.py':
        if text.count("receipt['evaluation_observer_version']='v3'")!=1:
            raise RuntimeError('Executor version anchor changed')
        text=text.replace("receipt['evaluation_observer_version']='v3'","receipt['evaluation_observer_version']='v4'")
    ast.parse(text)
    target=destination/path.name
    with target.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(text)
    shutil.copy2(target,frozen/path.name)
    hashes[path.name]=lab['sha'](target)
lab['write'](HERE/'orchestration-v4-seal.json',hashes)
lab['write'](HERE/'sender-verifier-revision.json',dict(
    change='INITIALIZE_DJANGO_IN_R209_VERIFIER_BEFORE_EXISTING_DURABLE_WITNESS_READ',
    reason='REPRODUCED_APP_REGISTRY_NOT_READY_WITHOUT_SETUP',
    predecessor='orchestration-v3',sources=hashes,
    preflight_sha256=lab['sha'](HERE/'sender-verifier-preflight.json'),
    physical_executor_behavior_changed=False,provider_changed=False,base_changed=False,
    runtime_source_changed=False,previous_attempts_rewritten=False,
    applies_to='ONLY_NEW_JOBS; PRIOR_AND_CURRENT_ATTEMPTS_KEEP_THEIR_SEALED_SOURCES'))
state['orchestration']=str(frozen)
(task/'session.json').write_text(json.dumps(state),encoding='utf-8')
print('Sender verifier setup repair sealed; active job and previous receipts untouched',flush=True)
