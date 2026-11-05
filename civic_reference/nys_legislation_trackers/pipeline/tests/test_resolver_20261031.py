"""Plain script: Oct 31 2026 night resolver rules R1-R3 (raw office titles in the agency field). Prints 'N passed, M failed'."""
import os, sys
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

def rec(agency, raw="the director", jur="state", **kw):
    d = {"actor_raw": raw, "actor_resolved_model": None, "agency": agency, "agency_full": agency, "agency_matched": agency != "Unspecified", "jurisdiction": jur, "quote": "x"}
    d.update(kw); return d

def run(o):
    return ar.fix_20261027(o, "", ed.LOOKUP, ed.BY_CANON, ed.eo.match_agency)

for t in ("Director of the Division of Minority and Women-Owned Business Development", "Division of Minority and Women's Business Development"):
    o = rec(t); run(o)
    check("R1 " + t, o["agency"] == "ESD" and o["agency_full"] == "Empire State Development" and o["agency_unit"] == "Division of Minority and Women-Owned Business Development" and o["agency_matched"])
o = rec("Commissioner of Finance of the City of New York", jur="nyc"); run(o)
check("R2 DOF", o["agency"] == "DOF" and o["jurisdiction"] == "nyc" and o["agency_unit"] is None)
o = rec("Commissioner of Health and Mental Hygiene of the City of New York", jur="nyc"); run(o)
check("R2 DOHMH", o["agency"] == "DOHMH" and o["jurisdiction"] == "nyc")
o = rec("Commissioner of Labor of the State of New York"); run(o)
check("R2 DOL", o["agency"] == "DOL" and o["jurisdiction"] == "state")
o = rec("Director of the Governor's Office of Employee Relations"); run(o)
check("R2 GOER", o["agency"] == "OER" and o["jurisdiction"] == "state")
o = rec("Unspecified", raw="The chief diversity officer", actor_unresolved=True); run(o)
check("R3 chief diversity officer", o["agency"] == "Governor" and o["agency_unit"] == "Chief Diversity Officer" and not o.get("actor_unresolved"))
o = rec("Unspecified", raw="A chief diversity officer for the state"); run(o)
check("R3 variant", o["agency"] == "Governor" and o["agency_unit"] == "Chief Diversity Officer")
# negatives
o = rec("SED", raw="the commissioner of education"); before = dict(o); run(o)
check("neg SED unchanged", o["agency"] == "SED" and o.get("agency_unit") == before.get("agency_unit"))
o = rec("Commissioner of Education"); run(o)
check("neg 'Commissioner of Education' not turned into another body", o["agency"] in ("Commissioner of Education", "SED"))
o = rec("Unspecified", raw="the director"); run(o)
check("neg bare director stays Unspecified", o["agency"] == "Unspecified")
o = rec("Commissioner of Nonexistent Things of the State of New York"); run(o)
check("neg unresolvable title untouched", o["agency"].startswith("Commissioner of Nonexistent"))
# R4 OFPC -> DHSES from 2010
for ag in ("DOS", "Office of Fire Prevention and Control", "Unspecified"):
    o = rec(ag, raw="the office of fire prevention and control", enactment_date="2017-10-22", agency_unit="Office of Fire Prevention and Control" if ag == "DOS" else None); run(o)
    check("R4 2017 " + ag, o["agency"] == "DHSES" and o["agency_unit"] == "Office of Fire Prevention and Control" and o["agency_matched"])
o = rec("Unspecified", raw="The state fire administrator", enactment_date="2013-07-11", actor_unresolved=True); run(o)
check("R4 fire administrator", o["agency"] == "DHSES" and not o.get("actor_unresolved"))
o = rec("DOS", raw="the office of fire prevention and control", enactment_date="2009-08-11", agency_unit="Office of Fire Prevention and Control"); run(o)
check("R4 pre-2010 keeps DOS", o["agency"] == "DOS")
# R5 named public library
o = rec("School districts", raw="the Oswego City Library", jur="local", agency_unit="Transferred Oswego School District", agency_group="School districts"); run(o)
check("R5 Oswego City Library", o["agency"] == "Public libraries" and o["agency_unit"] == "Oswego City Library" and o["agency_group"] == "Public libraries" and o["jurisdiction"] == "local")
o = rec("School districts", raw="the Hyde Park Free Library", jur="local", agency_unit="X"); run(o)
check("R5 free library", o["agency"] == "Public libraries" and o["agency_unit"] == "Hyde Park Free Library")
o = rec("School districts", raw="the public library of Oswego", jur="local"); run(o)
check("R5 public library of", o["agency"] == "Public libraries" and o["agency_unit"] == "Public Library of Oswego")
o = rec("SED", raw="the state library"); run(o)
check("R5 state library unchanged", o["agency"] == "SED")
o = rec("School districts", raw="the library", jur="local"); run(o)
check("R5 bare library unchanged", o["agency"] == "School districts")
# R6 county board of elections
for raw in ("the county board of elections", "board of elections of the county of Westchester", "the board of elections"):
    o = rec("Counties", raw=raw, jur="local", quote="In the County of Westchester the %s shall act." % raw); run(o)
    check("R6 " + raw, o["agency"] == "Boards of elections" and o["agency_unit"] == "County of Westchester" and o["agency_group"] == "Boards of elections")
