"""Nov 12 2026 B63 recall fixes: A (sub_item_of_parent keeps own-appointer items and action items under 'the commission shall, at a minimum:'),
B ('X may exempt from disclosure' is a power, not an applicability clause), C (a joint-subject sentence gets one record per named actor)."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
if not (HERE / "cache" / "text_marked").is_dir() or not (HERE / "cache" / "extracted").is_dir():
    print("0 passed, 0 failed (skipped: cache/text_marked or cache/extracted is not present here)"); sys.exit(0)
import extract_duties as ed
passed = failed = 0
def check(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1; print("FAIL", name)

check("B63a flag off after the Nov 12 blind judge (8/13)", ed.APPLY_B63A is False)
check("B63b flag on", ed.APPLY_B63B is True)
check("B63c flag off after the Nov 12 blind judge (7/21)", ed.APPLY_B63C is False)
_A0, _C0 = ed.APPLY_B63A, ed.APPLY_B63C          # the rule checks below run with the rules on; restored at the end
ed.APPLY_B63A = True
check("appointer item is kept", ed.b63a_keep("one member to be appointed by the temporary president of the senate", lead="The task force shall consist of seven members as follows:"))
check("composite appointer quote is not", not ed.b63a_keep("(b) one member appointed by the governor; (c) two members appointed by the speaker of the assembly", lead="x:"))
check("plain membership item is not", not ed.b63a_keep("the commissioner of health", lead="The task force shall consist of seven members as follows:"))
check("action item under body 'at a minimum' lead is kept", ed.b63a_keep("Allow, not later than sixty days after a rule is promulgated, any interested person to file a petition", tail="C. When promulgating a rule, the interstate commission shall, at a minimum:"))
check("content item under an agreement lead is not", not ed.b63a_keep("Describe the project and the financial assistance", tail="the agreement shall, at a minimum:"))
ed.APPLY_B63A = False
check("flag off: nothing kept", not ed.b63a_keep("one member to be appointed by the governor", lead="x:"))
ed.APPLY_B63A = True
check("may exempt from disclosure matches", bool(ed.B63B_MAY_EXEMPT.search("The interstate commission may exempt from disclosure any information or official records to the extent they would adversely affect personal privacy rights.")))
check("'is exempt from' does not", not ed.B63B_MAY_EXEMPT.search("The applicant is exempt from the fee."))
check("designator half stays off", ed.APPLY_B63B_DES is False and not ed.b63b_designator_named({"actor_raw": "the county clerk"}, "to be designated by the county clerk of the county"))

ed.APPLY_B63C = True
try:
    p = lambda a, q: ed.b63c_partner({"actor_raw": a, "quote": q})
    check("joint subject: partner found", (p("the department", "The department and the division shall: (a) analyze the factors") or "").lower() == "division")
    check("joint subject: other side", (p("the division", "The department and the division shall: (a) analyze") or "").lower() == "department")
    check("record already names a non-member: no partner", p("the governor", "The department and the division shall analyze") is None)
    check("mid-sentence 'and' is no joint subject", p("the licensee", "Prior to commencing operation, the licensee shall notify the authority of the location and the board may act") is None)
    check("position pair is not two bodies", p("the commission", "A chairperson and vice-chairperson of the commission shall be elected by a majority of its members.") is None)
    check("'provided that' clause is not", p("the state", "provided that the state and city of new york shall extend such lease") is None)
    res = {"obligations": [{"obligation_id": "2099-X1-01", "actor_raw": "the department", "quote": "The department and the division shall report.", "agency": "DOH", "agency_matched": True}]}
    add = ed.b63c_split(res, "2099-X1")
    check("split appends one copy with the next id", len(add) == 1 and add[0]["obligation_id"] == "2099-X1-02" and add[0]["actor_raw"].lower() == "the division" and add[0]["agency"] == "Unspecified" and len(res["obligations"]) == 2)
    check("split twice adds nothing", ed.b63c_split(res, "2099-X1") == [])
    ed.APPLY_B63C = False
    check("flag off: no partner", p("the department", "The department and the division shall report.") is None)
finally:
    ed.APPLY_B63C = True
ed.APPLY_B63A, ed.APPLY_B63C = _A0, _C0
print("%d passed, %d failed" % (passed, failed))
