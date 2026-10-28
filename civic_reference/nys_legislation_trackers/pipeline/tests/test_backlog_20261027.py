"""Plain script: Oct 27 2026 backlog B1, B2, B3, B11, B12, B13. Prints 'N passed, M failed'."""
import os, sys, json, re
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

_laws = {}
def build(key):
    sess = int(key.split("-")[0])
    laws = [l for l in ed.signed_laws(sessions=[sess]) if l["key"] == key]
    ed.EFFECTIVE.update(ed.effective_table(laws))
    d, p, _ = ed.build_records(laws)
    return {o["obligation_id"]: o for o in d + p}

# B11: a one-time plaque installation with no deadline keeps on_effective_date
r = build("2017-S5570")
check("B11 plaque items on_effective_date", all(r[i]["deadline_kind"] == "on_effective_date" for i in r if r[i].get("deliverable_type") == "signage or installation" and r[i]["kind"] == "duty" and r[i]["recurrence"] == "one-time") and any(o.get("deliverable_type") == "signage or installation" for o in r.values()))

# B1: follow-on pilot design duty keeps none (the model said none; triggered_to_setup must not stamp it)
r = build("2013-S1195")
check("B1 pilot follow-on none", all(r[i]["deadline_kind"] == "none" for i in ("2013-S1195-09", "2013-S1195-13", "2013-S1195-17") if i in r) and "2013-S1195-09" in r)

# B12: year-relative dates
check("B12 July first next succeeding", ed.year_relative_date("on and after July first in the year next succeeding the year in which this sentence shall take effect", "2010-09-17", "2010-08-01") == "2011-07-01")
check("B12 October first of the year next succeeding", ed.year_relative_date("by October first of the year next succeeding the effective date of this section", "2016-11-28", "2016-10-01") == "2017-10-01")
check("B12 first day of January next succeeding", ed.year_relative_date("from and after the first day of January next succeeding the effective date", "2010-09-17", "2010-08-01") == "2011-01-01")
check("B12 plain text none", ed.year_relative_date("within ninety days of the effective date", "2010-09-17", "2010-08-01") is None)
r = build("2009-A4687")
check("B12 A4687-01 fixed_date", r["2009-A4687-01"]["deadline_kind"] == "fixed_date" and r["2009-A4687-01"]["deadline_date"] == "2011-07-01")

# B3: next sentence sets the appointment period
text = "1. The governor shall appoint the members of the council. The appointments shall be made within ninety days of the effective date of this section.\n"
o = {"kind": "duty", "quote": "The governor shall appoint the members of the council.", "deadline_kind": "none", "effective_date": "2020-01-01", "enactment_date": "2019-12-01", "obligation_id": "X-01"}
check("B3 next sentence", ed.appointment_next_sentence_period(o, text) is not None)
ed.STATS.clear(); ed.appointment_period([o], text)
check("B3 days_after_effective", o["deadline_kind"] == "days_after_effective" and o["deadline_date"] == "2020-03-31")
o2 = {"kind": "duty", "quote": "The governor shall appoint the members of the council.", "deadline_kind": "none", "effective_date": "2020-01-01", "enactment_date": "2019-12-01", "obligation_id": "X-02"}
check("B3 unrelated sentence", ed.appointment_next_sentence_period(o2, "1. The governor shall appoint the members. The board shall report within ninety days of the effective date.\n") is None)

# B2: no-modal actor lead-in
t = "1. The duties of the board:\n(a) Advise the governor on rates;\n(b) Review the budget.\n"
q = "Review the budget."
sp = (t.index(q), t.index(q) + len(q))
check("B2 nomodal lead-in found", ed.nomodal_actor_lead_in(sp, t) is not None and ed.nomodal_lead_actor(ed.nomodal_actor_lead_in(sp, t)) == "the board")
t2 = "1. The board shall:\n(a) Advise the governor on rates;\n(b) Review the budget.\n"
check("B2 modal lead-in left to existing rules", ed.nomodal_actor_lead_in((t2.index(q), t2.index(q) + len(q)), t2) is None)
t3 = "1. Some prose here.\n(a) Advise the governor on rates;\n(b) Review the budget.\n"
check("B2 no lead-in paragraph keeps flag", ed.nomodal_actor_lead_in((t3.index(q), t3.index(q) + len(q)), t3) is None)

# B13: same sentence in two sections for different statutes stays two records
text = ("Section 1. Section 4902 of the insurance law is amended by adding a new subdivision 3 to read as follows:\n{{3. The superintendent shall publish the list.}}\n"
        "§ 2. Section 4902 of the public health law is amended by adding a new subdivision 3 to read as follows:\n{{3. The superintendent shall publish the list.}}\n")
a = {"obligation_id": "L-01", "quote": "The superintendent shall publish the list.", "citation": "Insurance Law § 4902"}
b = {"obligation_id": "L-02", "quote": "The superintendent shall publish the list.", "citation": "Public Health Law § 4902"}
check("B13 different laws partition", len(ed.merge_partitions([a, b], text)) == 2)
check("B13 distinct_provisions different law, same section", ed.distinct_provisions(a, b))
c = dict(a, obligation_id="L-03")
check("B13 same citation same section merges", len(ed.merge_partitions([a, c], text)) == 1)
e = {"obligation_id": "L-04", "quote": a["quote"], "citation": ""}
check("B13 one empty citation stays apart", len(ed.merge_partitions([a, e], text)) == 2 and ed.distinct_provisions(a, e))
check("B13 both empty merge", len(ed.merge_partitions([dict(e), dict(e, obligation_id="L-05")], text)) == 1)

print("%d passed, %d failed" % (passed, failed))
