"""Read-only progress, no tuning, SQL text, or workload injection."""
import json
import sys
from pathlib import Path
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT))
import authorized_lab as lab
task,state=lab.session()
with lab.connect(state['config']) as con:
    rows=con.execute("SELECT datname,pid,state,wait_event_type,wait_event,extract(epoch FROM clock_timestamp()-query_start)::float FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()").fetchall()
    dbs=[r[0] for r in con.execute("SELECT datname FROM pg_database WHERE datname LIKE 'test_d29_reg_v2_%'")]
print(json.dumps(dict(databases=dbs,clients=[dict(zip(('database','backend_pid','state','wait_type','wait_event','query_elapsed_seconds'),r)) for r in rows]),indent=2))