o = rec("Counties", raw="the county board of elections", jur="local", quote="x", agency_unit="County of Erie"); run(o)
check("R6 keeps stored county unit", o["agency"] == "Boards of elections" and o["agency_unit"] == "County of Erie")
o = rec("Board of Elections", raw="the state board of elections"); run(o)
check("R6 state board unchanged", o["agency"] == "Board of Elections")
# R7 assessing unit
for raw in ("approved assessing unit", "an approved assessing unit", "such assessing unit"):
    o = rec("Counties", raw=raw, jur="local", quote="x", law_title="Relates to base proportions in approved assessing units in Nassau county"); r = ar.fix_20261027(o, "Section 1. The county of Nassau shall adopt.", ed.LOOKUP, ed.BY_CANON, ed.eo.match_agency)
    check("R7 " + raw, o["agency"] == "Municipalities (all)" and o["agency_unit"] == "County of Nassau")
o = rec("Municipalities (all)", raw="approved assessing unit in the county of Suffolk", jur="local", quote="x"); run(o)
check("R7 raw county", o["agency"] == "Municipalities (all)" and o["agency_unit"] == "County of Suffolk")
o = rec("Municipalities (all)", raw="an approved assessing unit", jur="local", quote="x"); run(o)
check("R7 no locality keeps unit None", o["agency"] == "Municipalities (all)" and o.get("agency_unit") is None)
# R8 Regents chancellor
o = rec("Chancellor of the Board of Regents", raw="The chancellor", quote="The chancellor or the commissioner, or any five regents, may call a special meeting of the board of regents."); run(o)
check("R8 regents chancellor", o["agency"] == "Board of Regents" and o["agency_unit"] == "Chancellor" and o["agency_matched"])
o = rec("Unspecified", raw="the chancellor or the commissioner", quote="the chancellor or the commissioner shall report to the board of regents"); run(o)
check("R8 unspecified with regents", o["agency"] == "Board of Regents" and o["agency_unit"] == "Chancellor")
o = rec("SUNY", raw="the state university chancellor or his designee", quote="x"); run(o)
check("R8 SUNY unchanged", o["agency"] == "SUNY" and o.get("agency_unit") is None)
o = rec("CUNY", raw="the chancellor", quote="the chancellor of the city university and the board of regents"); run(o)
check("R8 CUNY unchanged", o["agency"] == "CUNY")
o = rec("NYCPS", raw="the chancellor", jur="nyc", quote="the chancellor shall notify the regents"); run(o)
check("R8 NYCPS unchanged", o["agency"] == "NYCPS")
# R9 generic named_body office phrase in an NYC school law
T9 = "Section 1. Section 2590-h of the education law is amended. The principal of each public school shall notify the parents."
o = rec("Principal of Each Public School", raw="the principal of each public school", jur="local", agency_source="named_body")
r = ar.fix_nyc_school_actor(o, T9, ed.NYC_BY)
check("R9 principal of each public school -> NYCPS", o["agency"] == "NYCPS" and o["jurisdiction"] == "nyc" and r)
o = rec("Principal of Each Public School", raw="the principal of each public school", jur="local", agency_source="named_body")
check("R9 no NYC school law -> unchanged", ar.fix_nyc_school_actor(o, "Section 1. Some other law.", ed.NYC_BY) is None and o["agency"] == "Principal of Each Public School")
o = rec("Battery Park City Authority", raw="the principal", jur="state", agency_source="named_body")
check("R9 real named body unchanged", ar.fix_nyc_school_actor(o, T9, ed.NYC_BY) is None and o["agency"] == "Battery Park City Authority")
# R10 state officials
q = "No official of this state, or of any city, county, town or village therein, charged with the enforcement of laws shall accept any plans"
for raw in ("No official of this state", "officers of the state", "a state official", "State officials"):
    o = rec("Unspecified", raw=raw, quote=q, actor_unresolved=True)
    r = ar.fix_resolvable_actor(o, ed.NYC_BY)
    check("R10 " + raw, r and o["agency"] == "State agencies" and o["agency_unit"] is None and o["jurisdiction"] == "state" and not o.get("actor_unresolved"))
