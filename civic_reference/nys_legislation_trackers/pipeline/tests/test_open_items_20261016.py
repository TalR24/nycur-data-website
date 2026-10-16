"""Plain script: the Oct 16 2026 open-items round O1-O8, all on synthetic fixtures (no stored data, no model calls). Prints 'N passed, M failed'."""
import os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import agency_resolve_nys as ar

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

# O1. reviewed_as_if is a condition of the accept-late power
for q in ("Any application so filed shall be reviewed as if it had been received on or before the deadline.",
          "Such an application shall be reviewed as if such application had been filed on or before July first."):
    g = ed.gate_record({"quote_verified": True, "quote": q, "actor_raw": "the department"}, "§ 1. " + q + "\n", False)
    check("O1 drop: " + q[:30], bool(g) and g[0] == "reviewed_as_if_condition")
g = ed.gate_record({"quote_verified": True, "quote": "The department shall review each application within thirty days.", "actor_raw": "the department"}, "§ 1. The department shall review each application within thirty days.\n", False)
check("O1 an ordinary review duty stays", g is None)
rules = open(HERE / "prompt_v2_rules.txt").read()
check("O1 prompt names the reviewed-as-if condition", "reviewed as if" in rules and "condition" in rules.split("reviewed as if")[1][:300])
check("O1 prompt boilerplate bullet names bill drafting commission notices", "legislative bill drafting commission" in rules)

# O2. 'the state' resolves to the State agencies group
for raw in ("the state", "The State of New York", "state"):
    o = {"actor_raw": raw, "agency": "Unspecified", "agency_matched": False, "actor_unresolved": True}
    ed.run_agency_fixes(o, "§ 1. The state shall pay.", {"title": "An act", "key": "x"})
    check("O2 '%s' -> State agencies" % raw, o["agency"] == "State agencies" and o["jurisdiction"] == "state" and o["agency_unit"] == "State of New York" and o["agency_matched"] and "actor_unresolved" not in o)
o = {"actor_raw": "the state", "agency": "DOH", "agency_matched": True}
check("O2 an already resolved agency is untouched", not ar.fix_state_actor(o) and o["agency"] == "DOH")

# O3. relocated quotes over 60 words are trimmed to a window around the braced matter
filler = " ".join("word%d" % i for i in range(1, 41))
sent = "The commissioner shall " + filler + "; and shall keep the records {{until June 1, 2031}}, " + " ".join("tail%d" % i for i in range(1, 51)) + "."
text = "§ 1. Section 4 of the law is amended to read as follows:\n\n§ 4. " + sent + "\n\n§ 2. This act shall take effect immediately.\n"
quote = "The commissioner shall word1 word2"
sp = ed.locate_span("The commissioner shall " + filler, text)
st = {}
nq = ed.relocate_quote("The commissioner shall " + filler, text, "the commissioner", trim=True, stats=st)
check("O3 relocated quote found", bool(nq))
check("O3 trimmed to at most 60 words", nq and len(nq.split()) <= 60 and st.get("before") == 1)
check("O3 window keeps the braced matter", nq and "until June 1, 2031" in nq)
check("O3 window is verbatim and verifies", nq and bool(ed.locate_span(nq, text)))
check("O3 window starts on a whole word", nq and nq.split()[0] in sent.replace("{{", "").replace("}}", "").split())
long_nq = ed.relocate_quote("The commissioner shall " + filler, text, "the commissioner")
check("O3 without trim the full sentence is kept (over 60 words)", long_nq and len(long_nq.split()) > 60)
check("O3 trim_to_window leaves a short sentence alone", ed.trim_to_window("one two three", 4, 7) == "one two three")

