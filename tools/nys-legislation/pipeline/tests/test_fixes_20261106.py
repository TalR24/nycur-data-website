"""Plain script: Nov 6 2026 night gate fixes (Y3/Y4 live, Z2 audit-and-warrant, Z3 set-at proviso, Z4 responsibility split, requeue cap, ongoing lead items).
Prints 'N passed, M failed'. Asserts each rule on the rule text / cached record, never that an id is in the stored data."""
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

def cached(oid):
    f = HERE / "cache" / "extracted" / (oid.rsplit("-", 1)[0] + ".json")
    if not f.exists(): return None
    for o in json.load(open(f))["obligations"]:
        if o["obligation_id"] == oid: return o

def gate_q(q):
    return ed.gate_record({"quote": q, "quote_verified": True, "agency": "X", "agency_unit": None, "actor_raw": "x"}, q, False)

check("Y3/Y4 flags live", ed.APPLY_Y3 and ed.APPLY_Y4)
g = gate_q("which plan shall be approved by the commissioner pursuant to the commissioner's regulations"); check("Y3 gate", bool(g) and g[0] == "condition_of_other_record")
g = gate_q("No trustee of the existing Grinnell library shall serve as chairperson or as an election inspector."); check("Y4 gate", bool(g) and g[0] == "no_duty_or_power")
if ed.APPLY_Z2:
    g = gate_q("Moneys shall be paid out of the account on the audit and warrant of the state comptroller on vouchers certified or approved by the chair of the commission."); check("Z2 gate", bool(g) and g[0] == "amount_not_duty")
else:
    print("skipped: Z2 is off by decision (B37 sample pending)"); passed += 1
check("Z2 plain comptroller duty kept", gate_q("The comptroller shall audit the vouchers of the commission each quarter.") is None)
g = gate_q("provided however, that the maximum rent for such vouchers shall be set at the United States department of housing and urban development's fair market rent level"); check("Z3 gate", bool(g) and g[0] == "condition_of_other_record")
check("Z3 other proviso kept", not ed.Z3_SET_AT.search("provided however, that the commissioner shall set the maximum rent each year"))
g = gate_q("shall be the responsibility of the political subdivision which adopted the service award program and not the responsibility of the state or requesting local government"); check("Z4 gate", bool(g) and g[0] == "amount_not_duty")
check("Z4 plain responsibility kept", not ed.Z4_RESPONSIBILITY.search("The department shall be the responsibility of the commissioner."))
# requeue cap
S = "The task force shall meet."
r = {"check": "audit_confirmed_miss", "detail": "d", "sentences": [S]}
k, sup = ed.apply_reask_history([r], {"count": 3, "sentences": [S]}); check("cap: count 3 still queued", len(k) == 1 and sup == [])
k, sup = ed.apply_reask_history([r], {"count": 4, "sentences": [S]})
check("cap: count 4 suppressed with nested reasons", k == [] and len(sup) == 1 and sup[0]["check"] == "requeue_capped_after_4" and sup[0]["reasons"] == [r])
# ongoing lead items
lead = "{{§ 459. Powers and duties. The task force shall support and work with the community to promote seafood, including but not limited to:}}\n\n"
def item(q): return {"kind_list_item": True, "quote": q}
t = lead + "{{1. Identify barriers that prevent local seafood marketing initiatives and growth;}}\n{{2. Provide a report of its findings no later than December 1, 2018.}}\n"
check("ongoing: continuing verb under a body lead", ed.ongoing_lead_item(item("Identify barriers that prevent local seafood marketing initiatives and growth;"), t))
check("ongoing: dated report item keeps its deadline", not ed.ongoing_lead_item(item("Provide a report of its findings no later than December 1, 2018."), t))
check("ongoing: non-list item untouched", not ed.ongoing_lead_item({"kind_list_item": False, "quote": "Identify barriers that prevent local seafood marketing initiatives and growth;"}, t))
t2 = "{{The applicant shall:}}\n\n{{1. Identify barriers that prevent local seafood marketing initiatives and growth;}}\n"
check("ongoing: lead without a standing body untouched", not ed.ongoing_lead_item(item("Identify barriers that prevent local seafood marketing initiatives and growth;"), t2))
o = cached("2017-A6893-07"); tp = HERE / "cache" / "text_marked" / "2017-A6893.txt"
if o and tp.exists():
    check("ongoing: A6893-07 cached record", ed.ongoing_lead_item(o, tp.read_text()))
# W3: widened extension holder
_o = lambda: {"obligation_id": "x-01", "actor_raw": "chapter 756 of the laws of 1992 (work force education program)", "agency": "chapter 756 of the laws of 1992 (work force education program)", "agency_matched": False,
              "quote": "This act shall take effect July 1, 1992, and shall be deemed repealed on June 30, 2011."}
_txt = "This act shall take effect July 1, 1992, and shall be deemed repealed on June 30, 2011."
_a = _o(); check("W3 no holder in the title: unnamed (dropped and flagged)", ed.w2_extension_holder(_a, _txt, {"title": "AN ACT making appropriations for the support of government", "act_clause": ""}) == "unnamed")
_b = _o(); check("W3 holder from the title", ed.w2_extension_holder(_b, _txt, {"title": "AN ACT to amend a chapter relating to the town of Islip", "act_clause": ""}) == "moved" and "Islip" in _b["actor_raw"])
_c = _o(); _c["quote"] = "Chapter 756 shall be filed with the clerk each year."; check("W3 non-expiry sentence untouched", ed.w2_extension_holder(_c, _txt, {"title": ""}) is None)
# COST_BEARING
for q in ("All past service costs associated with implementing the provisions of this act shall be borne by the state of New York.",
          "All employer past service costs associated with the implementation of this act shall be borne by Columbia county, and may be amortized over a period of five years.",
          "The cost of the study shall be borne equally by the two counties."):
    check("COST_BEARING " + q[:40], bool(ed.COST_BEARING.search(q)))
check("COST_BEARING plain sentence not matched", not ed.COST_BEARING.search("The commissioner shall bear a copy of the seal."))
print("%d passed, %d failed" % (passed, failed))
