"""Plain script: Oct 20 2026 closing fixes V1-V3 (sub-items of a parent duty, caps/FOIL exemptions/definitions, designations).
Each case is the exact stored quote, gated against the real marked law text in cache/. Prints 'N passed, M failed'."""
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

def stored(oid):
    key = oid.rsplit("-", 1)[0]
    res = json.loads((ed.EXTRACTED / (key + ".json")).read_text())
    text = (ed.TEXT_MARKED / (key + ".txt")).read_text()
    o = copy.deepcopy([x for x in res["obligations"] if x["obligation_id"] == oid][0])
    if "{{" in (o.get("quote") or ""):
        o["quote"] = ed.eo.clean_stored_quote(o["quote"], text)[0]
    return o, text

def rule(oid):
    o, text = stored(oid)
    g = ed.gate_record(o, text, "{{" in text)
    return g[0] if g else None

# V1: the 8 content items of one annual report (flag on), and the five permit criteria (V1B, off by default)
for n in range(12, 20):
    check("V1 2009-A7329-%d" % n, rule("2009-A7329-%d" % n) == "sub_item_of_parent")
check("V1B is on since Oct 21 (adjudicated: criteria items are sub-items)", ed.APPLY_V1B is True and rule("2011-A5318-10") == "sub_item_of_parent")
ed.APPLY_V1B = True
for n in (10, 12, 13, 14, 15):
    check("V1B 2011-A5318-%02d" % n, rule("2011-A5318-%02d" % n) == "sub_item_of_parent")
ed.APPLY_V1B = False
# keeps: a list item with its own verb, and imperative items under a powers-and-duties lead-in
q = "The department shall submit the plan to the governor."
check("V1 keeps an item with its own verb", ed.gate_record({"actor_raw": "the department", "quote": q, "quote_verified": True}, "", False) is None)
check("V1 lead regex ignores powers and duties", not ed.CONTENT_LEAD.search("The officer's powers and duties shall include:") or ed.CONTENT_LEAD_NOT.search("The officer's powers and duties shall include:"))

# V2: caps, FOIL exemptions, definitions
check("V2 cap list item", rule("2015-S5949-27") == "cap_not_duty")
check("V2 cap lead 'limited to:'", rule("2015-A4490-02") == "cap_not_duty")
check("V2 FOIL not subject to disclosure", rule("2013-S2320-15") == "exemption_or_applicability")
check("V2 FOIL paragraph (k) of POL 87", rule("2009-A7332-20") == "exemption_or_applicability")
check("V2 definition quoted term", rule("2013-A6357-03") == "definition")
check("V2 definition shall mean", rule("2009-A8518-06") == "definition")
check("V2 'means' as a noun is not a definition", ed.v_quote_rule("the superintendent May make such information available by any other means that provides for direct public access") is None)
check("V2 keeps a cap that names an actor's act", ed.v_quote_rule("The commissioner shall make no grant to any applicant in excess of the funds appropriated") is None)

# V3: designations and election mechanics
for oid in ("2013-A2051-06", "2013-A2051-07", "2013-A2051-08"):
    check("V3 " + oid, rule(oid) == "designation_composition")
check("V3 keeps a composition sentence that also assigns a duty", ed.v_quote_rule("The board shall consist of nine members and shall report annually to the governor.") is None)
check("V3 keeps 'shall constitute grounds'", ed.v_quote_rule("shall constitute cause, for the purposes of Section 118 of the alcoholic beverage control law") is None)

# W1: section-scoped sunset sentence inside an amended earlier chapter ("Subdivision 12 of section 246 of chapter 81 ...")
T1 = (ed.TEXT_MARKED / "2017-A7746.txt").read_text()
w1 = dict(ed.sunset_extension_sentences(T1))
check("W1 section-scoped sentence found", "Sections one hundred five-b through one hundred five-f of this act shall expire June 30, 2018." in w1
      and w1["Sections one hundred five-b through one hundred five-f of this act shall expire June 30, 2018."] == "Chapter 81 of the Laws of 1995, § 246")
LAWW = {"key": "2017-A7746", "title": "Extends the authority of the department of health to license clinics", "act_clause": "", "chapter_number": "9", "chapter_year": "2017",
        "session": "2017", "print_no": "A7746", "law_number_display": "Chapter 9 of 2017", "sponsor": "X", "enactment_date": "2017-06-01", "openleg_url": "u"}
EFFW = {"effective_date": "2017-06-01", "rule": "immediately", "expires_date": None, "section_dates": []}
rw, unw = ed.sunset_extension_records(LAWW, T1, EFFW, [{"quote": "unrelated stored quote"}], {"obligations": []})
check("W1 builds a record although the law stores other records", any(r["quote"].endswith("expire June 30, 2018.") and r["actor_raw"] == "the department of health" for r in rw))
rn, unn = ed.sunset_extension_records(dict(LAWW, title="Relates to clinics"), T1, EFFW, [], {"obligations": []})
check("W1 no body in the title: reask flag", rn == [] and unn is not None)

# W2: expiry counted from the signing date
import effective_date as efd
check("W2 five years after having become a law", efd.parse_effective("§ 5. This act shall take effect immediately and shall expire five years after having become a law.", "2017-10-23")["expires_date"] == "2022-10-23")
check("W2 after it shall have become a law", efd.parse_effective("§ 2. This act shall take effect immediately and shall expire 3 years after it shall have become a law.", "2020-02-29")["expires_date"] == "2023-02-28")
check("W2 2017-A7509 from the real text", efd.parse_effective((ed.TEXT_MARKED / "2017-A7509.txt").read_text(), "2017-10-23")["expires_date"] == "2022-10-23")

# W3: appointment duty missing
T3 = (ed.TEXT_MARKED / "2017-A10675.txt").read_text()
fl3 = [f for f in ed.judgment_flags(T3, []) if f["check"] == "appointment_duty_missing"]
check("W3 flags a law with appointments and no appointment record", len(fl3) == 1 and fl3[0]["sentences"])
check("W3 a stored appointment record suppresses it", not [f for f in ed.judgment_flags(T3, [{"quote": "The governor shall appoint nine members", "deliverable_type": "other", "actor_raw": "the governor"}]) if f["check"] == "appointment_duty_missing"])
check("W3 reask_manual carries the 2017-A6893 miss", any("Issue recommendations" in i["sentence"] and i["night"] == "20261020" for i in json.loads((ed.REASK_MANUAL_DATA).read_text())["laws"]["2017-A6893"]))

print("%d passed, %d failed" % (passed, failed))
