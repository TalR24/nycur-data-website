"""Plain script: the Oct 14 2026 audit fixes M30-M34 and J13-J14. Uses stored data when present. Prints 'N passed, M failed'."""
import json, os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import agency_resolve_nys as ar

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
            out += [x for x in json.load(open(p))[k] if x["obligation_id"] == key or x["matter_id"] == key]
    return out
def rec(oid):
    return next((x for x in stored(oid[:oid.rindex("-")]) if x["obligation_id"] == oid), None)

# M30. implementation precondition
q = "shall not be implemented until the chancellor of the city university of New York, the commissioner of the New York city office of labor relations and the director of employee relations of the state of New York shall have delivered to the director of the budget and the comptroller of the state of New York a certificate"
g = ed.gate_record({"quote_verified": True, "quote": q, "actor_raw": "the chancellor"}, "", False)
check("M30 precondition quote is dropped as condition_precedent", bool(g) and g[0] == "condition_precedent")
q2 = "The commissioner shall not pay any claim until the board approves the claim"
check("M30 a plain 'until' prohibition is not matched", not ed.CONDITION_PRECEDENT.search(q2))
check("M30 stored 2009-A8898-02 gone", rec("2009-A8898-02") is None)

# M31. parallel provisions for different named persons
a = "Upon the receipt of such application, Laura Strizzi shall be granted Tier V status in the New York state and local employees' retirement system and be eligible for all the rights and benefits thereof."
b = a.replace("Laura Strizzi", "Kirsten Mason")
check("M31 different personal names are distinct provisions", ed.distinct_provisions({"quote": a}, {"quote": b}))
check("M31 identical quotes are not distinct", not ed.distinct_provisions({"quote": a}, {"quote": a}))
check("M31 one side adding a word is not distinct", not ed.distinct_provisions({"quote": "The board of Albany shall act"}, {"quote": "The board of Albany County shall act"}))
check("M31 stored 2013-S6935 keeps all four", all(rec("2013-S6935-0%d" % i) for i in (1, 2, 3, 4)))

# M32. salary entitlement
r = {"actor_raw": "the state", "quote": "the basic annual salary of officers and employees in full-time employment status on the day before such payroll period shall be increased by two percent adjusted to the nearest whole dollar amount."}
check("M32 2011-S6960-01 shape is dropped", ed.benefit_entitlement(r, r["quote"]))
q = "The director of the budget shall determine how salaries shall be increased by the comptroller"
check("M32 an increase by a named official stays", not ed.salary_entitlement(q))
check("M32 'shall receive a salary increase'", ed.salary_entitlement("Employees in the unit shall receive a salary increase of three percent"))
check("M32 stored 2011-S6960-01 gone", rec("2011-S6960-01") is None)

# M33. NYC school actors
t = "§ 1. Section 2590-h of the education law is amended. The city school district of the city of New York shall act. article 52-A of the education law"
o = {"actor_raw": "the principal", "agency": "Unspecified", "agency_unit": None}
check("M33 principal -> NYCPS", ar.fix_nyc_school_actor(o, t, ed.NYC_BY) and o["agency"] == "NYCPS" and o["jurisdiction"] == "nyc")
o = {"actor_raw": "the board of education", "agency": "School districts", "agency_unit": None}
check("M33 board of education -> NYCPS", ar.fix_nyc_school_actor(o, t, ed.NYC_BY) and o["agency"] == "NYCPS")
o = {"actor_raw": "the board of education", "agency": "School districts", "agency_unit": None}
check("M33 an unrelated law is untouched", not ar.fix_nyc_school_actor(o, "The board of education of the Buffalo school district shall act.", ed.NYC_BY) and o["agency"] == "School districts")
o = {"actor_raw": "the chancellor", "agency": "Unspecified", "agency_unit": None}
check("M33 a bare chancellor needs the city school district named", not ar.fix_nyc_school_actor(o, "section 2590-x. the chancellor of the city university", ed.NYC_BY))
for oid in ("2011-A7259-01", "2011-A7259-02"):
    r = rec(oid)
    check("M33 stored " + oid, bool(r) and r["agency"] == "NYCPS" and r["jurisdiction"] == "nyc")

# M34. assessing units
o = {"actor_raw": "approved assessing unit in the county of Nassau", "agency": "Counties", "agency_unit": "County of Nassau"}
check("M34 assessing unit -> Municipalities (all) with county context", ar.fix_assessing_unit(o) and o["agency"] == "Municipalities (all)" and o["agency_unit"] is None and o["actor_context"] == "County of Nassau")
o = {"actor_raw": "assessing units", "agency": "Unspecified"}
check("M34 bare assessing units", ar.fix_assessing_unit(o) and o["agency"] == "Municipalities (all)" and "actor_context" not in o)
check("M34 a county actor is untouched", not ar.fix_assessing_unit({"actor_raw": "the county of Nassau", "agency": "Counties"}))
r = rec("2011-A9012-01")
check("M34 stored 2011-A9012-01", bool(r) and r["agency"] == "Municipalities (all)" and r.get("actor_context") == "County of Nassau")

# J13. joint officials
q = "any increase in compensation may be withheld in whole or in part from any employee when, in the opinion of the director of the budget and the director of employee relations, such increase is not warranted"
r1 = {"actor_raw": "the director of the budget", "quote": q}
check("J13 one record for two officials is flagged", ed.joint_actor_single(r1, [r1]))
check("J13 a sibling with the same quote clears it", not ed.joint_actor_single(r1, [r1, {"actor_raw": "the director of employee relations", "quote": q}]))
fl = ed.judgment_flags("", [r1])
check("J13 judgment_flags carries joint_actor_single", any(f["check"] == "joint_actor_single" for f in fl))
ru = DATA / "reask" / "2011.json"
if ru.exists():
    check("J13 stored reask 2011-S6960 has joint_actor_single", any(x["check"] == "joint_actor_single" for x in json.load(open(ru))["laws"]["2011-S6960"]["reasons"]))

# J14. audit-confirmed misses
m = json.load(open(DATA / "reask_manual.json"))["laws"]
for k in ("2011-S6960", "2013-S4800", "2011-A7259", "2013-A371", "2011-A9012", "2009-A8956", "2011-S5157"):
    check("J14 manual misses for " + k, any(i["night"] == "20261014" for i in m.get(k, [])))
if ru.exists():
    check("J14 2011-S6960 in data/reask with audit_confirmed_miss", any(x["check"] == "audit_confirmed_miss" for x in json.load(open(ru))["laws"]["2011-S6960"]["reasons"]))

print("%d passed, %d failed" % (passed, failed))
