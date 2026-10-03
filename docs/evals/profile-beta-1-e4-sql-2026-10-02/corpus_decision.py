"""Reconcile the complete frozen corpus with the acceptance runner journal."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    selected = read(ROOT / "docs/evals/b9e-corpus-selected.json")
    frozen = read(ROOT / "docs/evals/profile-beta-1-corpus-v1.json")
    inventory = read(OUT / "corpus-canonical.results.inventory.json")
    results = read(OUT / "corpus-canonical.results.json")
    exit_receipt = read(OUT / "corpus-canonical.exit.json")
    journal = [json.loads(line) for line in
               (OUT / "corpus-canonical.results.passed.jsonl").read_text(encoding="utf-8").splitlines()]
    actual = {row["test_id"] for row in journal if row["status"] == "ok"}
    expected = set(selected)
    assert len(selected) == len(expected) == 46
    assert len(inventory) == len(set(inventory)) == 46 and set(inventory) == expected
    assert len(journal) == len(actual) == 46 and actual == expected
    assert results["tests"] == 46 and set(results["test_ids"]) == expected
    assert not any(results[key] for key in ("failures", "errors", "skips", "xfail", "failed_ids"))
    assert results["exit_code"] == exit_receipt["exit_code"] == 0
    canonical = {}
    for section in ("application_e2e", "cross_component", "failure_injection"):
        canonical[section] = {}
        for canonical_id, test_id in frozen[section].items():
            assert test_id in expected
            canonical[section][canonical_id] = dict(test_id=test_id, status="PASS")
    decision = dict(schema="profile-beta-1-e4-sql-corpus-decision-v1", status="PASS",
                    unique_selected=46, unique_passed=46, failed_ids=[], missing_ids=[],
                    failures=0, errors=0, skips=0, xfail=0,
                    canonical_id_references=sum(map(len, canonical.values())),
                    by_canonical_id=canonical,
                    frozen_corpus="docs/evals/profile-beta-1-corpus-v1.json",
                    selected_ids="docs/evals/b9e-corpus-selected.json",
                    runner_exit=0, seconds=results["seconds"])
    target = OUT / "corpus-decision.json"
    if target.exists():
        raise FileExistsError(target)
    target.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: decision[k] for k in ("status", "unique_selected", "unique_passed",
                                               "failures", "errors", "skips", "xfail")}))


if __name__ == "__main__":
    main()
