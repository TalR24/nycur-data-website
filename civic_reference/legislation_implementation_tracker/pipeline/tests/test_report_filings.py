#!/usr/bin/env python3
"""Offline tests for the DORIS refresh: retry behaviour and the freshness check."""
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_report_filings as b  # noqa: E402


class Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body if body is not None else []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._b


class Fake:
    def __init__(self, seq):
        self.seq, self.calls = list(seq), 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        x = self.seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x


def test_retry_then_success():
    s = Fake([requests.ReadTimeout("t"), requests.ReadTimeout("t"), Resp(200, [{"a": 1}])])
    waits = []
    assert b.get_json("u", {}, session=s, sleep=waits.append) == [{"a": 1}]
    assert s.calls == 3 and waits == [5, 15]


def test_5xx_retried():
    s = Fake([Resp(503), Resp(200, [1])])
    assert b.get_json("u", {}, session=s, sleep=lambda w: None) == [1]
    assert s.calls == 2


def test_404_not_retried():
    s = Fake([Resp(404), Resp(200, [1])])
    try:
        b.get_json("u", {}, session=s, sleep=lambda w: None)
    except requests.HTTPError:
        pass
    else:
        raise AssertionError("404 should raise")
    assert s.calls == 1


def test_gives_up_after_retries():
    s = Fake([requests.ReadTimeout("t")] * b.RETRIES)
    try:
        b.get_json("u", {}, session=s, sleep=lambda w: None)
    except requests.Timeout:
        pass
    else:
        raise AssertionError("should raise after retries")
    assert s.calls == b.RETRIES


def test_paging_until_empty():
    row = {"agency": "A", "required_report_name": "R", "latest": "2026-01-02T00:00:00"}
    pages = [[row] * 5000, [row] * 3, []]
    seen = []
    got = b.fetch_grouped("x", get=lambda url, p: (seen.append(p["$offset"]), pages.pop(0))[1])
    assert len(got) == 1 and pages == [] and seen == [0, 5000, 10000]


def test_mandates_paged_until_empty():
    pages = [[{"n": i} for i in range(5000)], [{"n": 1}], []]
    got = b.fetch_all("m", {"$order": ":id"}, get=lambda url, p: pages.pop(0))
    assert len(got) == 5001 and pages == []


class BadJson(Resp):
    def json(self):
        raise ValueError("not json")


def test_non_json_200_and_chunked_retried():
    s = Fake([BadJson(200), requests.exceptions.ChunkedEncodingError("cut"), Resp(200, [7])])
    assert b.get_json("u", {}, session=s, sleep=lambda w: None) == [7]
    assert s.calls == 3


def test_overall_budget_stops_retries():
    clock = [0.0]
    b.set_budget(600, now=lambda: clock[0])
    s = Fake([requests.ReadTimeout("t")] * 4)
    def sl(w):
        clock[0] += 400
    try:
        b.get_json("u", {}, session=s, sleep=sl, now=lambda: clock[0])
    except (requests.Timeout, TimeoutError):
        pass
    else:
        raise AssertionError("should stop at the deadline")
    finally:
        b.set_budget(None)
    assert s.calls < 4


def test_regression_guard():
    assert b.regression_ok(591, 400)[0] is False
    assert b.regression_ok(591, 480)[0] is True
    assert b.regression_ok(None, 0)[0] is True


def test_freshness():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "report_filings.json"
        today = date(2026, 11, 10)
        p.write_text(json.dumps({"generated": (today - timedelta(days=40)).isoformat()}))
        assert b.check_fresh(p, today)[0] is False
        p.write_text(json.dumps({"generated": (today - timedelta(days=35)).isoformat()}))
        assert b.check_fresh(p, today)[0] is True
        p.write_text("{}")
        assert b.check_fresh(p, today)[0] is False


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v()
            n += 1
    print(f"{n} tests passed")
