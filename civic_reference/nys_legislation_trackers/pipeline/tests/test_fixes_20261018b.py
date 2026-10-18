"""Plain script: Oct 18 2026 night fixes T1-T8 (IDA agencies, NYC chancellor wording, first-of-month effective dates, kind_rule label, State employer,
'the state' flag, deadline starts and triggers, mandatory lead-in drop flag). Prints 'N passed, M failed'."""
import os, sys, json, re, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import agency_resolve_nys as ar
import effective_date as efd

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

def rec(raw, agency="Unspecified", **kw):
    d = {"actor_raw": raw, "actor_resolved_model": None, "agency": agency, "agency_full": agency, "agency_matched": agency != "Unspecified", "quote": "x", "citation": "x", "action_summary": "x"}
    d.update(kw); return d

def law_text(key):
    return (ed.TEXT_MARKED / (key + ".txt")).read_text()

# T1. IDA 'each agency'
t = law_text("2015-S5867")
LAW1 = {"title": "Relates to the accountability and efficiency of industrial development agencies and authorities"}
o = rec("Each agency", "All agencies"); ed.run_agency_fixes(o, t, LAW1)
check("T1 2015-S5867 'Each agency' resolves to Industrial development agencies, local", o["agency"] == "Industrial development agencies" and o["jurisdiction"] == "local" and o["agency_source"] == "ida_agency")
o = rec("the agency", "State agencies"); ed.run_agency_fixes(o, "A bill about parks. The agency shall report.", {"title": "Relates to parks"})
check("T1 a law that never names IDAs keeps State agencies", o["agency"] == "State agencies")
check("T1 crosswalk has the group as local", ed.BY_CANON["Industrial development agencies"]["jurisdiction"] == "local")

# T2. NYC chancellor wording
t = law_text("2011-S6732")
for raw in ("the chancellor of the city school District", "the chancellor of the city school district of the city of New York", "the District"):
    o = rec(raw); ed.run_agency_fixes(o, t, {"title": "x"})
    check("T2 %r -> NYCPS" % raw, o["agency"] == "NYCPS" and o["jurisdiction"] == "nyc")
o = rec("the District"); ed.run_agency_fixes(o, "The district shall file. Education Law.", {"title": "x"})
check("T2 'the District' outside Education Law 2590 stays unresolved", o["agency"] != "NYCPS")

# T3. first day of the month next succeeding the Nth day
clause = "§ 11. This act shall take effect on the first day of the first month next succeeding the one hundred twentieth day after it shall have become a law and shall apply to gross receipts."
r = efd.parse_effective(clause, "2016-04-14")
check("T3 2015-S5949 -> 2016-09-01", r["effective_date"] == "2016-09-01" and r["rule"] == "first_of_month_after_nth_day")
r = efd.parse_effective("This act shall take effect on the first of the month following the thirtieth day after it shall have become a law.", "2016-12-10")
check("T3 'first of the month following the thirtieth day' crosses the year", r["effective_date"] == "2017-02-01")
check("T3 plain 'one hundred twentieth day after' is unchanged", efd.parse_effective("This act shall take effect on the one hundred twentieth day after it shall have become a law.", "2016-04-14")["effective_date"] == "2016-08-12")

# T5. 'the employer' in a State employee-contract law; vested power
o = rec("the employer", "Public employers"); o["agency_matched"] = True
check("T5 State employer law -> State agencies", ar.fix_state_employer(o, "The state as employer under article fourteen of the civil service law") and o["agency"] == "State agencies")
o = rec("the employer", "Public employers")
check("T5 a city employer law keeps Public employers", not ar.fix_state_employer(o, "A city employer under article 14 of the labor law") and o["agency"] == "Public employers")
check("T5 'shall have and is hereby vested with jurisdiction' is a vested power", bool(ed.VESTED_POWER.search("The commission shall have and is hereby vested with exclusive jurisdiction over combative sports")))
check("T5 plain duty is not", not ed.VESTED_POWER.search("The commission shall file a report"))

# T6. 'the state' resolved to one named agency is flagged
q = "the state shall not award Any funds from this allowance to reimburse Any costs for the headstone"
fl = ed.judgment_flags("", [rec("the state", "DVS", quote=q, session=2013)])
check("T6 'the state' -> DVS is flagged state_as_single_agency", any(f["check"] == "state_as_single_agency" and q in f["sentences"] for f in fl))
fl = ed.judgment_flags("", [rec("the state", "State agencies", quote=q, session=2013)])
check("T6 'the state' -> State agencies is not flagged", not any(f["check"] == "state_as_single_agency" for f in fl))

# T7. dated starts, trigger, ongoing signage
check("T7 'beginning in January of each year' -> first January 1 on or after the base", ed.dated_deadline("beginning in January of each year", "2016-03-01") == ("2017-01-01", "start"))
check("T7 'commencing with the first day of July' -> same year", ed.dated_deadline("commencing with the first day of July", "2016-03-01") == ("2016-07-01", "start"))
check("T7 'after the notice is received' is a trigger", bool(ed.TRIGGER.search("shall respond within ten days after the notice is received")))

