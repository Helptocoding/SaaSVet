"""Explicit private-lab lifecycle; no matrix entry point."""
import argparse
import importlib.util
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'docs/evals/d29-authorized-probes-2026-10-07'
spec = importlib.util.spec_from_file_location('preserved_lab_helpers', OLD / 'authorized_lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)
lab.OUT = HERE
lab.PREFIX = 'vet-d29-rector-20261010-'


def initialize():
    request = Path('C:/Users/LAP/.codex/attachments/6d376ba4-e6f0-4f61-99a3-19d0fb8f3b65/Texto pegado.txt')
    with (HERE / 'PLAN-RECTOR.md').open('x', encoding='utf-8') as f:
        f.write(request.read_text(encoding='utf-8-sig'))
    lab.write(HERE / 'authorization.json', dict(request_path=str(request), sha256=lab.sha(request),
        harness=True, R106=True, seven_sequential_suites=True,
        R209_order=['uncertain_meta', 'slow_meta'], R104_bounded_investigation=True,
        R204_with_W32Time_intact=True, host_service_mutation=False, commits=False, full_matrix=False))
    lab.initialize()
    task, state = lab.session()
    # The original initializer copies an optional orchestration folder. Install
    # the sealed new overlay explicitly; leave the baseline copy untouched.
    scripts = Path(state['orchestration'])
    hashes = {}
    for source in HERE.iterdir():
        if source.suffix in ('.py', '.ps1'):
            shutil.copy2(source, scripts / source.name)
            hashes[source.name] = lab.sha(source)
    lab.write(HERE / 'installed-overlay.json', hashes)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['initialize', 'close'])
    args = p.parse_args()
    initialize() if args.command == 'initialize' else lab.close()
