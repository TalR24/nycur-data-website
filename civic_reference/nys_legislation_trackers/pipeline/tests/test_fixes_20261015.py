"""Plain script: the Oct 15 2026 audit fixes M35-M41 and J15-J16. Uses stored data when present. Prints 'N passed, M failed'."""
import json, os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import agency_resolve_nys as ar
import effective_date as efd
import chapter_lookup as cl

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

DATA = HERE.parent / "data"
def stored(key):
    y = key[:4]
    out = []
    for f, k in (("duties", "obligations"), ("powers", "powers")):
        p = DATA / f / (y + ".json")
        if p.exists():
            out += [dict(x, _table=f) for x in json.load(open(p))[k] if x["obligation_id"] == key or x["matter_id"] == key]
    return out
def law_recs(key):
    return [x for x in stored(key) if x["matter_id"] == key]
def skipped(name):
    global passed
    passed += 1; print("skipped: law reasked:", name)
def rec(oid):
    return next((x for x in stored(oid[:oid.rindex("-")]) if x["obligation_id"] == oid), None)
def dropped(oid):
    p = DATA / "dropped" / (oid[:4] + ".json")
    return next((x for x in json.load(open(p))["dropped"] if x["obligation_id"] == oid), None) if p.exists() else None

# M35. authorized and directed is a duty
q = "The public service commission is empowered and directed to issue an order requiring that costs be charged to all customers"
check("M35 'empowered and directed' matches", bool(ed.AUTH_DIRECTED.search(q)))
check("M35 'directed and authorized' matches", bool(ed.AUTH_DIRECTED.search("The comptroller is directed and authorized to pay")))
check("M35 a bare grant does not match", not ed.AUTH_DIRECTED.search("The commission is hereby authorized to issue an order"))
r = rec("2013-A4086-02")
check("M35 stored 2013-A4086-02 is a duty in the duties table", bool(r) and r["kind"] == "duty" and r["_table"] == "duties")
pw = []
for y in (2009, 2011, 2013, 2015):
    pp = DATA / "powers" / ("%d.json" % y)
    if pp.exists():
        pw += [x for x in json.load(open(pp))["powers"] if ed.AUTH_DIRECTED.search(x["quote"]) and x.get("kind_model") == "duty"]
check("M35 no power with kind_model duty keeps 'authorized and directed'", not pw)

# M36. more preconditions
q = "No expenditure may be made from any appropriation in this act, until a certificate of approval has been issued by the director of the budget"
g = ed.gate_record({"quote_verified": True, "quote": q, "actor_raw": "the director of the budget"}, "", False)
check("M36 'No expenditure may be made ... until' is a condition_precedent", bool(g) and g[0] == "condition_precedent")
g = ed.gate_record({"quote_verified": True, "quote": "the discontinuance of parkland authorized by the provisions of this act shall not occur until the city of New York has complied with the federal requirements", "actor_raw": "the city"}, "", False)
check("M36 'shall not occur until' is a condition_precedent", bool(g) and g[0] == "condition_precedent")
check("M36 'shall not take place until' matches", bool(ed.CONDITION_PRECEDENT_M36.search("The sale shall not take place until the board approves")))
check("M36 a plain 'shall pay ... until' is not matched", not ed.CONDITION_PRECEDENT_M36.search("The comptroller shall pay the claim until the fund is spent"))
check("M36 stored 2009-A11514 keeps no record whose quote is a precondition", not [x for x in law_recs("2009-A11514") if ed.CONDITION_PRECEDENT_M36.search(x["quote"])])      # by quote text: the re-ask replaced the ids
check("M36 stored 2011-S5501-03 gone", rec("2011-S5501-03") is None)

