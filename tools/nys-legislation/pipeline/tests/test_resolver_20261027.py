"""Plain script: Oct 27 2026 night resolver rules R1-R5 (off-track betting branch offices, named State commissions, locality casing,
officer phrases, city boards of education). Prints 'N passed, M failed'."""
import os, sys, copy
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

def rec(raw, agency="Unspecified", **kw):
    d = {"actor_raw": raw, "actor_resolved_model": None, "agency": agency, "agency_full": agency, "agency_matched": agency != "Unspecified", "quote": "x", "citation": "x", "action_summary": "x"}
    d.update(kw); return d

def run(o):
    return ar.fix_20261027(o, "", ed.LOOKUP, ed.BY_CANON, ed.eo.match_agency)

# R1
o = rec("every off-track betting corporation branch office", "Off-track Betting Corporation Branch Offices", quote="Each branch office of the Western regional off-track betting corporation shall post odds.")
check("R1 names Western", run(o) == "r1_otb_branch" and o["agency"] == "Off-track betting corporations" and o["agency_unit"] == "Western Regional Off-Track Betting Corporation")
o = rec("every off-track betting corporation branch office", "Off-track Betting Corporation Branch Offices")
run(o); check("R1 no region -> group, no unit", o["agency"] == "Off-track betting corporations" and not o["agency_unit"] and "branch" not in o["agency"].lower())
o = rec("the branch offices of the Suffolk off-track betting corporation", "Unspecified")
run(o); check("R1 'branch offices of the' wording, Suffolk", o["agency_unit"] == "Suffolk Regional Off-Track Betting Corporation")
o = rec("the off-track betting corporation", "Off-track Betting Corporation"); check("R1 leaves the corporation itself", run(o) is None and o["agency"] == "Off-track Betting Corporation")

# R2
o = rec("the state commission of correction", "State authorities")
check("R2 state commission of correction -> SCOC", run(o) == "r2_state_commission" and o["agency"] == "SCOC")
o = rec("the commission of correction", "DCS")
check("R2 corrects a wrong crosswalk hit to SCOC", run(o) and o["agency"] == "SCOC")
o = rec("the commission on quality of care and advocacy for persons with disabilities", "Commission on Quality of Care and Advocacy for Persons With Disabilities", jurisdiction="state", agency_source="named_body")
check("R2 no code -> State agencies with unit, not State authorities", run(o) and o["agency"] == "State agencies" and o["agency_unit"].startswith("Commission on Quality of Care"))
o = rec("the state commission on the restructuring of the Capitol", "State authorities", agency_source="group", jurisdiction="state")
check("R2 State authorities becomes State agencies", run(o) and o["agency"] == "State agencies")
o = rec("the council of the city", "Cities", agency_unit="City of Troy", jurisdiction="local")
check("R2 leaves a city council alone", run(o) is None and o["agency"] == "Cities")
check("R2 group regex: 'state commission' is State agencies", any(c == "State agencies" and rx.search("state commission") for rx, c, j, t in ar.GROUP_REGEX))

# R3
check("R3 hyphen small word", ar.locality_title("Village of Hastings-on-hudson") == "Village of Hastings-on-Hudson")
check("R3 Cornwall-on-Hudson stable", ar.locality_title("Village of Cornwall-on-Hudson") == "Village of Cornwall-on-Hudson")
check("R3 two words", ar.locality_title("Village of wappingers falls") == "Village of Wappingers Falls")
check("R3 Saranac Lake", ar.locality_title("Village of saranac lake") == "Village of Saranac Lake")
check("R3 apostrophe", ar.locality_title("Town of o'brien") == "Town of O'Brien")
check("R3 possessive not capitalised", ar.title_case("hell's kitchen") == "Hell's Kitchen")
check("R3 small word first stays capital", ar.title_case("of the people") == "Of the People")
check("R3 non-locality unit untouched", ar.locality_title("Board of Directors") == "Board of Directors")
o = rec("the village of hastings-on-hudson", "Villages", agency_unit="Village of Hastings-on-hudson", agency_matched=True)
check("R3 fix_unit_casing", run(o) == "r3_unit_casing" and o["agency_unit"] == "Village of Hastings-on-Hudson")
check("R3 title_case hyphen words", ar.title_case("madison-oneida board") == "Madison-Oneida Board")

# R4
o = rec("the chief executive officer of that agency, department or authority", "Chief Executive Officer of That Agency, Department Or Authority", agency_source="named_body",
        quote="the chief executive officer of that agency, department or authority shall report.")
check("R4 no named agency -> State agencies", run(o) == "r4_officer_phrase" and o["agency"] == "State agencies")
o = rec("the head of such agency", "Unspecified", quote="Each division of the budget unit's head: the head of such agency shall certify.")
check("R4 lead-in names one agency -> that agency", run(o) == "r4_officer_phrase" and o["agency"] == "DOB")
o = rec("the commissioner of such department", "Unspecified", quote="the commissioner of such department shall act")
check("R4 commissioner of such department -> State agencies", run(o) and o["agency"] == "State agencies")
o = rec("the chair of such authority", "NYSERDA", quote="x")
check("R4 keeps an already-crosswalked record", run(o) is None and o["agency"] == "NYSERDA")
o = rec("the commissioner of health", "DOH"); check("R4 ignores a named officer", run(o) is None)

# R5
o = rec("the board of education of the city school district of the city of Buffalo", "Cities", agency_unit="City of Buffalo", jurisdiction="local", agency_matched=True)
check("R5 Buffalo", run(o) == "r5_city_school_board" and o["agency"] == "School districts" and o["agency_unit"] == "Buffalo City School District")
o = rec("the board of education", "Cities", agency_unit="City of Yonkers", jurisdiction="local", agency_matched=True)
check("R5 bare board of education with city unit", run(o) and o["agency_unit"] == "Yonkers City School District")
o = rec("the school board", "Cities", agency_unit="City of Rensselaer", jurisdiction="local", agency_matched=True)
check("R5 school board", run(o) and o["agency_unit"] == "Rensselaer City School District")
o = rec("the board of education of the city of Utica", "Cities", agency_unit="City of Utica", jurisdiction="local", agency_matched=True)
check("R5 'of the city of Utica'", run(o) and o["agency_unit"] == "Utica City School District")
o = rec("the board of education of the city of New York", "Cities", agency_unit="City of New York")
check("R5 New York City not touched", run(o) is None)
o = rec("the board of education", "NYCPS", jurisdiction="nyc"); check("R5 NYCPS untouched", run(o) is None and o["agency"] == "NYCPS")
o = rec("the board of education of the city of Utica", "Cities", agency_unit="City of Albany")
check("R5 mismatched city unit left alone", run(o) is None)

# resolve_unmatched wiring
o = rec("the head of such agency", "Unspecified", quote="the head of such agency shall report")
res = ar.resolve_unmatched(o, "", {}, {**ed.RESOLVE_DEPS, "named_locality": ed.named_locality})
check("resolve_unmatched applies R4", res == "r4_officer_phrase" and o["agency"] == "State agencies")

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
