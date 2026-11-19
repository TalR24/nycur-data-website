"""Plain script: Oct 18 2026 carried fixes. C1 list items and AUTH_DIRECTED / lead-in duties through build_records; C2 actor_source narrowed. Synthetic fixtures only. Prints 'N passed, M failed'."""
import os, sys, json, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

# C1. regex
check("C1 'authorized and directed' matches AUTH_DIRECTED", bool(ed.AUTH_DIRECTED.search("The comptroller is authorized and directed to transfer three million dollars")))
check("C1 'authorized and required' matches AUTH_DIRECTED", bool(ed.AUTH_DIRECTED.search("All officers are hereby authorized and required to pay such funds")))
check("C1 plain 'authorized' does not", not ed.AUTH_DIRECTED.search("The comptroller is authorized to transfer funds"))

law = {"key": "2099-S2", "enactment_date": "2099-01-01", "chapter_number": 2, "chapter_year": 2099, "session": 2099, "print_no": "S2", "law_number_display": "Chapter 2 of 2099",
       "title": "An act relating to testing", "sponsor": "Test", "openleg_url": "https://example.test", "act_clause": "This act shall take effect immediately."}
Q_SHALL = "Publish an annual report on testing results;"
Q_INS = "To inspect outside laboratories for testing;"
Q_MAY = "Contract with outside laboratories for testing;"
Q_AD2 = "The office of the state comptroller is authorized and directed to audit the testing fund every year;"
Q_AD = "The office of the state comptroller is authorized and directed to transfer three million dollars to the testing fund;"
text = ("§ 1. The commissioner of health shall:\n1. {{" + Q_SHALL + "}}\n"
        "§ 2. The commissioner of health may:\n1. {{" + Q_MAY + "}}\n"
        "§ 3. The commissioner of health shall have the following powers:\n1. {{" + Q_INS + "}}\n"
        "§ 4. The following shall be done:\n1. {{" + Q_AD + "}}\n"
        "§ 5. This act shall take effect immediately.\n")
def ob(n, q, kind_model, **kw):
    d = {"obligation_id": "2099-S2-%02d" % n, "matter_id": "2099-S2", "actor_raw": "the commissioner of health", "agency": "DOH", "agency_full": "Department of Health", "agency_matched": True,
         "action_summary": "x", "deliverable_type": "other", "citation": "x", "quote": q, "quote_verified": True, "kind_rule": "power", "kind_list_item": True, "kind_model": kind_model,
         "provision_kind": kind_model, "deadline_kind": "none", "deadline_text": None, "deadline_date": None, "recurrence": "ongoing", "affected_groups": []}
    d.update(kw); return d
obs = [ob(1, Q_SHALL, "duty"), ob(2, Q_MAY, "power"), ob(3, Q_INS, "power"),
       ob(4, Q_AD, "power", actor_raw="the office of the state comptroller", agency="OSC", agency_full="Office of the State Comptroller"),
       ob(5, Q_AD2, "duty", actor_raw="the office of the state comptroller", agency="OSC", agency_full="Office of the State Comptroller")]
tmp = Path(tempfile.mkdtemp()); (tmp / "x").mkdir(); (tmp / "t").mkdir()
text += ""
(tmp / "x" / "2099-S2.json").write_text(json.dumps({"matter_id": "2099-S2", "model": "test", "effective_clause": {}, "effective_date": "2099-01-01", "obligations": obs, "extends_model": {}, "actor_model": {}}))
(tmp / "t" / "2099-S2.txt").write_text(text.replace(Q_AD2, Q_AD2))
# the fifth quote must exist in the text
(tmp / "t" / "2099-S2.txt").write_text(text.replace("}}\n§ 5.", "}}\n2. {{" + Q_AD2 + "}}\n§ 5."))
saved = (ed.EXTRACTED, ed.TEXT_MARKED, dict(ed.EFFECTIVE))
try:
    ed.EXTRACTED, ed.TEXT_MARKED = tmp / "x", tmp / "t"
    ed.EFFECTIVE["2099-S2"] = {"rule": "immediately", "effective_date": "2099-01-01", "expires_date": None, "raw_clause": "This act shall take effect immediately.", "section_dates": []}
    duties, powers, excluded = ed.build_records([law])
finally:
    ed.EXTRACTED, ed.TEXT_MARKED = saved[0], saved[1]
    ed.EFFECTIVE.clear(); ed.EFFECTIVE.update(saved[2])
kind = {x["obligation_id"]: "duty" for x in duties}; kind.update({x["obligation_id"]: "power" for x in powers})
check("C1 item under 'shall:' with no grant word is a duty", kind.get("2099-S2-01") == "duty")
check("C1 item under 'may:' stays a power", kind.get("2099-S2-02") == "power")
check("C1 item under 'shall have the following powers' stays a power", kind.get("2099-S2-03") == "power")
check("C1 'authorized and directed' item with kind_model power under a non-duty lead-in is a duty", kind.get("2099-S2-04") == "duty")
check("C1 'authorized and directed' item with kind_model duty is a duty", kind.get("2099-S2-05") == "duty")

# C2. actor_source only when the model-actor fallback resolved
def rec(raw, model, **kw):
    d = {"actor_raw": raw, "actor_resolved_model": model, "agency": "Unspecified", "agency_full": "Unspecified", "agency_matched": False, "quote": "x", "citation": "x", "action_summary": "x"}
    d.update(kw); return d
LAW = {"title": "Relates to a demonstration program in Nassau county"}
o = rec("such demonstration program", "Nassau county")
ed.attach_jurisdiction(o); ed.run_agency_fixes(o, "", LAW)
check("C2 passive raw resolved from the model keeps model_resolved", o.get("actor_source") == "model_resolved" and o["agency"] == "Counties")
o = rec("the town board", "town of Carmel", agency="Towns", agency_full="Towns", agency_matched=True)
ed.attach_jurisdiction(o); ed.run_agency_fixes(o, "", LAW)
check("C2 raw already resolved (town board) loses model_resolved", o.get("actor_source") is None and o["agency"] == "Towns")
o = rec("the commissioner of health", "Department of Health", agency="DOH", agency_full="Department of Health", agency_matched=True)
ed.attach_jurisdiction(o); ed.run_agency_fixes(o, "", LAW)
check("C2 a resolved state actor is not tagged", o.get("actor_source") is None)

print("%d passed, %d failed" % (passed, failed))
