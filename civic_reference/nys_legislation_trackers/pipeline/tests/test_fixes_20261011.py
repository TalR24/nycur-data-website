"""Plain script: the Oct 11 2026 audit fixes M7-M13 and J7. Uses the cached marked texts when present. Prints 'N passed, M failed'."""
import json, os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import effective_date as efd
import agency_resolve_nys as ar
import chapter_lookup

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

TM = HERE / "cache" / "text_marked"
DATA = HERE.parent / "data"
def law_text(key):
    p = TM / (key + ".txt")
    return p.read_text() if p.exists() else None
def signed(key):
    return {x["key"]: x for x in json.load(open(DATA / "signed" / (key[:4] + ".json")))}[key]

# M7. calendar months and years in deadlines
o = {"deadline_kind": "days_after_effective", "deadline_text": "no later than two months after the date this act shall take effect", "deadline_date": "2012-02-19"}
check("M7 2011-A8496-07 two months from 2011-12-21 = 2012-02-21", ed.calendar_deadline(o, ["2011-12-21"]) == "2012-02-21")
o = {"deadline_kind": "days_after_effective", "deadline_text": "within six months of the effective date", "deadline_date": "2012-02-27"}
check("M7 clamps to month end (2011-08-31 + 6 months = 2012-02-29)", ed.calendar_deadline(o, ["2011-08-31"]) == "2012-02-29")
o = {"deadline_kind": "days_after_enactment", "deadline_text": "within three years after enactment", "deadline_date": "2014-03-14"}
check("M7 years are calendar years", ed.calendar_deadline(o, [None, "2011-03-15"]) == "2014-03-15")
o = {"deadline_kind": "days_after_effective", "deadline_text": "within 90 days of the effective date", "deadline_date": "2012-03-20"}
check("M7 days untouched", ed.calendar_deadline(o, ["2011-12-21"]) is None)
o = {"deadline_kind": "days_after_effective", "deadline_text": "within two months of the effective date", "deadline_date": "2012-02-21"}
check("M7 an already calendar date is untouched", ed.calendar_deadline(o, ["2011-12-21"]) is None)
check("M7 effective dates use calendar months", efd.parse_effective("§ 3. This act shall take effect six months after it shall have become a law.", "2015-08-31")["effective_date"] == "2016-02-29")
p = DATA / "duties" / "2011.json"
if p.exists():
    r = next(x for x in json.load(open(p))["obligations"] if x["obligation_id"] == "2011-A8496-07")
    check("M7 stored 2011-A8496-07 = 2012-02-21", r["deadline_date"] == "2012-02-21")

# M8. generic role nouns are the State agencies group
for raw in ("the appointing authority", "the appointing authorities", "such appointing authority or authorities", "the appointing officer", "the head of the agency", "each agency head", "the public employer"):
    o = {"actor_raw": raw, "agency": "Appointing Authority", "agency_source": "named_body", "actor_unresolved": True}
    check("M8 %s" % raw, ar.fix_generic_role(o) and o["agency"] == "State agencies" and o["jurisdiction"] == "state" and not o.get("actor_unresolved"))
o = {"actor_raw": "the appointing authority for the advisory council", "agency": "Governor"}
check("M8 a qualified role is left alone", not ar.fix_generic_role(o) and o["agency"] == "Governor")
o = {"actor_raw": "such public employer", "agency": "Public employers"}
check("M8 'such public employer' keeps the Public employers group", not ar.fix_generic_role(o) and o["agency"] == "Public employers")
if (DATA / "duties" / "2009.json").exists():
    r = next(x for x in json.load(open(DATA / "duties" / "2009.json"))["obligations"] if x["obligation_id"] == "2009-A40011-02")
    check("M8 stored 2009-A40011-02 -> State agencies", r["agency"] == "State agencies")

# M9. same-as-chapter naming bills resolves the bill, not the amended chapter
clause = "§ 2. This act shall take effect on the same date and in the same manner as a chapter of the laws of 2015, amending chapter 672 of the laws of 1993, amending the public authorities law, as proposed in legislative bills numbers S.459 and A.5251, takes effect."
ref = efd.find_reference(clause)
check("M9 reference is the bills of 2015", ref["bills"] == [("S", 459), ("A", 5251)] and ref["year"] == 2015 and ref["chapter"] is None)
check("M9 a plain chapter reference still works", efd.find_reference("same date as chapter 815 of the laws of 2022")["chapter"] == 815)
rec = chapter_lookup.resolve(bills=ref["bills"], year=2015)
check("M9 S.459 -> chapter 467 of 2015, effective 2015-11-20", rec and rec["chapter"] == 467 and rec["effective_date"] == "2015-11-20")
t = law_text("2015-A9193")
if t:
    e = efd.parse_effective(t, signed("2015-A9193")["signed_date"], resolver=chapter_lookup.resolve)
    check("M9 2015-A9193 effective 2015-11-20 via same_as_chapter", e["effective_date"] == "2015-11-20" and e["rule"] == "same_as_chapter")

