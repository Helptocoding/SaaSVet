"""Prospectively freeze only the corrected physical burst observer."""
import runpy
import shutil
from pathlib import Path

HERE=Path(__file__).resolve().parent
lab=runpy.run_path(str(HERE/'orchestration/lab.py'))
task,state=lab['session']()
target=task/'orchestration-v2'
target.mkdir()
sources={}
for source in (HERE/'orchestration-v2').glob('*.py'):
    shutil.copy2(source,target/source.name)
    sources[source.name]=lab['sha'](source)
lab['write'](HERE/'orchestration-v2-seal.json',sources)
lab['write'](HERE/'observer-revision.json',dict(
    change='INITIAL_PHYSICAL_DRIVER_ACTIVATION_RECORDED_BEFORE_ACTUAL_MONOTONIC_WINDOW_START',
    reason='FIRST_BURST_OFFER_SNAPSHOT_LOST_THE_ALREADY_ELAPSED_WINDOW_PREFIX',
    supporting_evidence='individual/individual-R105-simultaneous/physical-phases.jsonl',
    observed_first_attempt_phase_span_seconds=119.989717,
    prior_attempts_rewritten=False,base_modified=False,rates_modified=False,
    windows_modified=False,workers_modified=False,bound_modified=False,
    original_orchestration=state['orchestration'],new_orchestration=str(target),
    sources=sources,new_run_ids_required=True))
# Only the owned laboratory's orchestration path changes. No database or
# runtime configuration is changed; accepted receipts retain their hashes.
state['orchestration']=str(target)
(task/'session.json').write_text(__import__('json').dumps(state),encoding='utf-8')
print('Observer v2 sealed for new attempts; earlier attempts preserved',flush=True)
