"""Nov 25 2026 (B111): a lead naming 'the following powers' / 'powers shall include' makes its items powers."""
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

lead = "(A) A land bank shall constitute a type c not-for-profit corporation under new york law, which powers shall include all powers necessary to carry out and effectuate the purposes of this article, including the following powers in addition to those granted by any other law:"
check("land bank powers lead is not a duty lead", not ed.lead_in_makes_duty(lead))
check("land bank powers lead gives power items", ed.infinitive_lead_kind(lead, "to adopt a seal and to alter the same at pleasure;") == "power")
check("'shall have the following powers and duties' stays a duty lead", ed.lead_in_makes_duty("The commissioner shall have the following powers and duties:"))
check("'The department shall:' stays a duty lead", ed.lead_in_makes_duty("The department shall:"))
check("flag on", ed.APPLY_B111)
print(f"{P} passed, {F} failed")
sys.exit(1 if F else 0)
