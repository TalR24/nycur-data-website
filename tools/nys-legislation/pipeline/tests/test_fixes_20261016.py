"""Plain script: the Oct 16 2026 night rules R1-R6 and J17, all on synthetic fixtures (no stored data, no model calls). Prints 'N passed, M failed'."""
import json, os, sys, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

# R1. own_act_clause_quote: a sunset reprinted inside braces is an amended earlier chapter's, not the law's own clause
sunset = "This act shall take effect immediately and shall expire July 1, {{2019}} when upon such date the provisions of this act shall be deemed repealed."
own = "This act shall take effect immediately."
text = ("§ 1. Section 3 of chapter 120 of the laws of 2012 is amended to read as follows:\n\n"
        "§ 3. " + sunset + "\n\n"
        "§ 2. " + own + "\n")
raw_clause = "This act shall take effect immediately."
check("R1 the braced sunset is recognised as act-clause shaped", ed.is_act_clause_quote(sunset))
check("R1 an amended chapter's braced sunset is not the law's own clause", not ed.own_act_clause_quote(sunset, text, raw_clause))
check("R1 the law's own clause (outside braces, equals raw_clause) is", ed.own_act_clause_quote(own, text, raw_clause))
check("R1 a non-clause sentence is never an act clause", not ed.own_act_clause_quote("The commissioner shall report to the governor.", text, raw_clause))

# R2. imperative list items under a granting lead-in
lead = "§ 5. The director shall have the following powers and duties:"
t2 = lead + "\n1. {{Work with the director of the budget to prepare the annual plan;}}\n2. {{Advise the Governor on matters of state policy.}}\n"
t2b = "§ 5. Definitions.\n1. {{Work with the director of the budget to prepare the annual plan;}}\n2. {{Advise the Governor on matters of state policy.}}\n"
for q in ("Work with the director of the budget to prepare the annual plan", "Advise the Governor on matters of state policy"):
    o = {"quote_verified": True, "quote": q, "actor_raw": "the director"}
    g = ed.gate_record(o, t2, True)
    check("R2 '%s' is rescued under the lead-in" % q[:12], g is None and o.get("kind_from_lead_in") == "duty" and "following powers and duties" in o.get("lead_in", ""))
    o = {"quote_verified": True, "quote": q, "actor_raw": "the director"}
    g = ed.gate_record(o, t2b, True)
    check("R2 '%s' with no granting lead-in stays designation_no_actor" % q[:12], bool(g) and g[0] == "designation_no_actor")
sp = ed.locate_span("Work with the director of the budget to prepare the annual plan", t2)
check("R2 imperative_lead_in returns the lead paragraph", "following powers and duties" in (ed.imperative_lead_in(sp, t2) or ""))
check("R2 lead_in_subject names the actor", ed.lead_in_subject("The chief diversity officer's responsibilities shall include the following:") == "The chief diversity officer")
check("R2 lead_in_subject on the director lead-in", (ed.lead_in_subject(lead) or "").lower() == "the director")

# R3. no id is silent: missing provision_kind and merged duplicates are listed in the dropped log
law = {"key": "2099-S1", "enactment_date": "2099-01-01", "chapter_number": 1, "chapter_year": 2099, "session": 2099, "print_no": "S1", "law_number_display": "Chapter 1 of 2099",
       "title": "An act relating to testing", "sponsor": "Test", "openleg_url": "https://example.test", "act_clause": "This act shall take effect immediately."}
t3 = ("§ 1. {{The commissioner of health shall publish an annual report on testing results.}} {{The commissioner of health shall publish an annual report on testing results.}} "
      "{{The department of health shall maintain a registry of testing sites.}}\n\n§ 2. This act shall take effect immediately.\n")
