"""Plain test script, fakes only, no network: prints 'N passed, M failed'. Run: python3 tests/test_prepare_packets.py"""
import json, os, sys, tempfile
from datetime import date
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import next_packet_batch as nb


def law(y, n, signed="2026-10-01"):
    return {"key": "%d-S%d" % (y, n), "session": y, "print_no": "S%d" % n, "signed_date": signed}


def tree(d, laws, packets=(), texts=(), answers=()):
    d = Path(d)
    (d / "data" / "signed").mkdir(parents=True); (d / "packets" / "2025" / "results").mkdir(parents=True); (d / "text").mkdir()
    json.dump(laws, open(d / "data" / "signed" / "2025.json", "w"))
    for k in packets: (d / "packets" / "2025" / (k + ".txt")).write_text("x")
    for k in texts: (d / "text" / (k + ".txt")).write_text("t")
    for k in answers: (d / "packets" / "2025" / "results" / (k + ".json")).write_text("{}")
    return dict(sessions=(2025,), data_dir=d / "data", packets_dir=d / "packets", text_dir=d / "text", excluded=set())


def run():
    out = []
    laws = [law(2025, i) for i in range(1, 6)]
    with tempfile.TemporaryDirectory() as t:
        kw = tree(t, laws, packets=["2025-S1"], texts=["2025-S2"], answers=["2025-S3"])
        lack = nb.laws_lacking_packet(**kw)
        out.append([l["key"] for l in lack] == ["2025-S2", "2025-S4", "2025-S5"])      # packet or answer present: not lacking
        out.append([l["has_text"] for l in lack] == [True, False, False])
        calls, emitted = [], []
        def fetch(sess, pn):
            calls.append(pn)
            if pn == "S4": raise RuntimeError("network down")
            return True
        def emit(sess, ls): emitted.extend(l["key"] for l in ls); return len(ls)
        r = nb.prepare(fetch_text=fetch, emit=emit, **kw)
        out.append(calls == ["S4", "S5"])                                               # S2 already has text: no fetch
        out.append(emitted == ["2025-S2", "2025-S5"])                                   # the failed fetch does not stop the others
        out.append(r["prepared"] == 2 and r["not_fetched"] == 1)
        # an emit that raises is also contained
        def bad_emit(sess, ls): raise ValueError("boom")
        r = nb.prepare(fetch_text=lambda s, p: True, emit=bad_emit, **kw)
        out.append(r["prepared"] == 0 and r["not_fetched"] == 3)
    with tempfile.TemporaryDirectory() as t:
        kw = tree(t, [law(2025, i) for i in range(1, 201)])
        seen = []
        r = nb.prepare(fetch_text=lambda s, p: seen.append(p) or True, emit=lambda s, ls: len(ls), **kw)
        out.append(len(seen) == 150 and r["prepared"] == 150 and r["left_over_cap"] == 50)      # the 150 cap
        r = nb.prepare(cap=10, fetch_text=lambda s, p: True, emit=lambda s, ls: len(ls), **kw)
        out.append(r["tried"] == 10)
    with tempfile.TemporaryDirectory() as t:
        kw = tree(t, [law(2025, 1, "2026-11-08"), law(2025, 2, "2026-10-01")])
        p = nb.gap_problems(today=date(2026, 11, 10), **kw)
        out.append(len(p) == 1 and "1 signed laws older than 10 days" in p[0])           # the 2-day-old law is not flagged
        out.append(nb.gap_problems(today=date(2026, 11, 10), **dict(kw, packets_dir=Path(t) / "absent")) == [])   # no cache: skipped, not failed
    return out


CASES = [(g, True) for g in run()]
fails = [i for i, (got, want) in enumerate(CASES) if got != want]
for i in fails:
    print("FAIL case", i)
print("%d passed, %d failed" % (len(CASES) - len(fails), len(fails)))
sys.exit(1 if fails else 0)
