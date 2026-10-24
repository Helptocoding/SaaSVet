import json,platform,sys,time
from datetime import datetime,timezone
info={}
for name in ('time','monotonic','perf_counter'):
    item=time.get_clock_info(name)
    info[name]={'implementation':item.implementation,'monotonic':item.monotonic,'adjustable':item.adjustable,'resolution':item.resolution}
print(json.dumps({'kind':'metadata','platform':platform.platform(),'python':sys.version,'clocks':info}),flush=True)
origin_m=time.monotonic_ns()
origin_w=time.time_ns()
while True:
    m=time.monotonic_ns()
    w=time.time_ns()
    row={'kind':'sample','wall_ns':w,'monotonic_ns':m,'elapsed_seconds':(m-origin_m)/1e9,'wall_minus_monotonic_seconds':((w-origin_w)-(m-origin_m))/1e9}
    for name in ('CLOCK_MONOTONIC_RAW','CLOCK_BOOTTIME'):
        if hasattr(time,name):
            row[name]=time.clock_gettime_ns(getattr(time,name))
    print(json.dumps(row),flush=True)
    if row['elapsed_seconds']>=120:
        break
    time.sleep(0.5)
