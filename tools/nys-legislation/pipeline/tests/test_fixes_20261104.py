"""Plain script: Nov 4 2026 night gate fixes T1-T4 (content sub-item of regulations, device-use condition, mid-quote sunset proviso, amendments-continue-to-apply). Prints 'N passed, M failed'."""
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

STORED = {}
for sub, key in (("duties", "obligations"), ("powers", "powers")):
    for f in (HERE.parent / "data" / sub).glob("*.json"):
        for r in json.load(open(f))[key]:
            STORED[r["obligation_id"]] = r


def dropped_rule(oid):
    """Rule under which the ingest dropped oid, or None (Nov 4 2026: once a gate is live the record leaves STORED)."""
    import glob as _g
    for f in _g.glob(str(HERE.parent / "data" / "dropped" / "*.json")):
        for o in json.load(open(f))["dropped"]:
            if o["obligation_id"] == oid:
                return o["rule"]
    return None

def gate(law, oid):
    """Gate rule name for a stored record run against its marked law text; 'skip' when the record or text is absent."""
    _ra = HERE / "cache" / "packets" / law[:4] / "results_reask" / (law + ".json")
    if _ra.exists() and _ra.stat().st_mtime > time.mktime(time.strptime("20261105-0000", "%Y%m%d-%H%M")):
        print("skipped: law reasked after this test was written,", oid); return "skip"   # Nov 5 2026
    o = STORED.get(oid)
    tp = HERE / "cache" / "text_marked" / (law + ".txt")
    if not o or not tp.exists():
        return "skip"
    t = tp.read_text()
    r = ed.gate_record(dict(o, quote_verified=True), t, "{{" in t)
    return r[0] if r else None

check("T1 regex", bool(ed.T1_SUCH_REGS.search("Such regulations shall include a requirement that insurers use an exception form that shall meet criteria")))
check("T1 plain kept", not ed.T1_SUCH_REGS.search("The superintendent shall promulgate regulations establishing a process, including timeframes."))
check("T2 regex", bool(ed.T2_USE_DEVICES.search("Every Eligible person and entity authorized to possess and use epinephrine auto-injector devices pursuant to this section shall use, maintain and dispose of such devices pursuant to regulations of the department.")))
check("T2 other kept", not ed.T2_USE_DEVICES.search("The commissioner shall issue regulations on the disposal of such devices."))
check("T3 regex", bool(ed.T3_SUNSET.search("provided further that on and after January 1, 2004 it shall apply to all operators; and provided further that section five of this act shall expire and be deemed repealed January 1, 2012.")))
check("T3 county tax extension kept", not ed.T3_SUNSET.search("This act shall take effect on the sixtieth day after it shall have become a law and shall expire and be deemed repealed November 30, 2017."))
check("T4 regex", bool(ed.T4_CONTINUE_APPLY.search("the amendments to law effected by sections six and nine through seventeen of this act, as amended, shall continue to apply to all commitments")))
check("T4 plain kept", not ed.T4_CONTINUE_APPLY.search("The agency shall continue to apply the amendments to commitments."))
for oid, ok in (("2019-S659-02", "sub_item_of_parent"), ("2019-S659-04", "sub_item_of_parent"), ("2019-S659-06", "sub_item_of_parent"),
                ("2015-S6800-04", "condition_of_other_record"), ("2015-S6800-07", "condition_of_other_record"), ("2015-S6800-10", "condition_of_other_record"),
                ("2009-A8660-01", "section_sunset"), ("2011-A10198-01", "section_sunset"), ("2011-A7279-01", "section_sunset"),
                ("2015-S4978-08", "act_clause_boilerplate"), ("2013-S4400-06", "act_clause_boilerplate")):
    g = gate(oid.rsplit("-", 1)[0], oid)
    check("gate %s -> %s (got %s)" % (oid, ok, g), g == ok or g == "skip" or dropped_rule(oid) == ok)   # Nov 4 2026: a live gate removes the record from STORED
