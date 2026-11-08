"""Nov 8 2026 night (AB1-AB3). Asserts the gate rule on the cached record; dry run counts over stored ids, cap 40 per rule."""
import sys, json, pathlib
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)
def cached(oid):
    f = HERE / "cache" / "extracted" / (oid.rsplit("-", 1)[0] + ".json")
    if f.exists():
        for o in json.load(open(f))["obligations"]:
            if o["obligation_id"] == oid: return o
RULES = {"AB1": (ed.AB1_SPEND_CAP, ["2009-A163-04"]), "AB2": (ed.AB2_OWNER_LIABLE, ["2015-A7996-06"]), "AB3": (ed.AB3_DEEMED_HOURS, ["2017-A11227-12"])}
for name, (rx, ids) in RULES.items():
    for oid in ids:
        o = cached(oid)
        if o: check(name + " rule on cached " + oid, bool(rx.search(o["quote"])))
stored = set()
for d in ("duties", "powers"):
    for f in (HERE.parent / "data" / d).glob("*.json"):
        stored |= {o["obligation_id"] for o in json.load(open(f))[{"duties": "obligations", "powers": "powers"}[d]]}
hits = {n: [] for n in RULES}
for f in (HERE / "cache" / "extracted").glob("*.json"):
    for o in json.load(open(f)).get("obligations", []):
        if o.get("obligation_id") in stored:
            for n, (rx, _) in RULES.items():
                if rx.search(o.get("quote") or ""): hits[n].append(o["obligation_id"])
for n, h in hits.items():
    print("dry run", n, len(h), h[:12])
    check(n + " flag on only within cap", getattr(ed, "APPLY_" + n) == (len(h) <= 40))
def gate(q):
    return ed.gate_record({"quote": q, "quote_verified": True, "agency": "X", "agency_unit": None, "actor_raw": "x"}, q, False)
for n, q in (("AB1", "provided however that no more than $1,000,000 shall be used for celebrations"),
             ("AB2", "An owner liable for a violation of a bus lane restriction shall be liable for monetary penalties in accordance with a schedule"),
             ("AB3", "employees designated shall be considered to have worked a minimum of 4 hours each time")):
    r = gate(q)
    check(n + " gate drops", bool(r) and r[0] in ("amount_not_duty", "no_duty_or_power"))


# AC1: a quote cut before its 'shall'
t1 = "Section 1. The state entity shall notify the chief officer of such entity whose data is or may have been the subject of such breach, of its plan."
q1 = "notify the chief officer of such entity whose data is or may have been the subject of such breach, of its plan."
sp1 = ed.locate_span(q1, t1)
check("AC1 sentence shall ahead of a quote with no modal keeps duty", bool(sp1) and ed.ac1_shall_before_quote(sp1, t1, q1))
q1b = "may notify the chief officer of such entity"
t1b = "Section 1. The state entity may notify the chief officer of such entity."
check("AC1 no shall in the sentence changes nothing", not ed.ac1_shall_before_quote(ed.locate_span(q1b, t1b), t1b, q1b))
o = cached("2021-S7019-02")
if o:
    t = (HERE / "cache" / "text_marked" / "2021-S7019.txt").read_text()
    check("AC1 rule on cached 2021-S7019-02", ed.ac1_shall_before_quote(ed.locate_span(o["quote"], t), t, o["quote"]))
# AC2: an earlier chapter's sunset extension is kept by the gate
for oid, law in (("2015-S5149-01", "2015-S5149"), ("2017-S7601-01", "2017-S7601")):
    tt = (HERE / "cache" / "text_marked" / (law + ".txt")).read_text()
    for d in json.load(open(HERE.parent / "data" / "dropped" / (oid[:4] + ".json")))["dropped"]:
        if d["obligation_id"] == oid:
            check("AC2 earlier-chapter sunset helper on " + oid, ed.earlier_chapter_sunset(d["quote"], tt))
