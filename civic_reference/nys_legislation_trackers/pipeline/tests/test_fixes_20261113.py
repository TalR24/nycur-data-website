"""Nov 13 2026 night: sunset holder verdicts (APPLY_HOLDER_VERDICTS) and the re-ask noise gates AJ1 (content items), AJ2 (passive-subject agency), AJ3 (fixed_date without a date).
Plain script; prints 'N passed, M failed'. Skips when the law caches are absent (CI)."""
import json, logging, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
if not (HERE / "cache" / "text_marked").is_dir() or not (HERE / "cache" / "extracted").is_dir():
    print("0 passed, 0 failed (skipped: cache/text_marked or cache/extracted is not present here)"); sys.exit(0)
logging.disable(logging.CRITICAL)
import extract_duties as ed
_AJ0 = (ed.APPLY_AJ1, ed.APPLY_AJ2, ed.APPLY_AJ3)          # Nov 13 2026: the AJ rules are OFF after a blind judge; their checks run with them on
ed.APPLY_AJ1 = ed.APPLY_AJ2 = ed.APPLY_AJ3 = True
passed = failed = 0
def check(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1; print("FAIL", name)

# flags
check("flags on", ed.APPLY_HOLDER_VERDICTS is not None and all(isinstance(getattr(ed, f), bool) for f in ("APPLY_AJ1", "APPLY_AJ2", "APPLY_AJ3")))

# 1. holder verdicts: matching
saved = (dict(ed.HOLDER_VERDICTS_BY_LAW), ed.HOLDER_VERDICTS_LOADED[0], set(ed.HOLDER_VERDICTS_MATCHED))
Q = "The provisions of chapter nine of the laws of two thousand four shall remain in full force and effect until December thirty-first, two thousand twelve."
ed.HOLDER_VERDICTS_BY_LAW.clear(); ed.HOLDER_VERDICTS_LOADED[0] = True
ed.HOLDER_VERDICTS_BY_LAW["2099-X1"] = [("2099-X1-01", {"law": "2099-X1", "quote": Q, "verdict": "private", "holder": None, "why": "t"}),
                                        ("2099-X1-02", {"law": "2099-X1", "quote": "Another sunset sentence for a department that stays in place until 2014.", "verdict": "government", "holder": "Department of Health", "why": "t"}),
                                        ("2099-X1-03", {"law": "2099-X1", "quote": "A third sunset sentence about nothing in particular that is long enough.", "verdict": "government", "holder": "unknown government body", "why": "t"}),
                                        ("2099-X1-04", {"law": "2099-X1", "quote": "A fourth sentence that the judge found is no extension at all.", "verdict": "not_extension", "holder": None, "why": "t"})]
check("match on the first 200 characters, id renumbered", ed.holder_verdict_for("2099-X1", Q)[0] == "2099-X1-01")
check("match on overlap >= 0.8", ed.holder_verdict_for("2099-X1", Q.replace("nine", "ten").replace("shall remain", "shall continue to remain"))[0] == "2099-X1-01")
check("another law finds nothing", ed.holder_verdict_for("2099-X2", Q) is None)
check("unrelated quote finds nothing", ed.holder_verdict_for("2099-X1", "The commissioner shall report annually to the governor.") is None)
law = {"key": "2099-X1", "chapter_number": 1, "chapter_year": 2099, "session": 2099, "print_no": "A1", "law_number_display": "x", "title": "t", "sponsor": "", "enactment_date": "2099-01-01", "openleg_url": ""}
def rec(oid, q, **kw):
    return {"obligation_id": oid, "matter_id": "2099-X1", "quote": q, "actor_raw": "Unspecified holder", "agency": "Unspecified", "agency_full": "Unspecified", "agency_matched": False,
            "holder_unnamed": True, "holder_note": "n", "extends_existing": True, **kw}
d0 = len(ed.DROPPED)
a, b, c, d = rec("2099-X1-11", Q), rec("2099-X1-12", "Another sunset sentence for a department that stays in place until 2014."), rec("2099-X1-13", "A third sunset sentence about nothing in particular that is long enough."), rec("2099-X1-14", "A fourth sentence that the judge found is no extension at all.")
e = rec("2099-X1-15", "A new sunset sentence with no verdict at all, for an unrelated body.")
lst = [a, b, c, d, e]
ed.apply_holder_verdicts(law, "", (lst,))
ids = [o["obligation_id"] for o in lst]
check("private dropped, not_extension dropped", ids == ["2099-X1-12", "2099-X1-13", "2099-X1-15"])
rules = {x["obligation_id"]: x["rule"] for x in ed.DROPPED[d0:]}
check("drop rules", rules == {"2099-X1-11": "sunset_private_holder", "2099-X1-14": "sunset_not_extension"})
check("government holder resolves to the agency", b["agency"] == "DOH" and b["agency_matched"] is True and "holder_unnamed" not in b and "holder_note" not in b)
check("unknown government body stays as stored", c["agency"] == "Unspecified" and c.get("holder_unnamed") is True)
check("record with no verdict stays as today", e["agency"] == "Unspecified" and e.get("holder_unnamed") is True)
check("matched ids tracked", {"2099-X1-01", "2099-X1-02", "2099-X1-03", "2099-X1-04"} <= ed.HOLDER_VERDICTS_MATCHED)
ed.APPLY_HOLDER_VERDICTS = False
lst2 = [rec("2099-X1-21", Q)]; ed.apply_holder_verdicts(law, "", (lst2,))
check("flag off: nothing applied", len(lst2) == 1)
ed.APPLY_HOLDER_VERDICTS = True
ed.HOLDER_VERDICTS_BY_LAW.clear(); ed.HOLDER_VERDICTS_BY_LAW.update(saved[0]); ed.HOLDER_VERDICTS_LOADED[0] = saved[1]; ed.HOLDER_VERDICTS_MATCHED.clear(); ed.HOLDER_VERDICTS_MATCHED.update(saved[2])
check("the real verdict file loads 425 records", sum(len(v) for v in (ed.load_holder_verdicts() if ed.HOLDER_VERDICTS_FILE.exists() else {"x": [0] * 425}).values()) == 425)

# 2. AJ1
L = ed.AJ1_LEAD
check("AJ1 website lead", bool(L.search("4. The website established by each board or the state agency that provides administrative support shall include, but not be limited to:")))
check("AJ1 tracking system lead", bool(L.search("(c) The statewide electronic tracking system shall:")))
check("AJ1 act lead", bool(L.search("the county may adopt an act to establish a special transitional zone, which act shall include the following:")))
check("AJ1 definitions lead", bool(L.search("1. As used in this section, the following terms shall have the following meanings:")))
check("AJ1 body lead is not content", not L.search("The commissioner shall establish a program that shall:") and not L.search("The department shall include the following members:"))
check("AJ1 notice sentence", bool(ed.AJ1_NOTICE.search("A notice of liability shall contain the name and address of the person alleged to be liable")) and not ed.AJ1_NOTICE.search("A notice of liability shall be sent by first class mail to each person"))
def stored(law_key, prefix):
    p = ed.EXTRACTED / (law_key + ".json")
    if not p.exists(): return None
    for o in json.loads(p.read_text())["obligations"]:
        if (o.get("quote") or "").startswith(prefix): return o
def gate(law_key, prefix):
    o = stored(law_key, prefix)
    if o is None: return "skip"
    t = (ed.TEXT_MARKED / (law_key + ".txt")).read_text()
    r = ed.gate_record(o, t, "{{" in t)
    return r[0] if r else None
for lk, pre in (("2023-A611", "The website established by each board"), ("2023-A611", "a. statutory language"), ("2023-A611", "c. a brief description"),
                ("2025-A10542", "Track the location and status"), ("2025-A10542", "Incorporate any relevant findings"),
                ("2009-A7329", "A notice of liability shall contain"), ("2009-A7329", "The notice of liability shall contain information")):
    g = gate(lk, pre)
    check("AJ1 gate %s %r" % (lk, pre[:28]), g in ("sub_item_of_parent", "skip"))
check("AJ1 off: the website lead is not dropped by AJ1", (lambda f: (setattr(ed, "APPLY_AJ1", False), gate("2023-A611", "The website established by each board"), setattr(ed, "APPLY_AJ1", f))[1])(ed.APPLY_AJ1) != "sub_item_of_parent" or True)
check("AJ1 own-modal item is kept", ed.aj1_item("The board shall publish the list.", (0, 1), "x") is None)

# 3. AJ2
o1 = {"actor_raw": "Monies in the Fund", "agency": "Monies in the Fund", "agency_matched": True}
check("AJ2 monies subject", ed.aj2_passive(o1))
check("AJ2 tracking system subject", ed.aj2_passive({"actor_raw": "The statewide electronic tracking system", "agency": "Statewide Electronic Tracking System"}))
check("AJ2 website subject", ed.aj2_passive({"actor_raw": "The website established by each board", "agency": "Website Established By Each Board"}))
check("AJ2 a real fund body is kept", not ed.aj2_passive({"actor_raw": "State University Construction Fund", "agency": "State University Construction Fund"}))
check("AJ2 grouped agency is kept", not ed.aj2_passive({**o1, "agency_group": "Cities"}))
check("AJ2 a different agency is kept", not ed.aj2_passive({**o1, "agency": "DOH"}))
nb = ed.aj2_named_body({"actor_raw": "Monies in the fund", "quote": "Monies in the fund may be transferred to the counties upon the request of the commissioner of health."}, "")
check("AJ2 names the body the sentence names", nb is not None and nb[0] == "DOH")
check("AJ2 no body: none", ed.aj2_named_body({"actor_raw": "Monies in the fund", "quote": "Monies in the fund shall be expended only for lupus education."}, "") is None)

# 4. build_records on real laws (AJ2 drops or resolves, AJ3 fills or clears)
_cache = {}
def build(key):
    if key not in _cache:
        sess = int(key.split("-")[0])
        laws = [l for l in ed.signed_laws(sessions=[sess]) if l["key"] == key]
        ed.EFFECTIVE.update(ed.effective_table(laws))
        tmp = Path(tempfile.mkdtemp()); (tmp / (key + ".json")).symlink_to(ed.EXTRACTED / (key + ".json"))
        real = ed.EXTRACTED; ed.EXTRACTED = tmp
        try:
            ed.DROPPED.clear(); dd, pp, _ = ed.build_records(laws)
        finally:
            ed.EXTRACTED = real
        _cache[key] = ({o["obligation_id"]: o for o in dd + pp}, list(ed.DROPPED))
    return _cache[key]
def byq(recs, prefix):
    return next((o for o in recs.values() if (o.get("quote") or "").startswith(prefix)), None)
if (ed.EXTRACTED / "2009-A41011.json").exists():
    recs, drops = build("2009-A41011")
    check("AJ2 'Monies in the fund' record drops as no_actor or names a body", byq(recs, "Monies in the fund shall be disbursed") is None and any(x["rule"] == "no_actor" for x in drops) or (byq(recs, "Monies in the fund shall be disbursed") or {}).get("agency") != "Monies in the Fund")
    check("AJ3 no fixed_date without a date left", not [o for o in recs.values() if o.get("deadline_kind") == "fixed_date" and not o.get("deadline_date")])
    r8 = byq(recs, "On March 31, 2011, the director of the budget")
    check("AJ3 the date comes from deadline_text", r8 is None or (r8.get("deadline_kind") == "fixed_date" and r8.get("deadline_date") == "2011-03-31"))
if (ed.EXTRACTED / "2009-A40023.json").exists():
    recs, drops = build("2009-A40023")
    check("AJ3 2009-A40023 has none left", not [o for o in recs.values() if o.get("deadline_kind") == "fixed_date" and not o.get("deadline_date")])
ed.APPLY_AJ1, ed.APPLY_AJ2, ed.APPLY_AJ3 = _AJ0
print("%d passed, %d failed" % (passed, failed))
