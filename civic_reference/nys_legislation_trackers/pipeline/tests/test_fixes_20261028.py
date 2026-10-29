"""Plain script: Oct 28 2026 close-the-not-real-list fixes H1 (board salary), H2 (process list item with a 'which shall satisfy' tail), H3 ('Now, therefore' findings). Prints 'N passed, M failed'."""
import os, sys, json, copy
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

def rule(oid):
    key = oid.rsplit("-", 1)[0]
    res = json.loads((ed.EXTRACTED / (key + ".json")).read_text())
    text = (ed.TEXT_MARKED / (key + ".txt")).read_text()
    o = copy.deepcopy([x for x in res["obligations"] if x["obligation_id"] == oid][0])
    if "{{" in (o.get("quote") or ""):
        o["quote"] = ed.eo.clean_stored_quote(o["quote"], text)[0]
    g = ed.gate_record(o, text, "{{" in text)
    return g[0] if g else None

# H1: the chairman and members of an authority receive a salary: the members are the subject
check("H1 A4687-02 salary dropped", rule("2009-A4687-02") == "benefit_entitlement")
check("H1 synthetic stipend", ed.salary_entitlement("the chairperson and the members of the board shall receive a stipend of five thousand dollars."))
check("H1 an actor who sets the salary stays", not ed.salary_entitlement("the board shall set the salary of the director."))
check("H1 members who report stay", not ed.salary_entitlement("the members of the board shall receive reports from the director."))

# H2: list items under 'the ... process shall include ... the following:' with a trailing 'which shall satisfy' clause
for i in ("01", "02", "05", "06"):
    check("H2 S6390-" + i + " sub-item", rule("2015-S6390-" + i) == "sub_item_of_parent")
check("H2 tail stripper", ed.WHICH_SATISFY.sub("", "a form to attest X, which shall satisfy the legal component") == "a form to attest X")
check("H2 other modal stays", ed.VERBISH.search(ed.WHICH_SATISFY.sub("", "a form that the operator shall file, which shall satisfy the component")) is not None)

# H3: the 'Now, therefore' resolving sentence of the legislative findings
check("H3 S5570-01 findings", rule("2017-S5570-01") == "legislative_findings")
check("H3 S5570-02 findings", rule("2017-S5570-02") == "legislative_findings")
check("H3 regex", bool(ed.NOW_THEREFORE.search("yet it is unrecognized. Now therefore, ")) and not ed.NOW_THEREFORE.search("The department shall, therefore, "))
t = "§ 1. Findings. Things happened. Now, therefore, the board shall install a plaque at the capitol.\n"
q = "the board shall install a plaque at the capitol."
check("H3 synthetic", (ed.gate_record({"quote": q, "quote_verified": True}, t, False) or [None])[0] == "legislative_findings")
print("%d passed, %d failed" % (passed, failed))
