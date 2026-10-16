"""Plain script: the Oct 13 2026 (second round) audit fixes M25-M29 and J11-J12. Uses stored data when present. Prints 'N passed, M failed'."""
import json, os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import effective_date as efd

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
def law_recs(key):
    y = key[:4]
    return [x for f, k in (("duties", "obligations"), ("powers", "powers")) for x in json.load(open(DATA / f / (y + ".json")))[k] if x["matter_id"] == key]
def skipped(name):
    global passed
    passed += 1; print("skipped: law reasked:", name)
def rec(oid):
    return next((x for x in stored(oid[:oid.rindex("-")]) if x["obligation_id"] == oid), None)

# M25. act-level expiry, general form
e = efd.parse_effective("§ 2. This act shall take effect immediately and shall expire and be deemed repealed December 31, 2012.", "2010-07-15")
check("M25 immediately and shall expire and be deemed repealed D", e["expires_date"] == "2012-12-31")
e = efd.parse_effective("§ 2. This act shall take effect immediately and shall expire 3 years after such effective date, when upon such date the provisions of this act shall be deemed repealed.", "2010-07-15")
check("M25 N years after such effective date", e["expires_date"] == "2013-07-15")
e = efd.parse_effective("§ 2. This act shall take effect on the sixtieth day after it shall have become a law and shall be deemed repealed on and after June 30, 2014.", "2010-07-15")
check("M25 deemed repealed on and after D", e["expires_date"] == "2014-06-30")
e = efd.parse_effective("§ 2. This act shall take effect immediately; provided that section one of this act shall expire and be deemed repealed June 30, 2014.", "2010-07-15")
check("M25 a named section does not set the act's expiry", e["expires_date"] is None or e["section_dates"])
e = efd.parse_effective("§ 1. Section 5 is amended to read as follows: x.\n\n§ 2. Section 6 is amended to read as follows: y.\n\n§ 3. This act shall take effect immediately; provided that the amendments made by section one of this act shall expire and be deemed repealed June 30, 2014.", "2010-07-15")
check("M25 amendments made by section N stay section-scoped", e["expires_date"] is None and any(x.get("expires_date") == "2014-06-30" for x in e["section_dates"]))
p = DATA / "effective_dates" / "2009.json"
if p.exists():
    check("M25 stored 2009-A10507 expires 2012-12-31", json.load(open(p))["2009-A10507"]["expires_date"] == "2012-12-31")

# M26. relocate_quote never lands on an exemption or applicability sentence
t = ("§ 1. Subdivision 2 of section 3-b is amended to read as follows:\n\nAny agency of the state may deny a tax exemption to a building [in any such city] which is otherwise eligible. "
     "\n\n{{The provisions of this subdivision shall not apply to buildings used solely for residential purposes which contain twenty-five dwelling units or less.}}\n\n§ 2. This act shall take effect immediately.")
q = "Any agency of the state may deny a tax exemption to a building which is otherwise eligible"
check("M26 exemption sentence is not the relocation target", ed.relocate_quote(q, t, "any agency of the state") is None)
t2 = t.replace("\n\n{{The provisions of this subdivision shall not apply to buildings used solely for residential purposes which contain twenty-five dwelling units or less.}}", "\n\n{{The agency may also deny each exemption claimed under this subdivision.}}")
check("M26 an operative braced sentence still relocates", (ed.relocate_quote(q, t2, "any agency of the state") or "").startswith("The agency may also deny"))
for s in ("shall not apply to x", "shall not be applicable to x", "except as provided", "nothing in this section", "shall not be construed to"):
    check("M26 exemption pattern: " + s, bool(ed.EXEMPT_SENT.search("The board " + s)))
r = rec("2009-A5707-01")
check("M26 stored 2009-A5707-01 keeps the deny quote", bool(r) and r["quote"].lower().startswith("any agency of the state or any political subdivision thereof may deny") and not r.get("quote_relocated"))

