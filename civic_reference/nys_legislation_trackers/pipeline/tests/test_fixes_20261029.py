"""Plain script: Oct 29 2026 night gate fixes P1-P5 (content lead-ins, private actors, swapped consultees, joint actors in dedupe, savings clauses and
sunset holders). Prints 'N passed, M failed'."""
import os, sys, re
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

def item_rule(text, quote):
    a = text.index(quote)
    r = ed.v_item_rule({"quote": quote}, (a, a + len(quote)), text, "", "")
    return r[0] if r else None

# P1. content-list lead-ins
for lead in ("The agreement shall include:", "Such protocols shall include:", "The plan shall, at a minimum, address the following:", "The report shall also include:"):
    t = "Section 1. " + lead + "\n(a) the names of the parties and the term of the loan;\n(b) the date of each payment.\n"
    check("P1 %r drops its items" % lead, item_rule(t, "(b) the date of each payment.") == "sub_item_of_parent")
t = "Section 1. The commissioner shall have the following powers and duties, including:\n(a) the names of the parties;\n"
check("P1 a powers-and-duties lead keeps its items", item_rule(t, "(a) the names of the parties;") is None)

# P2. private actors
def rec(raw, quote, model=None, agency="Unspecified"):
    return {"quote": quote, "quote_verified": True, "actor_raw": raw, "actor_resolved_model": model, "agency": agency, "kind_model": "duty"}
T = "Section 1. A bill. The district management association shall file a plan. The commissioner shall review it."
check("P2 district management association", ed.private_actor_record(rec("the district management association", "The district management association shall file a plan with the board."), "The district management association shall file a plan with the board.", T))
check("P2 applicant with model actor unspecified", ed.private_actor_record(rec("the applicant", "The applicant shall submit a form.", "unspecified"), "The applicant shall submit a form.", T))
check("P2 cemetery corporation", ed.gate_record(rec("A cemetery corporation", "A cemetery corporation shall keep records of burials."), T, False) == ("private_actor", ed.gate_record(rec("A cemetery corporation", "A cemetery corporation shall keep records of burials."), T, False)[1]))
check("P2 government actor named before the modal is kept", not ed.private_actor_record(rec("the operator", "The commissioner, on a request by the operator, shall issue a permit."), "The commissioner, on a request by the operator, shall issue a permit.", T))
check("P2 a government actor_raw is kept", not ed.private_actor_record(rec("the commissioner", "The commissioner shall notify the owner."), "The commissioner shall notify the owner.", T))
check("P2 model actor naming a department is kept", not ed.private_actor_record(rec("the provider", "The provider shall report to the department.", "department of health"), "The provider shall report to the department.", T))
check("P2 employer in a Civil Service Law act is kept", not ed.private_actor_record(rec("the employer", "The employer shall pay the fee."), "The employer shall pay the fee.", "Civil Service Law section 5. The employer shall pay the fee."))

# P3. swapped consultee reprints
s1 = "The secretary and commissioner, in consultation with the [board] {{armored car carrier industry,}} are hereby authorized to promulgate rules."
check("P3 consultation swap is a reprint", ed.reprinted_name_swap(s1))
s2 = "The commissioner shall act in consultation with [the commissioner of health] {{the commissioner of education}} on the plan."
check("P3 multi-word office swap in consultation", ed.reprinted_name_swap(s2))
s3 = "The commissioner shall act with the approval of [the director of the budget] {{the comptroller}}."
check("P3 approval swap", ed.reprinted_name_swap(s3))
s4 = "The commissioner shall report to [the commissioner of health] {{the commissioner of education}} on the plan."
check("P3 outside a consultation clause the multi-word swap stays a record", not ed.reprinted_name_swap(s4))
s5 = "The commissioner shall act in consultation with [the board] {{the board within ninety days}}."
check("P3 a swap bringing a period stays a record", not ed.reprinted_name_swap(s5))

# P4. joint actors survive dedupe
Q = "Seven members shall be appointed by the governor, six by the speaker of the assembly and six by the temporary president of the senate."
def jr(i, model):
    return {"obligation_id": "X-%02d" % i, "agency": "Legislature", "agency_unit": None, "quote": Q, "kind": "duty", "actor_resolved_model": model, "deadline_kind": "none"}
recs = [jr(1, "the governor"), jr(2, "the speaker of the assembly"), jr(3, "the temporary president of the senate")]
ed.DROPPED.clear()
out = ed.dedupe_law(list(recs))
check("P4 three actors, one sentence: all three kept", len(out) == 3 and not ed.DROPPED)
parts = ed.merge_partitions([dict(r, citation="Public Health Law 1", quote=Q) for r in recs], "Section 1. " + Q)
check("P4 merge partitions keep the three actors apart", len(parts) == 3)
check("P2 a hospital operated by a State office is kept", not ed.private_actor_record(rec("contracts for special education in hospitals operated by the office of mental health", "This act shall take effect July 1, 2012 and shall expire June 30, 2021."), "This act shall take effect July 1, 2012 and shall expire June 30, 2021.", T))
check("P2 a participating employer in a retirement program is kept", not ed.private_actor_record(rec("Each participating employer", "Each participating employer shall contribute."), "Each participating employer shall contribute.", "Retirement and Social Security Law. Each participating employer shall contribute."))
recs2 = [jr(1, "the governor"), jr(2, "The Governor")]
ed.DROPPED.clear()
out = ed.dedupe_law(list(recs2))
check("P4 true duplicates still collapse", len(out) == 1 and ed.DROPPED and ed.DROPPED[0]["rule"] == "duplicate_provision")
ed.DROPPED.clear()

# P5. savings clauses and sunset holders
for q in ("Nothing contained in this act shall be deemed to alter, affect or limit the powers of the board.", "Nothing in this section shall be construed to prohibit a town from adopting a stricter rule."):
    check("P5 savings clause %r" % q[:30], ed.gate_record(rec("the board", q), q, False) and ed.gate_record(rec("the board", q), q, False)[0] == "savings_clause")
q = "The board shall not be deemed to have waived its authority."
check("P5 an ordinary sentence is not a savings clause", not ed.SAVINGS_CLAUSE.search(q))
ACT = "AN ACT to amend chapter 576 of the laws of 1974 relating to rent, chapter 329 of the laws of 1963 relating to Albany, chapter 555 of the laws of 1982 relating to the city of New York, and chapter 402 of the laws of 1983 relating to the counties of Nassau, Westchester and Rockland"
check("P5 a multi-chapter, multi-county act title names no holder", ed.sunset_holder("Relates to rent control", ACT) is None)
check("P5 a single-town act still names its holder", ed.sunset_holder("Relates to the town of Islip", "AN ACT to amend chapter 12 of the laws of 2001 relating to the town of Islip") == "the town of Islip")

print("%d passed, %d failed" % (passed, failed))
