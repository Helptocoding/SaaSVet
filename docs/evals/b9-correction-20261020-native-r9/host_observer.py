"""Durably observe RAM, disk and wall/monotonic time in one owned Windows process."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import time
from native_support import resources

HERE=Path(__file__).resolve().parent

def main():
    directory=HERE/'resource-observer'
    directory.mkdir()
    assert sys.platform=='win32'
    control={'state':'RUNNING','pid':os.getpid(),'python':sys.executable,
        'sample_interval_seconds':1,'maximum_sample_age_seconds':10,
        'measurement':'GlobalMemoryStatusEx, disk_usage and wall/monotonic time',
        'run_method':'one private persistent Windows process; fsync each sample',
        'application_tests_executed':False,'maximum_lifetime_seconds':46800}
    (HERE/'resource-observer-control.json').write_text(json.dumps(control,indent=2)+'\n',encoding='utf-8')
    start=time.monotonic();wall=time.time();count=0
    with (directory/'samples.jsonl').open('w',encoding='utf-8',newline='\n') as stream:
        while not (directory/'stop.request').exists() and time.monotonic()-start<46800:
            now=time.monotonic();now_wall=time.time()
            row=resources()
            row.update(utc_epoch_seconds=now_wall,observer_pid=os.getpid(),
                monotonic_seconds=now,elapsed_seconds=now-start,
                wall_minus_monotonic_seconds=(now_wall-wall)-(now-start))
            stream.write(json.dumps(row)+'\n');stream.flush();os.fsync(stream.fileno());count+=1
            if count==1:print('HOST_OBSERVER_STARTED '+str(os.getpid()),flush=True)
            time.sleep(1)
    (HERE/'resource-observer-closure.json').write_text(json.dumps({'state':'PASS','pid':os.getpid(),
        'samples':count,'seconds':time.monotonic()-start,'explicit_stop_requested':(directory/'stop.request').exists()},indent=2)+'\n',encoding='utf-8')
    print('HOST_OBSERVER_STOPPED',flush=True)

if __name__=='__main__':
    main()
