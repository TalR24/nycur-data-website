"""Nov 24 2026: window reads are compared by unique quotes (B82); employee pay entitlements are beneficiary records (B104)."""
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

f = ed.b104_employee_pay
check("employee of the court system receives pay", f("Effective March 31, 2017, each such nonjudicial officer and employee in the employ of the unified court system shall receive a one-time bonus of 500 dollars."))
check("fragment receives location pay", f("whose principal place of employment is in Dutchess county shall receive location pay at a rate of 1,848 dollars annually"))
check("members entitled to reimbursement", f("The members shall serve without compensation, but they shall be entitled to reimbursement for their actual expenses."))
check("county receives proposals is a duty", not f("shall receive any proposals for modifications of such proposal which may be submitted by proponents of the district"))
check("appointed officer's salary sentence kept", not f("A chief diversity officer shall be appointed by the Governor and shall receive a salary to be fixed by the Governor."))
check("agency receives information is not pay", not f("The department shall receive information about the program from the office."))
check("flag on", ed.APPLY_B104)
print(f"{P} passed, {F} failed")
sys.exit(1 if F else 0)
