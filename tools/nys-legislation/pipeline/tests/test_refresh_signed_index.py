"""Plain test script: prints 'N passed, M failed', exit 1 on failure. Run: python3 tests/test_refresh_signed_index.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import refresh_signed_index as r

COLS = ["session", "print_no", "base_print_no", "status", "chapter", "status_date"]


def make(d, generated, rows, laws, refreshed=None):
    os.makedirs(os.path.join(d, "bills")); os.makedirs(os.path.join(d, "signed"))
    json.dump({"session": 2025, "generated": generated, "cols": COLS, "rows": rows}, open(os.path.join(d, "bills", "2025.json"), "w"))
    json.dump(laws, open(os.path.join(d, "signed", "2025.json"), "w"))
    if refreshed:
        json.dump({"refreshed": {"2025": refreshed}}, open(os.path.join(d, "signed_state.json"), "w"))


ROWS = [[2025, "S1", "S1", "SIGNED_BY_GOV", 10, "2026-10-01"], [2025, "S2", "S2", "SIGNED_BY_GOV", 11, "2026-11-08"],
        [2025, "S3", "S3", "IN_ASSEMBLY_COMM", None, "2026-11-08"], [2025, "S4", "S4", "SIGNED_BY_GOV", None, "2026-11-08"]]
LAW = {"key": "2025-S1", "print_no": "S1"}


def fake_fetch(sess, pn):
    return {"session": sess, "print_no": pn, "base_print_no": pn, "title": "t", "act_clause": "AN ACT", "law_section": None, "sponsor": None,
            "openleg_url": "u", "chapter": {"number": 11, "year": 2026, "signed_date": "2026-11-08"}, "status": {"type": "SIGNED_BY_GOV"}}


def run():
    out = []
    with tempfile.TemporaryDirectory() as d:
        make(d, "2026-11-10", ROWS, [LAW])
        out.append(r.missing_laws(d, 2025) == [("S2", 11, "2026-11-08")])          # chapterless and unsigned rows are ignored
        out.append(r.stale_problems(d) == [])                                       # signed 2 days ago: not stale yet
        out.append(r.refresh_session(d, 2025, fetch=fake_fetch) == ["2025-S2"])
        out.append([l["print_no"] for l in json.load(open(os.path.join(d, "signed", "2025.json")))] == ["S1", "S2"])
        out.append(r.refresh_session(d, 2025, fetch=fake_fetch) == [])             # idempotent
    with tempfile.TemporaryDirectory() as d:
        make(d, "2026-11-10", ROWS, [])                                             # S1 signed Oct 1, 40 days before the index date
        p = r.stale_problems(d)
        out.append(len(p) == 1 and "2 signed laws" not in p[0] and "1 signed laws" in p[0])   # only S1 is older than 10 days
    with tempfile.TemporaryDirectory() as d:
        make(d, "2026-11-10", ROWS[:1], [LAW], refreshed="2026-10-20")              # nothing missing, but refresh date 21 days old
        p = r.stale_problems(d)
        out.append(len(p) == 1 and "21 days" in p[0])
    with tempfile.TemporaryDirectory() as d:
        make(d, "2026-11-10", ROWS[:1], [LAW], refreshed="2026-11-05")
        out.append(r.stale_problems(d) == [])
    return out


CASES = [(g, True) for g in run()]
fails = [i for i, (got, want) in enumerate(CASES) if got != want]
for i in fails:
    print("FAIL case", i)
print("%d passed, %d failed" % (len(CASES) - len(fails), len(fails)))
sys.exit(1 if fails else 0)
