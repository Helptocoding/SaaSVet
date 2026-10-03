"""Isolated PostgreSQL 16 design benchmark. This file is never imported by runtime."""
import importlib.util
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PY = Path(tempfile.gettempdir()) / 'vet-b8b-locked/Scripts/python.exe'
PG = Path(tempfile.gettempdir()) / 'vet-b8b-pg16-bin/pgsql/bin'
DATA = Path(tempfile.gettempdir()) / 'vet-e4-sql-redesign-2026-10-01-data'
PREFIX = 'test_e4_sql_redesign_'
BASELINE = '1d04e72f69e9c1576ac1be901624db127b879bf4'


def write(name, value):
    path = OUT / name
    if path.exists():
        raise RuntimeError(f'Refusing overwrite: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + '\n', encoding='utf-8')


def command(args, **kwargs):
    return subprocess.run(['rtk', 'proxy', *map(str, args)], check=True, **kwargs)


def environment(port, database):
    env = dict(os.environ, SECRET_KEY='e4-sql-redesign-isolated-only', DEBUG='False',
               ENVIRONMENT='dev', DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='',
               DISCORD_WEBHOOK_URL='', HEALTHCHECK_AGENT_WORKER_URL='',
               HEALTHCHECK_AGENT_SENDER_URL='', PYTHONIOENCODING='utf-8',
               DATABASE_URL=f'postgresql://e4bench@127.0.0.1:{port}/{database}')
    for key in list(env):
        if key.startswith(('E4_', 'B8', 'B9', 'W1_')):
            env.pop(key)
    return env


def summary(values):
    values = sorted(values)
    return dict(n=len(values), **{f'p{q}': values[math.ceil(q / 100 * (len(values) - 1))]
                                   for q in (50, 95, 99)}, max=values[-1])


def plan_nodes(plan):
    nodes = []
    def walk(node):
        nodes.append(dict(type=node['Node Type'], relation=node.get('Relation Name'),
            index=node.get('Index Name'), loops=node.get('Actual Loops'),
            hits=node.get('Shared Hit Blocks', 0), reads=node.get('Shared Read Blocks', 0),
            rows_removed=node.get('Rows Removed by Filter', 0),
            temp_read=node.get('Temp Read Blocks', 0), temp_written=node.get('Temp Written Blocks', 0),
            sort_method=node.get('Sort Method'), sort_space=node.get('Sort Space Used')))
        for child in node.get('Plans', []):
            walk(child)
    walk(plan['Plan'])
    return nodes


def point(kind, count, mode):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    sys.path.insert(0, str(ROOT / 'backend'))
    import django
    django.setup()
    from django.db import connection
    from django.utils import timezone
    from apps.agent import worker
    from apps.agent.models import ContactIdentity, Conversation, TurnWork
    from apps.channels.models import ChannelAccount, Message
    from apps.organizations.models import Organization
    from apps.agent.tests.e4_sql_oracle import old_selector
    from candidates import selector_one_query, selector_two_queries, _future_organization_ids, _selector

    assert connection.vendor == 'postgresql'
    assert connection.settings_dict['NAME'].startswith(PREFIX)
    clock = timezone.now()
    conversations, pending = (8, count) if kind == 'messages' else (count, 2000)
    orgs = Organization.objects.bulk_create([
        Organization(name=f'E4 synthetic org {i}', timezone='UTC') for i in range(3)])
    channels = ChannelAccount.objects.bulk_create([
        ChannelAccount(organization=o, external_account_id=f'e4-synthetic-{kind}-{count}-{i}')
        for i, o in enumerate(orgs)])
    contacts = ContactIdentity.objects.bulk_create([
        ContactIdentity(organization=o, external_id=f'e4-{kind[0]}-{count}-{i}')
        for i, o in enumerate(orgs)])
    history = Conversation.objects.bulk_create([
        Conversation(organization=o, channel_account=channels[i], contact=contacts[i],
                     last_activity_at=clock - timedelta(hours=2))
        for i, o in enumerate(orgs)])
    anchors = Message.objects.bulk_create([
        Message(organization=orgs[i], channel_account=channels[i],
                contact=contacts[i], conversation=history[i], direction='in',
                author_type='client', status='processed', available_at=clock - timedelta(hours=2))
        for i in range(3)])
    TurnWork.objects.bulk_create([
        TurnWork(organization=orgs[i], conversation=history[i], anchor_message=anchors[i],
                 anchor_created_at=anchors[i].created_at, cursor_message_id=anchors[i].pk,
                 cursor_created_at=anchors[i].created_at, context_at=anchors[i].created_at,
                 clinic_timezone='UTC', status='COMPLETED',
                 claimed_at=clock - timedelta(minutes=3-i), completed_at=clock - timedelta(minutes=3-i),
                 outcome_code='completed') for i in range(3)])
    convs = Conversation.objects.bulk_create([
        Conversation(organization=orgs[i % 3], channel_account=channels[i % 3],
                     contact=contacts[i % 3], last_activity_at=clock - timedelta(seconds=i))
        for i in range(conversations)])
    ready = pending * 4 // 5
    assert ready >= conversations
    rows = []
    for i in range(pending):
        conv = convs[i % conversations]
        j = i % conversations % 3
        rows.append(Message(organization=orgs[j], channel_account=channels[j],
                            contact=contacts[j], conversation=conv, direction='in',
                            author_type='client', status='pending',
                            available_at=clock - timedelta(seconds=1) if i < ready
                            else clock + timedelta(milliseconds=500)))
    Message.objects.bulk_create(rows, batch_size=500)
    with connection.cursor() as cursor:
        for table in ('organizations_organization', 'agent_conversation',
                      'channels_message', 'agent_turnwork'):
            cursor.execute(sql.SQL('ANALYZE {}').format(sql.Identifier(table)))
        cursor.execute("SET statement_timeout = '15s'")
        indexes = cursor.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE tablename IN ('channels_message','agent_conversation','agent_turnwork') ORDER BY tablename,indexname").fetchall()
    if kind == 'messages' and count == 10:
        index_path='indexes-post.json' if mode=='post' else 'indexes.json'
        if (OUT/index_path).exists():
            assert json.loads((OUT/index_path).read_text())==[list(row) for row in indexes]
        else:
            write(index_path, indexes)

    old = list(old_selector(now=clock))
    if kind == 'messages' and count == 10 and mode != 'post':
        old_query, old_parameters = old_selector(now=clock).query.sql_with_params()
        write('sql-old.json', dict(sql=old_query,
            parameters=list(map(str, old_parameters))))
    alternatives = [('OLD',old_selector),('NEW',worker._pending_conversation_candidates)] if mode=='post' else (
        [('A', selector_one_query)] if mode == 'pilot' else [
        ('A', selector_one_query), ('B', selector_two_queries)])
    results = []
    for label, candidate in alternatives:
        statements = []
        def observe(execute, query, parameters, many, context):
            statements.append(query)
            return execute(query, parameters, many, context)
        with connection.execute_wrapper(observe):
            selected = list(candidate(now=clock))
        assert selected == old, (kind, count, label, old, selected)
        assert len(selected) <= 3
        queries = []
        if label != 'B':
            queries.append(candidate(now=clock).query.sql_with_params())
        else:
            future = _future_organization_ids(clock)
            queries.append(future.query.sql_with_params())
            future_ids = list(future.values_list('organization_id', flat=True))
            queries.append(_selector(clock, (), future_ids).query.sql_with_params())
        assert len(queries) == len(statements)
        if kind == 'messages' and count == 10:
            sql_path=f'sql-post-{label.lower()}.json' if mode=='post' else f'sql-{label}.json'
            write(sql_path, [dict(sql=q, parameters=list(map(str,p))) for q,p in queries])
        n = 5 if mode == 'pilot' else 30
        warmup = 1 if mode == 'pilot' else 5
        values = []
        representative = None
        with connection.cursor() as cursor:
            for i in range(warmup + n):
                plans = []
                for query, params in queries:
                    cursor.execute('EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON) ' + query, params)
                    plans.append(cursor.fetchone()[0][0])
                if i >= warmup:
                    values.append(sum(p['Execution Time'] for p in plans))
                    if i == warmup + n // 2:
                        representative = plans
        write(f'explain/{mode}/{label}-{kind}-{count}.json', representative)
        results.append(dict(variant=label, kind=kind, x=count,
            conversations=conversations, pending_messages=pending, ready_messages=ready,
            future_messages=pending-ready, query_count=len(statements),
            selected_conversation_ids=selected,
            execution_ms=summary(values), warmup=warmup,
            planning_ms=sum(p['Planning Time'] for p in representative),
            nodes=[plan_nodes(p) for p in representative]))
    return results


def orchestrate(mode):
    head = subprocess.check_output(['rtk', 'proxy', 'git', 'rev-parse', 'HEAD'],
                                   cwd=ROOT, text=True).strip()
    assert head == BASELINE, head
    assert PY.exists() and (PG / 'postgres.exe').exists() and not DATA.exists()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    uri = f'postgresql://e4bench@127.0.0.1:{port}/postgres'
    server = None
    databases = []
    write(f'environment-{mode}.json', dict(head=head, postgres='16.15',
        python=str(PY), pg_binary=str(PG / 'postgres.exe'), port=port,
        fsync='on', synchronous_commit='on', isolated=True, mode=mode,
        samples=5 if mode == 'pilot' else 30, warmup=1 if mode == 'pilot' else 5))
    try:
        command([PG / 'initdb.exe', '-D', DATA, '-U', 'e4bench', '-A', 'trust',
                 '--encoding=UTF8', '--locale=C'], stdout=subprocess.DEVNULL)
        with (DATA / 'server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([str(PG / 'postgres.exe'), '-D', str(DATA),
                '-p', str(port), '-h', '127.0.0.1'], stdout=log,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(uri, connect_timeout=1) as conn:
                    row = conn.execute("SELECT version(),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('data_directory')").fetchone()
                    assert '16.15' in row[0] and row[1:3] == ('on','on')
                    assert Path(row[3]).resolve() == DATA.resolve()
                    break
            except psycopg.OperationalError:
                if server.poll() is not None:
                    raise RuntimeError(f'Postgres exited {server.returncode}')
                time.sleep(.2)
        else:
            raise RuntimeError('Postgres did not start')
        template = PREFIX + 'template'
        with psycopg.connect(uri, autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(template)))
        databases.append(template)
        with (OUT / f'migrate-{mode}.log').open('x', encoding='utf-8') as log:
            command([PY, '-X', 'utf8', 'manage.py', 'migrate', '--noinput'],
                    cwd=ROOT / 'backend', env=environment(port, template),
                    stdout=log, stderr=subprocess.STDOUT)
        if mode == 'full':
            oracle_db = PREFIX + 'oracle'
            with psycopg.connect(uri, autocommit=True) as conn:
                conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                    sql.Identifier(oracle_db), sql.Identifier(template)))
            databases.append(oracle_db)
            proc = command([PY, '-X', 'utf8', OUT / 'oracle.py'],
                           cwd=ROOT / 'backend', env=environment(port, oracle_db),
                           capture_output=True, text=True)
            write('oracle.json', json.loads(proc.stdout))
            with psycopg.connect(uri, autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(oracle_db)))
            databases.remove(oracle_db)
        series = [('conversations', [100])] if mode == 'pilot' else [
            ('messages', [10,50,100,250,500,1000,2000]),
            ('conversations', [10,25,50,100,250,500,1000])]
        for kind, sizes in series:
            results = []
            for size in sizes:
                name = PREFIX + kind + '_' + str(size)
                with psycopg.connect(uri, autocommit=True) as conn:
                    conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                        sql.Identifier(name), sql.Identifier(template)))
                databases.append(name)
                proc = command([PY, '-X', 'utf8', __file__, 'point', kind, size, mode],
                               cwd=ROOT / 'backend', env=environment(port, name),
                               capture_output=True, text=True)
                results.extend(json.loads(proc.stdout))
                print(json.dumps(dict(kind=kind, size=size, result=results[-1]['execution_ms'])), flush=True)
                with psycopg.connect(uri, autocommit=True) as conn:
                    conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
                databases.remove(name)
            write(f'matrix-{mode}-{kind}.json', results)
    finally:
        if server is not None and server.poll() is None:
            with psycopg.connect(uri, autocommit=True) as conn:
                for database in reversed(databases):
                    conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
            command([PG / 'pg_ctl.exe', '-D', DATA, '-m', 'fast', '-w', 'stop'],
                    stdout=subprocess.DEVNULL)
            server.wait(timeout=15)
        if DATA.exists():
            assert DATA.resolve().parent == Path(tempfile.gettempdir()).resolve()
            import shutil
            shutil.rmtree(DATA)
        write(f'cleanup-{mode}.json', dict(stopped=True, data_directory_absent=not DATA.exists(),
              port=port))


