"""Plain script: the Oct 10 2026 audit fixes M1-M6, J5-J6 and H1. Uses the cached marked texts when present. Prints 'N passed, M failed'."""
import json, os, sys, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import effective_date as efd
import agency_resolve_nys as ar
import next_packet_batch as npb

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

TM = HERE / "cache" / "text_marked"
DATA = HERE.parent / "data"
def law_text(key):
    p = TM / (key + ".txt")
    return p.read_text() if p.exists() else None

# M1. "N years after it shall have become a law"
e = efd.parse_effective("§ 4. This act shall take effect one year after it shall have become a law.", "2015-08-13")
check("M1 one year -> 2016-08-13", e["effective_date"] == "2016-08-13" and e["rule"] == "n_years_after_law")
check("M1 two years", efd.parse_effective("§ 3. This act shall take effect two years after it shall have become a law.", "2015-08-13")["effective_date"] == "2017-08-13")
check("M1 months still parse", efd.parse_effective("§ 3. This act shall take effect six months after it shall have become a law.", "2015-08-13")["effective_date"] == "2016-02-13")
check("M1 'one year after the expiration' is not parsed as the signing offset",
      efd.parse_effective("§ 3. This act shall take effect one year after the expiration of chapter 5.", "2015-08-13")["effective_date"] is None)
t = law_text("2015-A5652")
if t:
    sg = {x["key"]: x for x in json.load(open(DATA / "signed" / "2015.json"))}["2015-A5652"]["signed_date"]
    check("M1 2015-A5652 = signed date + 1 year", efd.parse_effective(t, sg)["effective_date"] == efd.add_months(efd._d(sg), 12).isoformat())

# M2. a generic State officer noun never takes a locality from the quote
q = "the authority may issue a retail license for on-premises consumption for a premises located within two hundred feet of a church on a parcel in the City of Kingston"
o = {"actor_raw": "the authority", "actor_resolved_model": "state liquor authority", "quote": q, "action_summary": "Issue a license in the City of Kingston.",
     "citation": "Alcoholic Beverage Control Law § 64(7)(e-7)", "agency": "Unspecified", "agency_matched": False}
ed.attach_jurisdiction(o)
check("M2 not local after attach", o.get("jurisdiction") != "local" and not o.get("agency_unit"))
ed.agency_resolve_nys.resolve_unmatched(o, "", {}, {**ed.RESOLVE_DEPS, "named_locality": ed.named_locality})
check("M2 2015-S3217-01 -> ABC, state, no unit", o["agency"] == "ABC" and o["jurisdiction"] == "state" and not o.get("agency_unit"))
o = {"actor_raw": "the authority", "actor_resolved_model": None, "quote": q, "citation": "Alcoholic Beverage Control Law § 64(7)(e-7)", "agency": "Unspecified", "agency_matched": False}
ed.agency_resolve_nys.resolve_unmatched(o, "", {}, {**ed.RESOLVE_DEPS, "named_locality": ed.named_locality})
check("M2 'the authority' in the ABC Law -> ABC", o["agency"] == "ABC" and o["jurisdiction"] == "state")
o = {"actor_raw": "the assessor", "actor_resolved_model": None, "quote": "the assessor of the town of Cornwall, shall list the parcel", "action_summary": "", "agency": "Unspecified", "agency_matched": False}
ed.attach_jurisdiction(o)
check("M2 a local noun still takes the quote's locality", o["jurisdiction"] == "local" and o["agency_unit"] == "Town of Cornwall")
o = {"actor_raw": "the department", "actor_resolved_model": None, "quote": "the department shall notify the town of Cornwall", "action_summary": "", "agency": "Unspecified", "agency_matched": False}
ed.attach_jurisdiction(o)
check("M2 'the department' never takes a locality", o["jurisdiction"] != "local")

check("M2 DTF carve-out regex exists", ed.STATE_GENERIC_ACTOR.match("the commissioner") and ed.STATE_MARK.search("commissioner of taxation and finance"))

# M3. 200-foot-rule place exception extends an existing authority
for key, qt in (("2015-A7331", "notwithstanding the provisions of paragraph (a) of this subdivision, the authority may issue a retail license for on-premises consumption for a premises which shall be located within two hundred feet of a building occupied as a church, synagogue or other place of worship"),
                ("2015-S3217", "notwithstanding the provisions of paragraph (a) of this subdivision, the authority may issue a retail license for on-premises consumption for a premises which shall be located within two hundred feet of a building occupied exclusively as a church")):
    check("M3 %s place exception" % key, bool(ed.PLACE_EXCEPTION.search(qt)))
check("M3 label before notwithstanding (context sentence)", bool(ed.PLACE_EXCEPTION.search("(e-7) notwithstanding the provisions of paragraph (a) of this subdivision, the authority may issue a license within two hundred feet of a church")))
check("M3 other notwithstanding is not matched", not ed.PLACE_EXCEPTION.search("notwithstanding the provisions of section 5 of this chapter, the board may issue a permit"))

# M4. precondition triggers
for k in ("2013-A8113-18", "2013-A8113-21"):
    quote = {"2013-A8113-18": "must submit a plan to the commissioner that specifies the land or space the campus or college wants to include",
             "2013-A8113-21": "At least thirty days prior to submitting such plan, the campus or college must provide the municipality with a copy of the plan."}[k]
    check("M4 %s triggered" % k, bool(ed.TRIGGER.search(quote)))
for term in ("prior to submitting", "before submitting", "wishes to", "seeks to", "elects to", "chooses to", "that applies", "prior to the filing", "prior to approval"):
    check("M4 term '%s'" % term, bool(ed.TRIGGER.search("The campus shall act " + term + " a plan")))
