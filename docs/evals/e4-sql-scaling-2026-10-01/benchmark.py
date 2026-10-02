"""Isolated, diagnostic-only E4 selector SQL cardinality experiment.

Runs the unmodified worker queryset against migrated PostgreSQL 16. All rows
are synthetic, and every database is cloned from the same empty template.
"""
import json
import math
import os
import platform
import shutil
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
OUT = Path(os.environ.get('SQL_SCALING_OUT', Path(__file__).resolve().parent)).resolve()
PY = Path(tempfile.gettempdir()) / 'vet-b8b-locked/Scripts/python.exe'
PG = Path(tempfile.gettempdir()) / 'vet-b8b-pg16-bin/pgsql/bin'
DATA = Path(tempfile.gettempdir()) / 'vet-e4-sql-scaling-2026-10-01-data'
BASELINE = '6e59f6c05514ad6eca0985796e538de4fd749560'
RUNTIME = '83ee3b24c84b170e22e401cb09a34da5320ae0a3'
PREFIX = 'test_e4_sql_scaling_'
N = 30
WARMUP = 5


def write(name, value):
    path = OUT / name
    if path.exists():
        raise RuntimeError(f'Refusing overwrite: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + '\n', encoding='utf-8')


def command(args, **kw):
    return subprocess.run(['rtk', 'proxy', *map(str, args)], check=True, **kw)


def environment(port, database):
    env = dict(os.environ, SECRET_KEY='e4-sql-scaling-isolated-only', DEBUG='False',
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
                                   for q in (50, 75, 90, 95, 99)}, max=values[-1])


def point(kind, count):
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

    assert connection.vendor == 'postgresql'
    assert connection.settings_dict['NAME'].startswith(PREFIX)
    clock = timezone.now()
    if kind == 'messages':
        conversations, pending = 8, count
    elif kind == 'conversations':
        conversations, pending = count, 2000
    else:
        conversations, pending = 354, 231

    orgs = Organization.objects.bulk_create([
        Organization(name=f'E4 synthetic org {i}', timezone='UTC') for i in range(3)])
    channels = ChannelAccount.objects.bulk_create([
        ChannelAccount(organization=o, external_account_id=f'e4-synthetic-{kind}-{count}-{i}')
        for i, o in enumerate(orgs)])
    contacts = ContactIdentity.objects.bulk_create([
        ContactIdentity(organization=o, external_id=f'e4-{kind[0]}-{count}-{i}')
        for i, o in enumerate(orgs)])

    # One completed claim per org keeps the E4 forecast branch observable.
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

    if kind in ('mixed', 'mixed_ready'):
        assignments = [0] * 231 + [1] * 62 + [2] * 61
    else:
        assignments = [i % 3 for i in range(conversations)]
    convs = Conversation.objects.bulk_create([
        Conversation(organization=orgs[j], channel_account=channels[j], contact=contacts[j],
                     last_activity_at=clock - timedelta(seconds=i))
        for i, j in enumerate(assignments)])

    ready = pending if kind in ('mixed', 'mixed_ready') else pending * 4 // 5
    if kind in ('mixed', 'mixed_ready'):
        # A noisy org plus one ready inbound in each healthy org; the remaining
        # healthy conversations are deliberately idle. Separate from A/B.
        targets = convs[:229] + [convs[231], convs[293]]
        ready = 185
    else:
        assert ready >= conversations
        targets = [convs[i % conversations] for i in range(pending)]
    mapping = {o.pk: i for i, o in enumerate(orgs)}
    rows = []
    for i, conv in enumerate(targets):
        j = mapping[conv.organization_id]
        is_ready = (i < 183 or i >= 229) if kind == 'mixed_ready' else i < ready
        rows.append(Message(organization=orgs[j], channel_account=channels[j],
                            contact=contacts[j], conversation=conv, direction='in',
                            author_type='client', status='pending',
                            semantic_type='safety_signal' if kind in ('mixed', 'mixed_ready') and i == 229 else '',
                            available_at=clock - timedelta(seconds=1) if is_ready
                            else clock + timedelta(milliseconds=500)))
    Message.objects.bulk_create(rows, batch_size=500)
    with connection.cursor() as cursor:
        for table in ('organizations_organization', 'agent_conversation',
                      'channels_message', 'agent_turnwork'):
            cursor.execute(sql.SQL('ANALYZE {}').format(sql.Identifier(table)))
        cursor.execute("SET statement_timeout = '15s'")
        cursor.execute("SELECT version(), current_setting('fsync'), current_setting('synchronous_commit')")
        pg_version, fsync, synchronous_commit = cursor.fetchone()

    queryset = worker._pending_conversation_candidates(now=clock)
    compiled, params = queryset.query.sql_with_params()
    if kind == 'messages' and count == 10:
        (OUT / 'compiled-sql.txt').write_text(
            compiled + '\n\nPARAMS (synthetic):\n' + json.dumps(params, indent=2, default=str) + '\n',
            encoding='utf-8')

    statements = []
    def observe(execute, query, parameters, many, context):
        statements.append(query)
        return execute(query, parameters, many, context)
    with connection.execute_wrapper(observe):
        selected = list(worker._pending_conversation_candidates(now=clock))
    assert len(statements) == 1, f'Expected one selector statement, got {len(statements)}'
    assert len(selected) <= 3

    with connection.cursor() as cursor:
        cursor.execute('EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON) ' + compiled, params)
        first = cursor.fetchone()[0][0]
        for _ in range(WARMUP):
            cursor.execute('EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON) ' + compiled, params)
            cursor.fetchone()
        values = []
        representative = None
        for i in range(N):
            cursor.execute('EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON) ' + compiled, params)
            plan = cursor.fetchone()[0][0]
            values.append(plan['Execution Time'])
            if i == N // 2:
                representative = plan
    label = f'{kind}-{count}'
    write(f'explain/{label}.json', representative)
    result = dict(kind=kind, x=count, organizations=3, conversations=conversations,
                historical_conversations=3, pending_messages=pending,
                historical_messages=3, ready_messages=ready, upcoming_messages=pending-ready,
                safety_messages=1 if kind in ('mixed', 'mixed_ready') else 0,
                process_work=0, historical_completed_work=3,
                selector_sql_ms=summary(values), coldish_first_explain_ms=first['Execution Time'],
                warmup=WARMUP, query_count=len(statements), n_plus_one=False,
                selected_count=len(selected), planning_ms=representative['Planning Time'],
                postgresql=pg_version, fsync=fsync, synchronous_commit=synchronous_commit)
    write(f'points/{label}.json', result)
    return result


