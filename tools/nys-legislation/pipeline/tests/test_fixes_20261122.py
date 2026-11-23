"""Nov 22 2026: county units are validated county names (no 'County of The'); court clerks fold into Unified Court System (B91)."""
import sys, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import extract_duties as ed  # noqa: E402
import agency_resolve_nys as ar  # noqa: E402

P = F = 0
def check(name, ok):
    global P, F
    if ok: P += 1
    else: F += 1; print("FAIL", name)

check("county_name rejects 'The'", ar.county_name("The") is None)
check("county_name keeps Erie", ar.county_name("Erie") == "Erie")
for ag, unit in (("Clerk of the Court", "Clerk of the court"), ("Clerk of Court", "Clerk of court"), ("New York State Unified Court System", None)):
    o = {"agency": ag, "agency_source": "named_body", "agency_unit": None}
    check("B91 folds " + ag, ed.b91_court_clerk(o) and o["agency"] == "Unified Court System" and o["agency_unit"] == unit)
o = {"agency": "Traffic Violations Bureau Or Court With Jurisdiction Over Traffic Infractions", "agency_source": "named_body"}
check("B91 leaves a mixed body alone", not ed.b91_court_clerk(o))
o = {"agency": "Clerk of the Court", "agency_source": "crosswalk"}
check("B91 only touches named_body", not ed.b91_court_clerk(o))
data = HERE.parent.parent / "data"
if (data / "duties" / "2015.json").exists():
    recs = []
    for k in ("duties", "powers"):
        for f in (data / k).glob("20*.json"):
            recs += next(v for v in json.load(open(f)).values() if isinstance(v, list))
    check("no stored 'County of The' unit", not any((r.get("agency_unit") or "") == "County of The" for r in recs))
    check("no stored named-body court clerk", not any(r.get("agency_source") == "named_body" and ed.B91_COURT.match(r.get("agency") or "") for r in recs))
print(f"{P} passed, {F} failed")
sys.exit(1 if F else 0)
