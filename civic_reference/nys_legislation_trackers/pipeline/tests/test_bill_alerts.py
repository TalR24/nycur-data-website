"""Plain test script: prints 'N passed, M failed', exit 1 on failure. Run: python3 tests/test_bill_alerts.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import send_bill_alerts as s
from apply_updates import write_index


def act(date, seq, text, ver="", chamber="SENATE"):
    return {"date": date, "sequenceNo": seq, "text": text, "chamber": chamber, "billId": {"version": ver}}


def vote(date, chamber, ayes, nays):
    m = lambda n: {"items": [{"chamber": chamber} for _ in range(n)]}
    return {"voteType": "FLOOR", "voteDate": date, "memberVotes": {"items": {"AYE": m(ayes), "NAY": m(nays)}}}


BILL = {"session": 2025, "basePrintNo": "S1", "votes": {"items": [vote("2026-03-03", "SENATE", 61, 0), vote("2026-03-03", "ASSEMBLY", 100, 3)]},
        "actions": {"items": [
            act("2026-02-01", 1, "REFERRED TO CODES"),
            act("2026-03-03", 2, "PASSED SENATE"), act("2026-03-04", 3, "PASSED ASSEMBLY", chamber="ASSEMBLY"),
            act("2026-03-05", 4, "AMEND (T) AND RECOMMIT TO WAYS AND MEANS"), act("2026-03-05", 5, "PRINT NUMBER 1A", ver="A"),
            act("2026-04-01", 6, "DELIVERED TO GOVERNOR"), act("2026-04-02", 7, "SIGNED CHAP.412"),
            act("2026-04-03", 8, "COMMITTEE DISCHARGED AND COMMITTED TO RULES")]}}
LINES = [l for _, _, l in s.bill_events(BILL, "2026-03-01")]
ASSEMBLY_VOTE = s.floor_vote(BILL, act("2026-03-03", 2, "PASSED ASSEMBLY", chamber="ASSEMBLY"))

CASES = [
    (LINES[0], "Passed the Senate, 61-0 (Mar 3)"),
    (LINES[1], "Passed the Assembly (Mar 4)"),
    (LINES[2], "Amended (version A) and sent back to the Ways and Means committee"),
    (len(LINES), 6),                                                   # the PRINT NUMBER action on an AMEND day adds no second line
    (LINES[3], "Delivered to the governor"),
    (LINES[4], "Signed: chapter 412 of 2026"),
    (ASSEMBLY_VOTE, "100-3"),
    ([i for i, _, _ in s.bill_events(BILL, "2026-03-01")][0], "2025-S1|2026-03-03|2"),
    (s.bill_events(BILL, "2026-04-04"), []),
    (s.describe(BILL, act("2026-01-05", 1, "REFERRED TO CORPORATIONS, AUTHORITIES AND COMMISSIONS")), "Moved to the Corporations, Authorities and Commissions committee"),
    (s.describe(BILL, act("2026-06-01", 9, "PRINT NUMBER 1B", ver="B")), "Amended: version B"),
    (s.describe(BILL, act("2026-12-19", 9, "VETOED MEMO.116")), "Vetoed (veto message 116, Dec 19)"),
    (s.describe(BILL, act("2026-12-19", 9, "")), None),
    (s.hid("A@B.com"), s.hid(" a@b.COM ")),
]


def roundtrip():
    doc = {"session": 2025, "generated": "2026-10-07", "total_in_api": 2, "cols": ["a", "b"], "rows": [[1, "x"], [2, "y"]]}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.json")
        write_index(p, doc)
        text = open(p).read()
        return json.loads(text) == doc and text.count("\n") == 3


def follows():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f.csv")
        open(p, "w").write("email,session,bill,added\na@x.test,2025,s11,2026-10-01\nbad,row\nb@x.test,2025,S11,2026-10-02\n")
        f = s.load_follows(p)
        return list(f) == ["2025-S11"] and len(f["2025-S11"]) == 2


CASES += [(roundtrip(), True), (follows(), True)]
fails = [i for i, (got, want) in enumerate(CASES) if got != want]
for i in fails:
    print("FAIL case", i, "got", repr(CASES[i][0]), "want", repr(CASES[i][1]))
print("%d passed, %d failed" % (len(CASES) - len(fails), len(fails)))
sys.exit(1 if fails else 0)
