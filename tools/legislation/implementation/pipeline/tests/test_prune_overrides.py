"""Pruning rules for record_overrides.json, on small fixtures (Nov 10 2026).
Run: python3 -m pytest pipeline/tests/test_prune_overrides.py  (or python3 this file)"""
import os
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-no-calls")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import prune_overrides as P  # noqa: E402

Q = "the department shall submit a report every year to the mayor"


def rec(mid, quote, agency="DOT"):
    return {"matter_id": mid, "obligation_id": f"{mid}-01", "quote": quote, "agency": agency}


def ov(mid, action, quote=Q, agency="DOT"):
    return {mid: {"set": [], "remove": [], "add": [], action: [
        {"quote_prefix": quote[:60], "agency": agency, "fields": {"recurrence": "annual"}}]}}


def versions(*row_lists):
    return [(f"v{i}", P.rows_by_matter(rows, [])) for i, rows in enumerate(row_lists)]


def test_absent_in_all_three_and_not_emitted_is_pruned():
    o = ov("1", "remove")
    p = P.plan(o, versions([], [], []), {"1": []})
    assert [x["matter_id"] for x in p["pruned"]] == ["1"]
    assert P.apply_prune(o, p["pruned"])["1"]["remove"] == []


def test_absent_only_in_current_is_kept():
    o = ov("1", "remove")
    p = P.plan(o, versions([], [rec("1", Q)], []), {"1": []})
    assert p["pruned"] == []


def test_producer_still_emits_is_kept():
    o = ov("1", "remove")
    p = P.plan(o, versions([], [], []), {"1": [rec("1", Q.upper())]})
    assert p["pruned"] == [] and p["kept_already_absent"]


def test_no_cache_is_kept():
    o = ov("1", "remove")
    assert P.plan(o, versions([], [], []), None)["pruned"] == []


def test_ambiguous_is_kept_and_queued():
    o = ov("1", "remove", agency=None)
    rows = [rec("1", Q, "DOT"), rec("1", Q, "DEP")]
    p = P.plan(o, versions(rows, rows, rows), {"1": []})
    assert p["pruned"] == [] and [q["class"] for q in p["queue"]] == ["ambiguous"]


def test_applying_entry_is_kept():
    o = ov("1", "remove")
    p = P.plan(o, versions([rec("1", Q)], [rec("1", Q)], [rec("1", Q)]), {"1": []})
    assert p["pruned"] == [] and p["queue"] == [] and p["counts"] == {"applies": 1}


def test_stale_set_is_queued_never_pruned():
    o = ov("1", "set")
    p = P.plan(o, versions([], [], []), {"1": []})
    assert p["pruned"] == [] and [q["class"] for q in p["queue"]] == ["stale"]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
