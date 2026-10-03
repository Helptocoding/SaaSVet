"""Recover the interrupted cluster and certify already successful test IDs."""
import hashlib
import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import psycopg

from benchmark import DATA, OUT, PG, ROOT


def main():
    assert not (OUT/'environment-regression-resume.json').exists()
    expected = json.loads((OUT/'regression-ids.json').read_text())
    passed = []
    for index in range(2):
        sources = json.loads((OUT/f'regression-{index}.results.sources.json').read_text())
        for filename, digest in sources.items():
            source = ROOT / filename
            assert source.is_file(), filename
            assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, filename
        rows = [json.loads(line) for line in (OUT/f'regression-{index}.results.passed.jsonl').read_text().splitlines()]
        assert all(row['status']=='ok' for row in rows)
        passed.extend(row['test_id'] for row in rows)
        log = (OUT/f'regression-{index}.log').read_text(encoding='utf-8')
        assert not any(line.strip() in ('FAIL','ERROR') or line.startswith(('FAIL:','ERROR:'))
                       for line in log.splitlines())
    assert len(passed) == len(set(passed)) == 659
    assert set(passed) <= set(expected) and len(expected)==775
    assert DATA.resolve() == (Path(tempfile.gettempdir())/'vet-e4-sql-redesign-2026-10-01-data').resolve()
    assert DATA.is_dir()
    port = json.loads((OUT/'environment-full.json').read_text())['port']
    uri = f'postgresql://e4bench@127.0.0.1:{port}/postgres'
    with socket.socket() as probe:
        probe.settimeout(.5)
        running = probe.connect_ex(('127.0.0.1',port)) == 0
    if not running:
        with (DATA/'server.log').open('a',encoding='utf-8') as log:
            subprocess.Popen([str(PG/'postgres.exe'),'-D',str(DATA),'-p',str(port),'-h','127.0.0.1'],
                stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic()+900
    while time.monotonic()<deadline:
        try:
            with psycopg.connect(uri,connect_timeout=1) as conn:
                version,fsync,synchronous,actual = conn.execute("""SELECT version(),current_setting('fsync'),
                    current_setting('synchronous_commit'),current_setting('data_directory')""").fetchone()
                assert 'PostgreSQL 16.15' in version and fsync == synchronous == 'on'
                assert Path(actual).resolve()==DATA.resolve()
                break
        except psycopg.OperationalError:
            time.sleep(.5)
    else:
        raise RuntimeError('Isolated PostgreSQL recovery did not finish within 900 seconds')
    partial = dict(status='INTERRUPTED_WITH_SUCCESSFUL_IDS_RETAINED',
        tests=len(passed),test_ids=sorted(passed),failures_recorded=0,errors_recorded=0,
        skips=0,xfail=0,exit_code=None,source_hashes_verified=True,
        evidence=['regression-0.results.passed.jsonl','regression-1.results.passed.jsonl'],
        remaining=len(set(expected)-set(passed)))
    (OUT/'regression-partial.json').write_text(json.dumps(partial,indent=2)+'\n',encoding='utf-8')
    receipt = dict(postgres=version,fsync=fsync,synchronous_commit=synchronous,port=port,
        server_pid=int((DATA/'postmaster.pid').read_text().splitlines()[0]),
        source_hashes_verified=True,retained_passes=len(passed),remaining=partial['remaining'],
        reason='Previous host processes no longer present; two regression shards interrupted without final receipts')
    (OUT/'environment-regression-resume.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print('RECOVERED: 659 source-verified passes retained; 116 remaining',flush=True)


if __name__=='__main__':
    main()
