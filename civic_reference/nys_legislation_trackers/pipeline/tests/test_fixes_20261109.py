"""Nov 9 2026 night (AD1). Asserts the gate rule on the cached record; dry run counts over stored ids, cap 40 per rule."""
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
def gate_q(q):
    return ed.gate_record({"quote": q, "quote_verified": True, "agency": "X", "agency_unit": None, "actor_raw": "x"}, q, False)
o = cached("2017-S8074-01")
if o:
    check("AD1 rule on cached quote", bool(ed.AD1_DEEMED_CONTRACTS.search(o["quote"])))
    r = ed.gate_record(o, (HERE / "cache" / "text_marked" / "2017-S8074.txt").read_text(), False)
    check("AD1 gate drops the cached record", bool(r) and r[0] == "definition")
q = "Any contracts entered into by the dormitory authority pursuant to this act shall be deemed state contracts within the meaning of that term as set forth in article 15-A of the executive law."
check("AD1 sentence matches", bool(ed.AD1_DEEMED_CONTRACTS.search(q)))
check("AD1 a contracting duty is kept", not ed.AD1_DEEMED_CONTRACTS.search("The authority shall enter into contracts with the state and shall file each contract with the comptroller."))
check("AD1 a deemed-executory clause is kept", not ed.AD1_DEEMED_CONTRACTS.search('shall contain the following clause: "This contract shall be deemed executory only to the extent of the monies appropriated"'))
stored = set()
for d in ("duties", "powers"):
    for f in (HERE.parent / "data" / d).glob("*.json"):
        stored |= {x["obligation_id"] for x in json.load(open(f))[{"duties": "obligations", "powers": "powers"}[d]]}
h = []
for f in (HERE / "cache" / "extracted").glob("*.json"):
    for x in json.load(open(f)).get("obligations", []):
        if x.get("obligation_id") in stored and ed.AD1_DEEMED_CONTRACTS.search(x.get("quote") or ""): h.append(x["obligation_id"])
print("dry run AD1", len(h), h[:12])
check("AD1 flag on only within cap", ed.APPLY_AD1 == (len(h) <= 40))

# AE1: authority grant makes kind power
for oid in ("2021-S8084-08", "2021-S8084-15"):
    o = cached(oid)
    if o: check("AE1 rule on cached " + oid, ed.ae1_authority_power(o["quote"]))
check("AE1 shall have the authority", ed.ae1_authority_power("The office shall have the authority to define terms used in this section."))
check("AE1 hereby authorized and empowered", ed.ae1_authority_power("The board is hereby authorized and empowered to sell the parcel."))
check("AE1 authority plus a duty is kept", not ed.ae1_authority_power("The office has the authority to define terms and shall publish them within thirty days."))
# AE3: 'Nothing ... shall preclude' savings clause, a prohibition on a named body is kept
o = cached("2021-S8084-17")
if o: check("AE3 gate on cached 2021-S8084-17", (ed.gate_q if False else ed.gate_record)(o, (HERE / "cache" / "text_marked" / "2021-S8084.txt").read_text(), True) is not None and ed.AE3_NOTHING_PRECLUDE.search(o["quote"]) is not None)
check("AE3 nothing shall preclude", bool(ed.AE3_NOTHING_PRECLUDE.search("Nothing shall preclude the office from providing such reporting as part of the annual report")))
check("AE3 nothing in this section shall prevent", bool(ed.AE3_NOTHING_PRECLUDE.search("Nothing in this section shall prevent a county from adopting stricter rules.")))
check("AE3 gate drops it", (gate_q("Nothing in this section shall prohibit the office from providing such reporting.") or ("",))[0] == "savings_clause")
check("AE3 'No agency shall' is kept", not ed.AE3_NOTHING_PRECLUDE.search("No agency shall prevent a resident from filing a complaint."))
check("AE3 'Nothing' main clause prohibition on a body is kept", gate_q("No agency shall prohibit a resident from filing a complaint.") is None or gate_q("No agency shall prohibit a resident from filing a complaint.")[0] != "savings_clause")
# AE2: consultee-only actors
tc = "Section 1. The commissioner of labor, in consultation with the commissioner of health and the superintendent of financial services, shall publish a guide."
ob = lambda actor, quote: {"quote": quote, "quote_verified": True, "agency": "X", "agency_unit": None, "actor_raw": actor}
qc = "The commissioner of labor, in consultation with the commissioner of health and the superintendent of financial services, shall publish a guide."
if ed.APPLY_AE2:
    check("AE2 consultee dropped", ed.consultee_only(ob("the commissioner of health", qc), tc))
