"""Own one Windows memory probe process; never execute application code."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import time

HERE=Path(__file__).resolve().parent

def main():
    directory=HERE/'resource-observer'
    directory.mkdir()
    assert sys.platform=='win32'
    control={'state':'RUNNING','pid':os.getpid(),'python':sys.executable,
        'sample_interval_seconds':1,'maximum_sample_age_seconds':10,
        'measurement':'Unmodified host_resources.py / GlobalMemoryStatusEx',
        'run_method':'runpy in one private persistent Windows process',
        'application_tests_executed':False,'maximum_lifetime_seconds':46800}
    (HERE/'resource-observer-control.json').write_text(json.dumps(control,indent=2)+'\n',encoding='utf-8')
    start=time.monotonic();count=0
    with (directory/'samples.jsonl').open('w',encoding='utf-8',newline='\n') as stream:
        while not (directory/'stop.request').exists() and time.monotonic()-start<46800:
            capture=io.StringIO()
            with contextlib.redirect_stdout(capture):
                runpy.run_path(str(HERE/'host_resources.py'),run_name='host_memory_observation')
            row=json.loads(capture.getvalue())
            row.update(utc_epoch_seconds=time.time(),observer_pid=os.getpid())
            stream.write(json.dumps(row)+'\n');stream.flush();count+=1
            if count==1:print('HOST_OBSERVER_STARTED '+str(os.getpid()),flush=True)
            time.sleep(1)
    (HERE/'resource-observer-closure.json').write_text(json.dumps({'state':'PASS','pid':os.getpid(),
        'samples':count,'seconds':time.monotonic()-start,'explicit_stop_requested':(directory/'stop.request').exists()},indent=2)+'\n',encoding='utf-8')
    print('HOST_OBSERVER_STOPPED',flush=True)

if __name__=='__main__':
    main()