def orchestrate():
    head = subprocess.check_output(['rtk', 'proxy', 'git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                   text=True).strip()
    assert head == BASELINE, f'Baseline drift: {head}'
    assert PY.exists() and PG.joinpath('postgres.exe').exists()
    assert not DATA.exists(), f'Refusing existing data directory: {DATA}'
    assert not (OUT / 'matrix-messages.json').exists()
    assert not (OUT / 'matrix-conversations.json').exists()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    uri = f'postgresql://e4bench@127.0.0.1:{port}/postgres'
    started = False
    server = None
    databases = []
    write('environment.json', dict(baseline=head, runtime_sha=RUNTIME,
          python=sys.version, django='6.0.5', psycopg=psycopg.__version__,
          cpu=platform.processor(), cpu_count=os.cpu_count(), platform=platform.platform(),
          postgresql_binary=str(PG / 'postgres.exe'), data_directory=str(DATA), port=port,
          isolated=True, no_production=True, cache_policy='No OS cache flushing; first EXPLAIN is cold-ish only',
          measurement='PostgreSQL EXPLAIN ANALYZE Execution Time, 5 warmups, 30 repetitions per point'))
    try:
        command([PG / 'initdb.exe', '-D', DATA, '-U', 'e4bench', '-A', 'trust',
                 '--encoding=UTF8', '--locale=C'], stdout=subprocess.DEVNULL)
        with (DATA / 'server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([str(PG / 'postgres.exe'), '-D', str(DATA),
                '-p', str(port), '-h', '127.0.0.1'], stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(uri, connect_timeout=1):
                    break
            except psycopg.OperationalError:
                if server.poll() is not None:
                    raise RuntimeError(f'PostgreSQL exited: {server.returncode}')
                time.sleep(.2)
        else:
            raise RuntimeError('PostgreSQL did not become ready')
        started = True
        with psycopg.connect(uri, autocommit=True) as conn:
            row = conn.execute("SELECT version(), current_setting('fsync'), current_setting('synchronous_commit'), current_setting('data_directory')").fetchone()
            assert '16.' in row[0] and row[1:3] == ('on', 'on') and Path(row[3]).resolve() == DATA.resolve()
            template = PREFIX + 'template'
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(template)))
            databases.append(template)
        with (OUT / 'migrate.log').open('x', encoding='utf-8') as log:
            command([PY, '-X', 'utf8', 'manage.py', 'migrate', '--noinput'],
                    cwd=ROOT / 'backend', env=environment(port, template),
                    stdout=log, stderr=subprocess.STDOUT)

        for kind, sizes in (('messages', (10, 50, 100, 250, 500, 1000, 2000)),
                            ('conversations', (10, 25, 50, 100, 250, 500, 1000)),
                            ('mixed', (354,))):
            results = []
            for size in sizes:
                database = PREFIX + kind + '_' + str(size)
                with psycopg.connect(uri, autocommit=True) as conn:
                    conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                        sql.Identifier(database), sql.Identifier(template)))
                databases.append(database)
                proc = command([PY, '-X', 'utf8', __file__, 'point', kind, size],
                               cwd=ROOT / 'backend', env=environment(port, database),
                               capture_output=True, text=True)
                result = json.loads(proc.stdout)
                results.append(result)
                print(json.dumps(dict(kind=kind, x=size, ms=result['selector_sql_ms'])), flush=True)
                with psycopg.connect(uri, autocommit=True) as conn:
                    conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
                databases.remove(database)
                if result['selector_sql_ms']['p95'] > 5000:
                    print(f'STOP impractical {kind} at {size}', flush=True)
                    break
            write('matrix-' + kind + '.json', results)
    finally:
        dropped = []
        if started:
            with psycopg.connect(uri, autocommit=True) as conn:
                for database in reversed(databases):
                    conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
                    dropped.append(database)
            command([PG / 'pg_ctl.exe', '-D', DATA, '-m', 'fast', '-w', 'stop'],
                    stdout=subprocess.DEVNULL)
            server.wait(timeout=15)
        if DATA.exists():
            assert DATA.resolve().parent == Path(tempfile.gettempdir()).resolve()
            shutil.rmtree(DATA)
        write('cleanup.json', dict(stopped=started, dropped_databases=dropped,
             data_directory_absent=not DATA.exists(), port=port))