o = rec("Unspecified", raw="any city, county, town or village", quote=q)
check("R10 local sibling untouched by state rule", not ar.STATE_OFFICIAL.match(o["actor_raw"]))
# R11 bare "the state" is State agencies / State of New York; R12 assisting local governments
q = "the state or any requesting local government requesting assistance under this program shall be liable"
o = rec("DHSES", raw="the state", quote=q, agency_unit="State Office of Emergency Management", agency_source=None)
check("R11 call", ar.fix_20261031(o, ed.BY_CANON, ed.LOOKUP, "") and o["agency"] == "State agencies" and o["agency_unit"] == "State of New York")
o = rec("DHSES", raw="The state of New York", quote=q, agency_unit="State Office of Emergency Management", agency_source=None)
ar.fix_20261031(o, ed.BY_CANON, ed.LOOKUP, ""); check("R11 state of NY", o["agency"] == "State agencies")
o = rec("DHSES", raw="the state", quote="the state, acting through the division of homeland security, shall adopt rules", agency_unit="Division of Homeland Security", agency_source=None)
ar.fix_20261031(o, ed.BY_CANON, ed.LOOKUP, ""); check("R11 acting through keeps DHSES", o["agency"] == "DHSES")
for raw in ("Assisting local governments", "Any assisting local government", "the assisting state or local government"):
    o = rec("Unspecified", raw=raw, quote="x", actor_unresolved=True)
    check("R12 " + raw, ar.fix_20261031(o, ed.BY_CANON, ed.LOOKUP, "") and o["agency"] == "Municipalities (all)" and o["jurisdiction"] == "local" and not o.get("actor_unresolved"))
# Nov 1 2026: trailing "charged with enforcement" on a state official (2013-S3810-11)
check("state official charged with enforcement -> State agencies", bool(ar.STATE_OFFICIAL.match("any official of this state charged with enforcement")))

# Nov 3 2026: a bare "the state" stored as a named body from the law's context resolves to State agencies
_o = {"actor_raw": "the state", "agency": "State Office of Emergency Management", "agency_source": "named_body", "quote": "the state or any requesting local government requesting assistance under this program shall reimburse"}
ar.fix_20261031(_o, {}, None, "")
check("bare state over named_body -> State agencies", _o["agency"] == "State agencies" and _o.get("agency_unit") == "State of New York")

# Nov 3 2026 R13: district election inspectors are not the county board of elections
_o = {"actor_raw": "the election inspectors and the ballot clerks", "agency": "Boards of elections", "agency_source": "group", "quote": "After the polls have closed at such election, the election inspectors and the ballot clerks shall count the ballots"}
ar.fix_district_election_inspectors(_o, "An act to establish the Grinnell Library district ... a special district election shall be held ...")
check("district inspectors -> Public libraries", _o["agency"] == "Public libraries")
_o2 = {"actor_raw": "the election inspectors", "agency": "Boards of elections", "agency_source": "group", "quote": "the election inspectors shall certify"}
check("inspectors stay BOE when the law names a board of elections", not ar.fix_district_election_inspectors(_o2, "the county board of elections shall appoint election inspectors"))

# Nov 3 2026 R14: generic actor phrases are not named bodies
for ph, raw in (("Applicable Retirement System Or Systems", "the applicable retirement system or systems"), ("Duties of the Office", "duties of the office"), ("The Following Libraries", "the following libraries")):
    _o = {"actor_raw": raw, "agency": ph, "agency_full": ph, "agency_source": "named_body", "agency_matched": True, "quote": "x"}
    ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, "")
    check("R14 " + ph, _o["agency"] == "Unspecified" and _o["agency_source"] == "generic_phrase_r14" and _o["actor_unresolved"])
