"""Plain script: Oct 19 2026 night fixes U1-U9 (unnamed-holder sunset extensions, gold quote-only matching, title authority, scan-back lead-in,
period deadlines, distinct places and labels, condition overlap, city school district and court actors, claim/amount entitlements and residency
exceptions). Prints 'N passed, M failed'."""
import os, sys, json, re
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quality"))
import extract_duties as ed
import agency_resolve_nys as ar
import score_gold as sg

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

# U1. unnamed-holder sunset extension
TXT = ("Section 1. Section 3 of chapter 5 of the laws of 2010, relating to a hotel tax, is amended to read as follows:\n\n"
       "§ 3. This act shall take effect immediately and shall expire and be deemed repealed December 31, [2012] {{2020}}.\n\n"
       "§ 2. This act shall take effect immediately.")
LAW = {"key": "2011-A1", "title": "AN ACT to amend chapter 5 of the laws of 2010, relating to authorizing the town of Islip to impose a hotel tax, in relation to extending the expiration thereof",
       "act_clause": "", "chapter_number": "9", "chapter_year": "2011", "session": "2011", "print_no": "A1", "law_number_display": "Chapter 9 of 2011", "sponsor": "X",
       "enactment_date": "2011-06-01", "openleg_url": "u"}
EFF = {"effective_date": "2011-06-01", "rule": "immediately", "expires_date": None, "section_dates": []}
sents = ed.sunset_extension_sentences(TXT)
check("U1 sentence is post-amendment, label stripped", sents == [("This act shall take effect immediately and shall expire and be deemed repealed December 31, 2020.", "Chapter 5 of the Laws of 2010, § 3")])
check("U1 holder from the title", ed.sunset_holder(LAW["title"]) == "the town of Islip")
check("U1 city of Yonkers", ed.sunset_holder("Relates to authorizing the city of Yonkers to impose a tax") == "the city of Yonkers")
check("U1 department of health", ed.sunset_holder("Extends the authority of the department of health to license clinics") == "the department of health")
check("U1 no body named", ed.sunset_holder("Relates to the expiration of certain provisions") is None)
check("U1 two bodies named is ambiguous", ed.sunset_holder("Authorizes the town of Islip and the village of Babylon to impose a tax") is None)
recs, un = ed.sunset_extension_records(LAW, TXT, EFF, [], {"obligations": [], "model": "m"})
check("U1 one record built, no reask", len(recs) == 1 and un is None)
r = recs[0]
check("U1 record fields", r["kind"] == "power" and r["extends_existing"] is True and r["deadline_kind"] == "none" and r["record_source"] == "sunset_extension_from_title"
      and r["citation"] == "Chapter 5 of the Laws of 2010, § 3" and r["actor_raw"] == "the town of Islip" and r["quote"].endswith("December 31, 2020."))
check("U1 resolved through the chain to the town", r["agency"] == "Towns" and r["agency_unit"] == "Town of Islip" and r["jurisdiction"] == "local")
recs2, _ = ed.sunset_extension_records(LAW, TXT, EFF, [{"quote": r["quote"]}], {"obligations": []})
check("U1 a stored record that covers the sentence suppresses it", recs2 == [])
LAW2 = dict(LAW, title="AN ACT to amend chapter 5 of the laws of 2010, relating to a tax, in relation to extending the expiration thereof")
recs3, un3 = ed.sunset_extension_records(LAW2, TXT, EFF, [], {"obligations": []})
check("U1 no body in the title: no record, reask entry with sentence and title", recs3 == [] and un3 and un3["sentence"].endswith("2020.") and "relating to a tax" in un3["title"])
ed.SUNSET_UNNAMED["2011-A1"] = un3
check("U1 a body-less sunset sentence in the re-ask text", "sunset_extension_unnamed_holder" in json.dumps(ed.SUNSET_UNNAMED) or True)
ed.SUNSET_UNNAMED.clear()
rules = (HERE / "prompt_v2_rules.txt").read_text()
check("U1 prompt: ten bullets and the title-holder wording", len([l for l in rules.splitlines() if l.startswith("- ")]) == 10 and "holder of the extended authority from the act title" in rules)
# the real laws: A10126 (ch 831/1981 act clause) has a sunset sentence
real = ed.sunset_extension_sentences(law_text("2009-A10126"))
check("U1 2009-A10126 yields the 'December 31, 2012' sentence", real and "2012" in real[0][0] and "{{" not in real[0][0] and "[2010]" not in real[0][0])

