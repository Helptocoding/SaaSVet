"""Record the frozen PROFILE contract and source lineage before the timed run."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RUNTIME = "38c4d458996435d6df56b1b337aeb8987fa1045a"
BASELINE = "08310461337a284386299ec47c54125f2139bf7f"
EXPECTED = {
    "backend/apps/agent/tests/b9e_profile.py": "a09b3318f27f1b2970270a03cb90f46034628d5af39e448b3baceabfdf53da75",
    "backend/apps/agent/tests/b9e_collect.py": "c75a1ba720f04f372a51b1de89dc9bf1ea3efb4127c2c591bc2ad56e79610e21",
    "docs/evals/profile-beta-1-methodology.md": "48251eca301620a5e9a1f8ce1cbde9cb20d5927b1de9fc77b76b79ba0eea12c0",
    "docs/evals/profile-beta-1-v1.json": "ff0834449d1915b395be58e7cdbab09e39917fe0ddf3cc90e3f187fdfdc9f311",
    "docs/evals/profile-beta-1-corpus-v1.json": "d2c5cc67ff651654dafb19b2c1eebf52aba08c55cb5fd9c2c76cf334d792330a",
    "docs/evals/b9e-corpus-selected.json": "8eb3013b81d6a3d984113c588a5642652ec4fa5b3dcddf465b95f44360f21409",
}


def git(*args):
    return subprocess.check_output(["rtk", "git", *args], cwd=ROOT, text=True).strip()


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    assert git("rev-parse", "HEAD") == BASELINE
    assert subprocess.run(["rtk", "git", "merge-base", "--is-ancestor", RUNTIME, "HEAD"], cwd=ROOT).returncode == 0
    changed_lines = git("diff", "--name-only", RUNTIME, "HEAD").splitlines()
    docs_changes = [path for path in changed_lines if path.startswith("docs/evals/")]
    assert docs_changes and all(not path or path.startswith("docs/evals/") or path == "Changes:"
                                for path in changed_lines)
    assert not git("diff", "--name-only", "--", "backend")
    comparisons = {path: dict(expected=expected, actual=digest(path), match=digest(path) == expected)
                   for path, expected in EXPECTED.items()}
    assert all(row["match"] for row in comparisons.values())
    prior = json.loads((ROOT / "docs/evals/profile-beta-1-e4-2026-10-01/preflight.json").read_text())
    changed_from_prior = [path for path, expected in prior["source_sha256"].items()
                          if not (ROOT / path).exists() or digest(path) != expected]
    assert changed_from_prior == ["backend/apps/agent/worker.py"]
    profile = json.loads((ROOT / "docs/evals/profile-beta-1-v1.json").read_text())
    selected = json.loads((ROOT / "docs/evals/b9e-corpus-selected.json").read_text())
    assert len(selected) == len(set(selected)) == 46
    out = dict(schema="profile-beta-1-e4-sql-preflight-v1", recorded_utc=datetime.now(timezone.utc).isoformat(),
               head_initial=BASELINE, profile_baseline_sha=BASELINE,
               e4_sql_runtime_sha=RUNTIME, e4_sql_docs_sha=BASELINE,
               post_runtime_changes=docs_changes, prior_source_comparison_count=len(prior["source_sha256"]),
               changed_from_prior=changed_from_prior, frozen_hashes=comparisons,
               canonical_test_count=46, profile_version=profile["schema_version"],
               topology=profile["topology"], workload=profile["base_workload"],
               canonical_gates=profile["canonical_gates"],
               read_call_discrepancy="The v1 JSON models one basic LLM call; unchanged documented runner and READ path make two real calls.",
               historical_profile="FAIL: B9E-LOAD-01-CLAIM healthy global p95 10.015949 s, n=60, missing=0",
               historical_b9e="FAIL", b9="IN_PROGRESS", drift_detected=False)
    target = OUT / "preflight.json"
    if target.exists():
        raise FileExistsError(target)
    target.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(baseline=BASELINE, frozen_hashes_match=True,
                          prior_source_count=len(prior["source_sha256"]),
                          only_changed_source=changed_from_prior, canonical_tests=len(selected))))


if __name__ == "__main__":
    main()
