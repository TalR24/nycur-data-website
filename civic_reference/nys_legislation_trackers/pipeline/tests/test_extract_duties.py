"""Plain script: packet emit + ingest round trip on synthetic answers (no model). Prints 'N passed, M failed'."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import extract_obligations as eo

if not (ed.TEXT_MARKED / "2013-S4552.txt").exists():      # CI has no cached pilot texts (they are not committed)
    print("0 passed, 0 failed (skipped: pilot texts are not cached here)")
    sys.exit(0)
passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

tmp = Path(tempfile.mkdtemp())
ed.EXTRACTED = tmp / "extracted"
laws = {l["key"]: l for l in ed.signed_laws()}
ed.EFFECTIVE = ed.effective_table(laws.values())
todo = [(laws[k], (ed.TEXT_MARKED / (k + ".txt")).read_text()) for k in ("2013-S4552", "2019-S3360")]
pk = tmp / "packets"; (pk / "results").mkdir(parents=True)
eo.emit_packets(pk, todo, fixed_prompt=ed.FIXED_PROMPT, render=ed.render_variable_prompt)
txt = (pk / "2019-S3360.txt").read_text()
check("packet has metadata", '"chapter_number"' in txt and '"signed_date"' in txt and "LAW TEXT:" in txt)
check("no NYC wording", "Legistar" not in txt and "NYC Admin" not in txt)

def ob(actor, resolved, quote, kind, cit, dl=None):
    return {"actor_raw": actor, "actor_resolved": resolved, "actor_unit": None, "action_summary": "Do the thing.",
            "deliverable_type": "other", "citation": cit, "quote": quote,
            "deadline": dl or {"kind": "none", "fixed_date": None, "offset": None, "text": None},
            "recurrence": "one-time", "provision_kind": kind, "affected_groups": []}
eff = {"kind": "other", "offset": None, "fixed_date": None, "text": "x"}
res1 = {"effective_clause": eff, "obligations": [
    ob("the town board of the town of hempstead", "town of hempstead", "the town board of the town of hempstead may, by adoption of a local law or ordinance, provide for a residential parking permit system", "power", "Vehicle and Traffic Law § 1662-e(1)")]}
res2 = {"effective_clause": eff, "obligations": [
    ob("the department of state", "department of state", "The department of state shall create and make available to the public on the department's website a notice", "duty", "General Business Law § 778-aa(4)",
       {"kind": "days_after_effective", "fixed_date": None, "offset": {"amount": 30, "unit": "days"}, "text": "within 30 days"}),
    ob("any home improvement contractor", "contractor", "any home improvement contractors as defined in subdivision five", "neither", "x"),
    ob("the department of state", "department of state", "this sentence is not in the law at all", "duty", "x")]}
(pk / "results" / "2013-S4552.json").write_text(json.dumps(res1))
(pk / "results" / "2019-S3360.json").write_text(json.dumps(res2))
done, left = eo.ingest_packets(pk, todo, ed.LOOKUP, ed.BY_CANON, "test", writer=ed.write_cache, prepare=ed.prepare)
check("both ingested", sorted(done) == ["2013-S4552", "2019-S3360"] and not left)
duties, powers, excluded = ed.build_records(list(laws.values()))
check("one power", len(powers) == 1 and powers[0]["agency"] == "Towns" and powers[0]["agency_unit"] == "Town of Hempstead")
check("local jurisdiction", powers[0]["jurisdiction"] == "local" and powers[0]["agency_group"] == "Towns")
check("duties 2 (one unverified kept)", len(duties) == 2)
d0 = [d for d in duties if d["quote_verified"]][0]
check("state agency matched", d0["agency"] == "DOS" and d0["jurisdiction"] == "state" and d0["agency_matched"])
check("deadline is the parsed effective date plus 30 days", d0["effective_date"] == "2020-03-19" and d0["deadline_date"] == "2020-04-18")
check("private excluded", excluded == 1)
(tmp / "d.json").write_text(json.dumps({"obligations": duties})); (tmp / "p.json").write_text(json.dumps({"powers": powers}))
out = subprocess.run([sys.executable, str(HERE / "validate_duties.py"), "--duties", str(tmp / "d.json"), "--powers", str(tmp / "p.json")], capture_output=True, text=True).stdout
check("validator flags the fabricated quote only if marked verified", "quote_not_in_law_text" in out)
check("validator prints HARD FAILURES", "HARD FAILURES:" in out)
# phase 2d rules
check("grant-only: authorized and empowered", ed.grant_only("the city of New Rochelle is hereby further authorized and empowered to adopt and amend local laws"))
check("grant-only: shall have power is still a grant", ed.grant_only("the commissioner shall have the power to inspect"))
check("grant-only: shall is a duty", not ed.grant_only("the commissioner shall inspect and may impose a fee"))
check("grant-only: past participle is not a grant", not ed.grant_only("the types and amounts of services plans have authorized;"))
check("cap pattern", bool(ed.CAP_RE.search("The agency shall not issue bonds in an aggregate principal amount exceeding fifteen billion dollars")))
check("cutoff pattern", bool(ed.CAP_RE.search("No such bond or note shall be issued by the agency on or after July 23, 2013")))
check("not a cap", not ed.CAP_RE.search("The department shall issue a report on or before June 1."))
eff = {"effective_date": "2023-03-03", "section_dates": [
    {"applies_to": "section one of this act", "effective_date": "2023-02-28", "rule": "same_as_chapter"},
    {"applies_to": "paragraph d of subdivision 5 of section 167 of the labor law, as added by section one of this act,", "effective_date": "2023-03-30", "rule": "nth_day_after_chapter"}]}
txt = "Section 1. Labor law is amended.\n\n{{(c) The department shall establish an enforcement officer.}}\n\n{{(d) The department shall post a notice.}}\n\n§ 2. Other.\n\n§ 3. This act shall take effect immediately; provided that section one of this act shall take effect later."
d1, src1 = ed.section_effective({"citation": "Labor Law § 167(5)(c)", "quote": "The department shall establish an enforcement officer."}, txt, eff)
d2, src2 = ed.section_effective({"citation": "Labor Law § 167(5)(d)", "quote": "The department shall post a notice."}, txt, eff)
d3, src3 = ed.section_effective({"citation": "x", "quote": "Other."}, txt, eff)
check("record in act section one gets the section date", (d1, src1) == ("2023-02-28", "section"))
check("paragraph citation gets the paragraph date", (d2, src2) == ("2023-03-30", "paragraph"))
check("other sections keep the law's date", (d3, src3) == ("2023-03-03", "law"))
rel = "Section 1. [(d) No person shall knowingly transport move buy sell possess barter offer for sale deliver any species of bees which have been determined by the department.] \n\n§ 2. {{(d) No person shall knowingly transport, move, buy, sell, possess, barter, offer for sale, deliver, any species of bees which have been determined by the commissioner.}}"
check("D4 relocated text is an extension", ed.relocated("No person shall knowingly transport, move, buy, sell, possess, barter, offer for sale, deliver, any species of bees", rel))
check("D4 genuinely new text is not", not ed.relocated("The commissioner shall create a brand new registry of apiaries within the state", "Section 1. [old words about something else entirely here and there] \n\n§ 2. {{The commissioner shall create a brand new registry of apiaries within the state.}}"))
ll = ed.law_locality((ed.TEXT_MARKED / "2023-S9106.txt").read_text(), "")
check("DTF fallback: the act's single locality", ll == ("Towns", "Town of Smithtown"))
import text_markup
mk = text_markup.from_plain_old("DO ENACT AS FOLLOWS:\n  Section 1. Until [June 30, 2011] JULY 23, 2013 at which time it shall end.\n  S 2. This act shall take effect immediately.\n")
check("markup: digits continue a braced month", "{{July 23, 2013}}" in mk)
mk = text_markup.from_plain_old("DO ENACT AS FOLLOWS:\n  Section 1. Title 2 is REPEALED.\n  S 2. This act shall take effect immediately.\n")
check("markup: status word not braced", "{{" not in mk)
print(out.strip().splitlines()[-1])
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
