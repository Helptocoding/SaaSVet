import json
from pathlib import Path
import psycopg

e = json.loads(Path('docs/evals/d29-authorized-probes-2026-10-07/environment.json').read_text())
s = json.loads((Path(e['task']) / 'session.json').read_text())
with psycopg.connect(dbname='postgres', user=s['config']['USER'], password=s['config']['PASSWORD'], host='127.0.0.1', port=e['port']) as con:
    print('dbs', con.execute("select datname from pg_database where datname like 'test_d29%'").fetchall())
for db in ('postgres', e['template']):
    with psycopg.connect(dbname=db, user=s['config']['USER'], password=s['config']['PASSWORD'], host='127.0.0.1', port=e['port']) as con:
        print(db, con.execute("select tablename from pg_tables where schemaname='public' and tablename like 'channels%'").fetchall())
