"""Nov 10 2026 night (AG1-AG4). Asserts the gate rule on the cached record; dry run counts over stored ids, cap 40 per rule."""
import sys, json, pathlib, re
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)
def cached(oid):
    f = HERE / "cache" / "extracted" / (oid.rsplit("-", 1)[0] + ".json")
    if f.exists():
        for o in json.load(open(f))["obligations"]:
            if o["obligation_id"] == oid: return o
def gate_q(q, actor="the department", agency="SED"):
    return ed.gate_record({"quote": q, "quote_verified": True, "agency": agency, "agency_unit": None, "actor_raw": actor}, q, False)
def rule(r): return (r or ("",))[0]
# AG1 applicant licensing conditions
o = cached("2013-S3810-06")
if o: check("AG1 gate drops cached 2013-S3810-06", rule(ed.gate_record(o, "", False)) == "condition_of_other_record")
check("AG1 good moral character", bool(ed.AG1_APPLICANT.search("Character: Be of good moral character as determined by the department")))
check("AG1 applicant shall be licensed", bool(ed.AG1_APPLICANT.search("An applicant shall be licensed in this state and shall have at least five years of experience.")))
check("AG1 years of experience", bool(ed.AG1_APPLICANT.search("The nominee shall have at least five years of professional experience in the field.")))
check("AG1 applicant must file is kept", not ed.AG1_APPLICANT.search("To obtain a tax abatement pursuant to this title, an applicant must file an application for tax abatement."))
check("AG1 notified applicant is kept", not ed.AG1_APPLICANT.search("The nominating elected official and the applicant shall be notified by the office if such applicant is not accepted."))
check("AG1 'unless the applicant shall be' is kept", not ed.AG1_APPLICANT.search("No retail license shall be granted for any premises, unless the applicant shall be a resident."))
# AG2 licence precondition
o = cached("2013-S3810-09")
if o: check("AG2 gate drops cached 2013-S3810-09", rule(ed.gate_record(o, "", False)) == "condition_of_other_record")
check("AG2 matches", bool(ed.AG2_LICENCE_PRECOND.search("may offer to provide or provide professional engineering services only after obtaining a certificate of authorization from the department")))
check("AG2 a department power is kept", not ed.AG2_LICENCE_PRECOND.search("The department may issue a certificate of authorization to a firm that applies."))
# AG3 manner fragment
o = cached("2015-S6503-04")
if o and ed.APPLY_AG3: check("AG3 gate drops cached 2015-S6503-04", rule(ed.gate_record(o, "", False)) == "condition_of_other_record")
check("AG3 fragment matches", bool(ed.AG3_MANNER_FRAGMENT.search("if a meeting of a Committee, by such means, including the postal service, as determined by the Committee.")))
check("AG3 sentence with a modal is kept", gate_q("If a meeting is held by electronic means, the chair shall give notice as determined by the board.") is None or rule(gate_q("If a meeting is held by electronic means, the chair shall give notice as determined by the board.")) != "condition_of_other_record")
# AG4 eligibility, Unspecified actor
o = cached("2021-S8887-01")
if o and ed.APPLY_AG4: check("AG4 gate drops cached 2021-S8887-01", rule(ed.gate_record(o, "", False)) == "amount_not_duty")
q4 = "For each county, new shared services actions in an approved plan may be eligible for funding to match savings, subject to available appropriation."
check("AG4 unspecified actor dropped", (not ed.APPLY_AG4) or rule(gate_q(q4, "unspecified", "Unspecified")) == "amount_not_duty")
check("AG4 named body is kept", rule(gate_q("The office may be eligible for funding under this section.", "the office", "OTDA")) != "amount_not_duty")
# dry run over stored ids
stored = set()
for d in ("duties", "powers"):
    for f in (HERE.parent / "data" / d).glob("*.json"):
        stored |= {x["obligation_id"] for x in json.load(open(f))[{"duties": "obligations", "powers": "powers"}[d]]}
h = {k: [] for k in ("AG1", "AG2", "AG3", "AG4")}
for f in (HERE / "cache" / "extracted").glob("*.json"):
    for x in json.load(open(f)).get("obligations", []):
        if x.get("obligation_id") not in stored: continue
        q = x.get("quote") or ""
        if ed.AG1_APPLICANT.search(q): h["AG1"].append(x["obligation_id"])
        if ed.AG2_LICENCE_PRECOND.search(q): h["AG2"].append(x["obligation_id"])
        if ed.AG3_MANNER_FRAGMENT.search(q) and not ed.MODAL_SENT.search(q): h["AG3"].append(x["obligation_id"])
        if ed.AG4_ELIGIBLE_FUNDING.search(q) and re.sub(r"\W", "", x.get("actor_raw") or "").lower() in ("unspecified", "") and (x.get("agency") or "") in ("Unspecified", ""): h["AG4"].append(x["obligation_id"])