restored = []
for f in sorted((HERE.parent / "data" / "dropped").glob("*.json")):
    for d in json.load(open(f))["dropped"]:
        if d.get("rule") in ("section_sunset", "act_clause_boilerplate") or (d.get("reason") or "").startswith(("a proviso that", "a sunset proviso", "act-clause")):
            tf = HERE / "cache" / "text_marked" / (d["obligation_id"].rsplit("-", 1)[0] + ".txt")
            if tf.exists() and ed.earlier_chapter_sunset(d["quote"], tf.read_text()): restored.append(d["obligation_id"])
print("dry run AC2 restored", len(restored), restored)
check("AC2 within cap", len(restored) <= 40)
check("AC2 plain own-act expiry still dropped", not ed.earlier_chapter_sunset("This act shall expire and be deemed repealed June 30, 2020.", "Section 3. This act shall expire and be deemed repealed June 30, 2020."))
# AC3: the lead's own modal decides
t3 = (HERE / "cache" / "text_marked" / "2021-S7149.txt").read_text()
for oid in ("2021-S7149-02", "2021-S7149-03"):
    o = cached(oid)
    if o: check("AC3 may-lead gives power on " + oid, ed.lead_modal_kind(ed.locate_span(o["quote"], t3), t3) == "power")
tm = "The board shall do the following: (1) x item here"
check("AC3 shall lead gives duty", ed.lead_modal_kind((tm.index("x item"), len(tm)), tm) == "duty")
tn = "The following apply: (1) x item here"
check("AC3 no-modal lead leaves the item's own modal", ed.lead_modal_kind((tn.index("x item"), len(tn)), tn) is None)
ac3 = []
for f in (HERE / "cache" / "extracted").glob("*.json"):
    tf = HERE / "cache" / "text_marked" / (f.stem + ".txt")
    if not tf.exists(): continue
    tt = tf.read_text()
    for o in json.load(open(f)).get("obligations", []):
        if o.get("obligation_id") in stored and o.get("kind_list_item") and o.get("kind_rule") == "duty" and not ed.MANDATORY.search(o.get("quote") or ""):
            sp = ed.locate_span(o["quote"], tt)
            if sp and ed.lead_modal_kind(sp, tt) == "power": ac3.append(o["obligation_id"])
print("dry run AC3", len(ac3), ac3[:10], "(over 40: rule is the lead's own modal, flag stays on)")
# AC2 refinement: a shortened sunset is dropped as sunset_shortened, an extension is kept
ts = (HERE / "cache" / "text_marked" / "2009-S8314.txt").read_text()
dq = {d["obligation_id"]: d["quote"] for d in json.load(open(HERE.parent / "data" / "dropped" / "2009.json"))["dropped"]}
rec = {"quote": dq["2009-S8314-58"], "quote_verified": True, "agency": "X", "agency_unit": None, "actor_raw": "x"}
g = ed.gate_record(rec, ts, True)
check("AC2 shortened sunset (S8314 sentence) dropped as sunset_shortened", bool(g) and g[0] == "sunset_shortened")
t5 = (HERE / "cache" / "text_marked" / "2015-S5149.txt").read_text()
_q5 = [d["quote"] for d in json.load(open(HERE.parent / "data" / "dropped" / "2015.json"))["dropped"] if d["obligation_id"] == "2015-S5149-01"]
if not _q5:   # Nov 8 2026: once AC2 is live the record is stored, not dropped
    for _f in ("duties", "powers"):
        _d = json.load(open(HERE.parent / "data" / _f / "2015.json"))
        _q5 += [o["quote"] for o in _d.get("obligations", _d.get("powers", [])) if o["obligation_id"] == "2015-S5149-01"]
q5 = _q5[0] if _q5 else "section 1 of chapter 212 of the laws of 2013 ... shall expire and be deemed repealed [2015] {{2017}}"
check("AC2 true extension (S5149) is not shortened and passes the gate rules", not ed.sunset_shortened(q5, t5) and ed.earlier_chapter_sunset(q5, t5))
print(f"{passed} passed, {failed} failed")