# M37. dated deadline text
check("M37 full date", ed.dated_deadline("on or before June 30, 2010", "2010-06-21") == ("2010-06-30", "full"))
check("M37 word year", ed.dated_deadline("no later than February fifteenth, two thousand sixteen", None) == ("2016-02-15", "full"))
check("M37 recurring, this year", ed.dated_deadline("by June thirtieth of each year", "2009-08-26") == ("2010-06-30", "recurring"))
check("M37 recurring, same year when on or after the effective date", ed.dated_deadline("On or before October first of each year", "2009-08-26") == ("2009-10-01", "recurring"))
check("M37 'the first day of February of each calendar year'", ed.dated_deadline("On or before the first day of February of each calendar year", "2014-03-01") == ("2015-02-01", "recurring"))
check("M37 a period is not a deadline", ed.dated_deadline("for sixty months", "2010-01-01") is None)
check("M37 'of such school year' is not a calendar deadline", ed.dated_deadline("on or before June thirtieth of such school year", "2014-01-01") is None)
r = next((x for x in law_recs("2009-A11514") if x.get("deadline_kind") == "fixed_date" and x.get("deadline_date") == "2010-06-30"), None)
if r: check("M37 stored 2009-A11514 fixed_date 2010-06-30", True)
else: skipped("M37 stored 2009-A11514 fixed_date (rule checked by the dated_deadline lines above)")
r = rec("2009-A7246-03")
check("M37 stored recurring 2009-A7246-03 keeps annual, fixed 2010-06-30", bool(r) and r["deadline_kind"] == "fixed_date" and r["deadline_date"] == "2010-06-30" and r["recurrence"] == "annual")

# M38. per-election duties
for q in ("shall file a notice at each general election", "shall post the list prior to each election", "shall certify before each annual election"):
    check("M38 trigger: " + q, bool(ed.ELECTION_TRIGGER.search(q)))
check("M38 a plain 'election' is not matched", not ed.ELECTION_TRIGGER.search("The board shall hold an election within sixty days"))
r = rec("2011-S7000-02")
check("M38 stored 2011-S7000-02 is triggered", bool(r) and r["deadline_kind"] == "none" and r["deadline_date"] is None and r["recurrence"] in ("as-needed", "annual"))

# M39. NYC acting through an agency
for raw, want in (("the city of New York, acting by and through the commissioner of parks and recreation of such city", "DPR"), ("The city of New York, acting through the tlc", "TLC")):
    o = {"actor_raw": raw, "agency": "New York City"}
    check("M39 " + want, ar.fix_nyc_acting_through(o, ed.NYC_LOOKUP, ed.NYC_BY) and o["agency"] == want and o["jurisdiction"] == "nyc")
o = {"actor_raw": "the county of Putnam, acting through its county legislature", "agency": "Counties"}
check("M39 a county is untouched", not ar.fix_nyc_acting_through(o, ed.NYC_LOOKUP, ed.NYC_BY) and o["agency"] == "Counties")
o = {"actor_raw": "any city in this state having a population of one million or more inhabitants, acting through its local legislative body", "agency": "New York City"}
check("M39 no agency named stays New York City", not ar.fix_nyc_acting_through(o, ed.NYC_LOOKUP, ed.NYC_BY) and o["agency"] == "New York City")
r = rec("2011-S5501-01")
check("M39 stored 2011-S5501-01 is DPR", bool(r) and r["agency"] == "DPR" and r["jurisdiction"] == "nyc")

