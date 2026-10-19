"""Plain script: Oct 19 2026 closing fixes N1-N5 (amount/cap/term/form subjects, availability windows, goal statements, gender reprint
sentence boundary, pre-existing actor reprint). Each case is the exact stored quote. Prints 'N passed, M failed'."""
import os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

def rec(raw, q, agency="Unspecified"):
    return {"actor_raw": raw, "agency": agency, "quote": q, "quote_verified": True}

def gate(raw, q):
    return ed.gate_record(rec(raw, q), "", False)

# N1: benefit, amount, cap, term and form sentences
N1 = [
 ("the Retirement System", "A member's final average salary shall be calculated in accordance with such Provisions of Article eight or Article eleven of This Chapter as govern the member's Benefits, except that earnings classified as overtime compensation shall be excluded from such calculation."),
 ("an employer in the New York city police pension fund and in the New York city fire department pension fund", "the rate of such contribution assumed by an employer in the New York city police pension fund and in the New York city fire department pension fund shall be equal to the rate of such contributions assumed by such employer"),
 ("public retirement systems", "shall be continued notwithstanding any other provision of any general, special or local law provided, however, that all such supplemental retirement allowances or supplemental pensions which are scheduled to expire at any time during two thousand nine shall be continued notwithstanding any other provisions of any general, special or local law."),
 ("the Retirement Board", "the Rate of Interest that was being charged on such loans immediately prior to the Effective Date of This subdivision shall be Used for new loans from the tax-deferred Annuity Program made on or after the Effective Date of This subdivision"),
 ("the office of temporary and disability assistance", "state reimbursement otherwise payable to such local social services district shall be reduced by seventy percent of the non-federal share of total administrative costs, as determined by the office of temporary and disability assistance and approved by the director of the budget."),
 ("a school district", "The claim for an apportionment to be paid to a school district pursuant to subdivision a of this section shall be submitted to the commissioner of education on a form prescribed for such purpose, and shall be payable upon determination by such commissioner that the form has been submitted as prescribed."),
 ("an amount equal to the amount paid", "an amount equal to the amount paid to a school district pursuant to subdivisions a and b of this section shall first be deducted from the following payments due the school district"),
 ("The amount of such additional accrual", "The amount of such additional accrual shall be certified to the commissioner of education by the president of the board of education or the trustees"),
 ("A new permit", "new permit for a Water withdrawal system and any subsequent renewal thereof shall be valid for a period of time not to exceed ten years from the date of issuance."),
 ("the department", "Application for grants made pursuant to this section shall be made in the manner and on forms prescribed by the department."),
 ("the department", "no grant shall be made to any one or any consortium of career education agencies and not-for-profit corporations in excess of seventy-five thousand dollars"),
]
for raw, q in N1:
    g = gate(raw, q)
    check("N1 drops: " + q[:45], g and g[0] == "benefit_entitlement")
# keeps: an officer who sets the salary, and a department that prescribes
check("N1 keeps salary set by the governor", gate("the governor", "The salary of the director shall be established by the governor within the limit of funds available therefor") is None)
check("N1 keeps the commissioner who shall set a grant", gate("the commissioner", "The commissioner shall make no grant to any applicant in excess of the funds appropriated") is None)

# N2: availability windows
for raw, q in [("the city of New York", "no benefits pursuant to this part shall be granted for construction work performed pursuant to a building permit issued after April first, two thousand fifteen."),
               ("the emergency housing rent control law", "The provisions of this act, and all regulations, orders and requirements thereunder shall remain in full force and effect until and including June 23, 2015."),
               ("conversion to cooperative or condominium ownership provisions, city of New York", "the provisions of sections one, two and nine of this act shall remain in full force and effect only until and including June 23, 2015"),
               ("conversion provisions, counties of Nassau, Westchester and Rockland", "the provisions of sections one and three of this act shall remain in full force and effect only until and including June 23, 2015")]:
    g = gate(raw, q)
    check("N2 drops: " + q[:45], g and g[0] == "benefit_window")
check("N2 keeps an agency that grants benefits", gate("the commissioner", "The commissioner shall grant benefits under this part to each eligible applicant within thirty days.") is None)

# N3: goal statements and litigation consequences
g = gate("the task force", "The goals of the task force may include, but are not limited to, the study, evaluation and development of recommendations: (I) to encourage the establishment and expansion of community gardens")
check("N3 goals of the task force", g and g[0] == "goal_statement")
g = gate("the agency", "Shall be deemed abandoned if the agency fails to serve and file a record and brief within sixty days after the date of service upon the petitioner of the notice of appeal")
check("N3 deemed abandoned", g and g[0] == "goal_statement")
check("N3 keeps authorized rulemaking to effectuate purposes", gate("the authority", "The authority is hereby authorized to promulgate rules and regulations to effectuate the purposes of this section.") is None)

# N4: a span that opens a sentence is not part of the previous sentence
TXT = "Section 1. Section 5 of the vehicle law is amended to read as follows:\n\n§ 5. The registrant or his {{or her}} agent shall file a form. Where an application is denied, the commissioner may, in his {{or her}} discretion, deny a renewal application."
Q = "Where an application is denied, the commissioner may, in his or her discretion, deny a renewal application"
sp = ed.locate_span(Q, TXT)
check("N4 sentence starts at the quote", sp and ed.context_sentence(sp, TXT)[0].startswith("Where an application"))
g = ed.gate_record(rec("the commissioner", Q), TXT, True)
check("N4 reprinted_gender_neutral fires", g and g[0] == "reprinted_gender_neutral")

# N5: a braced second actor leaves the first actor's record a reprint
TXT5 = "Section 1. Section 2 of the community gardens law is amended to read as follows:\n\n2. State agencies {{and municipalities}} which have received an application for use of public lands for community garden purposes shall respond to the applicant within thirty days."
Q5 = "State agencies and municipalities which have received an application for use of public lands for community garden purposes shall respond to the applicant within thirty days"
g = ed.gate_record(rec("State agencies", Q5), TXT5, True)
check("N5 first actor is a reprint", g and g[0] == "reprinted_existing_actor")
g = ed.gate_record(rec("municipalities", Q5), TXT5, True)
check("N5 braced actor stays", g is None or g[0] != "reprinted_existing_actor")

print("%d passed, %d failed" % (passed, failed))
