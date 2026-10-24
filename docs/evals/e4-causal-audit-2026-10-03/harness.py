"""Disposable PostgreSQL microbenchmark for HEAD 6e59f6c (not PROFILE-BETA-1)."""

import json
import math
import os
import socket
import statistics
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import psycopg
from psycopg import sql as pgsql


ROOT = Path(r"C:\Users\LAP\.codex\worktrees\e4-causal-audit-6e59\VeterinariaSaaS")
PYTHON = Path(r"C:\Users\LAP\AppData\Local\Temp\vet-b8b-locked\Scripts\python.exe")
PG = Path(r"C:\Users\LAP\AppData\Local\Temp\vet-b8b-pg16-bin\pgsql\bin")
DATA = Path(r"C:\Users\LAP\AppData\Local\Temp\vet-e4-causal-6e59-pg")
OUT = Path(r"C:\Users\LAP\AppData\Local\Temp\vet-e4-causal-6e59-matrix.json")
PORT = 35445
DB = "test_e4_causal_6e59"
USER = "b9e"
BASE_URI = f"postgresql://{USER}@127.0.0.1:{PORT}/postgres"
TEST_URI = f"postgresql://{USER}@127.0.0.1:{PORT}/{DB}"


def command(*args):
    subprocess.run([str(a) for a in args], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def port_closed():
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", PORT)) != 0


def start():
    assert PYTHON.exists() and PG.joinpath("pg_ctl.exe").exists()
    assert not DATA.exists() and port_closed()
    command(PG / "initdb.exe", "-D", DATA, "-U", USER, "-A", "trust",
            "--encoding=UTF8", "--locale=C")
    command(PG / "pg_ctl.exe", "-D", DATA, "-l", DATA / "server.log", "-o",
            f"-p {PORT} -h 127.0.0.1 -c fsync=on -c synchronous_commit=on", "-w", "start")
    with psycopg.connect(BASE_URI, autocommit=True) as conn:
        assert conn.execute("SHOW fsync").fetchone()[0] == "on"
        assert conn.execute("SHOW synchronous_commit").fetchone()[0] == "on"
        conn.execute(pgsql.SQL("CREATE DATABASE {} ").format(pgsql.Identifier(DB)))
    os.environ.update(DATABASE_URL=TEST_URI, SECRET_KEY="disposable-e4-causal-local-only",
                      DEBUG="False", ENVIRONMENT="dev", DISABLE_SENTRY="True",
                      SENTRY_DSN="", REDIS_URL="", DISCORD_WEBHOOK_URL="",
                      DJANGO_SETTINGS_MODULE="config.settings")
    sys.path.insert(0, str(ROOT / "backend"))
    import django
    django.setup()
    from django.core.management import call_command
    call_command("migrate", interactive=False, verbosity=0)
    return django


def percentile(values, proportion):
    ordered = sorted(values)
    return ordered[math.ceil(proportion * (len(ordered) - 1))]


def nodes(root):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.get("Plans", []))


