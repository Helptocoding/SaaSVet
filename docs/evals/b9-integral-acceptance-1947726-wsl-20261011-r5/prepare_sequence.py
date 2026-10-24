"""Sequential preparation; never start a formal campaign here."""
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent

if __name__=='__main__':
    for step in ('assemble','runtimes','postgres-packages','stage','validate','interpreters','preseal-prepare'):
        print('PREPARATION_STEP '+step,flush=True)
        subprocess.run(['rtk','proxy',sys.executable,'-X','utf8','-B',str(HERE/'capture_wsl.py'),step],check=True)
    print('ALL_PREPARATION_PASS',flush=True)