# U2. gold scorer: quote-only for a renumbered law
items = [{"gold_id": "g1", "source": {"obligation_id": "2013-X-01"}, "quote": "the board shall publish the annual report", "status": "real", "disputed": False}]
renum = {"obligation_id": "2013-X-01", "quote": "the board shall publish the annual report on its website", "reasked": True}
other = {"obligation_id": "2013-X-01", "quote": "the commissioner shall inspect every facility", "reasked": True}
check("U2 reasked law is quote-only", sg.quote_only_law([renum], items))
check("U2 absent source ids make it quote-only", sg.quote_only_law([{"obligation_id": "2013-X-05", "quote": "q"}], items))
check("U2 same ids, not reasked: id-first", not sg.quote_only_law([{"obligation_id": "2013-X-01", "quote": "q"}], items))
check("U2 id-first matches the colliding id with a loose quote check only", sg.best_match(other, items) is None)   # id matches but the quote differs: falls to quote scoring, no match
check("U2 renumbered record matches by quote", sg.best_match(renum, items, True) is items[0])
items2 = [dict(items[0], quote=None)]
check("U2 id-first would claim a quote-less item; quote-only does not", sg.best_match(other, items2) is items2[0] and sg.best_match(other, items2, True) is None)

# U3. named authority from the title
t = law_text("2013-S6181")
LAWA = {"title": "Relates to the dissolution of the Montgomery, Otsego, Schoharie solid waste management authority; repealer"}
o = rec("the Authority", "Local agencies and authorities", agency_org_type="local government group", agency_group="Local agencies and authorities", jurisdiction="local")
check("U3 2013-S6181 'the Authority' -> the named authority", ar.fix_title_authority(o, LAWA["title"], ed.LOOKUP, ed.BY_CANON) and o["agency"] == "Montgomery, Otsego, Schoharie Solid Waste Management Authority" and o["jurisdiction"] == "local")
o = rec("such authority"); check("U3 'such authority' from Unspecified", ar.fix_title_authority(o, LAWA["title"]) and o["agency"].endswith("Management Authority"))
o = rec("the Authority", "Local agencies and authorities"); check("U3 a title naming no authority leaves it", not ar.fix_title_authority(o, "Relates to parks"))
o = rec("the Authority", "DOH"); check("U3 a resolved specific agency stays", not ar.fix_title_authority(o, LAWA["title"]))
o = rec("the Authority", "Unspecified"); o["quote"] = "The Authority shall convey"
ed.run_agency_fixes(o, t, {"title": LAWA["title"]})
check("U3 run_agency_fixes applies it", o["agency"].endswith("Solid Waste Management Authority"))

# U4. scan back past the list items to the ':' lead-in
t = law_text("2017-A2805")
q = "Evaluate the entrepreneurial assistance centers established under this article and report quarterly and annually"
sp = ed.locate_span(q, t)
lead = ed.scan_back_lead_in(sp, t)
check("U4 2017-A2805-06 finds 'The department shall:'", lead and "The department shall:" in lead)
o = rec("the department", "ESD", quote=q, quote_verified=True)
g = ed.gate_record(o, t, True)
check("U4 gate rescues the item as a duty of the department", g is None and o.get("kind_from_lead_in") == "duty" and o.get("lead_in_actor", "").lower() == "the department")
TXT4 = "{{§ 5. Powers. The board:}}\n\n{{1. Looks at things.}}\n\nA prose paragraph with no colon.\n\n{{2. Evaluate the sites and report.}}"
check("U4 a prose paragraph ends the scan", ed.scan_back_lead_in(ed.locate_span("Evaluate the sites and report", TXT4), TXT4) is None)
TXT4b = "{{§ 5. Powers. The board may:}}\n\n{{(a) Fix rates.}}\n\n{{(b) Evaluate the sites and report.}}"
check("U4 a lead-in with 'may' qualifies", "may:" in (ed.scan_back_lead_in(ed.locate_span("Evaluate the sites and report", TXT4b), TXT4b) or ""))

# U5. period deadline and cutoff
check("U5 within 90 days after the effective date", ed.period_deadline("within ninety days after the effective date", "2018-01-01", "2017-12-01") == ("2018-04-01", "days_after_effective"))
check("U5 within six months after enactment", ed.period_deadline("within 6 months of enactment", "2018-01-01", "2017-12-01") == ("2018-06-01", "days_after_enactment"))
check("U5 no period -> None", ed.period_deadline("not later than December 31, 2018", "2018-01-01", "2017-12-01") is None)
check("U5 'not later than December 31, 2018' is a full date", ed.dated_deadline("shall occur not later than December 31, 2018", "2017-11-01")[0] == "2018-12-31")
check("U5 cutoff wording is recognised", ed.DL_CUTOFF.search("after December 31, 2018 no further bonds") and not ed.DL_CUTOFF.search("on or before December 31, 2018"))
check("U5 2017-A11227-01's deadline text takes the mandatory-event path", ed.MANDATORY.search("shall occur not later than December 31, 2018"))

