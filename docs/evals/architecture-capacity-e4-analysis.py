"""Offline derivation from closed E4 evidence; never imports runtime or opens a DB.

Run from any directory with Python 3.11+: python <absolute path to this file>.
The output is diagnostic evidence, not a new load run or acceptance receipt.
"""

import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "docs/evals"
BASELINE_HEAD = "4adcb4ad3cca768ddde7ee7be54a4cc37426e78d"
INPUTS = set()


def read_json(name):
    path = EVALS / name
    INPUTS.add(path)
    return json.loads(path.read_text(encoding="utf-8"))


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        **{f"p{int(q * 100)}": values[math.ceil((len(values) - 1) * q)]
           for q in (0.5, 0.75, 0.9, 0.95, 0.99)},
        "min": values[0],
        "max": values[-1],
    }


out = {
    "schema": "architecture-capacity-e4-offline-v1",
    "classification": "DIAGNOSTIC_ONLY_NO_NEW_RUN",
    "baseline_documentary_head": BASELINE_HEAD,
    "candidate_runtime_head": "7e5aa9e8cec4f6fa08ecd92870c19560c91bb469",
    "method": {
        "quantile": "higher: sorted[ceil((n-1)*q)]",
        "organization": "fixture rank 0=healthy-1, 1=healthy-2, 2=noisy; not database PK",
        "latency_cohort": "measurement-window Message cohort with a claim in the closed collection",
        "noisy_censoring": "unclaimed noisy arrivals absent; never treat selected tail as all 300 arrivals",
        "T0": "Message.created_at, not an exact ingestion commit timestamp",
        "T1": "final Message.available_at, after any preclaim extensions",
        "gate": "original 60 healthy Messages including 20 immediate safety; threshold 10 seconds",
        "service_cohort": "baseline ordinary works whose claim-return marker falls in the 300 s measurement window; completion may be in drain",
        "service_proxy": "finalize_end minus claim_commit journal return markers; not exact DB slot occupancy",
        "service_rates": "inverse mean observed service proxy, not achieved throughput or a stochastic queue fit",
        "log_timestamps": "not used; log fields used only to map work IDs to fixture organization rank",
        "postfix_service_limitation": "closed collection has aggregate durable service only; no per-org exact service reconstructed",
        "no_percentile_addition": True,
    },
    "scenarios": {},
}

for scenario in ("diagnostic-baseline", "postfix-base", "postfix-blocked_llm"):
    receipt = read_json(f"e4-{scenario}.json")
    data = read_json(f"e4-{scenario}.analysis.json")
    samples = data["timing_samples"]
    healthy = [s for s in samples if s["organization"] < 2]
    ordinary_healthy = [s for s in healthy if s["ordinary"]]
    assert len(healthy) == 60 and len(ordinary_healthy) == 40
    scenario_out = {
        "healthy_gate": distribution(s["claimed_at"] - s["T0"] for s in healthy),
        "ordinary_healthy": distribution(s["claimed_at"] - s["T0"] for s in ordinary_healthy),
        "healthy_over_10_count": sum(s["claimed_at"] - s["T0"] > 10 for s in healthy),
        "ordinary_over_10_count": sum(s["claimed_at"] - s["T0"] > 10 for s in ordinary_healthy),
        "ordinary_eligibility_over_10_count": sum(s["T1"] - s["T0"] > 10 for s in ordinary_healthy),
        "ordinary_over_10_without_eligibility_over_10_count": sum(
            s["claimed_at"] - s["T0"] > 10 and s["T1"] - s["T0"] <= 10
            for s in ordinary_healthy),
        "ordinary_remaining_budget_after_final_eligibility": distribution(
            10 - (s["T1"] - s["T0"]) for s in ordinary_healthy),
        "durable_service_all_run": data["service"]["claim_to_completion"],
        "calls_per_work_all_run": data["service"]["calls_per_work"],
        "stage_distributions_from_source": data["distributions"],
        "organizations": [],
    }
    for rank in range(3):
        rows = [s for s in samples if s["organization"] == rank and s["ordinary"]]
        scenario_out["organizations"].append({
            "fixture_rank": rank,
            "ordinary_claimed_members": len(rows),
            "distinct_work_ids_in_message_cohort": len({s["work"] for s in rows}),
            "persisted_to_final_eligible": distribution(s["T1"] - s["T0"] for s in rows),
            "final_eligible_to_claim": distribution(s["claimed_at"] - s["T1"] for s in rows),
            "persisted_to_claim": distribution(s["claimed_at"] - s["T0"] for s in rows),
        })
    if scenario == "diagnostic-baseline":
        start, end = [datetime.fromisoformat(t).timestamp() for t in receipt["window_utc"]]
        assert end - start == 300
        events_by_work = defaultdict(list)
        work_org = {}
        for role in ("planner-1", "planner-2"):
            for event in read_json(f"e4-{scenario}-{role}.timing.json")["events"]:
                if event.get("work"):
                    events_by_work[event["work"]].append(event)
            log = EVALS / f"e4-{scenario}-{role}.log"
            INPUTS.add(log)
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("turn_work_id") and event.get("organization_id"):
                    work_org[event["turn_work_id"]] = receipt["fixture_organization_ids"].index(event["organization_id"])
        assert len(work_org) == 166
        capacity = []
        for rank in range(3):
            durations = []
            completed_in_window = 0
            for work, events in events_by_work.items():
                if work_org.get(work) != rank:
                    continue
                claims = [e["time"] for e in events if e["event"] == "claim_commit"]
                ends = [e["time"] for e in events if e["event"] == "finalize_end"]
                calls = [e for e in events if e["event"] == "llm_dispatch"]
                assert len(claims) == len(ends) == 1 and len(calls) == 2
                if start <= claims[0] < end:
                    durations.append(ends[0] - claims[0])
                if start <= ends[0] < end:
                    completed_in_window += 1
            mean_service = statistics.mean(durations)
            lambda_raw = 0.1 if rank < 2 else 1.0
            lambda_ordinary = 20 / 300 if rank < 2 else 1.0
            ordinary_messages = [s for s in samples if s["organization"] == rank and s["ordinary"]]
            observed_jobs = len({s["work"] for s in ordinary_messages})
            capacity.append({
                "fixture_rank": rank,
                "measurement_seconds": end - start,
                "lambda_all_messages_per_s": lambda_raw,
                "lambda_ordinary_input_per_s": lambda_ordinary,
                "lambda_safety_input_per_s": 10 / 300 if rank < 2 else 0,
                "observed_claimed_message_cohort_work_rate_per_s": observed_jobs / 300,
                "message_cohort_work_rate_is_arrival_rate_estimate": rank < 2,
                "coalescence_and_window_boundary_limit": True,
                "service_proxy": distribution(durations),
                "mu_service_proxy_per_s": 1 / mean_service,
                "rho_ordinary_uncoalesced": lambda_ordinary * mean_service,
                "rho_raw_if_every_message_were_read_work": lambda_raw * mean_service,
                "rho_observed_coalesced_healthy_only": observed_jobs / 300 * mean_service if rank < 2 else None,
                "completions_in_measurement": completed_in_window,
                "achieved_completion_throughput_per_s": completed_in_window / 300,
                "arrival_to_departure_ratio_not_utilization": lambda_ordinary / (completed_in_window / 300),
            })
        scenario_out["observed_capacity"] = capacity
        extended = next(s for s in ordinary_healthy if s.get("eligibility_extended_after_observation"))
        same_work = sorted((s for s in samples if s["work"] == extended["work"]), key=lambda s: s["T0"])
        origin = same_work[0]["T0"]
        scenario_out["exact_extension"] = {
            "origin_unix": origin,
            "fixture_rank": extended["organization"],
            "turn_work": extended["work"],
            "members": [{
                "message_id": s["id"],
                **{k: s[k] - origin for k in ("T0", "T1", "claimed_at", "first_eligible_observation", "T2", "T3", "T4", "T5", "T6")},
            } for s in same_work],
            "initial_available_at": None,
            "initial_deadline_limitation": "not retained; first eligible observation proves readiness before later ingestion",
        }
    out["scenarios"][scenario] = scenario_out

