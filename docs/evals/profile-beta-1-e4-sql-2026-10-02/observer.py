"""Read-only SQL timing observer copied from the prior formal E4 profile."""

import datetime as dt
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


OUT = Path(__file__).resolve().parent
TEMP = Path(tempfile.gettempdir())
DATA = TEMP / "vet-profile-beta-1-e4-sql-20261002"
PG = TEMP / "vet-b8b-pg16-bin" / "pgsql" / "bin"
PORT = 35443


def server():
    # Raw SQL is consumed in memory only. No postmaster logfile, logging collector,
    # auto_explain or statement text is persisted by this observer.
    command_line = [str(PG / "postgres.exe"), "-D", str(DATA), "-p", str(PORT), "-h", "127.0.0.1",
        "-c", "logging_collector=off", "-c", "log_destination=stderr", "-c", "log_min_duration_statement=-1",
        "-c", "log_line_prefix=PB1|%m|%p|%d| ", "-c", "log_parameter_max_length=0",
        "-c", "log_parameter_max_length_on_error=0"]
    proc = subprocess.Popen(command_line, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    (OUT / "server-owner.json").write_text(json.dumps(
        {"observer_pid": os.getpid(), "postgres_pid": proc.pid, "port": PORT}))
    previous = None
    availability = {}
    with (OUT / "sql-observations.jsonl").open("x", encoding="utf-8", buffering=1) as target:
        def consume(record):
            if not record:
                return
            timestamp, pid, database, body = record
            duration = re.search(r"duration: ([0-9.]+) ms", body)
            if duration and "ROW_NUMBER()" in body and "agent_conversation" in body and "EXPLAIN" not in body:
                target.write(json.dumps(dict(event="selector_sql", timestamp=timestamp, pid=int(pid),
                    database=database, milliseconds=float(duration.group(1)))) + "\n")
            if duration and re.search(r'UPDATE "channels_message" SET "available_at"', body):
                value = re.search(r'"available_at" = \'([^\']+)\'', body)
                identifiers = re.search(r'"channels_message"\."id" IN \(([0-9, ]+)\)', body)
                if not identifiers:
                    identifiers = re.search(r'"channels_message"\."id" = ([0-9]+)', body)
                if value and identifiers:
                    new = dt.datetime.fromisoformat(value.group(1))
                    observed = dt.datetime.fromisoformat(timestamp.replace(" UTC", "+00:00"))
                    ids = [int(x.strip()) for x in identifiers.group(1).split(",")]
                    extended = []
                    for mid in ids:
                        old = availability.get((database, mid))
                        if old is not None and observed >= old and new > old:
                            extended.append(mid)
                        availability[(database, mid)] = new
                    target.write(json.dumps(dict(event="availability_update", timestamp=timestamp,
                        database=database, message_ids=ids, available_at=new.isoformat(),
                        ready_reextensions=extended)) + "\n")
        for line in proc.stdout:
            if line.startswith("PB1|"):
                consume(previous)
                bits = line.rstrip("\r\n").split("|", 4)
                previous = bits[1:]
            elif previous:
                previous[3] += line
        consume(previous)
    code = proc.wait()
    (OUT / "server-exit.json").write_text(json.dumps(
        {"exit_code": code, "raw_sql_persisted": False}))


if __name__ == "__main__":
    server()
