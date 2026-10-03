"""Environment and logging wrapper; invokes the frozen acceptance programs."""

import argparse
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
PORT = 35443
PREFIX = "test_b8b_pb1sql_"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.database.startswith(PREFIX):
        raise ValueError("Only the isolated PROFILE test databases are allowed")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise ValueError("Missing command")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    if args.log.exists() or args.log.with_suffix(".exit.json").exists():
        raise FileExistsError("Refusing to overwrite an evaluation receipt")
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("E4_", "B8", "B9", "W1_")):
            env.pop(key)
    env.update(
        DATABASE_URL=f"postgresql://b9e@127.0.0.1:{PORT}/{args.database}",
        SECRET_KEY=secrets.token_urlsafe(48),
        DEBUG="False", ENVIRONMENT="dev", DISABLE_SENTRY="True",
        SENTRY_DSN="", REDIS_URL="", DISCORD_WEBHOOK_URL="",
        HEALTHCHECK_AGENT_WORKER_URL="", HEALTHCHECK_AGENT_SENDER_URL="",
        PYTHONIOENCODING="utf-8", DJANGO_SETTINGS_MODULE="config.settings",
    )
    started = datetime.now(timezone.utc).isoformat()
    with args.log.open("w", encoding="utf-8") as log:
        result = subprocess.run([sys.executable, *command], cwd=BACKEND, env=env,
                                stdout=log, stderr=subprocess.STDOUT, check=False)
    finished = datetime.now(timezone.utc).isoformat()
    receipt = dict(database=args.database, command=command, started_utc=started,
                   finished_utc=finished, exit_code=result.returncode)
    args.log.with_suffix(".exit.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
