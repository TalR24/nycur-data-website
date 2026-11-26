"""Nov 26 2026 (B120): parallel provisions far apart in a law are not duplicates."""
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

filler = " The commissioner shall publish the plan." * 60
text = "PART A. Section 1. The director of the budget is authorized to allocate funds to the agencies for the program." + filler + " PART B. Section 1. The director of the budget is authorized to allocate funds to the agencies for the programs."
a = {"quote": "The director of the budget is authorized to allocate funds to the agencies for the program."}
b = {"quote": "The director of the budget is authorized to allocate funds to the agencies for the programs."}
check("far-apart parallel provisions are distinct", ed.b120_far_apart(a, b, text))
near = "The campaign shall start. The campaign shall begin no later than ninety days after the effective date."
check("adjacent sentences are not far apart", not ed.b120_far_apart({"quote": "The campaign shall start."}, {"quote": "The campaign shall begin no later than ninety days after the effective date."}, near))
check("same code citation stays a duplicate", not ed.b120_far_apart(dict(a, citation="Vehicle and Traffic Law § 401(5-a)(a) (section 1-c of the act)"), dict(b, citation="Vehicle and Traffic Law § 401(5-a)(a) (section 1-a of the act)"), text))
check("no text means no change", not ed.b120_far_apart(a, b, None))
check("flag on", ed.APPLY_B120)
print(f"{P} passed, {F} failed")
sys.exit(1 if F else 0)