def install_data(orgs, channels, contacts, label, conversations, messages,
                 noise=0, due_work=0, active_orgs=3, layout="clustered"):
    from django.db import connection, transaction
    from django.utils import timezone
    from apps.agent.models import Conversation, TurnWork
    from apps.channels.models import Message

    assert conversations >= 100 and messages >= conversations
    assert 0 <= noise <= conversations - 60
    assert 0 <= due_work <= 50
    assert 1 <= active_orgs <= 3
    assert layout in ("clustered", "spread")
    fixed = timezone.now() - timedelta(minutes=3)
    targets = [0, 1, 2] + list(range(3, 3 + noise)) + [conversations - 1]
    max_stride = (messages - conversations) // conversations
    positions = {}
    for rank, conv_index in enumerate(targets):
        stride = (round(rank * max_stride / (len(targets) - 1))
                  if layout == "spread" else 0)
        position = conv_index + stride * conversations
        assert position < messages and position not in positions
        positions[position] = conv_index
    future_position = next(position for position, conv_index in positions.items()
                           if conv_index == conversations - 1)
    with transaction.atomic():
        conversation_rows = []
        for i in range(conversations):
            if active_orgs == 3:
                org_index = i if i < 2 else 2
            else:
                org_index = i % active_orgs
            conversation_rows.append(Conversation(
                organization=orgs[org_index], channel_account=channels[org_index],
                contact=contacts[org_index],
                last_activity_at=fixed - timedelta(seconds=conversations - i),
            ))
        created_conversations = Conversation.all_objects.bulk_create(conversation_rows, batch_size=500)
        message_rows = []
        for i in range(messages):
            conv_index = i % conversations
            conv = created_conversations[conv_index]
            pending = i in positions
            availability = (fixed + timedelta(milliseconds=500)
                            if i == future_position
                            else fixed - timedelta(seconds=2))
            message_rows.append(Message(
                organization_id=conv.organization_id, channel_account_id=conv.channel_account_id,
                conversation_id=conv.pk, contact_id=conv.contact_id,
                direction="in", author_type="client", body="synthetic",
                status="pending" if pending else "processed", available_at=availability,
            ))
        created_messages = Message.all_objects.bulk_create(message_rows, batch_size=500)
        # Three completed works establish a non-null last-claim ordering in each org.
        completed_indices = [conversations - 54, conversations - 53, conversations - 52]
        completed = []
        for rank, idx in enumerate(completed_indices):
            conv, anchor = created_conversations[idx], created_messages[idx]
            completed.append(TurnWork(
                organization_id=conv.organization_id, conversation_id=conv.pk,
                anchor_message_id=anchor.pk, anchor_created_at=anchor.created_at,
                cursor_message_id=anchor.pk, cursor_created_at=anchor.created_at,
                context_at=fixed, clinic_timezone="UTC", status="COMPLETED",
                claimed_at=fixed - timedelta(seconds=60 - rank * 10),
                completed_at=fixed - timedelta(seconds=50 - rank * 10),
                outcome_code="synthetic",
            ))
        pending = []
        for rank, idx in enumerate(range(conversations - 51, conversations - 1)):
            conv, anchor = created_conversations[idx], created_messages[idx]
            pending.append(TurnWork(
                organization_id=conv.organization_id, conversation_id=conv.pk,
                anchor_message_id=anchor.pk, anchor_created_at=anchor.created_at,
                cursor_message_id=anchor.pk, cursor_created_at=anchor.created_at,
                context_at=fixed, clinic_timezone="UTC", status="PENDING",
                next_attempt_at=(fixed - timedelta(seconds=1) if rank < due_work
                                 else fixed + timedelta(days=1)),
            ))
        works = TurnWork.all_objects.bulk_create(completed + pending, batch_size=500)
        anchor_updates = []
        for idx, work in zip(completed_indices + list(range(conversations - 51, conversations - 1)), works):
            anchor = created_messages[idx]
            anchor.turn_work_id = work.pk
            anchor_updates.append(anchor)
        Message.all_objects.bulk_update(anchor_updates, ["turn_work"], batch_size=500)
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE agent_conversation")
        cursor.execute("ANALYZE channels_message")
        cursor.execute("ANALYZE agent_turnwork")
        cursor.execute("SELECT count(*) FROM agent_conversation")
        assert cursor.fetchone()[0] == conversations
        cursor.execute("SELECT count(*) FROM channels_message")
        assert cursor.fetchone()[0] == messages
    return fixed, created_conversations[0].pk


def measure(label, clock, claim_conv_id, counts):
    from django.db import connection, transaction
    from django.test.utils import CaptureQueriesContext
    from apps.agent.worker import _pending_conversation_candidates
    from apps.agent.durable import claim_turn

    selector_ms, sql_text, selected = [], None, None
    for repeat in range(20):
        with CaptureQueriesContext(connection) as captured:
            begin = time.perf_counter()
            value = list(_pending_conversation_candidates(now=clock))
            elapsed = (time.perf_counter() - begin) * 1000
        selector_ms.append(elapsed)
        if sql_text is None:
            assert len(captured.captured_queries) == 1
            sql_text = captured.captured_queries[0]["sql"]
            selected = value
        else:
            assert value == selected
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN (FORMAT JSON) " + sql_text)
        estimated = cursor.fetchone()[0][0]
        cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql_text)
        measured = cursor.fetchone()[0][0]
    message_nodes = [
        {"type": n["Node Type"], "loops": n.get("Actual Loops"),
         "rows_per_loop": n.get("Actual Rows"), "hit": n.get("Shared Hit Blocks"),
         "read": n.get("Shared Read Blocks"), "time_per_loop_ms": n.get("Actual Total Time")}
        for n in nodes(measured["Plan"])
        if n.get("Relation Name") == "channels_message"
    ]
    with transaction.atomic():
        with CaptureQueriesContext(connection) as captured_claim:
            begin = time.perf_counter()
            witness = claim_turn(claim_conv_id, eligible_at=clock)
            claim_ms = (time.perf_counter() - begin) * 1000
        assert witness is not None
        claim_query_count = len(captured_claim.captured_queries)
        claim_query_ms = [float(q["time"]) * 1000 for q in captured_claim.captured_queries]
        transaction.set_rollback(True)
    return {
        "label": label, **counts, "selector_query_count": 1,
        "selector_wall_ms": {"p50": percentile(selector_ms, .5),
                             "p95": percentile(selector_ms, .95), "max": max(selector_ms)},
        "selector_sql": sql_text if label == "A-c354-m354" else None,
        "selected_candidate_ids": selected,
        "explain_estimate": estimated,
        "explain_analyze_execution_ms": measured["Execution Time"],
        "explain_analyze_planning_ms": measured["Planning Time"],
        "message_nodes": message_nodes,
        "claim_query_count": claim_query_count,
        "claim_wall_ms": claim_ms,
        "claim_query_ms": claim_query_ms,
    }


