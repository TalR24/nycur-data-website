"""Plain script: the Oct 8 2026 audit fixes (dedupe guard, condition rules, triggers, kind, DTF, list lead-ins, agency resolver,
expiration-keyed effective dates, per-session stores). Synthetic inputs, no model, no cached texts. Prints 'N passed, M failed'."""
import json, os, sys
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

# 4. dedupe: different citations or different nouns are different provisions
a = {"citation": "Public Authorities Law § 2041-w(2)(A)", "quote": "The Authority shall convey to the counties the real property constituting the transfer stations"}
b = {"citation": "Public Authorities Law § 2041-w(2)(C)", "quote": "The Authority shall convey to the counties the real property constituting the landfills"}
check("citations 2(A) vs 2(C) differ", ed.distinct_provisions(a, b))
c = {"citation": "Criminal Procedure Law § 530.12(5)", "quote": "x"}; d = {"citation": "Criminal Procedure Law § 530.13(4)", "quote": "x"}
check("different sections differ", ed.distinct_provisions(c, d))
e = {"citation": "Tax Law § 5(a)", "quote": "The department shall grant agents prior approval in a manner and form to be determined"}
f = {"citation": "Tax Law § 5(a)(1)", "quote": "The department shall grant agents prior approval in a manner and form to be determined"}
check("nested citations are one provision", not ed.distinct_provisions(e, f))
g = {"quote": "the Authority shall convey all property constituting the transfer stations and moveable fixtures"}
h = {"quote": "the Authority shall convey all property constituting the landfills and monitoring wells"}
check("noun rule without citations", ed.distinct_provisions(g, h))

# 5. conditions
def rec(oid, agency, quote):
    return {"obligation_id": oid, "agency": agency, "agency_unit": None, "quote": quote, "kind": "duty"}
ed.DROPPED.clear()
lst = [rec("T-01", "SUNY", "The trustees shall enter into a lease for the construction of a dormitory facility"),
       rec("T-02", "Attorney General", "The lease for the dormitory facility construction shall be subject to the approval of the attorney general")]
out = ed.drop_conditions(lst)
check("subject to approval of another actor is a condition", [r["obligation_id"] for r in out] == ["T-01"])
lst = [rec("T-03", "DOS", "The finances of the authority shall be the subject of a final audit conducted by the department of state dissolution accounts"),
       rec("T-04", "ABO", "The final audit accounts shall be subject to the review and approval of the authorities budget office")]
check("subject to review by X is X's duty: kept", len(ed.drop_conditions(lst)) == 2)

# 7. triggers
for ph in ("On the written request of any of the counties, the office shall assist", "at dissolution any accounts shall be assigned", "after receipt of the report"):
    check("trigger: " + ph[:30], bool(ed.TRIGGER.search(ph)))

# 8. a limit on a power is not a duty
check("limit regex", bool(ed.LIMIT_RE.search("shall not exceed the greater of eight years")) and not ed.DEBT_WORDS.search("an order of protection"))

# 9. several localities
t = "The town of Brookhaven and the village of Westbury may exempt. The county of Nassau may not."
units = ed.law_localities(t, "AN ACT in relation to the town of Brookhaven and the village of Westbury")
check("law_localities finds several", len(units) >= 2 and ("Towns", "Town of Brookhaven") in units)
check("law_locality is None for several", ed.law_locality(t, "x") is None)

# 6. list lead-in inline in the same subdivision, in existing text
txt = "4. To develop standards and training for investigators. Such topics include: (a) how to identify incidents; (d) {{protocols and procedures; And (e)}} employees' rights;\n"
q = "protocols and procedures; And (e)"
sp = ed.locate_span(q, txt)
il = ed.inline_lead_in(sp, txt)
check("inline lead-in found", il is not None and il[1] is True and "To develop" in il[0])
check("To <verb> counts as a functions item", bool(ed.FUNCTION_ITEM.match("28. {{To carry out investigations by observing protocols}}")))

# 1/2/3. agency resolver
deps = {"eo": ed.eo, "LOOKUP": ed.LOOKUP, "BY_CANON": ed.BY_CANON, "NYC_LOOKUP": ed.NYC_LOOKUP, "NYC_BY": ed.NYC_BY, "NYC_MARKERS": ed.NYC_MARKERS, "named_locality": ed.named_locality}
def run(raw, model, agency=None, text="", **kw):
    o = {"actor_raw": raw, "actor_resolved_model": model, "agency": agency or raw, "agency_matched": False}
    r = ar.resolve_unmatched(o, text, {}, deps)
    return o, r
o, r = run("the authority", "state liquor authority")
check("the authority + model -> ABC", o["agency"] == "ABC" and o["agency_matched"])
o, r = run("the tlc", "new york city taxi and limousine commission")
check("TLC -> NYC", o["jurisdiction"] == "nyc" and o["agency_matched"])
o, r = run("each state agency", "state agencies")
check("state agencies group", o["agency"] == "State agencies" and o["agency_matched"])
o, r = run("a court of this state", "new york state courts")
check("court -> Unified Court System", o["agency"] == "Unified Court System")
o, r = run("the board of trustees of the brunswick community library district", "brunswick community library district")
check("library district unit under group", o["agency_group"] == "Library districts" and "Brunswick" in (o["agency_unit"] or ""))
o, r = run("the board of directors", None, text="There is hereby created a public benefit corporation to be known as the Montgomery, Otsego, Schoharie Solid Waste Management Authority, which shall exist.")
check("board of directors -> the authority the act creates", "Solid Waste Management Authority" in o["agency"] and o["agency_matched"])
o, r = run("moneys", None)
check("unresolvable stays Unspecified and flagged", o["agency"] == "Unspecified" and o.get("actor_unresolved") and r == "unresolved")

# 10c. effective date keyed to another chapter's expiration
clause = "§ 3. This act shall take effect immediately; except that section two of this act shall take effect on the expiration of section 1 of chapter 321 of the laws of 2011."
eff = efd.parse_effective(clause, "2013-07-12")
sd = eff["section_dates"]
check("expiration-keyed section is an open date", len(sd) == 1 and sd[0]["rule"] == "on_expiration_of_other_law" and sd[0]["effective_date"] is None)
check("section_effective returns open for that section", ed.section_effective({"quote": "x", "citation": ""}, "§ 1. a\n\n§ 2. b shall do something here ok\n", eff)[1] in ("law", "open"))

# the per-session stores (when present)
D = HERE.parent / "data"
if (D / "duties").exists():
    sets = {k: {f.stem for f in (D / k).glob("*.json")} for k in ("duties", "powers", "reask", "dropped")}
    check("per-session file sets match", all(v == sets["duties"] for v in sets.values()))
    check("no legacy single pilot files", not (D / "duties.json").exists() and not (D / "powers.json").exists())
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
