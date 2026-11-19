"""Validator split of absent `remove` overrides (Nov 10 2026).
Run: python3 -m pytest pipeline/tests/test_validate_overrides_20261110.py  (or python3 this file)"""
import os
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-no-calls")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import validate_obligations as V  # noqa: E402

Q = "the department shall submit a report every year to the mayor"
REP = {"action": "remove", "status": "already_absent", "quote_prefix": Q[:60]}


def test_cache_still_emits_is_working_remove():
    cache = {"1": [{"quote": Q + " and more"}]}
    assert V.classify_absent_remove("1", REP, cache) == "override_working_remove"


def test_cache_no_longer_emits_is_dead_remove():
    cache = {"1": [{"quote": "something else entirely"}]}
    assert V.classify_absent_remove("1", REP, cache) == "override_dead_remove"


def test_no_cache_keeps_already_absent():
    assert V.classify_absent_remove("1", REP, None) == "override_already_absent"
    assert V.classify_absent_remove("2", REP, {"1": []}) == "override_already_absent"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")