def resume():
    """Recover the migrated isolated template after the host interrupted full run."""
    assert subprocess.check_output(['rtk', 'proxy', 'git', 'rev-parse', 'HEAD'],
                                   cwd=ROOT, text=True).strip() == BASELINE
    receipt = json.loads((OUT / 'environment-full.json').read_text())
    assert DATA.exists() and receipt['head'] == BASELINE
    port = receipt['port']
    uri = f'postgresql://e4bench@127.0.0.1:{port}/postgres'
    server = None
    with socket.socket() as probe:
        running = probe.connect_ex(('127.0.0.1', port)) == 0
    if not running:
        with (DATA / 'server.log').open('a', encoding='utf-8') as log:
            server = subprocess.Popen([str(PG / 'postgres.exe'), '-D', str(DATA),
                '-p', str(port), '-h', '127.0.0.1'], stdout=log,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic()+120
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(uri, connect_timeout=1) as conn:
                row = conn.execute("SELECT version(),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('data_directory')").fetchone()
                assert '16.15' in row[0] and row[1:3] == ('on','on')
                assert Path(row[3]).resolve() == DATA.resolve()
                break
        except psycopg.OperationalError:
            if server is not None and server.poll() is not None:
                raise RuntimeError(f'Postgres exited {server.returncode}')
            time.sleep(.2)
    else:
        raise RuntimeError('Postgres did not recover')
    write('environment-resume.json', dict(postgres=row[0],fsync=row[1],synchronous_commit=row[2],
        port=port, server_pid=int((DATA/'postmaster.pid').read_text().splitlines()[0]), template_reused=True,
        reason='Host process interruption after completed migrations; no matrix points completed'))
    template = PREFIX+'template'
    oracle_db = PREFIX+'oracle'
    with psycopg.connect(uri, autocommit=True) as conn:
        names = [r[0] for r in conn.execute('SELECT datname FROM pg_database')]
        assert template in names
        if oracle_db in names:
            assert conn.execute('SELECT count(*) FROM pg_stat_activity WHERE datname=%s',(oracle_db,)).fetchone()[0] == 0
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(oracle_db)))
        conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
            sql.Identifier(oracle_db),sql.Identifier(template)))
    proc = subprocess.run(['rtk','proxy',str(PY),'-X','utf8',str(OUT/'oracle.py')],
        cwd=ROOT/'backend',env=environment(port,oracle_db),capture_output=True,text=True)
    (OUT/'oracle-stderr.log').write_text(proc.stderr,encoding='utf-8')
    (OUT/'oracle-stdout.json').write_text(proc.stdout,encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(f'Oracle failed {proc.returncode}: {proc.stderr[-2000:]}')
    write('oracle.json',json.loads(proc.stdout))
    print(json.dumps(dict(oracle=json.loads(proc.stdout)['decision_mismatches'])),flush=True)
    with psycopg.connect(uri,autocommit=True) as conn:
        conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(oracle_db)))
    for kind,sizes in [('messages',[10,50,100,250,500,1000,2000]),
                       ('conversations',[10,25,50,100,250,500,1000])]:
        results=[]
        for size in sizes:
            name=PREFIX+kind+'_'+str(size)
            with psycopg.connect(uri,autocommit=True) as conn:
                conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                    sql.Identifier(name),sql.Identifier(template)))
            proc=subprocess.run(['rtk','proxy',str(PY),'-X','utf8',__file__,'point',kind,str(size),'full'],
                cwd=ROOT/'backend',env=environment(port,name),capture_output=True,text=True)
            (OUT/f'point-{kind}-{size}.log').write_text(proc.stderr,encoding='utf-8')
            if proc.returncode:
                raise RuntimeError(f'Point failed {kind}/{size}: {proc.stderr[-2000:]}')
            results.extend(json.loads(proc.stdout))
            write(f'points/full-{kind}-{size}.json',json.loads(proc.stdout))
            print(json.dumps(dict(kind=kind,size=size,
                variants=[dict(variant=r['variant'],ms=r['execution_ms']) for r in results[-2:]])),flush=True)
            with psycopg.connect(uri,autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        write(f'matrix-full-{kind}.json',results)
    print('DESIGN_MEASUREMENTS_COMPLETE: isolated template retained for post-fix verification',flush=True)


def post():
    """Paired OLD/NEW measurements on exactly the same freshly cloned datasets."""
    import hashlib
    receipt=json.loads((OUT/'environment-full.json').read_text())
    port=receipt['port']
    uri=f'postgresql://e4bench@127.0.0.1:{port}/postgres'
    source=ROOT/'backend/apps/agent/worker.py'
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    if (OUT/'environment-post.json').exists():
        assert json.loads((OUT/'environment-post.json').read_text())['worker_sha256']==source_hash
    else:
        write('environment-post.json',dict(port=port,paired=True,old_runtime='83ee3b24c84b170e22e401cb09a34da5320ae0a3',
            worker_sha256=source_hash,samples=30,warmup=5,metric='EXPLAIN ANALYZE Execution Time',
            no_os_cache_flush=True,order='OLD then NEW, independent five warmups each'))
    name=PREFIX+'oracle_post'
    if not (OUT/'oracle-post.json').exists():
        with psycopg.connect(uri,autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                sql.Identifier(name),sql.Identifier(PREFIX+'template')))
        proc=subprocess.run(['rtk','proxy',str(PY),'-X','utf8',str(OUT/'oracle.py'),'--post'],
            cwd=ROOT/'backend',env=environment(port,name),capture_output=True,text=True)
        (OUT/'oracle-post-stderr.log').write_text(proc.stderr,encoding='utf-8')
        (OUT/'oracle-post-stdout.json').write_text(proc.stdout,encoding='utf-8')
        assert proc.returncode==0,proc.stderr[-2000:]
        write('oracle-post.json',json.loads(proc.stdout))
        with psycopg.connect(uri,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
    print('POST_ORACLE_PASS',flush=True)
    for kind,sizes in [('messages',[10,50,100,250,500,1000,2000]),
                       ('conversations',[10,25,50,100,250,500,1000])]:
        results=[]
        for size in sizes:
            point_path=OUT/f'points/post-{kind}-{size}.json'
            if point_path.exists():
                results.extend(json.loads(point_path.read_text()))
                continue
            name=PREFIX+'post_'+kind+'_'+str(size)
            with psycopg.connect(uri,autocommit=True) as conn:
                assert Path(conn.execute("SELECT current_setting('data_directory')").fetchone()[0]).resolve()==DATA.resolve()
                if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():
                    assert conn.execute('SELECT count(*) FROM pg_stat_activity WHERE datname=%s',(name,)).fetchone()[0]==0
                    assert not (OUT/f'explain/post/OLD-{kind}-{size}.json').exists()
                    conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
                conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                    sql.Identifier(name),sql.Identifier(PREFIX+'template')))
            proc=subprocess.run(['rtk','proxy',str(PY),'-X','utf8',__file__,'point',kind,str(size),'post'],
                cwd=ROOT/'backend',env=environment(port,name),capture_output=True,text=True)
            (OUT/f'post-{kind}-{size}.log').write_text(proc.stderr,encoding='utf-8')
            if proc.returncode:
                raise RuntimeError(f'Post point failed {kind}/{size}: {proc.stderr[-2000:]}')
            point_results=json.loads(proc.stdout)
            results.extend(point_results)
            write(f'points/post-{kind}-{size}.json',point_results)
            print(json.dumps(dict(kind=kind,size=size,
                variants=[dict(variant=r['variant'],ms=r['execution_ms']) for r in point_results])),flush=True)
            with psycopg.connect(uri,autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        write(f'matrix-post-{kind}.json',results)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
    print('PAIRED_POST_FIX_MATRICES_COMPLETE',flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == 'point':
        print(json.dumps(point(sys.argv[2], int(sys.argv[3]), sys.argv[4]), default=str))
    elif len(sys.argv) == 2 and sys.argv[1] in ('pilot', 'full'):
        orchestrate(sys.argv[1])
    elif len(sys.argv) == 2 and sys.argv[1] == 'resume':
        resume()
    elif len(sys.argv) == 2 and sys.argv[1] == 'post':
        post()
    else:
        raise SystemExit('usage: benchmark.py pilot|full')
