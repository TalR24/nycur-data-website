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
print("%d passed, %d failed" % (passed, failed))
