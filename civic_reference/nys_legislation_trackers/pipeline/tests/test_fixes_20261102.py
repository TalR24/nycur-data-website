"""Plain script: Nov 2 2026 night gate fixes R1-R4 (closing not-real classes). Prints 'N passed, M failed'."""
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

def gate(law, oid):
    p = HERE / "cache" / "extracted" / (law + ".json")
    if not p.exists():
        return "skip"
    t = (HERE / "cache" / "text_marked" / (law + ".txt")).read_text()
    o = [x for x in json.load(open(p))["obligations"] if x["obligation_id"] == oid][0]
    r = ed.gate_record(o, t, "{{" in t)
    return r[0] if r else None

check("R1 pledge", bool(ed.R1_PLEDGE.search("that the state will not take any action which will (a) substantially impair the authority of the board")))
check("R1 duty kept", not ed.R1_PLEDGE.search("The state shall not take any action without notice to the board."))
check("R2 sunset", bool(ed.R2_SUNSET.search("The provisions of section sixty-two through sixty-six of this act shall expire on December thirty-first, two thousand sixteen, except that:")))
check("R2 other expiry kept", not ed.R2_SUNSET.search("The commissioner shall report before the program shall expire."))
check("R4 contracts", bool(ed.R4_FORM.search("Contracts must be executed by the board of cooperative educational services and the trustees")))
check("R4 approval", bool(ed.R4_FORM.search("To be approved by the commissioner, the contract and any business plan, shall demonstrate that any services")))
check("R4 application", bool(ed.R4_FORM.search("Such application shall be made by a school district, after the board of education have adopted a resolution")))
check("R4 commissioner duty kept", not ed.R4_FORM.search("The commissioner shall approve the contract within thirty days."))
check("R3 off", ed.APPLY_R3 is False)
for law, oid, rule in (("2013-A7175", "2013-A7175-11", "state_pledge"), ("2009-S8314", "2009-S8314-58", "section_sunset"),
                       ("2011-A10205", "2011-A10205-02", "contract_form_condition"), ("2011-A10205", "2011-A10205-03", "contract_form_condition"),
                       ("2011-A2289", "2011-A2289-17", "contract_form_condition")):
    g = gate(law, oid)
    check("gate %s" % oid, g in (rule, "skip"))
def rec(law, oid):
    p = HERE / "cache" / "extracted" / (law + ".json")
    if not p.exists():
        return None, None
    t = (HERE / "cache" / "text_marked" / (law + ".txt")).read_text()
    return [x for x in json.load(open(p))["obligations"] if x["obligation_id"] == oid][0], t

# X1. deadline in the next sentence (or 'no later than' in the quote)
for law, oid, kind in (("2019-S7172", "2019-S7172-02", "days_after_effective"), ("2019-S7172", "2019-S7172-04", "days_after_effective"), ("2009-A8392", "2009-A8392-01", "fixed_date")):
    o, t = rec(law, oid)
    r = ed.next_sentence_deadline(o, t, "2020-01-01", "2019-06-01") if o else None
    check("X1 " + oid, o is None or (r and r[1] == kind))
check("X1 no period in the next sentence", ed.next_sentence_deadline({"quote": "The board shall establish a program."}, "The board shall establish a program. The board shall meet monthly.", "2020-01-01", "2019-06-01") is None)
check("X1 program", ed.next_sentence_deadline({"quote": "The board shall establish a program."}, "The board shall establish a program. Such program shall be established within one year of the effective date.", "2020-01-01", "2019-06-01") == ("2021-01-01", "days_after_effective", "within one year of the effective date"))
# X2. procedure of an election
o, t = rec("2009-S7182", "2009-S7182-02")
r = ed.gate_record(o, t, "{{" in t) if o else None
check("X2 so elect", o is None or (r and r[0] == "condition_of_other_record"))
check("X2 regex", bool(ed.X2_SO_ELECT.search("The village may so elect by filing with the state comptroller")) and not ed.X2_SO_ELECT.search("The village may elect to file"))
# X3. infinitive items under 'shall have the following powers and duties: 1. to ...' are duties
for oid in ("2011-S4376-01", "2011-S4376-02", "2011-S4376-05", "2011-S4376-06", "2011-S4376-07"):
    o, t = rec("2011-S4376", oid)
    if o is None: continue
    li = ed.imperative_lead_in(ed.locate_span(o["quote"], t), t)
    check("X3 lead found " + oid, bool(li) and ed.infinitive_lead_kind(li) == "duty")
check("X3 labels", all(ed.NUM_LABEL_X3.match(x) for x in ("2. [to", "3.] to conduct", "[4] {{3}}. to determine", "[6] {{5}}. to adopt", "1. to")))
check("X3 power lead stays", ed.infinitive_lead_kind("The board shall have the following powers: 1. to hire staff which may be needed;") == "power")
# X4. period from an undated event
for q in ("The task force shall convene within ninety days after the adjournment of the 2020 regular legislative session",
          "The appointing authorities shall make their appointments to the task force not later than thirty days after the adjournment of the 2020 regular legislative session."):
    check("X4 " + q[:25], bool(ed.X4_EVENT_PERIOD.search(q)))
check("X4 effective date untouched", not ed.X4_EVENT_PERIOD.search("shall report within one year after the effective date of this act"))
print("%d passed, %d failed" % (passed, failed))