# M10. act-level sunset after a proviso
c = "§ 4. This act shall take effect immediately, provided that section two of this act shall take effect July 1, 2010; further provided that this act shall expire and be deemed repealed December 31, 2012."
check("M10 expires_date 2012-12-31", efd.parse_effective(c, "2009-12-01")["expires_date"] == "2012-12-31")
check("M10 a section's sunset is not the act's", efd.parse_effective("§ 4. This act shall take effect immediately; provided that section two of this act shall expire and be deemed repealed December 31, 2012.", "2009-12-01")["expires_date"] is None)
t = law_text("2009-S6150")
if t:
    check("M10 2009-S6150 real text", efd.parse_effective(t, signed("2009-S6150")["signed_date"])["expires_date"] == "2012-12-31")

# M11. "will" + verb with a government subject is a duty modal
q = "Six months from the effective date of this act, and every six months thereafter, the director of the budget will report to the speaker of the assembly and the temporary president of the senate"
check("M11 WILL_DUTY matches the director of the budget", bool(ed.WILL_DUTY.search(q)))
check("M11 a private subject does not", not ed.WILL_DUTY.search("firms that, under the general supervision of the authority, will provide mentoring services"))
t = law_text("2009-A40011")
if t:
    o = {"quote": q, "quote_verified": True, "actor_raw": "the director of the budget"}
    g = ed.gate_record(o, t, "{{" in t)
    check("M11 not dropped as designation_no_actor", not g or g[0] != "designation_no_actor")
    p = DATA / "duties" / "2009.json"
    if p.exists():
        r = next((x for x in json.load(open(p))["obligations"] if x["obligation_id"] == "2009-A40011-05"), None)
        check("M11 stored 2009-A40011-05 is a duty", bool(r) and r["kind"] == "duty")

# M12. BOCES
for raw in ("board of cooperative educational services", "boards of cooperative educational services", "The boces", "Southern Westchester BOCES", "such board of cooperative educational services"):
    o = {"actor_raw": raw, "agency": "School districts", "jurisdiction": "local"}
    check("M12 %s" % raw, ar.fix_boces(o) and o["agency"] == "BOCES" and o["jurisdiction"] == "local" and o["agency_group"] == "BOCES")
o = {"actor_raw": "Each school district and board of cooperative educational services", "agency": "School districts"}
check("M12 a compound actor keeps its split", not ar.fix_boces(o) and o["agency"] == "School districts")

# M13. benefit entitlements are not duties
q = "eligible dwelling units in property whose average unit assessed value is less than or equal to fifty thousand dollars shall receive a Partial abatement of the real property taxes"
check("M13 beneficiary subject, actor not in quote", ed.benefit_entitlement({"actor_raw": "the commissioner of finance"}, q))
check("M13 actor in the quote keeps the record", not ed.benefit_entitlement({"actor_raw": "the department of finance"}, "the department of finance shall receive applications from owners"))
check("M13 'such property shall be exempt'", ed.benefit_entitlement({"actor_raw": "the assessor"}, "such property shall be exempt from taxation"))
check("M13 a government subject keeps the record", not ed.benefit_entitlement({"actor_raw": "the county"}, "the commissioner shall be entitled to inspect the premises"))
check("M13 receiving notice is kept", not ed.benefit_entitlement({"actor_raw": "the school"}, "the parents of the student in question shall receive proper written notice of their right"))
check("M13 an authorization before the modal keeps the record", not ed.benefit_entitlement({"actor_raw": "the city"}, "is hereby authorized and empowered to adopt local laws to provide that any increase in assessed valuation of real property shall be exempt from taxation"))
check("M13 receiving training is kept", not ed.benefit_entitlement({"actor_raw": "the department"}, "all security and medical staff with direct inmate contact shall receive a minimum of eight hours of such training each year"))
check("M13 a quote that starts at the modal is kept", not ed.benefit_entitlement({"actor_raw": "the state"}, "shall receive a monthly stipend in the amount of two hundred dollars"))
t = law_text("2013-S2320")
if t:
    g = ed.gate_record({"quote": q + " of twenty-five percent, twenty-six and one-half percent and twenty-eight and one-tenth percent respectively.", "quote_verified": True, "actor_raw": "the commissioner of finance"}, t, True)
    check("M13 gate rule benefit_entitlement", bool(g) and g[0] == "benefit_entitlement")

# J7. data/reask_manual.json is merged into the re-ask list
man = json.load(open(DATA / "reask_manual.json"))
check("J7 file lists the seven laws", set(man["laws"]) == {"2011-A8496", "2013-S2320", "2013-S5236", "2009-A2021", "2011-A8007", "2009-A163", "2009-A40011"} and man["laws"]["2011-A8496"][0]["night"] == "20261011")
t = law_text("2013-S2320")
if t and (ed.EXTRACTED / "2013-S2320.json").exists():
    out = ed.build_reask([(signed("2013-S2320"), t)], [], [])
    rs = [r for r in out.get("2013-S2320", {}).get("reasons", []) if r["check"] == "audit_confirmed_miss"]
    check("J7 2013-S2320 carries audit_confirmed_miss with 4 sentences", len(rs) == 1 and len(rs[0]["sentences"]) == 4)
    ins = ed.reask_instruction(out["2013-S2320"])
    check("J7 sentences reach the re-ask instruction", "the commissioner of finance May waive Any interest" in ins)

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
