"""Plain script: the Oct 17 2026 night rules S1-S7, all on synthetic fixtures (no stored data, no model calls). Prints 'N passed, M failed'."""
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

def rec(raw, model, **kw):
    d = {"actor_raw": raw, "actor_resolved_model": model, "agency": "Unspecified", "agency_full": "Unspecified", "agency_matched": False, "quote": "x", "citation": "x", "action_summary": "x"}
    d.update(kw); return d

LAW = {"title": "Relates to adjudications and owner liability for a violation of traffic-control signal indications in Nassau county"}

# S1. model-actor fallback (2009-A7329-03 and -09 shapes)
o = rec("such demonstration program", "Nassau county")
ed.attach_jurisdiction(o); ed.run_agency_fixes(o, "", LAW)
check("S1 passive program subject resolves to the model's county", o["agency"] == "Counties" and o["agency_unit"] == "County of Nassau" and o["jurisdiction"] == "local")
check("S1 actor_raw kept, actor_source model_resolved", o["actor_raw"] == "such demonstration program" and o.get("actor_source") == "model_resolved" and not o.get("actor_unresolved"))
o = rec("the court having jurisdiction over traffic infractions", "courts having jurisdiction over traffic infractions in Nassau county")
ed.attach_jurisdiction(o); ed.run_agency_fixes(o, "", LAW)
check("S1 courts resolve to the Unified Court System", o["agency"] == "Unified Court System")
o = rec("such demonstration program", "Unspecified")
ed.attach_jurisdiction(o); ed.run_agency_fixes(o, "", LAW)
check("S1 an Unspecified model actor leaves the record Unspecified", o["agency"] == "Unspecified")
o = rec("the notice", "State Liquor Authority", actor_unresolved=True)
ed.attach_jurisdiction(o); ed.run_agency_fixes(o, "", LAW)
check("S1 the model's crosswalk body is used (alias path)", o["agency"] == "ABC" and o.get("actor_source") == "model_resolved")

# S2. county units are real counties
check("S2 62 counties", len(ar.COUNTIES) == 62 and len(set(ar.COUNTIES)) == 62)
check("S2 'any other entity county' is no locality", ed.named_locality("any other entity county", "such county") is None)
check("S2 'empower county' is no locality", ed.named_locality("shall empower county officials") is None)
check("S2 'Nassau County' is County of Nassau", ed.named_locality("such Nassau County shall") == ("Counties", "County of Nassau"))
check("S2 'suffolk county' (lower case) is County of Suffolk", ed.named_locality("the suffolk county board") == ("Counties", "County of Suffolk"))
check("S2 'county of onondaga for any county purpose' trims to the county", ed.named_locality("the county of Onondaga for any county purpose, shall") == ("Counties", "County of Onondaga"))
check("S2 'county of entity' is rejected", ed.named_locality("the county of Entity shall") is None)
check("S2 law_locality ignores junk counties", ed.law_locality("Any other entity county shall file.", "An act") is None)
o = rec("such county", "Empower", quote="Such county shall file a report.")
ed.attach_jurisdiction(o); ed.run_agency_fixes(o, "The county of Suffolk is authorized to act.", {"title": "An act in relation to the county of Suffolk"})
check("S2 'such county' takes the law's named county", o["agency"] == "Counties" and o["agency_unit"] == "County of Suffolk")
o = rec("such county", "Nassau county", quote="Such county shall file a report.")
ed.attach_jurisdiction(o); ed.run_agency_fixes(o, "No locality here.", {"title": "An act"})
check("S2 'such county' falls back to the model's actor", o["agency"] == "Counties" and o["agency_unit"] == "County of Nassau")

# S3. list item under a 'shall' lead-in, kind_model duty: the cap does not apply
ed.STATS.clear(); ed.STATS["r6a_shall_lead_in_duty"] = ed.R6_CAP
t3 = "§ 5. The office shall:\n(a) {{coordinate community gardens across the state;}}\n(b) {{publish a directory of gardens.}}\n"
q = "coordinate community gardens across the state"
lead = ed.list_item_lead(ed.locate_span(q, t3), t3)
check("S3 the lead-in is found and makes a duty", bool(lead) and ed.lead_in_makes_duty(lead))
check("S3 r6_ok refuses once capped (other R6 rules keep the cap)", not ed.r6_ok("a_shall_lead_in_duty", {}))
src = open(HERE / "extract_duties.py").read()
check("S3 the uncapped branch is keyed on kind_model duty", 'o.get("kind_model") == "duty" and lead_in_makes_duty(lead)' in src)