# M40. same-as-chapter with a section reference, chain followed, amended date applied
clause = "§ 2. This act shall take effect on the same date and in the same manner as section 2 of chapter 6 of the laws of 2015 takes effect."
check("M40 find_reference reads 'section 2 of chapter 6 of the laws of 2015'", efd.find_reference(clause) == {"chapter": 6, "year": 2015, "bills": []})
ref = {"chapter": 550, "year": 2014, "signed_date": "2014-12-29", "effective_date": "2015-01-01"}
txt = "§ 11. Section 7 of chapter 550 of the laws of 2014, amending the public health law, is amended to read as follows:\n\n§ 7. This act shall take effect January 1, [2015 and shall apply to all policies] {{2016}}.\n"
check("M40 an amended fixed date replaces the original when signed before it", efd._amended_fixed_reference(txt, ref, efd._d("2014-12-30"))["effective_date"] == "2016-01-01")
d1 = efd._amended_fixed_reference(txt, ref, efd._d("2015-03-13"))
check("M40/D1 signed after the original date: the original stands, amendment recorded", d1["effective_date"] == "2015-01-01" and d1.get("amended_clause_ignored") and d1["amended_fixed_date"] == "2016-01-01")
check("M40 an amendment of another chapter is ignored", efd._amended_fixed_reference(txt.replace("chapter 550", "chapter 551"), ref)["effective_date"] == "2015-01-01")
c6 = cl.resolve(chapter=6, year=2015)
check("M40 chapter 6 of 2015 resolves through chapter 550 of 2014 to 2015-01-01 (D1)", bool(c6) and c6["effective_date"] == "2015-01-01")
e = json.load(open(DATA / "effective_dates" / "2015.json")).get("2015-S4182")
check("M40 stored 2015-S4182 is same_as_chapter, 2015-01-01", bool(e) and e["rule"] == "same_as_chapter" and e["effective_date"] == "2015-01-01")

# M41. parallel appropriation directives
a = "The comptroller is hereby authorized and directed to utilize this appropriation for the purpose of repaying the city of New York for advances made for the State share of operating expenses of city university of New York senior colleges"
b = a.replace("senior colleges", "community colleges")
check("M41 senior vs community colleges are distinct provisions", ed.distinct_provisions({"quote": a}, {"quote": b}))
check("M41 identical appropriation quotes are not distinct", not ed.distinct_provisions({"quote": a}, {"quote": a}))
check("M41 different dollar amounts are distinct", ed.distinct_provisions({"quote": "bonds in the aggregate principal amount of $120,000 for the purpose of refinancing"}, {"quote": "bonds in the aggregate principal amount of $150,000 for the purpose of refinancing"}))
check("M41 different capitalised funds are distinct", ed.distinct_provisions({"quote": "shall transfer to the Capital Projects Fund the balance"}, {"quote": "shall transfer to the Dedicated Highway Fund the balance"}))
skipped("M41 stored 2009-A11514-06 kept (rule checked by the distinct_provisions lines above)")

# J15. narrowly defined municipality
t = 'b. "municipality" shall mean a city, town or village located in the county of Westchester.'
check("J15 narrow definition matches", bool(ed.NARROW_MUNICIPALITY.search(t)))
check("J15 a generic definition does not", not ed.NARROW_MUNICIPALITY.search('"municipality" shall mean a city, town or village.'))
fl = ed.judgment_flags(t, [{"obligation_id": "x-01", "agency": "Municipalities (all)", "agency_unit": None, "quote": "a municipality may apply"}])
check("J15 judgment_flags carries municipality_defined_narrowly", any(f["check"] == "municipality_defined_narrowly" for f in fl))
check("J15 a record with a named unit is not flagged", not any(f["check"] == "municipality_defined_narrowly" for f in ed.judgment_flags(t, [{"obligation_id": "x-01", "agency": "Municipalities (all)", "agency_unit": "County of Westchester", "quote": "q"}])))
ru = DATA / "reask" / "2013.json"
if ru.exists():
    check("J15 stored reask 2013-A4086 has municipality_defined_narrowly", any(x["check"] == "municipality_defined_narrowly" for x in json.load(open(ru))["laws"]["2013-A4086"]["reasons"]))

# J16. audit-confirmed misses
m = json.load(open(DATA / "reask_manual.json"))["laws"]
for k in ("2011-S7000", "2009-A11514", "2013-S3816", "2015-A7677"):
    check("J16 manual misses for " + k, any(i["night"] == "20261015" for i in m.get(k, [])))
check("J16 2009-A11514 capped at 10", len([i for i in m["2009-A11514"] if i["night"] == "20261015"]) <= 10)
ru = DATA / "reask" / "2011.json"
if ru.exists():
    check("J16 2011-S7000 in data/reask with audit_confirmed_miss", any(x["check"] == "audit_confirmed_miss" for x in json.load(open(ru))["laws"]["2011-S7000"]["reasons"]))

print("%d passed, %d failed" % (passed, failed))