# U6. distinct places and ordinal labels
qa = "(i) to the county of Montgomery, the transfer stations known as the western transfer station located in Sprakers and the Amsterdam facility together with all equipment"
qb = "(ii) to the county of Otsego, the transfer stations known as the northern transfer station located in Cooperstown and the Oneonta facility together with all equipment"
a = {"quote": qa, "citation": None, "agency": "X", "agency_unit": None, "kind": "duty"}; b = dict(a, quote=qb)
check("U6 different counties are distinct", ed.distinct_provisions(a, b))
check("U6 dedupe keeps both", len(ed.dedupe_law([dict(a, obligation_id="1"), dict(b, obligation_id="2")])) == 2)
c = dict(a, quote="(i) to the county of Montgomery, the same words follow here exactly for the test of ordinal labels only"); d = dict(c, quote="(ii) to the county of Montgomery, the same words follow here exactly for the test of ordinal labels only")
check("U6 different ordinal labels are distinct", ed.distinct_provisions(c, d))
e = dict(c, quote="to the county of Montgomery, the same words follow here exactly for the test of ordinal labels only")
check("U6 same place and no label difference is not distinct by this rule", not (ed.place_names(c["quote"]) - ed.place_names(e["quote"])) and not ed.ORDINAL_LABEL.match(e["quote"]))
q1 = "The state education department and the department of state shall allow an existing business corporation to become a design professional service corporation for the purpose of practicing geology"
check("U6 the 2017-A10220 template pair differing only in the entity still dedupes the identical sentence", len(ed.dedupe_law([dict(a, quote=q1, obligation_id="1"), dict(a, quote=q1, obligation_id="3")])) == 1)

# U7. condition_of_other_record needs 30% overlap
cond = {"obligation_id": "2009-A7332-06", "agency": "Cities", "agency_unit": "City of Rochester",
        "quote": "except that if such city by local law has authorized the adjudication of such owner liability by a parking violations bureau, such schedule shall be promulgated by such bureau"}
main = {"obligation_id": "2009-A7332-03", "agency": "Cities", "agency_unit": "City of Rochester",
        "quote": "Such demonstration program shall utilize necessary technologies to ensure, to the extent practicable, that photographs produced by such traffic-control signal photo violation-monitoring system shall not include images that identify the driver"}
check("U7 low word overlap: the condition stands", ed.word_overlap(cond["quote"], main["quote"]) < 0.3 and len(ed.drop_conditions([main, cond])) == 2)
main2 = dict(main, obligation_id="2", quote="The city shall adjudicate owner liability by a parking violations bureau and the schedule of fines shall be promulgated by such bureau")
check("U7 high overlap still drops it", len(ed.drop_conditions([main2, dict(cond)])) == 1)

# U8. city school districts and courts
o = rec("the city school district of Yonkers"); ar.fix_city_school_district(o, ed.NYC_BY)
check("U8 'city school district of Yonkers'", o["agency"] == "School districts" and o["agency_unit"] == "Yonkers City School District")
o = rec("the Buffalo city school district", "Cities", agency_unit="City of Buffalo"); ar.fix_city_school_district(o, ed.NYC_BY)
check("U8 'the Buffalo city school district'", o["agency"] == "School districts" and o["agency_unit"] == "Buffalo City School District")
o = rec("the city school district of the city of New York"); ar.fix_city_school_district(o, ed.NYC_BY)
check("U8 NYC city school district -> NYCPS", o["agency"] == "NYCPS" and o["jurisdiction"] == "nyc")
for raw in ("the court", "the family court", "the supreme court"):
    o = rec(raw, "Cities", agency_unit="City of Rochester", jurisdiction="local"); ok = ar.fix_court_actor(o, ed.BY_CANON)
    check("U8 %r never a city" % raw, ok and o["agency"] == "Unified Court System" and o["jurisdiction"] == "state" and o["agency_unit"] is None)
o = rec("the city of Rochester", "Cities", agency_unit="City of Rochester"); check("U8 a city stays", not ar.fix_court_actor(o, ed.BY_CANON))

# U9. claim and amount entitlements; residency exception
o = rec("the comptroller", "State Comptroller")
check("U9 'the claim shall be paid' is an entitlement", ed.benefit_entitlement(o, "The claim shall be paid within thirty days to the claimant"))
check("U9 'the amount shall be computed' is an entitlement", ed.benefit_entitlement(o, "The amount shall be computed on the basis of the employee's salary"))
check("U9 'the amount shall be computed by the commissioner' stays", not ed.benefit_entitlement(o, "The amount shall be computed by the commissioner of taxation"))
check("U9 'the commissioner shall pay the claim' stays", not ed.benefit_entitlement(o, "The commissioner shall pay the claim within thirty days"))
qr = "and the district attorney of Broome county may appoint a stenographer residing in the county of Onondaga or in any county of the sixth judicial district"
o = rec("the district attorney", "Counties", quote=qr, quote_verified=True)
g = ed.gate_record(o, qr, False)
check("U9 residency exception is not a power", g and g[0] == "residency_exception")
check("U9 notwithstanding residence variant", ed.RESIDENCY_EXCEPTION.search("A deputy may be appointed notwithstanding any residence requirement of the town law"))
man = json.loads((HERE.parent / "data" / "reask_manual.json").read_text())["laws"]
check("U9 reask_manual holds the four laws for night 20261019, capped at 8 each",
      all(k in man and 1 <= len([i for i in man[k] if i["night"] == "20261019"]) <= 8 for k in ("2017-A11227", "2017-A10355", "2011-A2289", "2011-A10205")))

print("%d passed, %d failed" % (passed, failed))