out["noisy_ideal_capacity_bound"] = {
    "calls_per_read": 2,
    "latency_per_llm_s": 0.5,
    "read_latency_s": 0.1,
    "N": 1,
    "minimum_service_s_excluding_local_work_and_polling": 1.1,
    "maximum_mu_per_s": 1 / 1.1,
    "lambda_per_s": 1,
    "minimum_rho": 1.1,
    "stable_at_offered_load": False,
    "healthy_slo_impossibility_proven": False,
}

# Hash frozen authority, runtime trace sources, and historical acceptance evidence.
for relative in (
    "docs/plan-implementacion-auditoria-agente-whatsapp-2026-09md",
    "docs/contrato-trabajo-durable-b3.md",
    "docs/contrato-presupuesto-turnwork-b9b.md",
    "docs/contrato-concurrencia-b9c.md",
    "docs/contrato-matter-binding-b6md",
    "docs/modules/agent.md",
    "docs/implementacion-b1-agente-whatsapp-2026-09-14.md",
    "docs/mapa-interno-b9-2026-09-26.md",
    "docs/reporte-aceptacion-b9-profile-beta-1-2026-09-29.md",
    "docs/diagnostico-e4-capacidad-scheduling-2026-09-30.md",
    "backend/apps/agent/services.py",
    "backend/apps/agent/worker.py",
    "backend/apps/agent/durable.py",
    "backend/apps/agent/turn_context.py",
    "backend/apps/agent/models.py",
    "backend/apps/channels/models.py",
    "backend/apps/channels/migrations/0012_b3_scope_and_membership.py",
    "backend/apps/agent/management/commands/run_agent_worker.py",
    "backend/apps/agent/tests/test_w1_experience.py",
    "backend/apps/agent/tests/b9e_profile.py",
):
    INPUTS.add(ROOT / relative)
for pattern in ("e4-*", "b9e-*", "profile-beta-1*"):
    INPUTS.update(p for p in EVALS.glob(pattern) if p.is_file())
out["source_sha256"] = {
    p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(INPUTS)
}
target = EVALS / "architecture-capacity-e4-analysis.json"
target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({
    "output": target.relative_to(ROOT).as_posix(),
    "source_hash_count": len(INPUTS),
    "healthy_over_10": {name: data["healthy_over_10_count"] for name, data in out["scenarios"].items()},
    "ordinary_over_10_without_eligibility_over_10": {
        name: data["ordinary_over_10_without_eligibility_over_10_count"]
        for name, data in out["scenarios"].items()},
    "capacity": out["scenarios"]["diagnostic-baseline"]["observed_capacity"],
}, ensure_ascii=False))
