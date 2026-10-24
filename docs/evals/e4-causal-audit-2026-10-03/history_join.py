"""Read-only join of historical E4 claim samples and selector timing receipts."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(r"C:\Users\LAP\.codex\worktrees\e4-causal-audit-6e59\VeterinariaSaaS")
HERE = ROOT / "docs/evals/profile-beta-1-e4-2026-10-01"
DIAG = json.loads((HERE / "base-diagnostics.json").read_text())
SQL = [json.loads(line) for line in (HERE / "sql-observations.jsonl").read_text().splitlines()]
SQL = [row for row in SQL if row.get("event") == "selector_sql" and row.get("database") == "test_b8b_pb1e4_base"]


def timestamp(value):
    return datetime.fromisoformat(value.replace(" UTC", "+00:00"))


for row in SQL:
    row["when"] = timestamp(row["timestamp"])
work_role = {}
role_pid = {}
for role in ("planner-1", "planner-2"):
    path = HERE / f"base-{role}.log"
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("B9E_READY "):
            role_pid[role] = json.loads(line.split(" ", 1)[1])["backend_pid"]
            continue
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "AGENT_TURN_CLAIMED":
            work_role[event["turn_work_id"]] = role

samples = []
for org in DIAG["organizations"][:2]:
    for item in org["messages"]:
        created = timestamp(item["created_at"])
        available = timestamp(item["available_at"])
        claimed = timestamp(item["claimed_at"])
        role = work_role.get(item["work_id"])
        pid = role_pid.get(role)
        recent = [x for x in SQL if x["pid"] == pid and available <= x["when"] <= claimed]
        last = recent[-1] if recent else None
        samples.append({
            "org": org["org_index"], "work": item["work_id"], "role": role,
            "semantic": item["semantic_type"],
            "persisted_claim_s": round((claimed-created).total_seconds(),6),
            "persisted_eligible_s": round((available-created).total_seconds(),6),
            "eligible_claim_s": round((claimed-available).total_seconds(),6),
            "selector_count_since_eligible_on_claiming_pid": len(recent),
            "selector_ms_since_eligible_on_claiming_pid": round(sum(x["milliseconds"] for x in recent),3),
            "last_selector_ms": last["milliseconds"] if last else None,
            "last_selector_to_claim_s": round((claimed-last["when"]).total_seconds(),6) if last else None,
            "pre_last_selector_wait_s": round((last["when"]-timedelta(milliseconds=last["milliseconds"])-available).total_seconds(),6) if last else None,
        })
samples.sort(key=lambda x:x["persisted_claim_s"],reverse=True)
result = {"role_pid": role_pid, "matched_work": len(work_role),
          "healthy_samples": len(samples), "top10": samples[:10], "all_samples": samples}
Path(r"C:\Users\LAP\AppData\Local\Temp\vet-e4-causal-6e59-history.json").write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"healthy_samples": len(samples), "top3": samples[:3]}, indent=2))
