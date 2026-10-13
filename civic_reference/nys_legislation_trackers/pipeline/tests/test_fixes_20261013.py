"""Plain script: the Oct 13 2026 audit fixes M20-M24 and J9-J10. Uses stored data when present. Prints 'N passed, M failed'."""
import json, os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import effective_date as efd
import agency_resolve_nys as ar

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

TM = HERE / "cache" / "text_marked"
DATA = HERE.parent / "data"
def stored(key):
    y = key[:4]
    out = []
    for f, k in (("duties", "obligations"), ("powers", "powers")):
        p = DATA / f / (y + ".json")
        if p.exists():
            out += [x for x in json.load(open(p))[k] if x["obligation_id"] == key or x["matter_id"] == key]
    return out
def rec(oid):
    return next((x for x in stored(oid[:oid.rindex("-")]) if x["obligation_id"] == oid), None)


# M20. section dates in numbered provisos
c = ("§ 7. This act shall take effect on the thirtieth day after it shall have become a law, provided, however, that: 1. retailers shall have sixty days "
     "from the effective date of this act to sell through product; 2. sections three, four and five of this act shall take effect January 1, 2012; "
     "3. persons may continue to use it; and 4. section two of this act shall take effect on the ninetieth day after it shall have become a law.")
e = efd.parse_effective(c, "2010-07-15")
sd = {x["applies_to"]: x for x in e["section_dates"]}
check("M20 sections three, four and five -> 2012-01-01", sd.get("sections three, four and five of this act", {}).get("effective_date") == "2012-01-01")
check("M20 section two -> signed + 90 days", sd.get("section two of this act", {}).get("effective_date") == "2010-10-13")
check("M20 the act's own date is untouched", e["effective_date"] == "2010-08-14")
check("M20 'from the effective date of this act' is not a section date", len(e["section_dates"]) == 2)
check("M20 lettered proviso", any(x["effective_date"] == "2013-07-01" for x in efd.parse_effective("§ 5. This act shall take effect immediately, provided that: (a) section three of this act shall take effect July 1, 2013.", "2010-07-15")["section_dates"]))
check("M20 the expiration-keyed form is not dated", all(x["effective_date"] is None for x in efd.parse_effective("§ 5. This act shall take effect immediately; provided that: 1. section two of this act shall take effect upon the expiration of section 4 of chapter 3.", "2010-07-15")["section_dates"]))
tx = TM / "2009-S3780.txt"
if tx.exists():
    e = efd.parse_effective(tx.read_text(), "2010-07-15")
    check("M20 2009-S3780 sections three-six -> 2012-01-01", any(x["effective_date"] == "2012-01-01" and ed._section_set(x["applies_to"]) == {3, 4, 5, 6} for x in e["section_dates"]))
r = rec("2009-S3780-01")
check("M20 stored 2009-S3780-01 -> 2012-01-01", bool(r) and r["effective_date"] == "2012-01-01")
r = rec("2009-S3780-02")
check("M20 stored 2009-S3780-02 -> 2012-01-01", bool(r) and r["effective_date"] == "2012-01-01")

# M21. section-scoped sunset
c = "§ 2. This act shall take effect on the one hundred twentieth day after it shall have become a law; provided, however that the amendments made by section one of this act shall expire and be deemed repealed April 1, 2015."
two = "§ 1. Subdivision 1 of section 5 of the education law is amended to read as follows: x.\n\n" + c
e = efd.parse_effective(two, "2011-12-01")
check("M21 single substantive section -> expires_date", e["expires_date"] == "2015-04-01")
three = "§ 1. Subdivision 1 of section 5 is amended to read as follows: x.\n\n§ 2. Section 6 is amended to read as follows: y.\n\n" + c.replace("§ 2.", "§ 3.")
e = efd.parse_effective(three, "2011-12-01")
check("M21 two substantive sections -> stored per section", e["expires_date"] is None and any(x.get("expires_date") == "2015-04-01" and x["rule"] == "section_expiry" for x in e["section_dates"]))
check("M21 a section expiry is not a section effective date", all(x["effective_date"] is None for x in e["section_dates"]))
p = DATA / "effective_dates" / "2011.json"
if p.exists():
    check("M21 stored 2011-A7487 expires 2015-04-01", json.load(open(p))["2011-A7487"]["expires_date"] == "2015-04-01")

