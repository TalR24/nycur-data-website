"""Plain script: the Oct 12 2026 audit fixes M14-M19 and J8. Uses stored data when present. Prints 'N passed, M failed'."""
import json, os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import effective_date as efd
import agency_resolve_nys as ar

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

TM = HERE / "cache" / "text_marked"
DATA = HERE.parent / "data"
def stored(key):
    y = key[:4]
    out = []
    for f, k in (("duties", "obligations"), ("powers", "powers")):
        p = DATA / f / (y + ".json")
        if p.exists():
            out += [x for x in json.load(open(p))[k] if x["obligation_id"] == key or x["matter_id"] == key]
    return out
def rec(oid):
    return next((x for x in stored(oid[:oid.rindex("-")]) if x["obligation_id"] == oid), None)

# M14. "N years after the date on which it shall have become a law"
c = "§ 28. This act shall take effect two years after the date on which it shall have become a law."
check("M14 two years after the date on which", efd.parse_effective(c, "2014-11-21")["effective_date"] == "2016-11-21")
check("M14 one year after the date it shall have", efd.parse_effective("§ 2. This act shall take effect one year after the date it shall have become a law.", "2014-11-21")["effective_date"] == "2015-11-21")
check("M14 the old wording still parses", efd.parse_effective("§ 2. This act shall take effect two years after it shall have become a law.", "2014-11-21")["effective_date"] == "2016-11-21")
check("M14 months after the date on which", efd.parse_effective("§ 2. This act shall take effect six months after the date on which it shall have become a law.", "2014-11-21")["effective_date"] == "2015-05-21")
check("M14 'after such effective date' stays unparsed", efd.parse_effective("§ 2. This act shall take effect two years after such effective date.", "2014-11-21")["effective_date"] is None)
sg = DATA / "signed" / "2013.json"
if sg.exists() and (TM / "2013-S3810.txt").exists():
    s = {x["key"]: x for x in json.load(open(sg))}["2013-S3810"]
    e = efd.parse_effective((TM / "2013-S3810.txt").read_text(), s["signed_date"])
    check("M14 2013-S3810 = signed + 2 years", e["rule"] == "n_years_after_law" and e["effective_date"] == str(int(s["signed_date"][:4]) + 2) + s["signed_date"][4:])

# M15. resolvable actors stored as Unspecified
nyc_by = ed.NYC_BY
for raw in ("the borough president", "borough presidents", "the president of the borough of Queens"):
    o = {"actor_raw": raw, "agency": "Unspecified", "actor_unresolved": True, "quote": "x"}
    check("M15 %s" % raw, ar.fix_resolvable_actor(o, nyc_by) and o["agency"] == "Borough Presidents" and o["jurisdiction"] == "nyc" and not o.get("actor_unresolved"))
o = {"actor_raw": "official of this state charged with the enforcement of laws, ordinances or regulations", "agency": "Unspecified",
     "quote": "No official of this state, or of any city, county, town or village therein, charged with the enforcement of laws, ordinances or regulations shall accept or approve any plans"}
check("M15 State and local officials -> State agencies", ar.fix_resolvable_actor(o, nyc_by) and o["agency"] == "State agencies" and o["jurisdiction"] == "state")
o = {"actor_raw": "the code enforcement official", "agency": "Unspecified", "quote": "the code enforcement official of the town or village shall inspect the premises"}
check("M15 local only -> Local agencies and authorities", ar.fix_resolvable_actor(o, nyc_by) and o["agency"] == "Local agencies and authorities" and o["jurisdiction"] == "local")
o = {"actor_raw": "the enforcement officer", "agency": "Unspecified", "quote": "the enforcement officer shall issue a notice"}
check("M15 no State or local wording is left alone", not ar.fix_resolvable_actor(o, nyc_by) and o["agency"] == "Unspecified")
o = {"actor_raw": "the borough president", "agency": "Governor"}
check("M15 a resolved record is untouched", not ar.fix_resolvable_actor(o, nyc_by) and o["agency"] == "Governor")
r = rec("2013-A2448-01")
check("M15 stored 2013-A2448-01 -> Borough Presidents", bool(r) and r["agency"] == "Borough Presidents" and r["jurisdiction"] == "nyc")
r = rec("2013-S3810-04")
check("M15 stored 2013-S3810-04 -> State agencies", bool(r) and r["agency"] == "State agencies")

