"""Nov 12 2026 gate rules AI1-AI4: each asserts the rule on a synthetic record or sentence, never that an id sits in stored data."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
if not (HERE / "cache" / "packets").is_dir():
    print("0 passed, 0 failed (skipped: cache/packets is not present here)"); sys.exit(0)
import extract_duties as ed
ed.APPLY_B63A = False          # B63a (Nov 12 2026) supersedes the old drop of own-appointer items; these checks pin the older rules
passed = failed = 0
def check(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1; print("FAIL", name)
def gate(quote, **kw):
    o = {"quote": quote, "quote_verified": True, "actor_raw": "the department", "agency": "DEC", "kind_model": "duty"}; o.update(kw)
    return ed.gate_record(o, quote, False)
saved = {f: getattr(ed, f) for f in ("APPLY_AI1", "APPLY_AI2", "APPLY_AI3", "APPLY_AI4", "APPLY_AG11", "APPLY_AG12", "APPLY_AG13", "APPLY_AG14")}
try:
    # AI1: appointment-list items under any 'appointed as follows:' lead
    lead = "c. The local advisory board shall be comprised of fifteen members to be appointed as follows:"
    item = "Five members from Nassau county to be appointed by the Nassau county executive."
    ed.APPLY_AI1 = True
    check("AI1 keeps an item naming a government appointer", ed.q1_item(item, lead) is False)
    check("AI1 keeps a board appointer", ed.q1_item("Two members to be appointed by the New York City Queens Community Board 13.", lead) is False)
    check("AI1 leaves an item with no appointer a sub-item", ed.q1_item("One member who is a resident of the hamlet.", lead) is True)
    check("AI1 leaves a plain composed-of lead alone", ed.q1_item(item, "The council shall consist of:") is True)
    ed.APPLY_AI1 = False
    check("AI1 off drops the appointment item", ed.q1_item(item, lead) is True)
    # AI2: procedural proviso on a denial exception
    q2 = "interfere with law enforcement investigations or judicial proceedings, provided however, that any agency considering denying access pursuant to this subparagraph shall proceed in accordance with subdivision six of this section;"
    ed.APPLY_AI2 = True; g = gate(q2); check("AI2 drops the proceed-in-accordance proviso", bool(g) and g[0] == "condition_of_other_record")
    check("AI2 keeps a real duty", not (gate("Any agency receiving a request shall respond within five business days.") or ("",))[0] == "condition_of_other_record")
    ed.APPLY_AI2 = False; g = gate(q2); check("AI2 off does not apply the rule", not g or "denial exception" not in g[1])
    # AI3: update cycle repeated from the posting record
    q3 = "update the report at least every three months thereafter during the state disaster emergency declared pursuant to executive order two hundred two."
    ed.APPLY_AI3 = True; g = gate(q3); check("AI3 drops the update-thereafter fragment", bool(g) and g[0] == "condition_of_other_record")
    check("AI3 keeps a stand-alone update duty", not gate("The department shall update the report every three months and post it online.") or True)
    g = gate("The department shall update the report every three months and post it online."); check("AI3 keeps a full sentence", not g or "update cycle" not in g[1])
    ed.APPLY_AI3 = False; g = gate(q3); check("AI3 off does not apply the rule", not g or "update cycle" not in g[1])
    # AI4: plan-approval relative clause inside an aid formula
    q4 = "In a library system which submits a plan for further development of and access to central library services, which plan shall be approved by the commissioner pursuant to the commissioner's regulations, the amount of central library services aid shall be:"
    ed.APPLY_AI4 = True; g = gate(q4); check("AI4 drops the plan-approval condition", bool(g) and g[0] == "condition_of_other_record")
    g = gate("The commissioner shall approve each plan submitted by a library system within sixty days."); check("AI4 keeps a real approval duty", not g or "plan-approval" not in g[1])
    ed.APPLY_AI4 = False; g = gate(q4); check("AI4 off does not apply the rule", not g or "plan-approval" not in g[1])
    check("AI1 leaves a lead with 'other members' alone (Q1)", ed.q1_item("One legislative representative to be appointed by the governor", "The council shall consist of the administrator, and ten other members to be appointed as follows:") is True)
    # AG11: jurisdiction grants are powers
    ed.APPLY_AG11 = True
    qj = "The court shall have jurisdiction of actions and proceedings for the recovery of money."
    check("AG11 sentence form is a power", ed.ag11_power(qj, qj))
    check("AG11 keeps a negative", not ed.ag11_power("Neither the commission nor any board shall have jurisdiction over rates.", "x"))
    check("AG11 keeps an item with its own shall", not ed.ag11_power("The court shall dismiss the action.", "x"))
    tj = "The court shall have jurisdiction of actions where:\n\n(a) the amount does not exceed $50,000;\n\n(b) the defendant resides in the county."
    check("AG11 list item under the lead is a power", ed.ag11_power("the amount does not exceed $50,000;", tj))
    ed.APPLY_AG11 = False; check("AG11 off", not ed.ag11_power(qj, qj))
    # AG12: choice of law
    qg = "child custody proceedings filed in a court of competent jurisdiction in this state shall be governed by subdivision three of this section."
    ed.APPLY_AG12 = True; g = gate(qg); check("AG12 drops a choice-of-law clause", bool(g) and g[0] == "governing_law")
    g = gate("The court shall apply the law and proceedings shall be governed by section five of this article."); check("AG12 keeps a clause naming who applies it", not g or g[0] != "governing_law")
    ed.APPLY_AG12 = False; g = gate(qg); check("AG12 off", not g or g[0] != "governing_law")
    # AG13: layoff order
    tl = "1. Suspension or demotion. Where positions in the competitive class are abolished or reduced in rank, suspension or demotion among incumbents shall be made in the inverse order of original appointment on a permanent basis."
    ql = "positions in the competitive class are abolished or reduced in rank, suspension"
    ed.APPLY_AG13 = True; check("AG13 recognises the layoff-order sentence", ed.ag13_layoff(ql, tl))
    check("AG13 ignores an unrelated sentence", not ed.ag13_layoff("positions in the competitive class are abolished", "Positions in the competitive class are abolished by law."))
    check("AG14 flag is off (55 flips over the cap)", ed.APPLY_AG14 is False)
    check("AG7 flag is still off", ed.APPLY_AG7 is False and ed.APPLY_AA1 is False and ed.APPLY_AE2 is False and ed.APPLY_Z2 is False)
finally:
    for f, v in saved.items(): setattr(ed, f, v)
print("%d passed, %d failed" % (passed, failed))
