"""Plain script: Oct 29 2026 night resolver rules K1 (court actors), K2 (legislative leaders), K3 (governing body phrases). Prints 'N passed, M failed'."""
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

def rec(raw, agency="Unspecified", **kw):
    d = {"actor_raw": raw, "actor_resolved_model": None, "agency": agency, "agency_full": agency, "agency_matched": agency != "Unspecified", "quote": "x", "citation": "x", "action_summary": "x"}
    d.update(kw); return d

def run(o):
    return ar.fix_20261027(o, "", ed.LOOKUP, ed.BY_CANON, ed.eo.match_agency)

# K1
for raw in ["the court having jurisdiction over the matter", "the sentencing court", "the family court or the supreme court", "a court of competent jurisdiction",
            "the appellate division", "the court of appeals", "a justice of the supreme court"]:
    o = rec(raw); run(o)
    check("K1 " + raw, o["agency"] == "Unified Court System" and o["jurisdiction"] == "state" and o["agency_org_type"] == "judiciary" and not o.get("actor_unresolved"))
for raw in ["criminal justice agencies", "the justice center"]:
    o = rec(raw); run(o)
    check("K1 regression no match " + raw, o["agency"] != "Unified Court System")
    check("K1 group regex no match " + raw, not any(c == "Unified Court System" and rx.search(ar.strip_art(ar.norm(raw))) for rx, c, j, t in ar.GROUP_REGEX))
o = rec("the county court", "Counties", agency_unit="County of Erie"); run(o)
check("K1 local group corrected", o["agency"] == "Unified Court System" and o["agency_unit"] is None)

# K2
for raw in ["the temporary president of the senate", "the speaker of the assembly", "the minority leader of the senate", "the minority leader of the assembly",
            "the chairs of the senate finance and assembly ways and means committees"]:
    o = rec(raw, "Legislature" if "president" in raw or "speaker" in raw else "Unspecified"); run(o)
    check("K2 " + raw, o["agency"] == "State Legislature" and o["jurisdiction"] == "state" and not o.get("actor_unresolved"))
check("K2 group regex", any(c == "State Legislature" and rx.search("speaker of the assembly") for rx, c, j, t in ar.GROUP_REGEX))

# K3 (narrowed: only when no locality is named anywhere and the agency was defaulted)
o = rec("the applicable governing body or tax department", "Villages", agency_unit="Village of Lawrence"); run(o)
check("K3 named unit stays", o["agency"] == "Villages" and o["agency_unit"] == "Village of Lawrence")
o = rec("the applicable governing body or tax department", "Villages"); run(o)
check("K3 defaulted Villages, no locality -> Municipalities (all)", o["agency"] == "Municipalities (all)" and o["agency_unit"] is None)
o = rec("the governing body of such municipality", "Unspecified"); run(o)
check("K3 Unspecified -> Municipalities (all)", o["agency"] == "Municipalities (all)")
o = rec("the governing body of such municipality", "Towns", quote="the Town of Ramapo shall file"); run(o)
check("K3 quote names locality -> unchanged", o["agency"] == "Towns")
o = rec("the applicable governing body or tax department", "Counties"); o2 = ar.fix_20261027(o, "Nassau County law: the County of Nassau", ed.LOOKUP, ed.BY_CANON, ed.eo.match_agency)
check("K3 law text names locality -> unchanged", o["agency"] == "Counties")
o = rec("the governing body of the village", "Villages"); run(o)
check("K3 leaves other governing-body phrases", o["agency"] == "Villages")

# K4
def run4(o, text): return ar.fix_20261027(o, text, ed.LOOKUP, ed.BY_CANON, ed.eo.match_agency)
for raw in ["the city", "such city", "the city's", "the mayor"]:
    o = rec(raw, "Cities"); run4(o, "the city of New York shall report; the city shall file")
    check("K4 NYC-only moves " + raw, o["agency"] == "New York City" and o["jurisdiction"] == "nyc" and o["agency_unit"] is None)
o = rec("the city", "Cities"); run4(o, "the city of New York and the city of Buffalo")
check("K4 two cities stays", o["agency"] == "Cities")
o = rec("the city", "Cities", agency_unit="City of Buffalo"); run4(o, "the city of Buffalo shall file")
check("K4 Buffalo stays Cities with unit", o["agency"] == "Cities" and o["agency_unit"] == "City of Buffalo")
o = rec("the city", "Cities"); run4(o, "Hudson city law, city of Hudson")
check("K4 no NYC in text stays", o["agency"] == "Cities")

print(f"{passed} passed, {failed} failed")