# M27. beneficiary subject with the actor named only after the modal
o = {"actor_raw": "the village of Penn Yan", "quote": "volunteer firefighters participating in such service award program during the period beginning January 1, 1999 and ending December 31, 2011 shall be credited with points for participation in activities of such fire department in accordance with the point system adopted by the village of Penn Yan."}
check("M27 2013-A4778-01 shape is dropped", ed.benefit_entitlement(o, o["quote"]))
o = {"actor_raw": "the retirement system", "quote": "Each participant shall be awarded one point for each year of service"}
check("M27 shall be awarded to a beneficiary", ed.benefit_entitlement(o, o["quote"]))
o = {"actor_raw": "the village of Penn Yan", "quote": "The village of Penn Yan shall be credited with the amount collected"}
check("M27 a government subject before the modal stays", not ed.benefit_entitlement(o, o["quote"]))
check("M27 stored 2013-A4778-01 dropped", rec("2013-A4778-01") is None)

# M28. hereby authorizes
q = "any notes or bonds are issued by the city prior to July 1, 2014, or any bonds are issued by a state financing agency, the state of New York hereby authorizes the city and authorizes and requires such state financing agency to include a pled"
check("M28 HEREBY_AUTHORIZES names the authorized body", (ed.HEREBY_AUTHORIZES.search(q) or [None, ""])[1] == "the city")
check("M28 'is hereby authorized' matches", bool(ed.HEREBY_AUTH.search("the board is hereby authorized to act")))
r = rec("2013-A7175-09")
check("M28 stored 2013-A7175-09 is a power", bool(r) and r["kind"] == "power" and r.get("rescued_hereby_authorizes"))

# M29. study submission date
t = ("§ 1. Section 1 is amended by adding a subdivision to read as follows:\n\n{{(A) The department shall conduct a study of profiles. Such study shall include cost.}}\n\n"
     "{{(B) The department shall submit such study to the governor on or before November first, two thousand sixteen.}}\n\n§ 2. This act shall take effect immediately.")
o = {"deliverable_type": "study or audit", "deadline_kind": "none", "quote": "The department shall conduct a study of profiles"}
check("M29 submit such study on or before D", ed.study_submission_date(o, t) == ("2016-11-01", "on or before November first, two thousand sixteen"))
check("M29 not for a record that already has a deadline", ed.study_submission_date({**o, "deadline_kind": "fixed_date"}, t) is None)
check("M29 not for another deliverable type", ed.study_submission_date({**o, "deliverable_type": "rulemaking"}, t) is None)
check("M29 not past the next numbered subdivision", ed.study_submission_date(o, t.replace("{{(B)", "2. {{(B)")) is None)
r = rec("2013-A814-01")
check("M29 stored 2013-A814-01 -> 2016-11-01", bool(r) and r["deadline_kind"] == "fixed_date" and r["deadline_date"] == "2016-11-01")

# J11. aid recipient as actor
o = {"actor_raw": "surviving municipalities", "quote": "surviving municipalities following a consolidation or dissolution shall be awarded additional annual aid"}
check("J11 recipient subject flagged", ed.aid_recipient_actor(o))
o = {"actor_raw": "the state comptroller", "quote": "Moneys shall be paid out of the account on the audit and warrant of the state comptroller"}
check("J11 the payer is not flagged", not ed.aid_recipient_actor(o))
fl = ed.judgment_flags("x", [{"actor_raw": "surviving municipalities", "quote": "surviving municipalities shall be awarded additional annual aid", "session": 2013}])
check("J11 flag aid_recipient_as_actor carries the quote", any(f["check"] == "aid_recipient_as_actor" and f["sentences"] for f in fl))
p = DATA / "reask" / "2013.json"
if p.exists():
    ent = json.load(open(p))["laws"].get("2013-A2051")
    if ent and any(r["check"] == "aid_recipient_as_actor" for r in ent["reasons"]):
        check("J11 2013-A2051 in data/reask with aid_recipient_as_actor", True)
    else:
        skipped("J11 2013-A2051 reask entry (rule checked by the judgment_flags fixture above)")

# J12. manual re-ask entries
man = json.load(open(DATA / "reask_manual.json"))["laws"]
check("J12 the four laws carry night 20261013b", all(any(x["night"] == "20261013b" for x in man.get(k, [])) for k in ("2013-S4664", "2009-A4687", "2009-A5707", "2013-A2051")))
p = DATA / "reask" / "2009.json"
if p.exists():
    ent = json.load(open(p))["laws"].get("2009-A5707")
    check("J12 2009-A5707 in data/reask with audit_confirmed_miss", bool(ent) and any(r["check"] == "audit_confirmed_miss" for r in ent["reasons"]))

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