def cleanup():
    from django.db import connections
    connections.close_all()
    with psycopg.connect(BASE_URI, autocommit=True) as conn:
        clients = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (DB,)).fetchone()[0]
        waiting = conn.execute("SELECT count(*) FROM pg_locks WHERE NOT granted").fetchone()[0]
        prepared = conn.execute("SELECT count(*) FROM pg_prepared_xacts").fetchone()[0]
        assert clients == waiting == prepared == 0
        conn.execute(pgsql.SQL("DROP DATABASE {}").format(pgsql.Identifier(DB)))
    command(PG / "pg_ctl.exe", "-D", DATA, "-m", "fast", "-w", "stop")
    assert DATA.resolve().parent == Path(r"C:\Users\LAP\AppData\Local\Temp").resolve()
    import shutil
    shutil.rmtree(DATA)
    assert not DATA.exists() and port_closed()
    return {"clients": clients, "waiting_locks": waiting, "prepared_transactions": prepared,
            "database_dropped": DB, "port_closed": True, "data_dir_removed": True}


def main():
    start()
    from django.db import connection, transaction
    from apps.agent.tests.test_b9a_e2e import seed_domain
    fixtures = [seed_domain("CAUSAL" + str(i)) for i in range(3)]
    orgs = [row[0] for row in fixtures]
    channels = [row[1] for row in fixtures]
    contacts = [row[4] for row in fixtures]
    points = [
        (f"A-c354-m{m}", 354, m, 0, 0, 3) for m in (354, 708, 3540, 10000)
    ] + [
        (f"B-c{c}-m3540", c, 3540, 0, 0, 3) for c in (100, 354, 708, 1416)
    ] + [
        (f"C-noise{n}", 354, 3540, n, 0, 3) for n in (0, 30, 100, 200)
    ] + [
        (f"E-due{n}", 354, 3540, 0, n, 3) for n in (0, 10, 25, 50)
    ] + [
        (f"F-org{n}", 354, 3540, 0, 0, n) for n in (1, 2, 3)
    ]
    layout_mode = "--layout-matrix" in sys.argv
    if layout_mode:
        points = [
            (f"G-{layout}-{iteration}", 354, 10000, 200, 0, 3, layout)
            for iteration in (1, 2)
            for layout in ("clustered", "spread")
        ]
    else:
        points = [(*point, "clustered") for point in points]
    out_path = (OUT.with_name("vet-e4-causal-6e59-layout.json")
                if layout_mode else OUT)
    result = {"schema": "e4-causal-sql-microbenchmark-v1",
              "head": "6e59f6c05514ad6eca0985796e538de4fd749560",
              "not_profile_beta_1": True, "database": DB, "port": PORT,
              "fsync": "on", "synchronous_commit": "on", "points": []}
    try:
        for label, c, m, noise, due, active, layout in points:
            # Roll back the entire synthetic cohort, preserving B3 immutability.
            with transaction.atomic():
                fixed, claim_id = install_data(orgs, channels, contacts, label, c, m,
                                               noise, due, active, layout)
                entry = measure(label, fixed, claim_id, {
                    "conversations": c, "messages": m, "noisy_pending": noise,
                    "due_turnworks": due, "ineligible_turnworks": 50 - due,
                    "active_organizations": active, "layout": layout,
                })
                transaction.set_rollback(True)
            with connection.cursor() as cursor:
                cursor.execute("VACUUM ANALYZE agent_conversation, channels_message, agent_turnwork")
            result["points"].append(entry)
            out_path.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
            print(json.dumps({"point": label, "sql_ms": entry["explain_analyze_execution_ms"],
                              "bitmap": [n for n in entry["message_nodes"] if n["type"] == "Bitmap Heap Scan"]}), flush=True)
    finally:
        result["cleanup"] = cleanup()
        out_path.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPLETE", "points": len(result["points"]),
                      "output": str(out_path)}), flush=True)


if __name__ == "__main__":
    main()