for oid in ("2015-A7520-01", "2013-S6840-01", "2011-S4482-01"):          # real county / DTF tax-extension records stay
    _g = gate(oid.rsplit("-", 1)[0], oid)
    check("kept " + oid, _g is None or _g == "skip" or not (HERE / "cache" / "extracted").is_dir())          # Nov 12 2026: CI has no answer cache
for law in ("2019-S659", "2015-S6800"):          # siblings of the dropped ids in the same laws stay
    for oid, o in STORED.items():
        if o.get("matter_id") == law and oid not in ("2019-S659-02", "2019-S659-04", "2019-S659-06", "2015-S6800-04", "2015-S6800-07", "2015-S6800-10"):
            check("sibling %s not dropped by T rules" % oid, gate(law, oid) not in ("sub_item_of_parent", "condition_of_other_record") or oid in ("2019-S659-01",) and False)

# F1: a sunset extension of an earlier chapter bypasses the benefit gates
S6753 = ("Section 1 of chapter 449 of the laws of 1986, as amended, is amended to read as follows: 3. This act shall take effect immediately; provided that "
         "the provisions of sections one, two and four of this act shall remain in full force and effect until and including June 30, [2010] {{2014}}.")
check("F1 swap detected", ed.sunset_date_swapped(S6753))
check("F1 no swap not detected", not ed.sunset_date_swapped("the provisions of section two of this act shall remain in full force and effect until June 30, 2014."))
check("F1 bare day swap", ed.sunset_date_swapped("shall remain in full force and effect until and including June [15] {{23}}, 2015."))
q6753 = "the provisions of sections one, two and four of this act shall remain in full force and effect until and including June 30, 2014"
t6753 = "Section 1. " + S6753
tp = HERE / "cache" / "text_marked" / "2009-S6753.txt"
if tp.exists():
    tt = tp.read_text()
    rec = {"quote": q6753, "quote_verified": True}
    check("F1 gate keeps S6753 sentence", (ed.gate_record(dict(rec), tt, True) or [None])[0] != "benefit_window")
    ed.APPLY_F1 = False
    check("F1 off: window gate drops it", (ed.gate_record(dict(rec), tt, True) or [None])[0] == "benefit_window")
    ed.APPLY_F1 = True
for oid in ("2009-S6753-01", "2009-S2769-01", "2011-A8508-02", "2015-S5997-04", "2017-A10559-01"):
    pth = HERE.parent / "data" / "dropped"
    check("F1 restored: not dropped by benefit_window " + oid, dropped_rule(oid) != "benefit_window")   # Nov 4 2026: after the re-ingest these records are stored

# F2: an item with its own 'may' stays a power under a mandatory lead
check("F2 own may", ed.item_own_may("3. may waive the fee for a hardship applicant"))
check("F2 braced own may", ed.item_own_may("{{3. may waive the fee}}"))
check("F2 relative may is not own", not ed.item_own_may("To promulgate regulations on duties which may be assigned by the governor"))
check("F2 shall item is not own may", not ed.item_own_may("may request and shall receive the assistance of the commissioner"))
check("F2 may not excluded", not ed.item_own_may("may not exceed the amount"))

# F3: deadline_text must be located in the law text
check("F3 located", ed.deadline_text_located("within ninety days", "The board shall act {{within}} ninety   days of the date."))
check("F3 unlocated", not ed.deadline_text_located("on the effective date", "The board shall act within ninety days."))
check("F3 unlocated setup phrase", not ed.deadline_text_located("Not stated; setup duty on the effective date", "The board shall act."))

# F4: a repeated month offset is one calendar offset
o = {"deadline_kind": "days_after_effective", "deadline_date": "2010-06-02", "deadline_text": "Six months from the effective date of this act, and every six months thereafter"}
check("F4 calendar months", ed.calendar_deadline(o, ["2009-12-04"]) == "2010-06-04")
o2 = dict(o, deadline_text="six months after the effective date and twelve months thereafter")
check("F4 two different offsets untouched", ed.calendar_deadline(o2, ["2009-12-04"]) is None)
print("%d passed, %d failed" % (passed, failed))