# S4. infinitive list items under a granting lead-in
t4 = "§ 7. {{The interstate commission shall have the following powers:}}\n\n1. {{To appoint and remove officers and employees;}}\n\n2. {{To establish, operate and maintain offices.}}\n"
for q in ("To appoint and remove officers and employees", "To establish, operate and maintain offices"):
    o = {"quote_verified": True, "quote": q, "actor_raw": None}
    g = ed.gate_record(o, t4, True)
    check("S4 '%s' is rescued as a power" % q[:14], g is None and o.get("kind_from_lead_in") == "power" and "following powers" in o.get("lead_in", ""))
t4b = "§ 7. The commissioner shall:\n1. {{To appoint a deputy;}}\n2. {{To report annually.}}\n"
o = {"quote_verified": True, "quote": "To appoint a deputy", "actor_raw": None}
check("S4 'shall:' lead-in makes the infinitive item a duty", ed.gate_record(o, t4b, True) is None and o.get("kind_from_lead_in") == "duty")
t4c = "§ 7. Definitions.\n1. {{To appoint a deputy;}}\n2. {{To report annually.}}\n"
o = {"quote_verified": True, "quote": "To appoint a deputy", "actor_raw": None}
g = ed.gate_record(o, t4c, True)
check("S4 no granting lead-in stays designation_no_actor", bool(g) and g[0] == "designation_no_actor")
check("S4 'To the extent' is not an infinitive item", not ed.IMPERATIVE_ITEM.match("To the extent provided by law"))

# S5. gender-word reprints
t5 = ("§ 1. Section 9 of the executive law is amended to read as follows:\n\n"
      "§ 9. The commissioner shall notify the applicant and he {{or she}} shall be heard by the commissioner in person.\n\n"
      "The commissioner shall publish {{an annual report}} on all hearings.\n")
o = {"quote_verified": True, "quote": "The commissioner shall notify the applicant and he or she shall be heard by the commissioner in person.", "actor_raw": "the commissioner"}
g = ed.gate_record(o, t5, True)
check("S5 a sentence whose only braced matter is 'or she' is dropped", bool(g) and g[0] == "reprinted_gender_neutral")
o = {"quote_verified": True, "quote": "The commissioner shall publish an annual report on all hearings.", "actor_raw": "the commissioner"}
g = ed.gate_record(o, t5, True)
check("S5 a sentence with real new matter is kept", g is None or g[0] != "reprinted_gender_neutral")
check("S5 'his or her' is a gender edit", bool(ed.GENDER_EDIT.match("his or her")) and bool(ed.GENDER_EDIT.match(", or she")) and bool(ed.GENDER_EDIT.match("himself or herself")))
check("S5 a title is not a gender edit", not ed.GENDER_EDIT.match("the commissioner or his designee"))

# S6a. pilot follow-on duty with a stated period before it
t6 = ("§ 3. Within one hundred eighty days of the effective date of this act, the departments shall institute pilot projects for small businesses. "
      "Such pilot projects shall be designed by the agency in conjunction with the division for small business.\n")
q6 = "Such pilot projects shall be designed by the agency in conjunction with the division for small business."
sp = ed.locate_span(q6, t6)
check("S6a the pilot follow-on quote is recognised", bool(ed.PILOT_FOLLOW_ON.match(q6)))
check("S6a the preceding sentence sets the period", ed.preceding_sentence_has_period(sp, t6))
t6b = "§ 3. The departments shall institute pilot projects for small businesses. Such pilot projects shall be designed by the agency in conjunction with the division for small business.\n"
check("S6a no period before: unchanged", not ed.preceding_sentence_has_period(ed.locate_span(q6, t6b), t6b))

# S6b. benefit availability window with no government actor
q = "the benefits of this subparagraph shall be available in the borough of Manhattan for new multiple dwellings that commence construction after July first, nineteen hundred ninety-two"
check("S6b a benefits-available window is an entitlement", ed.benefit_entitlement({"actor_raw": "New York City"}, q))
check("S6b 'shall be eligible for benefits' is an entitlement", ed.benefit_entitlement({"actor_raw": "the owner"}, "A dwelling unit shall be eligible for benefits under this section."))
check("S6b a government actor before the modal keeps the record", not ed.benefit_entitlement({"actor_raw": "the commissioner"}, "The commissioner of finance shall certify that benefits of this section shall be available."))

# S7. local_body_unresolved judgment flag
recs = [{"actor_raw": "the Nassau county traffic and parking violations agency", "agency": "Nassau County Traffic and Parking Violations Agency", "agency_source": "named_body", "jurisdiction": "local",
         "agency_org_type": "named body", "quote": "The agency shall adjudicate."},
        {"actor_raw": "the department", "agency": "DOH", "agency_source": "crosswalk", "jurisdiction": "state", "quote": "The department shall report."}]
fl = ed.judgment_flags("", recs)
check("S7 the local named body is flagged", any(f["check"] == "local_body_unresolved" and f["sentences"] == ["The agency shall adjudicate."] for f in fl))

print("%d passed, %d failed" % (passed, failed))
