"""Execute the unchanged read-only collector from the prior formal profile."""

import ast
import datetime as dt
import hashlib
import json
import math
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "docs/evals/profile-beta-1-e4-2026-10-01/infrastructure-observer-source.txt"
BASELINE = "08310461337a284386299ec47c54125f2139bf7f"
PREFIX = "test_b8b_pb1sql_"
PORT = 35443
ENV = dict(os.environ, SECRET_KEY=secrets.token_urlsafe(48), DEBUG="False",
           ENVIRONMENT="dev", DISABLE_SENTRY="True", SENTRY_DSN="",
           REDIS_URL="", DISCORD_WEBHOOK_URL="", HEALTHCHECK_AGENT_WORKER_URL="",
           HEALTHCHECK_AGENT_SENDER_URL="", PYTHONIOENCODING="utf-8")
for key in list(ENV):
    if key.startswith(("E4_", "B8", "B9", "W1_")):
        ENV.pop(key)


def uri(database):
    return f"postgresql://b9e@127.0.0.1:{PORT}/{database}"


def immutable():
    head = subprocess.check_output(["rtk", "git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    assert head == BASELINE
    for relative, expected in {
        "backend/apps/agent/tests/b9e_profile.py": "a09b3318f27f1b2970270a03cb90f46034628d5af39e448b3baceabfdf53da75",
        "docs/evals/profile-beta-1-methodology.md": "48251eca301620a5e9a1f8ce1cbde9cb20d5927b1de9fc77b76b79ba0eea12c0",
        "docs/evals/profile-beta-1-v1.json": "ff0834449d1915b395be58e7cdbab09e39917fe0ddf3cc90e3f187fdfdc9f311",
    }.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def write(name, value):
    path = OUT / name
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "base"
    assert scenario in {"base", "blocked_llm", "meta_slow", "duplicate", "saturation"}
    source = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"distribution", "collect"}]
    assert {node.name for node in functions} == {"distribution", "collect"}
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    exec(compile(module, str(SOURCE), "exec"), globals())
    collect(scenario)
    from django.utils.dateparse import parse_datetime
    from apps.channels.models import Message

    receipt = json.loads((OUT / f"{scenario}.json").read_text(encoding="utf-8"))
    start, end = map(parse_datetime, receipt["window_utc"])
    outbounds = list(Message.objects.filter(
        direction="out", organization_id__in=receipt["fixture_organization_ids"],
        created_at__gte=start, created_at__lt=end))
    admitted = [(row.send_admitted_at - row.created_at).total_seconds()
                for row in outbounds if row.send_admitted_at]
    safety_rows = [row for row in outbounds
                   if row.semantic_type == Message.SEMANTIC_SAFETY_GUIDANCE]
    safety_admitted = [(row.send_admitted_at - row.created_at).total_seconds()
                       for row in safety_rows if row.send_admitted_at]
    assert distribution(admitted)["p95"] == receipt["outbox_dispatch"]["p95_seconds"]
    assert distribution(safety_admitted)["p95"] == receipt["safety_dispatch"]["p95_seconds"]
    write(f"{scenario}-dispatch-distributions.json", dict(
        boundary="Message(OUT).created_at to send_admitted_at in canonical measurement window",
        outbox=dict(**distribution(admitted), missing=len(outbounds) - len(admitted)),
        safety=dict(**distribution(safety_admitted), missing=len(safety_rows) - len(safety_admitted))))


if __name__ == "__main__":
    main()