# T4 + T7 through build_records
law = {"key": "2099-S3", "enactment_date": "2099-01-01", "chapter_number": 3, "chapter_year": 2099, "session": 2099, "print_no": "S3", "law_number_display": "Chapter 3 of 2099",
       "title": "An act relating to highway signs", "sponsor": "Test", "openleg_url": "https://example.test", "act_clause": "This act shall take effect immediately."}
QA = "The office of the state comptroller is authorized and directed to transfer three million dollars to the signs fund;"
QS = "The department shall provide for the installation and maintenance of signs on state highways;"
QD = "The department shall publish a notice on the website beginning in January of each year;"
text = ("§ 1. {{" + QA + "}}\n§ 2. {{" + QS + "}}\n§ 3. {{" + QD + "}}\n§ 4. This act shall take effect immediately.\n")
def ob(n, q, **kw):
    d = {"obligation_id": "2099-S3-%02d" % n, "matter_id": "2099-S3", "actor_raw": "the department", "agency": "DOH", "agency_full": "Department of Health", "agency_matched": True,
         "action_summary": "x", "deliverable_type": "other", "citation": "x", "quote": q, "quote_verified": True, "kind_rule": "duty", "kind_model": "duty", "provision_kind": "duty",
         "deadline_kind": "none", "deadline_text": None, "deadline_date": None, "recurrence": "one-time", "affected_groups": []}
    d.update(kw); return d
obs = [ob(1, QA, kind_rule="power", kind_model="power", kind_list_item=True, actor_raw="the office of the state comptroller", agency="OSC", agency_full="Office of the State Comptroller"),
       ob(2, QS), ob(3, QD, recurrence="annual")]
tmp = Path(tempfile.mkdtemp()); (tmp / "x").mkdir(); (tmp / "t").mkdir()
(tmp / "x" / "2099-S3.json").write_text(json.dumps({"matter_id": "2099-S3", "model": "test", "effective_clause": {}, "effective_date": "2099-01-01", "obligations": obs, "extends_model": {}, "actor_model": {}}))
(tmp / "t" / "2099-S3.txt").write_text(text)
saved = (ed.EXTRACTED, ed.TEXT_MARKED, dict(ed.EFFECTIVE))
try:
    ed.EXTRACTED, ed.TEXT_MARKED = tmp / "x", tmp / "t"
    ed.EFFECTIVE["2099-S3"] = {"rule": "immediately", "effective_date": "2099-01-01", "expires_date": None, "raw_clause": "This act shall take effect immediately.", "section_dates": []}
    duties, powers, excluded = ed.build_records([law])
finally:
    ed.EXTRACTED, ed.TEXT_MARKED = saved[0], saved[1]
    ed.EFFECTIVE.clear(); ed.EFFECTIVE.update(saved[2])
by = {x["obligation_id"]: (x, "duty") for x in duties}; by.update({x["obligation_id"]: (x, "power") for x in powers})
check("T4 three records built", len(by) == 3)
check("T4 kind_adjusted record: kind_rule equals the final kind", by["2099-S3-01"][0].get("kind_adjusted") == "authorized_and_directed" and by["2099-S3-01"][0]["kind_rule"] == by["2099-S3-01"][0]["kind"] == "duty")
check("T4 every record: kind_rule equals kind", all(r["kind_rule"] == r["kind"] == k for r, k in by.values()))
check("T7 signage installation and maintenance is ongoing", by["2099-S3-02"][0]["recurrence"] == "ongoing" and by["2099-S3-02"][0]["deadline_kind"] == "none")
check("T7 'beginning in January of each year' gets a fixed_date and keeps annual", by["2099-S3-03"][0]["deadline_kind"] == "fixed_date" and by["2099-S3-03"][0]["deadline_date"] == "2099-01-01" and by["2099-S3-03"][0]["recurrence"] == "annual")

# T8. mandatory lead-in drop flag
t8 = "§ 1. The department shall determine whether:\n(a) the first thing is true;\n(b) the second thing is true.\n"
fl = ed.mandatory_drop_flags(t8, [{"rule": "designation_no_actor", "quote": "the second thing is true"}, {"rule": "act_clause", "quote": "the first thing is true"}])
check("T8 designation_no_actor drop under 'shall determine whether:' is flagged", len(fl) == 1 and fl[0]["check"] == "mandatory_lead_in_item_dropped" and fl[0]["sentences"] == ["the second thing is true"])
t8b = "§ 1. The department may determine whether:\n(a) the first thing is true;\n(b) the second thing is true.\n"
check("T8 a 'may' lead-in is not flagged", ed.mandatory_drop_flags(t8b, [{"rule": "designation_no_actor", "quote": "the second thing is true"}]) == [])
m = json.loads((HERE.parent / "data" / "reask_manual.json").read_text())["laws"]
check("T8 reask_manual carries night 20261018 for 2011-S6732 and 2013-S7909", all(any(i["night"] == "20261018" for i in m.get(k, [])) for k in ("2011-S6732", "2013-S7909")))

if os.environ.get("DBG"):
    for k, (r, kk) in by.items(): print(k, kk, {x: r.get(x) for x in ("kind_rule", "kind_adjusted", "deadline_kind", "deadline_date", "recurrence")})
print("%d passed, %d failed" % (passed, failed))
