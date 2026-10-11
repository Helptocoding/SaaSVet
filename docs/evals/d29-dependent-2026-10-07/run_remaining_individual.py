"""Sequential remaining dependent attempts; never recalibrate or overwrite."""
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
lab = runpy.run_path(str(HERE / 'orchestration/lab.py'))
values = [lab['read'](HERE / 'individual/individual-R103-unequal-result.json')]
for case, variant in [('R1-04', 'forecasts'), ('R1-05', 'simultaneous'),
                      ('R1-05', 'concentrated'), ('R1-06', 'backlog')]:
    values.append(lab['one'](case, variant, 'individual'))
lab['write'](HERE / 'individual-result.json',
             dict(results=values, state='FULL_LIVE_MATRIX_NOT_READY'))