for k, v in h.items():
    print("dry run", k, len(v), v[:12])
    check(k + " flag on only within cap", getattr(ed, "APPLY_" + k) == (len(v) <= 40) or k in ("AG3", "AG4"))   # AG3, AG4 off by decision: more than four gates tonight

# AF1: condition in the same or the preceding sentence blocks the on_effective_date default
o = cached("2013-A814-02")
if o:
    tx = (HERE / "cache" / "text_marked" / "2013-A814.txt").read_text()
    check("AF1 context on cached 2013-A814-02", ed.af1_condition_context(o["quote"], tx))
tx2 = "3. (B) If the department determines that a study is feasible, the department, after consultation, shall outline a method. The department shall submit the study to the governor."
check("AF1 same sentence", ed.af1_condition_context("the department, after consultation, shall outline a method.", tx2))
tx3 = "3. (B) Upon a finding of need by the board. The department shall submit the study to the governor."
check("AF1 preceding sentence lead", ed.af1_condition_context("The department shall submit the study to the governor.", tx3))
tx4 = "3. The department shall conduct a study. The department shall submit the study to the governor."
check("AF1 plain setup duty has no context", not ed.af1_condition_context("The department shall submit the study to the governor.", tx4))
# AF2: forms prescribed by a government body keep their record
o = cached("2017-A2805-03")
if o: check("AF2 cached 2017-A2805-03 kept", rule(ed.gate_record(o, (HERE / "cache" / "text_marked" / "2017-A2805.txt").read_text(), True)) != "benefit_entitlement")
check("AF2 prescribe the form kept", not ed.amount_rule_subject("The commissioner shall prescribe the form of the application."))
check("AF2 forms prescribed by the department kept", not ed.amount_rule_subject("Application for grants made pursuant to this section shall be made in the manner and on forms prescribed by the department."))
check("AF2 private-subject form rule still matches without a body", ed.amount_rule_subject("Applications for grants shall be made on forms prescribed by law."))
# dry run AF1 over stored duties stamped on_effective_date
n = []
for f in (HERE.parent / "data" / "duties").glob("*.json"):
    for x in json.load(open(f))["obligations"]:
        if x.get("deadline_kind") == "on_effective_date":
            tp = HERE / "cache" / "text_marked" / (x["obligation_id"].rsplit("-", 1)[0] + ".txt")
            if tp.exists() and ed.af1_condition_context(x.get("quote") or "", tp.read_text()): n.append(x["obligation_id"])
print("dry run AF1", len(n), n[:10])

# AF3: trivial braces
o = cached("2023-A10110-01")
if o:
    tx = (HERE / "cache" / "text_marked" / "2023-A10110.txt").read_text()
    check("AF3 gate drops cached 2023-A10110-01", rule(ed.gate_record(o, tx, True)) == "reprinted_gender_neutral")
check("AF3 punctuation and conjunction braces", ed.af3_trivial_reprint("The board{{,}} after notice{{, and}} shall act."))
check("AF3 gender-neutral braces", ed.af3_trivial_reprint("The board shall notify [him] {{their}} agent{{;}}"))
check("AF3 real new matter is kept", not ed.af3_trivial_reprint("The board shall act {{within thirty days}}{{,}}."))
# AF4: fine on a private person stored for a court
o = cached("2023-A3120-01")
if o: check("AF4 gate drops cached 2023-A3120-01", rule(ed.gate_record(o, "", False)) == "no_duty_or_power")
q = "Any person who violates this section shall be punished by a fine of not less than five hundred dollars."
check("AF4 person fine dropped for a court actor", rule(gate_q(q, "courts", "courts")) == "no_duty_or_power")
check("AF4 court directed to impose is kept", rule(gate_q("Any person who violates this section shall be fined, and the court shall impose a fine of five hundred dollars.", "courts", "courts")) != "no_duty_or_power")
check("AF4 non-court actor untouched by AF4", rule(gate_q(q, "the department", "SED")) != "no_duty_or_power")
n3 = []; n4 = []
for f in [g for _d in ("duties", "powers") for g in (HERE.parent / "data" / _d).glob("*.json")]:          # Nov 12 2026: data/site holds non-record files
    d = json.load(open(f))
    for x in d.get("obligations", d.get("powers", [])) if isinstance(d, dict) else []:
        qq = x.get("quote") or ""
        if ed.AF4_PERSON_PENALTY.search(qq) and ed.AF4_COURT_ACTOR.search((x.get("actor_raw") or "") + " " + (x.get("agency") or "")) and not ed.AF4_COURT_DIRECTED.search(qq): n4.append(x["obligation_id"])
print("dry run AF4", len(n4), n4[:10])
check("AF4 within cap", len(n4) <= 40)
print(f"{passed} passed, {failed} failed")
