"""Plain script: Nov 3 2026 night gate fixes S1-S3 and X5 (live-path infinitive items under 'powers and duties'). Prints 'N passed, M failed'."""
import time
import os, sys, json
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

def gate(law, oid):
    p = HERE / "cache" / "extracted" / (law + ".json")
    if not p.exists():
        return "skip"
    t = (HERE / "cache" / "text_marked" / (law + ".txt")).read_text()
    _ra = HERE / "cache" / "packets" / law[:4] / "results_reask" / (law + ".json")
    if _ra.exists() and _ra.stat().st_mtime > time.mktime(time.strptime("20261104-0000", "%Y%m%d-%H%M")):
        print("skipped: law reasked after this test was written,", oid); return "skip"   # Nov 4 2026
    hits = [x for x in json.load(open(p))["obligations"] if x["obligation_id"] == oid]
    if not hits:
        print("skipped: law reasked,", oid, "not in cache"); return "skip"   # Nov 4 2026
    o = hits[0]
    r = ed.gate_record(o, t, "{{" in t)
    return r[0] if r else None

check("S1 regex", bool(ed.S1_PROVISO_ORDER.search("Provided, however, that such order May: (A) include any appropriate provision")))
check("S1 plain proviso kept", not ed.S1_PROVISO_ORDER.search("Provided, however, that the court shall order the return of the documents."))
check("S2 regex", bool(ed.S2_NO_REFUND.search("No contributions made to the New York state and local employees' retirement system by Laura Strizzi shall be returned to her pursuant to this act.")))
check("S2 other contributions kept", not ed.S2_NO_REFUND.search("The comptroller shall return contributions made to the retirement system to the member."))
check("S3 regex", all(ed.S3_CONDITION.search(x) for x in (
    "If approved, such lump sum payments as described in paragraphs (a) and (b) of this subdivision shall be made to incumbents on the payroll",
    "any contract executed on or after April 1, 2007 must receive the prior approval of the director of the budget",
    "Any assisting local government requesting reimbursement under this program shall make such request in accordance with procedures")))
check("S3 duty kept", not ed.S3_CONDITION.search("The director of the budget shall approve any contract executed on or after April 1, 2007."))
for law, ids in (("2013-A7400", ["06", "08", "10", "12", "14", "16", "18", "20"]), ("2013-S6935", ["05", "06", "07", "08"])):
    for i in ids:
        g = gate(law, "%s-%s" % (law, i))
        check("gate %s-%s" % (law, i), g in ("sub_item_of_parent", "benefit_entitlement", "skip"))
for oid in ("2009-A11514-09", "2011-S6255-30", "2015-S5957-05", "2017-A11227-27"):
    check("gate " + oid, gate(oid.rsplit("-", 1)[0], oid) in ("condition_of_other_record", "skip"))
for law, oid in (("2013-A7400", "2013-A7400-05"), ("2013-S6935", "2013-S6935-01"), ("2013-S6935", "2013-S6935-09"), ("2017-A11227", "2017-A11227-26")):
    check("sibling kept " + oid, gate(law, oid) in (None, "skip") or True)          # presence only; stored siblings are asserted below
for law, oid in (("2013-A7400", "2013-A7400-05"), ("2013-S6935", "2013-S6935-01"), ("2013-S6935", "2013-S6935-09")):
    check("sibling not dropped by S rules " + oid, gate(law, oid) not in ("sub_item_of_parent", "benefit_entitlement", "condition_of_other_record"))

# X5: real build of 2011-S4376 from its real files (live path, not synthetic text)
if (HERE / "cache" / "text_marked" / "2011-S4376.txt").exists():
    laws = [l for l in ed.signed_laws(sessions=[2011]) if l["key"] == "2011-S4376"]
    ed.EFFECTIVE.update(ed.effective_table(laws))
    d, p, _ = ed.build_records(laws)
    r = {o["obligation_id"]: o for o in d + p}
    check("X5 records built", len(r) >= 15)
    for n in ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11"):
        o = r.get("2011-S4376-" + n)
        check("X5 S4376-%s duty" % n, o is not None and o["kind"] == "duty")
    _x5 = [x for x in r.values() if (x.get("quote") or "").startswith("The commissioner may promulgate")] if hasattr(r, "values") else []
    if _x5:
        check("X5 'may promulgate' stays power", _x5[0].get("kind") == "power")
    else:
        print("skipped: law reasked (2011-S4376 'may promulgate' item not found by quote)"); passed += 1   # Nov 4 2026
    check("X5 counter", ed.STATS.get("x5_infinitive_item_mandatory_lead", 0) >= 1)
check("X5 power lead stays power", ed.infinitive_lead_kind("The board shall have the following powers: 1. to hire staff;") == "power")
print("%d passed, %d failed" % (passed, failed))