def ob(n, q, **kw):
    d = {"obligation_id": "2099-S1-%02d" % n, "matter_id": "2099-S1", "actor_raw": "the commissioner of health", "agency": "DOH", "agency_full": "Department of Health", "agency_matched": True,
         "action_summary": "x", "deliverable_type": "other", "citation": "x", "quote": q, "quote_verified": True, "kind_rule": "duty", "kind_list_item": False, "kind_model": "duty",
         "provision_kind": "duty", "deadline_kind": "none", "deadline_text": None, "deadline_date": None, "recurrence": "annual", "affected_groups": []}
    d.update(kw); return d
q1 = "The commissioner of health shall publish an annual report on testing results."
obs = [ob(1, q1), ob(2, q1), ob(3, "The department of health shall maintain a registry of testing sites.", kind_rule="neither", kind_model="neither", provision_kind=None, kind="neither")]
tmp = Path(tempfile.mkdtemp())
(tmp / "x").mkdir(); (tmp / "t").mkdir()
(tmp / "x" / "2099-S1.json").write_text(json.dumps({"matter_id": "2099-S1", "model": "test", "effective_clause": {}, "effective_date": "2099-01-01", "obligations": obs, "extends_model": {}, "actor_model": {}}))
(tmp / "t" / "2099-S1.txt").write_text(t3)
saved = (ed.EXTRACTED, ed.TEXT_MARKED, ed.dedupe_law, dict(ed.EFFECTIVE))
try:
    ed.EXTRACTED, ed.TEXT_MARKED = tmp / "x", tmp / "t"
    ed.EFFECTIVE["2099-S1"] = {"rule": "immediately", "effective_date": "2099-01-01", "expires_date": None, "raw_clause": "This act shall take effect immediately.", "section_dates": []}
    ed.dedupe_law = lambda lst: lst[:1] if len(lst) > 1 else lst      # a merge path that records no rule: the safety net must list the lost id
    duties, powers, excluded = ed.build_records([law])
finally:
    ed.EXTRACTED, ed.TEXT_MARKED, ed.dedupe_law = saved[0], saved[1], saved[2]
    ed.EFFECTIVE.clear(); ed.EFFECTIVE.update(saved[3])
stored_ids = {x["obligation_id"] for x in duties + powers}
drop_by_id = {d["obligation_id"]: d for d in ed.DROPPED}
check("R3 a record with no provision_kind ends in dropped as excluded_missing_provision_kind", drop_by_id.get("2099-S1-03", {}).get("rule") == "excluded_missing_provision_kind")
check("R3 a merged duplicate is excluded_merged_duplicate", drop_by_id.get("2099-S1-02", {}).get("rule") == "excluded_merged_duplicate")
check("R3 the surviving sibling is stored", "2099-S1-01" in stored_ids)
check("R3 no id is silent: every id is stored or dropped", all(o["obligation_id"] in stored_ids or o["obligation_id"] in drop_by_id for o in obs))

# R4. trim_unit_name
check("R4 'County of Nassau Is Hereby Authorized' -> 'County of Nassau'", ed.trim_unit_name("County of Nassau Is Hereby Authorized") == "County of Nassau")
check("R4 a plain name is unchanged", ed.trim_unit_name("County of Nassau") == "County of Nassau")
check("R4 a comma tail is cut", ed.trim_unit_name("Town of Hempstead, New York") == "Town of Hempstead")

# R5. paid_entitlement
q = "A lump sum shall be paid each year to an employee who has served ten years."
check("R5 a lump sum paid to an employee, actor 'the state', is an entitlement", ed.paid_entitlement({"actor_raw": "the state", "agency": "Unspecified"}, q))
check("R5 a uniform allowance with no agency is an entitlement", ed.paid_entitlement({"actor_raw": "", "agency": None}, "A uniform allowance shall be paid to each officer."))
check("R5 'the comptroller shall pay the claim within thirty days' is not", not ed.paid_entitlement({"actor_raw": "the comptroller", "agency": "Comptroller"}, "the comptroller shall pay the claim within thirty days"))
check("R5 an agency other than Unspecified with a named actor is not an entitlement", not ed.paid_entitlement({"actor_raw": "the department of labor", "agency": "DOL"}, q))
check("R5 a named government actor before 'shall be paid' is not", not ed.paid_entitlement({"actor_raw": "the state", "agency": "Unspecified"}, "The comptroller shall certify that a lump sum shall be paid to the claimant."))

