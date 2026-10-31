"""Plain script: Oct 31 2026 night gate fixes N1-N3 (list lead braces in reprint_date_only, act-clause provisos, payment timing to beneficiaries). Prints 'N passed, M failed'."""
import os, sys, json
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

# N1. a list lead with new matter keeps its items
lead = "To facilitate the marketing of any issue of serial bonds or notes of the county of Erie issued on or before June thirtieth, two thousand [fifteen] {{seventeen}} such county may ...:"
item = "a. The county may sell the bonds at private sale."
t = "Section 1. Subdivision 1 is amended to read as follows:\n" + lead + "\n" + item + "\n"
a = t.index(item); sp = (a, a + len(item))
sec = t[t.index("Section 1."):]
check("N1 Erie lead with braces is not reprint_date_only", ed.reprint_date_only(sp, t, sec) is False)
check("N1 item_lead_full keeps braces on request", "{{" in (ed.item_lead_full(sp, t, keep_markup=True) or ed.list_lead_in(sp, t) or ""))
check("N1 item_lead_full strips by default", "{{" not in (ed.item_lead_full(sp, t) or ""))
# a lead without braces and a date-only section is still dropped
t2 = "Section 1. Subdivision 1 is amended to read as follows:\nThe county may do the following until June thirtieth, two thousand [fifteen] {{seventeen}}.\n\nThe board shall file reports:\na. The board shall file a report each year.\n"
a2 = t2.index("a. The board"); sp2 = (a2, a2 + 40)
check("N1 no braces in the lead keeps the drop", ed.reprint_date_only(sp2, t2, t2[t2.index("Section 1."):]) is True)
R = ROOT = HERE.parent
p = HERE / "cache" / "text_marked" / "2011-S4426.txt"
if p.exists():
    t3 = p.read_text(); e = json.load(open(HERE / "cache" / "extracted" / "2011-S4426.json"))
    o = [x for x in e["obligations"] if x["obligation_id"] == "2011-S4426-02"][0]
    r = ed.gate_record(o, t3, True)
    check("N1 2011-S4426-02 (Insurance Law 2329) still dropped", bool(r) and r[0] == "reprint_date_only")

# N2. act-clause provisos
q = "provided, that the provisions of sections one, two and nine of this act shall remain in full force and effect only until and including June 23, 2015"
t = "Section 1. A.\n\n§ 10. This act shall take effect immediately; " + q.replace("June 23", "June {{23}}") + "; provided further that x.\n"
check("N2 S5997 proviso is the act's own clause", ed.own_act_clause_quote(q, t, None, None) is True)
check("N2 'shall apply' variant matches", bool(ed.N2_ACT_PROVISO.match("provided that the provisions of section three of this act shall apply to ")))
t4 = "Section 1. The board shall act.\n\n§ 2. This act shall take effect immediately.\n"
check("N2 a real duty is not an act clause", ed.own_act_clause_quote("The board shall act.", t4, None, None) is False)

# N3. payment timing
qa = "Such approved amounts shall be payable on the same day in September of the school year following the year in which application was made as funds provided pursuant to subparagraph 4"
check("N3 A2289 payable sentence is a beneficiary schedule", ed.benefit_entitlement({"quote": qa, "actor_raw": "SED", "agency": "SED"}, qa) is True)
qb = "The comptroller shall pay the approved amounts on or before June thirtieth to each district."
check("N3 'the comptroller shall pay' is kept", ed.payment_timing_beneficiary(qb) is False)
qc = "The comptroller shall make payments of such aid in September to each eligible district."
check("N3 government subject with 'make payments' is kept", ed.payment_timing_beneficiary(qc) is False)

print("%d passed, %d failed" % (passed, failed))
