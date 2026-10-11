"""Wait for independent attempts, then execute all required final sources.

Fault adapters/application regression may overlap in isolated databases.
Timed fixed-base jobs run only after both finish, with no concurrent probe.
"""
import json
import runpy
import subprocess
import sys
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
LAB=HERE/'orchestration/lab.py'
lab=runpy.run_path(str(LAB))


def start(command,logname):
    log=(HERE/logname).open('x',encoding='utf-8')
    process=subprocess.Popen(['rtk','proxy',sys.executable,'-B','-X','utf8',str(LAB),command],
                             stdout=log,stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return process,log


while not (HERE/'individual-result.json').exists():
    time.sleep(.2)
# That barrier is written only after the last individual database cleanup.
print('Final sources: finite fault variants and application regression starting',flush=True)
physical,physical_log=start('matrix-physical','matrix-physical-orchestration.log')
application,application_log=start('application','application-orchestration.log')
exits={}
for name,process,log in [('matrix-physical',physical,physical_log),
                          ('application',application,application_log)]:
    exits[name]=process.wait()
    log.close()
    print(name+' exit '+str(exits[name]),flush=True)
print('Final sources: sequential fixed-base matrix jobs starting',flush=True)
existing,existing_log=start('matrix-existing','matrix-existing-orchestration.log')
exits['matrix-existing']=existing.wait()
existing_log.close()
lab['write'](HERE/'matrix-orchestration-exits.json',exits)
print('matrix-existing exit '+str(exits['matrix-existing']),flush=True)
if any(exits.values()):
    raise RuntimeError('Orchestration incomplete; preserve laboratory for investigation')
for command in ['close']:
    subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(LAB),command],check=True)
subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(HERE/'finalize.py')],check=True)
print('Authorized phase finished; no following phase dispatched',flush=True)
