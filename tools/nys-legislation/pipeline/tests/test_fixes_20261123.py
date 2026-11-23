"""Nov 23 2026: a body housed in a department folds into it (B98); a window read does not replace an equal whole-law re-ask."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import extract_duties as ed  # noqa: E402

P = F = 0
def check(name, ok):
    global P, F
    if ok: P += 1
    else: F += 1; print("FAIL", name)

o = {"agency": "State Athletic Commission", "agency_source": "named_body", "agency_unit": None}
check("B98 folds the athletic commission into DOS", ed.b98_housed_body(o) and o["agency"] == "DOS" and o["agency_unit"] == "State Athletic Commission")
o = {"agency": "State Athletic Commission", "agency_source": "named_body", "agency_unit": "Medical Advisory Board"}
check("B98 keeps a sub-unit", ed.b98_housed_body(o) and o["agency_unit"] == "Medical Advisory Board")
check("B98 only touches named_body", not ed.b98_housed_body({"agency": "State Athletic Commission", "agency_source": "crosswalk"}))
tm = ed.TEXT_MARKED / "2015-S5949.txt"
if tm.exists() and (ed.PACKETS_ROOT / "2015" / "long" / "results" / "2015-S5949__w1.json").exists():
    check("2015-S5949 equal windows keep the whole answer", ed.long_window_thinner("2015-S5949", tm.read_text()))
print(f"{P} passed, {F} failed")
sys.exit(1 if F else 0)
