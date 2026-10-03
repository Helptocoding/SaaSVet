"""Read-only closure audit of the frozen E4 SQL PROFILE-BETA-1 receipts."""

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SCENARIOS = ("base", "blocked_llm", "meta_slow", "duplicate", "saturation")


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def write(name, value):
    (HERE / name).write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def plan_nodes(root):
    nodes = [root]
    while nodes:
        node = nodes.pop()
        yield node
        nodes.extend(node.get("Plans", []))


def verify_frozen():
    preflight = read("preflight.json")
    actual = {}
    for name, receipt in preflight["frozen_hashes"].items():
        digest = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        assert digest == receipt["expected"], name
        actual[name] = digest
    assert preflight["drift_detected"] is False
    assert preflight["changed_from_prior"] == ["backend/apps/agent/worker.py"]
    return actual


def main():
    frozen = verify_frozen()
    corpus = read("corpus-decision.json")
    assert corpus["status"] == "PASS"
    assert (corpus["unique_selected"], corpus["unique_passed"]) == (46, 46)
    assert not any(corpus[key] for key in ("failed_ids", "missing_ids", "failures", "errors", "skips", "xfail"))
    critical = read("critical-metrics.json")
    asserted_ids = {
        identifier for group in corpus["by_canonical_id"].values()
        for identifier, item in group.items() if item["status"] == "PASS"
    }
    assert all(value == 0 for value in critical["values"].values())
    assert all(set(ids) <= asserted_ids for ids in critical["corpus_evidence_ids"].values())
    assert read("cleanup.json")["status"] == "CLEANED"
    assert read("server-exit.json")["exit_code"] == 0
    scenarios = {}
    for name in SCENARIOS:
        profile = read(name + ".json")
        detail = read(name + "-diagnostics.json")
        exit_receipt = read(name + "-driver.exit.json")
        assert profile["scenario"] == detail["scenario"] == name
        assert profile["technical_pass"] is True
        assert profile["gates"] and all(profile["gates"].values())
        assert profile["profile_version"] == "profile-beta-1-v1"
        assert profile["warmup_seconds"] == 30 and profile["measurement_seconds"] == 300
        assert profile["smoke_only"] is False
        assert exit_receipt["exit_code"] == 0
        assert detail["healthy_missing"] == 0
        assert profile["max_active_per_org_observed"] <= 1
        assert detail["ready_reextensions"] == 0
        assert all(value == 0 for value in detail["critical_sql"].values())
        if name in ("base", "blocked_llm"):
            assert profile["healthy_claim"]["p95_seconds"] <= 10
            assert profile["safety_dispatch"]["p95_seconds"] <= 5
        if name == "base":
            assert profile["outbox_dispatch"]["p95_seconds"] <= 5
        message_scans = [
            {"node": node["Node Type"], "loops": node.get("Actual Loops"),
             "rows": node.get("Actual Rows")}
            for node in plan_nodes(detail["explain"]["Plan"])
            if node.get("Relation Name") == "channels_message"
        ]
        large_scans = [
            scan for scan in message_scans
            if scan["node"] == "Seq Scan" and scan["rows"] and scan["rows"] >= 20
        ]
        assert large_scans and all(scan["loops"] == 1 for scan in large_scans)
        org = detail["organizations"]
        scenarios[name] = {
            "gates": profile["gates"],
            "healthy_global": detail["healthy"],
            "healthy_missing": detail["healthy_missing"],
            "safety": profile["safety_dispatch"],
            "outbox": profile["outbox_dispatch"],
            "selector_sql_ms": detail["selector_sql_ms"],
            "explain_execution_ms": detail["explain"]["Execution Time"],
            "message_scan_nodes": message_scans,
            "ready_reextensions": detail["ready_reextensions"],
            "availability_updates_observed": detail["availability_updates_observed"],
            "critical_sql": detail["critical_sql"],
            "budget": detail["budget"],
            "orgs": [{key: item[key] for key in (
                "org_index", "inbound_n", "missing", "ordinary_persisted_to_eligible",
                "ordinary_eligible_to_claim", "ordinary_persisted_to_claim",
                "all_persisted_to_claim", "pending_inbound", "oldest_pending_age_seconds",
                "claims_total", "calls", "works", "deferrals", "joined_READY"
            )} for item in org],
            "max_active_per_org_observed": profile["max_active_per_org_observed"],
            "max_pending_inbound_sample": profile["max_pending_inbound_observed"],
            "turnwork_status_at_close": profile["turnwork_status"],
            "outbound_status_at_close": profile["outbound_status"],
            "duplicates_sent": profile["generator_events"]["duplicates"],
            "generator_errors": profile["generator_events"]["errors"],
        }
    assert scenarios["duplicate"]["duplicates_sent"] == 17
    assert all(not item["generator_errors"] for item in scenarios.values())
    base = scenarios["base"]
    assert abs(10 - base["healthy_global"]["p95"] - 0.18046) < 1e-9
    rows = re.findall(r"(?m)^\|\s*(\d+)\s*\|", (HERE / "report.md").read_text(encoding="utf-8"))
    assert [int(row) for row in rows] == list(range(1, 80))
    write("evaluation-summary.json", {
        "schema": "profile-beta-1-e4-sql-evaluation-summary-v1",
        "profile_result": "PROFILE_BETA_1_PASS",
        "profile_baseline_sha": read("preflight.json")["profile_baseline_sha"],
        "e4_sql_runtime_sha": read("preflight.json")["e4_sql_runtime_sha"],
        "frozen_hashes": frozen,
        "corpus": {key: corpus[key] for key in (
            "status", "unique_selected", "unique_passed", "failures", "errors", "skips", "xfail"
        )},
        "scenarios": scenarios,
        "scope": "Local frozen synthetic evaluation; not a production measurement",
    })
    # Only synthetic receipts and test logs are scanned; no production credentials are read.
    examined = 0
    hits = []
    secret_pattern = re.compile(r"(?i)\b(?:Bearer\s+[A-Za-z0-9._-]{12,}|sk-[A-Za-z0-9_-]{16,}|-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----)\b")
    for path in HERE.iterdir():
        if path.suffix not in (".json", ".jsonl", ".log", ".md"):
            continue
        examined += 1
        content = path.read_text(encoding="utf-8", errors="replace")
        if secret_pattern.search(content):
            hits.append(path.name)
    assert not hits, hits
    write("privacy.json", {
        "scope": "Synthetic local fixtures and numeric evaluation receipts only",
        "files_scanned": examined,
        "credential_pattern_hits": hits,
        "raw_sql_persisted_by_observer": False,
        "production_traffic_or_credentials_used": False,
        "limitation": "Pattern scan and controlled harness are not a universal proof about other files or systems",
    })
    print(json.dumps({"status": "PASS", "scenarios": list(scenarios),
                      "corpus_pass": corpus["unique_passed"], "privacy_files": examined}))


if __name__ == "__main__":
    main()