_o = {"actor_raw": "the such retirement system", "agency": "Such Retirement System", "agency_source": "named_body", "quote": "x"}
ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R14 Such Retirement System", _o["agency"] == "Unspecified")
_o = {"actor_raw": "the Battery Park City Authority", "agency": "Battery Park City Authority", "agency_source": "named_body", "quote": "x"}
ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R14 real body unchanged", _o["agency"] == "Battery Park City Authority" and _o["agency_source"] == "named_body")

# Nov 3 2026 R15: NYC retirement systems by Admin Code section
for sec, canon in (("13-582(o)", "TRS"), ("13-649(a)", "BERS"), ("13-149.1(5)", "NYCERS"), ("13-361.1(A)", "Fire Pension Fund"), ("13-316(e)(1)", "Fire Pension Fund"), ("13-256.1(A)", "PPF"), ("13-244.1(5)", "PPF")):
    _o = {"actor_raw": "the applicable retirement system or systems", "agency": "Police Pension Fund of the City of New York", "agency_source": "named_body", "citation": "Administrative Code of the City of New York § " + sec, "quote": "x"}
    ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R15 " + sec, _o["agency"] == canon and _o["jurisdiction"] == "nyc" and _o["agency_source"] == "retirement_section_r15")
_o = {"actor_raw": "the applicable retirement system or systems", "agency": "Applicable Retirement System Or Systems", "agency_source": "named_body", "citation": "Retirement and Social Security Law § 61-b(d)", "quote": "x"}
ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R15 state RSSL section not mapped", _o["agency_source"] == "generic_phrase_r14")

_o = {"actor_raw": "the retirement system", "agency": "TRS", "agency_source": "named_body", "citation": "Administrative Code of the City of New York § 13-638.2(b)(2)", "quote": "x"}
ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R15 13-638.2 (each retirement system) not mapped", _o["agency_source"] != "retirement_section_r15")
for ph, raw in (("Head of the Retirement System", "the head of the retirement system"), ("Such Retirement System", "such retirement system")):
    _o = {"actor_raw": raw, "agency": ph, "agency_source": "named_body", "quote": "x"}
    ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R14b " + ph, _o["agency"] == "Unspecified" and _o["agency_source"] == "generic_phrase_r14")
# Nov 5 2026 R16: a unit cut at the first "acting by/through" phrase
for u, want in (("Town of Smithtown Acting By", "Town of Smithtown"), ("Town of Islip Acting Through Its Legislative Body", "Town of Islip"), ("Town of Greenburgh Acting By And Through Its Town Board", "Town of Greenburgh"), ("Town of Smithtown", "Town of Smithtown"), ("Village of Port Chester Acting Police Justices", "Village of Port Chester Acting Police Justices")):
    _o = {"actor_raw": "the town of Smithtown acting by and through its governing body", "agency": "Towns", "agency_unit": u, "agency_source": "group", "quote": "x"}
    ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R16 " + u, _o["agency_unit"] == want)

# Nov 5 2026 R17: county vocational education and extension boards
for raw in ("county vocational education and extension boards", "the county vocational education and extension board"):
    _o = {"actor_raw": raw, "agency": "Unspecified", "agency_source": "unresolved", "actor_unresolved": True, "quote": "each county vocational education and extension board of Oneida county shall"}
    ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, "")
    check("R17 " + raw, _o["agency"] == "Vocational Education and Extension Board" and _o["agency_unit"] == "County of Oneida" and "actor_unresolved" not in _o)
_o = {"actor_raw": "county vocational education and extension boards", "agency": "Unspecified", "agency_source": "unresolved", "quote": "x"}
ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R17 no county named", _o["agency"] == "Vocational Education and Extension Board" and _o["agency_unit"] is None)
# Nov 5 2026 R18: any agency of the state -> State agencies
for raw in ("any agency of the state", "any state agency", "each agency of the state", "all agencies of the state"):
    _o = {"actor_raw": raw, "agency": "Unspecified", "agency_source": "unresolved", "actor_unresolved": True, "quote": "x"}
    ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, "")
    check("R18 " + raw, _o["agency"] == "State agencies" and _o["agency_unit"] is None and _o["agency_source"] == "state_agencies_r18" and "actor_unresolved" not in _o)