def resume():
    """Continue only missing points after an interrupted local process."""
    assert subprocess.check_output(['rtk', 'proxy', 'git', 'rev-parse', 'HEAD'],
                                   cwd=ROOT, text=True).strip() == BASELINE
    receipt = json.loads((OUT / 'environment.json').read_text(encoding='utf-8'))
    assert receipt['baseline'] == BASELINE and receipt['runtime_sha'] == RUNTIME
    assert Path(receipt['data_directory']).resolve() == DATA.resolve() and DATA.exists()
    port = receipt['port']
    uri = f'postgresql://e4bench@127.0.0.1:{port}/postgres'
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', port)) != 0, 'Port occupied'
    with (DATA / 'server.log').open('a', encoding='utf-8') as log:
        server = subprocess.Popen([str(PG / 'postgres.exe'), '-D', str(DATA),
            '-p', str(port), '-h', '127.0.0.1'], stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(uri, connect_timeout=1) as conn:
                row = conn.execute("SELECT version(), current_setting('fsync'), current_setting('synchronous_commit'), current_setting('data_directory')").fetchone()
                assert '16.15' in row[0] and row[1:3] == ('on', 'on')
                assert Path(row[3]).resolve() == DATA.resolve()
                break
        except psycopg.OperationalError:
            if server.poll() is not None:
                raise RuntimeError(f'PostgreSQL exited: {server.returncode}')
            time.sleep(.2)
    else:
        raise RuntimeError('PostgreSQL did not become ready')
    completed = []
    # These two completed receipts were printed before the process interruption.
    # Plans survived; no rerun is used to replace their distribution.
    recovered = {
        10: (24.299, 24.606, 27.433, 27.515, 28.405),
        25: (59.089, 72.544, 90.838, 90.887, 91.954),
    }
    for size, vals in recovered.items():
        plan = json.loads((OUT / f'explain/conversations-{size}.json').read_text())
        completed.append(dict(kind='conversations', x=size, organizations=3,
            conversations=size, historical_conversations=3, pending_messages=2000,
            historical_messages=3, ready_messages=1600, upcoming_messages=400,
            safety_messages=0, process_work=0, historical_completed_work=3,
            selector_sql_ms=dict(n=30, **dict(zip(('p50','p75','p90','p95','p99'), vals)),
                                 max=vals[-1]), warmup=5, query_count=1,
            n_plus_one=False, planning_ms=plan['Planning Time'],
            coldish_first_explain_ms=None, recovered_from_stdout=True,
            postgresql=row[0], fsync=row[1], synchronous_commit=row[2]))
    try:
        for kind, sizes in (('conversations', (50, 100, 250, 500, 1000)),
                            ('mixed', (354,))):
            results = completed if kind == 'conversations' else []
            for size in sizes:
                database = PREFIX + kind + '_' + str(size)
                with psycopg.connect(uri, autocommit=True) as conn:
                    existing = conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',
                                            (database,)).fetchone()
                    if existing:
                        clients = conn.execute('SELECT count(*) FROM pg_stat_activity WHERE datname=%s',
                                               (database,)).fetchone()[0]
                        assert clients == 0 and not (OUT / f'explain/{kind}-{size}.json').exists()
                        conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
                    conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                        sql.Identifier(database), sql.Identifier(PREFIX + 'template')))
                proc = subprocess.run(['rtk', 'proxy', str(PY), '-X', 'utf8', __file__,
                                      'point', kind, str(size)], cwd=ROOT / 'backend',
                                      env=environment(port, database), capture_output=True, text=True)
                with psycopg.connect(uri, autocommit=True) as conn:
                    conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
                if proc.returncode:
                    write('stopped-scale.json', dict(kind=kind, x=size, exit_code=proc.returncode,
                         stderr=proc.stderr[-4000:]))
                    break
                result = json.loads(proc.stdout)
                results.append(result)
                print(json.dumps(dict(kind=kind, x=size, ms=result['selector_sql_ms'])), flush=True)
                if result['selector_sql_ms']['p95'] > 5000:
                    write('stopped-scale.json', dict(kind=kind, x=size,
                         reason='p95 exceeded 5000 ms; larger points impractical'))
                    break
            write('matrix-' + kind + '.json', results)
            if (OUT / 'stopped-scale.json').exists():
                break
    finally:
        with psycopg.connect(uri, autocommit=True) as conn:
            names = [x[0] for x in conn.execute('SELECT datname FROM pg_database')
                     if x[0].startswith(PREFIX)]
            clients = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()").fetchone()[0]
            assert clients == 0
            for database in names:
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
        command([PG / 'pg_ctl.exe', '-D', DATA, '-m', 'fast', '-w', 'stop'],
                stdout=subprocess.DEVNULL)
        server.wait(timeout=15)
        assert DATA.resolve().parent == Path(tempfile.gettempdir()).resolve()
        shutil.rmtree(DATA)
        write('cleanup.json', dict(status='CLEANED', stopped=True,
             dropped_databases=names, clients_own=0, data_directory_absent=not DATA.exists(),
             port=port))