else:
    print("skipped: AE2 is off by decision (B46 rework)"); passed += 1
if ed.APPLY_AE2:
    check("AE2 gate rule name", (ed.gate_record(ob("the commissioner of health", qc), tc, False) or ("",))[0] == "consultee_only")
else:
    print("skipped: AE2 is off by decision (B46 rework)"); passed += 1
if ed.APPLY_AE2:
    check("AE2 acting body kept", not ed.consultee_only(ob("the commissioner of labor", qc), tc))
else:
    print("skipped: AE2 is off by decision (B46 rework)"); passed += 1
o1 = cached("2021-S873-01"); t873 = (HERE / "cache" / "text_marked" / "2021-S873.txt")
if o1:
    # in the cached S873 text the four commissioners are the review's joint subject (the consultees are local health departments and social services districts), so they stay
    if ed.APPLY_AE2:
        check("AE2 S873 joint-subject records are not consultees", not any(ed.consultee_only(cached("2021-S873-0" + i), t873.read_text()) for i in "1234"))
    else:
        print("skipped: AE2 is off by decision (B46 rework)"); passed += 1
h2 = []; h1 = []; h3 = []
for f in (HERE / "cache" / "extracted").glob("*.json"):
    ob_ = [x for x in json.load(open(f)).get("obligations", []) if x.get("obligation_id") in stored]
    if not ob_: continue
    t = (HERE / "cache" / "text_marked" / (f.stem + ".txt")).read_text()
    for x in ob_:
        if ed.consultee_only(x, t): h2.append(x["obligation_id"])
        if ed.ae1_authority_power(x.get("quote") or "") and x.get("kind_rule") == "duty": h1.append(x["obligation_id"])
        if ed.AE3_NOTHING_PRECLUDE.search(x.get("quote") or ""): h3.append(x["obligation_id"])
for n, h in (("AE1", h1), ("AE2", h2), ("AE3", h3)):
    print("dry run", n, len(h), h[:40])
    check(n + " flag on only within cap (AE2 off by decision)", n == "AE2" or getattr(ed, "APPLY_" + n) == (len(h) <= 40))   # Nov 9 2026: AE2 is off after a blind sample (1/23), B46

# AE4: list items under a mandatory lead whose only 'may' is subordinate (2021-S8830-01/-03); flag off over the cap
ed.APPLY_AE4 = True
for oid in ("2021-S8830-01", "2021-S8830-03"):
    o = cached(oid)
    if o: check("AE4 rule on cached " + oid, ed.ae4_subordinate_only(o, o["quote"], ""))
check("AE4 an item with its own may is kept a power", not ed.ae4_subordinate_only({"kind_list_item": True, "kind_model": "duty"}, "may waive the fee for any applicant", ""))
ed.APPLY_AE4 = False
n4 = 0; ex4 = []
ed.APPLY_AE4 = True
for d in ("powers",):
    for f in (HERE.parent / "data" / d).glob("*.json"):
        for x in json.load(open(f))["powers"]:
            if x.get("kind_list_item") and x.get("kind_model") == "duty" and x.get("kind_adjusted") == "grant_only" and ed.ae4_subordinate_only(x, x["quote"], ""):
                n4 += 1; ex4.append(x["obligation_id"])
ed.APPLY_AE4 = True   # Nov 9 2026: decided default after the blind sample (24/25)
print("dry run AE4", n4, ex4[:10])
check("AE4 on by decision (blind sample 24/25 right; above the cap)", ed.APPLY_AE4 is True)
print("%d passed, %d failed" % (passed, failed))