# R6a. lead_in_makes_duty
check("R6a a bare 'shall' lead-in makes a duty", ed.lead_in_makes_duty("§ 4. The board shall have the following powers and duties:"))
check("R6a 'shall perform the following:' makes a duty", ed.lead_in_makes_duty("The commissioner shall do the following:"))
check("R6a a 'may' lead-in does not", not ed.lead_in_makes_duty("The commissioner may do any of the following:"))
check("R6a 'shall not' does not", not ed.lead_in_makes_duty("The commissioner shall not do the following:"))
check("R6a 'shall have the following powers:' (no duties) does not", not ed.lead_in_makes_duty("The board shall have the following powers:"))
# R6b. resolve_said_agency
t6 = "§ 3. The director shall direct implementation of remedial actions to:\n1. {{Require said agency to submit a corrective plan within thirty days;}}\n"
lead_o = {"obligation_id": "x-01", "actor_raw": "the director", "agency": "DOB", "agency_full": "Division of the Budget", "agency_matched": True, "jurisdiction": "state",
          "quote": "The director shall direct implementation of remedial actions to:"}
item_o = {"obligation_id": "x-02", "actor_raw": "said agency", "agency": "Unspecified", "quote": "Require said agency to submit a corrective plan within thirty days"}
ed.STATS.clear()
n = ed.resolve_said_agency([lead_o, item_o], t6)
check("R6b 'said agency' takes the lead-in actor", n == 1 and item_o["agency"] == "DOB" and item_o["actor_raw"] == "the director" and item_o.get("actor_from_lead_in"))
# R6c. appointment_period
t6c = "§ 2. {{The governor shall appoint the members of the council. The appointments provided for in this section shall be made within ninety days of the effective date of this act.}}\n"
donor = {"obligation_id": "y-02", "kind": "duty", "deadline_kind": "days_after_effective", "deadline_date": None, "deadline_text": "within ninety days of the effective date",
         "quote": "The appointments provided for in this section shall be made within ninety days of the effective date of this act."}
ap = {"obligation_id": "y-01", "kind": "duty", "deadline_kind": "none", "deadline_date": None, "deadline_text": None, "quote": "The governor shall appoint the members of the council."}
ed.STATS.clear()
n = ed.appointment_period([ap, donor], t6c)
check("R6c appointment duty reads 'within ninety days' from the next sentence", n == 1 and ap["deadline_kind"] == "days_after_effective" and "ninety days" in (ap["deadline_text"] or ""))
# R6d. EVENT_TIED
check("R6d 'upon the completion of' is event-tied", bool(ed.EVENT_TIED.search("The board shall report upon the completion of the audit")))
check("R6d 'after the completion of' is event-tied", bool(ed.EVENT_TIED.search("shall publish the findings after the completion of the study")))
check("R6d a plain deadline is not", not ed.EVENT_TIED.search("The board shall report within ninety days"))

# J17. identifiable Unspecified actors
for raw in ("the court", "compacting states", "the detaining authority"):
    check("J17 '%s' with agency Unspecified is flagged" % raw, bool(ed.IDENTIFIABLE_UNSPECIFIED.search(raw)))
check("J17 'the state' is not flagged", not ed.IDENTIFIABLE_UNSPECIFIED.search("the state"))
fl = ed.judgment_flags("x", [{"actor_raw": "the court", "agency": "Unspecified", "quote": "the court shall hold a hearing", "session": 2013},
                             {"actor_raw": "the state", "agency": "Unspecified", "quote": "the state shall hold a hearing", "session": 2013}])
ia = [f for f in fl if f["check"] == "identifiable_actor_unspecified"]
check("J17 judgment_flags flags the court record only", len(ia) == 1 and ia[0]["sentences"] == ["the court shall hold a hearing"])
print("%d passed, %d failed" % (passed, failed))