def finish_missing():
    """Run only the two points blocked by an overlong synthetic contact ID."""
    assert subprocess.check_output(['rtk', 'proxy', 'git', 'rev-parse', 'HEAD'],
                                   cwd=ROOT, text=True).strip() == BASELINE
    assert not DATA.exists()
    assert (OUT / 'matrix-conversations.json').exists()
    assert not (OUT / 'explain/conversations-1000.json').exists()
    assert not (OUT / 'matrix-mixed.json').exists()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    uri = f'postgresql://e4bench@127.0.0.1:{port}/postgres'
    write('environment-completion.json', dict(baseline=BASELINE, runtime_sha=RUNTIME,
          port=port, data_directory=str(DATA), reason='Synthetic contact ID overflow at B=1000',
          method='Same selector, PostgreSQL 16.15, fixture proportions, warmup and n'))
    started = False
    server = None
    try:
        command([PG / 'initdb.exe', '-D', DATA, '-U', 'e4bench', '-A', 'trust',
                 '--encoding=UTF8', '--locale=C'], stdout=subprocess.DEVNULL)
        with (DATA / 'server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([str(PG / 'postgres.exe'), '-D', str(DATA),
                '-p', str(port), '-h', '127.0.0.1'], stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(uri, connect_timeout=1) as conn:
                    row = conn.execute("SELECT version(), current_setting('fsync'), current_setting('synchronous_commit'), current_setting('data_directory')").fetchone()
                    assert '16.15' in row[0] and row[1:3] == ('on', 'on')
                    assert Path(row[3]).resolve() == DATA.resolve()
                    break
            except psycopg.OperationalError:
                if server.poll() is not None:
                    raise RuntimeError(f'PostgreSQL exited: {server.returncode}')
                time.sleep(.2)
        else:
            raise RuntimeError('PostgreSQL did not become ready')
        started = True
        template = PREFIX + 'template'
        with psycopg.connect(uri, autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(template)))
        with (OUT / 'migrate-completion.log').open('x', encoding='utf-8') as log:
            command([PY, '-X', 'utf8', 'manage.py', 'migrate', '--noinput'],
                    cwd=ROOT / 'backend', env=environment(port, template),
                    stdout=log, stderr=subprocess.STDOUT)
        for kind, size in (('conversations', 1000), ('mixed', 354)):
            database = PREFIX + kind + '_' + str(size)
            with psycopg.connect(uri, autocommit=True) as conn:
                conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                    sql.Identifier(database), sql.Identifier(template)))
            proc = subprocess.run(['rtk', 'proxy', str(PY), '-X', 'utf8', __file__,
                                  'point', kind, str(size)], cwd=ROOT / 'backend',
                                  env=environment(port, database), capture_output=True, text=True)
            with psycopg.connect(uri, autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
            if proc.returncode:
                write('completion-failure.json', dict(kind=kind, x=size,
                      exit_code=proc.returncode, stderr=proc.stderr[-4000:]))
                break
            result = json.loads(proc.stdout)
            print(json.dumps(dict(kind=kind, x=size, ms=result['selector_sql_ms'])), flush=True)
            if kind == 'conversations':
                path = OUT / 'matrix-conversations.json'
                rows = json.loads(path.read_text(encoding='utf-8'))
                assert [r['x'] for r in rows] == [10, 25, 50, 100, 250, 500]
                rows.append(result)
                path.write_text(json.dumps(rows, indent=2, default=str) + '\n', encoding='utf-8')
            else:
                write('matrix-mixed.json', [result])
    finally:
        if started:
            with psycopg.connect(uri, autocommit=True) as conn:
                names = [r[0] for r in conn.execute('SELECT datname FROM pg_database')
                         if r[0].startswith(PREFIX)]
                clients = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()").fetchone()[0]
                assert clients == 0
                for name in names:
                    conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
            command([PG / 'pg_ctl.exe', '-D', DATA, '-m', 'fast', '-w', 'stop'],
                    stdout=subprocess.DEVNULL)
            server.wait(timeout=15)
        if DATA.exists():
            assert DATA.resolve().parent == Path(tempfile.gettempdir()).resolve()
            shutil.rmtree(DATA)
        write('cleanup-completion.json', dict(status='CLEANED', stopped=started,
             data_directory_absent=not DATA.exists(), port=port))


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == 'point':
        print(json.dumps(point(sys.argv[2], int(sys.argv[3])), default=str))
    elif len(sys.argv) == 2 and sys.argv[1] == 'resume':
        resume()
    elif len(sys.argv) == 2 and sys.argv[1] == 'finish-missing':
        finish_missing()
    elif len(sys.argv) == 1:
        orchestrate()
    else:
        raise SystemExit('usage: benchmark.py [point KIND COUNT]')