_o = {"actor_raw": "any agency of the state", "agency": "Unspecified", "agency_source": "unresolved", "quote": "the state, acting through the department of health, shall"}
ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R18 acting through left alone", _o["agency_source"] != "state_agencies_r18")
# Nov 5 2026 R19: interstate compact bodies are multi-state New York actors
_o = {"actor_raw": "the interstate commission", "agency": "Interstate Commission", "agency_source": "named_body", "law_title": "Adopts the interstate compact for juveniles; repealer", "quote": "The commission shall meet at least once each calendar year."}
ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R19 2011-A55 interstate commission", _o["agency"] == "Interstate Commission for Juveniles" and _o["multi_state"] is True and _o["agency_org_type"] == "multi-state compact body" and _o["jurisdiction"] == "state" and _o["agency_group"] is None)
_o = {"actor_raw": "the interstate commission", "agency": "Unspecified", "agency_source": "unresolved", "law_title": "Adopts the interstate compact for adult offender supervision", "quote": "x"}
ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R19 ICAOS by law title", _o["agency"] == "Interstate Commission for Adult Offender Supervision" and _o["multi_state"])
for nm in ("Delaware River Basin Commission", "the Susquehanna River Basin Commission", "Interstate Environmental Commission", "Northeast Interstate Low-Level Radioactive Waste Commission", "Appalachian Regional Commission", "Great Lakes Commission", "Waterfront Commission of New York Harbor"):
    _o = {"actor_raw": nm, "agency": "Unspecified", "agency_source": "unresolved", "actor_unresolved": True, "quote": "x"}
    ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R19 " + nm, _o["agency"] == nm.replace("the ", "").replace("Susquehanna", "Susquehanna") and _o["multi_state"] and "actor_unresolved" not in _o and nm.replace("the ", "").lower() in ed.LOOKUP)
_o = {"actor_raw": "the commission", "agency": "Unspecified", "agency_source": "unresolved", "law_title": "Relates to the powers of the state commission of correction", "quote": "x"}
ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R19 the commission, non-compact law unchanged", "multi_state" not in _o and _o["agency"] == "Unspecified")
_o = {"actor_raw": "the commission", "agency": "Unspecified", "agency_source": "unresolved", "law_title": "Adopts the interstate compact for juveniles", "quote": "x"}
ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R19 the commission, compact law", _o["agency"] == "Interstate Commission for Juveniles" and _o["multi_state"])
_o = {"actor_raw": "the Port Authority of New York and New Jersey", "agency": "Port Authority of New York and New Jersey", "agency_source": "named_body", "law_title": "Adopts the interstate compact for juveniles", "quote": "x"}
_b = dict(_o); ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R19 Port Authority unchanged", _o == _b)
# Nov 5 2026 R19 follow-ups: military-children compact, generic "Interstate Commission", compact officers
MIL = "Relates to educational opportunities for military children; in-state tuition at colleges and universities"
for raw, ag in (("The interstate commission", "Interstate Commission"), ("the interstate commission", "Interstate Commission on Educational Opportunity for Military Children")):
    _o = {"actor_raw": raw, "agency": ag, "agency_source": "named_body", "law_title": MIL, "quote": "x"}
    ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R19 military " + ag, _o["agency"] == "Interstate Commission on Educational Opportunity for Military Children" and _o["multi_state"] is True and _o["agency_org_type"] == "multi-state compact body")
ICJ = "Adopts the interstate compact for juveniles; repealer"
for raw, ag, unit in (("The chairperson", "Interstate Commission for Juveniles", "Chairperson"), ("The executive Committee", "Interstate Commission for Juveniles", "Executive Committee"),
                      ("a commissioner", "Commissioner for the Interstate Compact for Juveniles", "Commissioner"), ("the compact administrator", "Unspecified", "Compact Administrator")):
    _o = {"actor_raw": raw, "agency": ag, "agency_source": "named_body", "law_title": ICJ, "quote": "x"}
    ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R19 officer " + raw, _o["agency"] == "Interstate Commission for Juveniles" and _o["agency_unit"] == unit and _o["multi_state"] is True)
for raw in ("the chairperson", "a commissioner", "the compact administrator", "the executive committee"):
    _o = {"actor_raw": raw, "agency": "Unspecified", "agency_source": "unresolved", "law_title": "Relates to the powers of the state commission of correction", "quote": "x"}
    ar.fix_20261031(_o, ed.BY_CANON, ed.LOOKUP, ""); check("R19 officer in non-compact law unchanged " + raw, "multi_state" not in _o and _o["agency"] == "Unspecified")
print("%d passed, %d failed" % (passed, failed))