# M22. passive benefit sentences
o = {"actor_raw": "Interest", "quote": "Interest shall be allowed at the Rate of seven percent per annum, compounded annually"}
check("M22 Interest shall be allowed", ed.benefit_entitlement(o, o["quote"]))
o = {"actor_raw": "social services districts", "quote": "shall not be required to pay more than thirty percent of his or her monthly income toward the cost of rent"}
check("M22 shall not be required to pay", ed.benefit_entitlement(o, o["quote"]))
o = {"actor_raw": "the retirement system", "quote": "Each member shall be credited with one month of service for each month worked"}
check("M22 shall be credited with", ed.benefit_entitlement(o, o["quote"]))
o = {"actor_raw": "the department", "quote": "The department shall be reimbursed by the county for such costs"}
check("M22 a government subject stays", not ed.benefit_entitlement(o, o["quote"]))
o = {"actor_raw": "the commissioner", "quote": "The commissioner shall report annually to the governor"}
check("M22 an unrelated duty stays", not ed.benefit_entitlement(o, o["quote"]))
check("M22 stored 2009-A40026-04 dropped", rec("2009-A40026-04") is None)
check("M22 stored 2013-S6358-15 dropped", rec("2013-S6358-15") is None)

# M23. relocate_quote never lands on an amending instruction
r = rec("2015-A7996-01")
check("M23 2015-A7996-01 quote is not an instruction", bool(r) and not ed.AMEND_INSTR.search(r["quote"]))
for s in ("is amended to read as follows:", "is hereby amended by adding a new section", "is REPEALED", "are renumbered"):
    check("M23 instruction pattern: " + s, bool(ed.AMEND_INSTR.search("Section 5 of the law " + s)))
check("M23 an operative sentence is not an instruction", not ed.AMEND_INSTR.search("The commissioner shall report annually"))
t = "§ 1. Section 5 of the law, as added by part {{ii}} of chapter 9, is amended to read as follows:\n\nThe old sentence here stays unchanged and is long enough.\n\n§ 2. This act shall take effect immediately."
check("M23 only an instruction holds braces -> None", ed.relocate_quote("The old sentence here stays unchanged and is long enough.", t) is None)

# M24. act-clause boilerplate
o = {"quote_verified": True, "actor_raw": "the chair", "quote": "the chair shall notify the legislative bill drafting commission upon the occurrence of the commencement of operation in order that the commission may maintain an accurate and timely effective data base"}
g = ed.gate_record(o, o["quote"], False)
check("M24 bill drafting commission notice -> act_clause_boilerplate", bool(g) and g[0] == "act_clause_boilerplate")
check("M24 stored: no record carries the notice", not any(ed.BDC_NOTIFY.search(x["quote"]) for y in (2009, 2011, 2013, 2015) for f, k in (("duties", "obligations"), ("powers", "powers")) for x in json.load(open(DATA / f / ("%d.json" % y)))[k]))

# J9. approver as actor
o = {"actor_raw": "the director of the budget", "quote": "as determined by the commissioner of health and approved by the director of the budget, the payments shall be reduced"}
check("J9 approver only", ed.approver_only_actor(o))
o = {"actor_raw": "the commissioner", "quote": "the commissioner shall issue rules, subject to the approval of the director of the budget"}
check("J9 the acting body is not flagged", not ed.approver_only_actor(o))
o = {"actor_raw": "the director of the budget", "quote": "the director of the budget shall review and approve, and such plan shall be approved by the director of the budget"}
check("J9 an actor named as actor too is not flagged", not ed.approver_only_actor(o))
fl = ed.judgment_flags("x", [{"actor_raw": "the director of the budget", "quote": "paid as determined by the commissioner and approved by the director of the budget", "session": 2013}])
check("J9 flag approver_as_actor carries the quote", any(f["check"] == "approver_as_actor" and f["sentences"] for f in fl))
p = DATA / "reask" / "2013.json"
if p.exists():
    ent = json.load(open(p))["laws"].get("2013-S6358")
    check("J9 2013-S6358 in data/reask with approver_as_actor", bool(ent) and any(r["check"] == "approver_as_actor" for r in ent["reasons"]))

# J10. manual re-ask entries
man = json.load(open(DATA / "reask_manual.json"))["laws"]
check("J10 the four laws carry night 20261013", all(any(x["night"] == "20261013" for x in man.get(k, [])) for k in ("2009-S3780", "2009-A40026", "2013-S6358", "2015-A7996")))
p = DATA / "reask" / "2009.json"
if p.exists():
    ent = json.load(open(p))["laws"].get("2009-S3780")
    check("J10 2009-S3780 in data/reask with audit_confirmed_miss", bool(ent) and any(r["check"] == "audit_confirmed_miss" for r in ent["reasons"]))

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