# M16. public bodies
for raw in ("a public body", "the public body", "public bodies", "Public bodies"):
    o = {"actor_raw": raw, "agency": "Municipalities (all)", "jurisdiction": "local"}
    check("M16 %s" % raw, ar.fix_public_body(o) and o["agency"] == "State and local bodies" and o["jurisdiction"] == "state")
o = {"actor_raw": "the public body of the village", "agency": "Villages"}
check("M16 a qualified body is left alone", not ar.fix_public_body(o) and o["agency"] == "Villages")
r = rec("2009-A3169-01")
check("M16 stored 2009-A3169-01 -> State and local bodies", bool(r) and r["agency"] == "State and local bodies")

# M17. cost-bearing duties are ongoing with no deadline
for q in ("All past service costs shall be borne by the village", "the fees shall be paid by the applicant", "the county shall bear the cost of such services", "performed at the expense of the owner"):
    check("M17 matches: %s" % q[:30], bool(ed.COST_BEARING.search(q)))
check("M17 an unrelated payment does not match", not ed.COST_BEARING.search("the department shall pay the county within thirty days"))
r = rec("2009-S7182-02")
check("M17 stored 2009-S7182-02 none + ongoing", bool(r) and r["deadline_kind"] == "none" and r["recurrence"] == "ongoing" and not r.get("deadline_date"))

# M18. braced new matter that is only labels and numbers
check("M18 labels and numbers", ed.label_only_braces("x {{(a)}} y {{(b)}} z {{2014}}"))
check("M18 one real clause defeats it", not ed.label_only_braces("x {{(a)}} y {{the department shall report}}"))
check("M18 no braces", not ed.label_only_braces("plain text"))
check("M18 is switched off (APPLY_M18 False): the literal rule flips 312 records, over the 80 limit", ed.APPLY_M18 is False)
# SKIPPED: 2011-S2704-01 extends_existing true. Its braced spans are full sentences, so the 8-character rule cannot flip it; J8 re-asks the law.

# M19. truncated texts
t = efd.parse_effective("Debt service payments ........ 230,000,000\n\nSCHEDULE\n\nTotal of schedule ........ 231,000,000", "2015-03-01")
check("M19 no act clause -> text_truncated", t["rule"] == "text_truncated" and t["effective_date"] is None)
check("M19 a clause that cannot be parsed stays unparsed", efd.parse_effective("§ 2. This act shall take effect when the moon is full.", "2015-03-01")["rule"] == "unparsed")
check("M19 empty text -> text_truncated", efd.parse_effective("", "2015-03-01")["rule"] == "text_truncated")
p = DATA / "effective_dates" / "2015.json"
if p.exists():
    check("M19 stored 2015-S2002 rule text_truncated", json.load(open(p))["2015-S2002"]["rule"] == "text_truncated")
sk = {x["key"]: x for x in json.load(open(DATA / "deferred_skipped.json"))["laws"]}
check("M19 2015-S2002 in deferred_skipped", sk.get("2015-S2002", {}).get("reason") == "text truncated, no act clause")

# J8. manual re-ask entries
man = json.load(open(DATA / "reask_manual.json"))["laws"]
check("J8 the seven laws carry night 20261012", all(any(x["night"] == "20261012" for x in man.get(k, [])) for k in ("2011-S2704", "2015-A1327", "2013-A6567", "2013-S3810", "2013-S7644", "2009-S6753", "2015-S1393")))
check("J8 2011-S2704 has four section sentences", len([x for x in man["2011-S2704"] if x["night"] == "20261012"]) == 4)
p = DATA / "reask" / "2011.json"
if p.exists():
    ent = json.load(open(p))["laws"].get("2011-S2704")
    check("J8 2011-S2704 in data/reask with audit_confirmed_miss", bool(ent) and any(r["check"] == "audit_confirmed_miss" for r in ent["reasons"]))

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