check("M4 plain duty not triggered", not ed.TRIGGER.search("The commissioner shall adopt rules"))

# M5. units
check("M5 unit_title", ed.unit_title("start-up ny approval board") == "Start-up NY Approval Board" and ed.unit_title("mandate relief council") == "Mandate Relief Council")
check("M5 unit_title small words", ed.unit_title("division of the budget") == "Division of the Budget")
check("M5 local groups excluded", "Towns" in ed.STATE_UNIT_EXCLUDED and "Boards of elections" in ed.STATE_UNIT_EXCLUDED and "Governor" not in ed.STATE_UNIT_EXCLUDED)
duties = DATA / "duties" / "2013.json"
if duties.exists():
    for r in json.load(open(duties))["obligations"]:
        if r["obligation_id"] == "2013-A8113-05" and r.get("model_unit"):
            check("M5 2013-A8113-05 stored unit", r["agency_unit"] == "Start-up NY Approval Board")

# M6. quote moved onto the new matter
t = law_text("2015-A7631")
if t:
    stored = ("provided, however, that any lease entered into for a term greater than ten years during the effective period of this section shall continue in full force and effect, "
              "and provided that upon the expiration of such section the commissioner of general services shall continue to be empowered to enter into leases having terms not exceeding ten years")
    nq = ed.relocate_quote(stored, t)
    check("M6 2015-A7631-01 relocated quote holds 2020", bool(nq) and "2020" in nq and "2015" not in nq and ed.locate_span(nq, t) is not None)
    check("M6 a quote already on new matter is left alone", ed.relocate_quote("shall expire on June 30, 2020", t) is None)
    recs = [{"quote": stored, "extends_existing": True}]
    fl = [f for f in ed.judgment_flags(t, recs) if f["check"] == "quote_outside_new_matter"]
    check("M6 unmoved quote goes to reask with the stored quote", len(fl) == 1 and fl[0]["sentences"] == [stored])
    check("M6 relocated record is not flagged", not [f for f in ed.judgment_flags(t, [{"quote": nq, "extends_existing": True, "quote_relocated": True}]) if f["check"] == "quote_outside_new_matter"])
check("M6 no markers, nothing to move", ed.relocate_quote("the commissioner shall adopt rules", "The commissioner shall adopt rules.") is None)

# J5. dropped designation with a government subject
txt = "§ 1. The trustees shall have power:\n\n{{To participate in joint arrangements with businesses.}}\n"
drops = [{"rule": "designation_no_actor", "quote": "To participate in joint arrangements with businesses", "matter_id": "x"},
         {"rule": "designation_no_actor", "quote": "f. alewife until December thirty-first, two thousand fourteen,", "matter_id": "x"},
         {"rule": "designation_no_actor", "quote": "a total of five campuses designated by the board of trustees of the university", "matter_id": "x"}]
fl = [f for f in ed.recall_flags("x", txt, [], drops) if f["check"] == "dropped_designation_with_actor"]
check("J5 two of three drops go to reask, with the dropped quotes", len(fl) == 1 and len(fl[0]["sentences"]) == 2 and fl[0]["sentences"][0].startswith("To participate"))

# J6. exemption-dropped sunset extension
dq = "The provisions of subdivisions one, two, three and four of this section shall not be applicable to any procurement by the authority commenced during the period from the effective date of this subdivision until December thirty-first,"
txt = "§ 1. Subdivision 5 is amended to read as follows:\n\n5. The provisions of subdivisions one, two, three and four of this section shall not be applicable to any procurement by the authority commenced during the period from the effective date of this subdivision until December thirty-first, [nineteen hundred] {{two thousand twenty}}.\n"
fl = [f for f in ed.recall_flags("x", txt, [], [{"rule": "exemption_or_applicability", "quote": dq}]) if f["check"] == "exemption_sunset_extension"]
check("J6 braced date in an applicability sentence -> reask", len(fl) == 1 and fl[0]["sentences"] == [dq])
fl = [f for f in ed.recall_flags("x", txt.replace("{{two thousand twenty}}", "two thousand twenty"), [], [{"rule": "exemption_or_applicability", "quote": dq}]) if f["check"] == "exemption_sunset_extension"]
check("J6 no braced date -> not flagged", not fl)
t = law_text("2015-A7335")
if t:
    drop_real = next((d for d in json.load(open(DATA / "dropped" / "2015.json"))["dropped"] if d["obligation_id"] == "2015-A7335-01"), None)
    if drop_real:
        fl = [f for f in ed.recall_flags("2015-A7335", t, [], [drop_real]) if f["check"] == "exemption_sunset_extension"]
        check("J6 2015-A7335-01 real text", len(fl) == 1)

# H1. deferred_skipped
tmp = Path(tempfile.mkdtemp()) / "deferred_skipped.json"
tmp.write_text(json.dumps({"rule": "x", "laws": [{"key": "2015-A8083", "reason": "too long"}]}))
check("H1 reads keys", npb.deferred_skipped(tmp) == {"2015-A8083"})
check("H1 missing file -> empty", npb.deferred_skipped(tmp.parent / "none.json") == set())
real = npb.deferred_skipped()
check("H1 real file lists 12 keys", len(real) == 12 and "2015-S2001" in real)
full, skipped = npb.unanswered(set()), npb.unanswered({"2015-A8083", "2009-A9708"})
check("H1 skip removes only the named keys", not [f for f in skipped if f.stem in ("2015-A8083", "2009-A9708")] and len(full) - len(skipped) == len([f for f in full if f.stem in ("2015-A8083", "2009-A9708")]))

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
