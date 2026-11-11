"""`keep` (remove) and `all` (set) override keys (Nov 10 2026).
Run: python3 -m pytest pipeline/tests/test_override_keep_all_20261110.py  (or python3 this file)"""
import os
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-no-calls")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extract_obligations as X  # noqa: E402

Q = "the commissioner shall submit to the mayor and post a report every year"


def _recs():
    return [{"obligation_id": f"9-0{i}", "quote": Q, "agency": "DOC"} for i in (1, 2, 3)]


def test_keep_one_removes_the_other_duplicates():
    ov = {"9": {"remove": [{"quote_prefix": Q[:40], "agency": "DOC", "keep": 1}]}}
    recs = _recs()
    _, rep = X.apply_record_overrides(recs, "9", ov)
    assert [r["obligation_id"] for r in recs] == ["9-01"] and rep == []


def test_keep_second():
    ov = {"9": {"remove": [{"quote_prefix": Q[:40], "agency": "DOC", "keep": 2}]}}
    recs = _recs()
    X.apply_record_overrides(recs, "9", ov)
    assert [r["obligation_id"] for r in recs] == ["9-02"]


def test_keep_single_candidate_is_noop_not_absent():
    ov = {"9": {"remove": [{"quote_prefix": Q[:40], "agency": "DOC", "keep": 1}]}}
    recs = _recs()[:1]
    _, rep = X.apply_record_overrides(recs, "9", ov)
    assert len(recs) == 1 and rep == []


def test_remove_without_keep_still_ambiguous():
    ov = {"9": {"remove": [{"quote_prefix": Q[:40], "agency": "DOC"}]}}
    recs = _recs()
    _, rep = X.apply_record_overrides(recs, "9", ov)
    assert len(recs) == 3 and rep[0]["status"] == "ambiguous"


def test_set_agency_all_applies_to_every_candidate():
    ov = {"9": {"set": [{"quote_prefix": Q[:40], "agency": "DOC",
                         "fields": {"agency": "DOC", "deadline_date": "2026-01-01"}, "all": True}]}}
    recs = _recs()
    _, rep = X.apply_record_overrides(recs, "9", ov)
    assert rep == [] and all(r["deadline_date"] == "2026-01-01" for r in recs)


def test_set_agency_without_all_is_ambiguous():
    ov = {"9": {"set": [{"quote_prefix": Q[:40], "agency": "DOC",
                         "fields": {"agency": "DOC", "deadline_date": "2026-01-01"}}]}}
    recs = _recs()
    _, rep = X.apply_record_overrides(recs, "9", ov)
    assert rep[0]["status"] == "ambiguous" and "deadline_date" not in recs[0]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")