# O4. agency re-resolved after a gate rescue
t4 = "§ 5. The department of health shall have the following powers and duties:\n1. {{Advise the Governor on matters of public health.}}\n2. {{Prepare the annual plan.}}\n"
o = {"quote_verified": True, "quote": "Prepare the annual plan", "actor_raw": "the director", "agency": "DOB", "agency_full": "Division of the Budget", "agency_matched": True}
g = ed.gate_record(o, t4, True)
check("O4 imperative item rescued with the lead-in actor", g is None and o.get("rescued_imperative_item") and o.get("lead_in_actor", "").lower() == "the department of health")
ch = ed.reresolve_after_rescue(o, t4, {"title": "An act", "key": "x"})
check("O4 agency re-resolved to the lead-in actor", ch and o["agency"] == "DOH" and o["actor_raw"].lower() == "the department of health")
o2 = {"actor_raw": "the commissioner", "agency": "DOH", "agency_matched": True}
check("O4 an unrescued record is left alone", not ed.reresolve_after_rescue(o2, t4, {"title": "An act", "key": "x"}) and o2["agency"] == "DOH")

# O5. condition precedent: shall not proceed with / commence ... until
for q in ("The authority shall not proceed with construction of the project until the director of the budget has approved the plan.",
          "No agency shall commence the program, and the department shall not commence operations until a certificate is filed."):
    g = ed.gate_record({"quote_verified": True, "quote": q, "actor_raw": "the authority"}, "§ 1. " + q + "\n", False)
    check("O5 condition: " + q[:35], bool(g) and g[0] == "condition_precedent")
g = ed.gate_record({"quote_verified": True, "quote": "The authority shall proceed with construction of the project.", "actor_raw": "the authority"}, "§ 1. The authority shall proceed with construction of the project.\n", False)
check("O5 a plain 'shall proceed' is not a condition", g is None)

# O6. a relative-clause 'may' no longer keeps the item a power under a 'shall' lead-in
item = "To promulgate regulations defining and restricting the duties which may be assigned to specialist assistants, and the manner in which such duties may be performed;"
check("O6 relative 'may' stripped", not ed.GRANT_WORD.search(ed.strip_relative_may(item)))
check("O6 the item's own 'may' stays", bool(ed.GRANT_WORD.search(ed.strip_relative_may("The board may adopt rules that may be needed"))))
check("O6 'as the commissioner may require' stripped", not ed.GRANT_WORD.search(ed.strip_relative_may("To report as the commissioner may require")))
check("O6 the shall lead-in makes a duty", ed.lead_in_makes_duty("The commissioner shall have the following powers and duties:"))

# O7. imperative list item with no granting lead-in goes to reask
drops = [{"obligation_id": "x-01", "matter_id": "x", "rule": "designation_no_actor", "quote": "Advise the Governor on matters of public health."},
         {"obligation_id": "x-02", "matter_id": "x", "rule": "designation_no_actor", "quote": "The first member of the board."}]
txt = "§ 1. Definitions.\n1. Advise the Governor on matters of public health.\n2. The first member of the board.\n"
fl = [f for f in ed.recall_flags("x", txt, [], drops) if f["check"] == "imperative_item_no_lead_in"]
check("O7 imperative item flagged with its text", len(fl) == 1 and fl[0]["sentences"] == ["Advise the Governor on matters of public health."])

# O8. ABC display name and aliases
abc = ed.BY_CANON["ABC"]
check("O8 ABC agency_full", abc["full_name"] == "State Liquor Authority (Division of Alcoholic Beverage Control)" and abc["display_name"] == abc["full_name"])
check("O8 old variants kept", all(v in abc["variants"] for v in ("ABC", "Division of Alcohol Beverage Control", "nys Division of Alcohol Beverage Control")))
for raw in ("the State Liquor Authority", "state liquor authority", "Division of Alcoholic Beverage Control"):
    o = {"actor_raw": raw, "agency": "Unspecified", "agency_matched": False}
    ed.run_agency_fixes(o, "§ 1. x", {"title": "An act", "key": "x"})
    check("O8 '%s' -> ABC" % raw, o["agency"] == "ABC" and o["agency_full"].startswith("State Liquor Authority"))
o = {"actor_raw": "the authority", "agency": "Unspecified", "agency_matched": False, "citation": "Alcoholic Beverage Control Law § 17"}
ed.run_agency_fixes(o, "§ 1. x", {"title": "An act", "key": "x"})
check("O8 'the authority' under the ABC Law -> ABC", o["agency"] == "ABC")
print("%d passed, %d failed" % (passed, failed))
