"""Plain script: packet emit + ingest round trip on synthetic answers (no model). Prints 'N passed, M failed'."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import extract_obligations as eo

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
check("one power", len(powers) == 1 and powers[0]["agency"] == "Town of Hempstead")
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
print(out.strip().splitlines()[-1])
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
