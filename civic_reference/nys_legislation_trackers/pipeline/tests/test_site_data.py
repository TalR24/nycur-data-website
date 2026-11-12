"""Plain script: invariants of the public export on a tiny fixture, plus a smoke run on real data. Prints 'N passed, M failed'."""
import glob, json, os, sys, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import build_site_data as b

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

def rec(n, kind, agency="DOB", **kw):
    r = {"obligation_id": "2025-S1-%02d" % n, "matter_id": "2025-S1", "actor_raw": "the director of the budget", "agency": agency,
         "agency_full": "Division of the Budget", "action_summary": "Do it.", "citation": "Section 1", "quote": "shall do it",
         "deadline_kind": "none", "recurrence": "ongoing", "kind": kind, "chapter": 5, "chapter_year": 2025, "session": 2025,
         "law_number_display": "Chapter 5 of 2025", "law_title": "T", "prime_sponsor": "Dan Stec", "enactment_date": "2025-01-02",
         "effective_date": "2025-01-02", "openleg_url": "u", "kind_rule": "x", "quote_verified": True}
    r.update(kw); return r

tmp = Path(tempfile.mkdtemp()); d = tmp / "data"
for s in ("duties", "powers", "signed", "effective_dates"): (d / s).mkdir(parents=True)
json.dump({"obligations": [rec(1, "duty", deadline_kind="fixed", deadline_date="2999-01-01"), rec(2, "duty", actor_raw="DOB")]}, open(d / "duties/2025.json", "w"))
json.dump({"powers": [rec(3, "power", multi_state=True)]}, open(d / "powers/2025.json", "w"))
json.dump([{"key": "2025-S1", "print_no": "S1", "signed_date": "2025-01-02", "sponsor": "Dan Stec"}], open(d / "signed/2025.json", "w"))
json.dump({}, open(d / "effective_dates/2025.json", "w"))
json.dump({"agencies": [{"canonical": "DOB", "org_type": "division"}]}, open(d / "agency_crosswalk_nys.json", "w"))
json.dump([{"member_id": 1, "session": 2025, "chamber": "Senate", "full_name": "Dan Stec", "district": 45}], open(d / "members.json", "w"))
s = b.build(data=str(d), out=str(tmp / "site"))
rows = json.load(open(tmp / "site/records_2025.json")); laws = json.load(open(tmp / "site/laws.json"))
check("fixture totals", (s["duties"], s["powers"], s["records"]) == (2, 1, 3))
check("law keys exist", {r["l"] for r in rows} <= {l["key"] for l in laws})
check("id and quote present", all(r["i"] and r["q"] for r in rows))
check("actor_raw only when different", "ar" in rows[0] and "ar" not in rows[1])
check("internals dropped", all("kind_rule" not in r and "quote_verified" not in r for r in rows))
check("multi_state flag", rows[2].get("ms") == 1)
ag = json.load(open(tmp / "site/agencies.json"))[0]
check("agency counts and deadline", ag["duties"] == {"2025": 2} and ag["powers"] == {"2025": 1} and len(ag["next_deadlines"]) == 1 and ag["org_type"] == "division")
lg = json.load(open(tmp / "site/legislators.json"))[0]
check("legislator matched", lg["chamber"] == "Senate" and lg["districts"] == [45] and lg["laws"] == 1 and lg["duties"] == 2)

if (b.DATA and os.path.isdir(os.path.join(b.DATA, "duties"))):
    real = tmp / "real"; s = b.build(out=str(real))
    n = 0
    for p in glob.glob(os.path.join(b.DATA, "duties/*.json")): n += len(json.load(open(p))["obligations"])
    m = 0
    for p in glob.glob(os.path.join(b.DATA, "powers/*.json")): m += len(json.load(open(p))["powers"])
    check("real totals equal working files", s["duties"] == n and s["powers"] == m and s["records"] == n + m)
    lk = {l["key"] for l in json.load(open(real / "laws.json"))}
    allr = [r for p in glob.glob(str(real / "records_*.json")) for r in json.load(open(p))]
    check("real: every law key in laws.json", all(r["l"] in lk for r in allr))
    check("real: id and quote everywhere", all(r["i"] and r["q"] for r in allr))
    check("real: record files under 3 MB", all(os.path.getsize(p) < 3e6 for p in glob.glob(str(real / "records_*.json"))))
else:
    print("(real-data smoke skipped: data/ absent)")
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
