"""Reproduce framework setup omission without emitting offers or changing DB."""
import argparse
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent


def child(setup):
    import verify_case
    from django.core.exceptions import AppRegistryNotReady
    if setup:
        from apps.agent.tests.scheduling_characterization.runner import bootstrap
        bootstrap()
    try:
        from apps.channels.models import Message
    except AppRegistryNotReady:
        if setup:
            raise
        print('DEFECT_REPRODUCED: sender durable witness model requires Django setup')
        return
    if not setup:
        raise AssertionError('Expected uninitialized verifier to reproduce model-loading defect')
    print('PASS: verifier can import sender witness model after explicit local bootstrap')


def main():
    lab=runpy.run_path(str(HERE/'orchestration/lab.py'))
    task,state=lab['session']()
    env=lab['environment'](state['config'],Path(state['copy']))
    env['PYTHONPATH']=state['orchestration']+os.pathsep+env['PYTHONPATH']
    outputs={}
    for name,extra in [('original',[]),('with_local_bootstrap',['--setup'])]:
        proc=subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'--child']+extra,
            env=env,cwd=Path(state['copy'])/'backend',text=True,capture_output=True)
        outputs[name]=dict(exit_code=proc.returncode,output=proc.stdout,errors=proc.stderr)
    result=dict(scope='EVALUATION_VERIFIER_SETUP_PREFLIGHT_NOT_PHYSICAL_ACCREDITATION',
                results=outputs,offers_emitted=0,base_changed=False,
                source_sha256=lab['sha'](Path(state['orchestration'])/'verify_case.py'))
    lab['write'](HERE/'sender-verifier-preflight.json',result)
    print(json.dumps(result))
    if any(v['exit_code'] for v in outputs.values()):
        raise RuntimeError('Sender verifier preflight failed')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--child',action='store_true');p.add_argument('--setup',action='store_true')
    args=p.parse_args()
    child(args.setup) if args.child else main()
