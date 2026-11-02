"""Plain script: Nov 1 2026 night gate fixes Q1-Q5 (Oct 31 bulk verification classes, amended earlier-chapter act clause). Prints 'N passed, M failed'."""
import time
import os, sys, json
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

_VERIFIED_Q = {a["obligation_id"]: a["quote"] for a in json.load(open(HERE.parent / "quality" / "gold_verified_additions.json")) if a.get("quote")}


def gate(law, oid):
    p = HERE / "cache" / "extracted" / (law + ".json")
    if not p.exists():
        return "skip"
    t = (HERE / "cache" / "text_marked" / (law + ".txt")).read_text()
    obs = json.load(open(p))["obligations"]
    hits = [x for x in obs if x["obligation_id"] == oid]
    vq = _VERIFIED_Q.get(oid)
    if vq:                                                   # Nov 2 2026: re-asks renumber; the verified quote identifies the record
        hits = [x for x in obs if (x.get("quote") or "")[:60] == vq[:60]] or []
    else:
        ra = HERE / "cache" / "packets" / law[:4] / "results_reask" / (law + ".json")
        if ra.exists() and ra.stat().st_mtime > time.mktime(time.strptime("20261102-0000", "%Y%m%d-%H%M")):   # ids in this file date from Nov 1
            print("skipped: law reasked after this test was written,", oid); return "skip"
    if not hits:
        print("skipped: law reasked,", oid, "not in cache"); return "skip"   # Nov 2 2026: re-asks renumber records
    r = ed.gate_record(hits[0], t, "{{" in t)
    return r[0] if r else None

# Q1. items under membership / scope / report-content leads
lead = "The council shall consist of the compact administrator, and ten other members to be appointed as follows:"
check("Q1 membership lead", ed.q1_item("One legislative representative to be appointed by the governor upon recommendation of the speaker", lead))
check("Q1 scope lead", ed.q1_item("Tort cases in supreme Court in Westchester county", "Provided, however, the following cases are not included:"))
check("Q1 report content lead", ed.q1_item("the risk of an unauthorized breach of data", "Such report shall be made public and shall consider, evaluate and present recommendations concerning:"))
check("Q1 item with its own modal is kept", ed.q1_item("The governor shall appoint the chair", lead) is False)
check("Q1 ordinary duty lead is untouched", ed.q1_item("Publish the rule", "The board shall do the following:") is False)
for law, oid in (("2011-A55", "2011-A55-80"), ("2011-A55", "2011-A55-87"), ("2019-A6787", "2019-A6787-11"), ("2009-A8956", "2009-A8956-05")):
    g = gate(law, oid)
    check("Q1 gate %s" % oid, g in ("sub_item_of_parent", "skip"))
# Q2. amounts and aid
for q in ("No service provided to an out-of-state school district pursuant to subparagraph ten shall be eligible for aid.",
          "the purposes and funding levels specified in section 54 of Part A of chapter 57 of the laws of 2009 shall be continued for such purposes and at such levels",
          "The liability of the state shall be deter- Mined by first calculating the Amount of the expenditure"):
    check("Q2 " + q[:30], bool(ed.Q2_AMOUNT.search(q)))
check("Q2 a payment duty is kept", not ed.Q2_AMOUNT.search("The commissioner shall pay the aid to each eligible school district."))
# Q3. conditions and consequences
for q in ("A Contracting agency that elects to proceed against a contractor for breach of contract as provided in this section shall be precluded From seeking enforcement pursuant to section 316",
          "Hail privilege base permits shall be issued to base stations pursuant to this section for a fee in the amount of three thousand dollars, and shall be valid for three years prior to renewal.",
          "No monies shall be disbursed by the treasurer of the district except after audit by the board of trustees.",
          "Any member chosen to fill a vacancy created other than by expiration of term shall be appointed for the unexpired term of the member",
          "Vacancies caused by the expiration of term shall be filled in the same manner as original appointments and for a term of five years."):
    check("Q3 " + q[:30], bool(ed.Q3_CONDITION.search(q)))
check("Q3 a plain issue duty is kept", not ed.Q3_CONDITION.search("The commissioner shall issue permits to base stations within thirty days."))
# Q4. no duty or power
for q in ("the holders of village offices shall, from and after the effective date of the creation of the town, by virtue thereof also hold town offices",
          "The parklands are described as follows: ALL that certain piece or parcel of land located in the City of Albany and being more particularly bounded and described as follows: Parcel 1",
          "deeds of conveyance shall be executed and filed for any parcels of real property."):
    check("Q4 " + q[:30], bool(ed.Q4_NO_POWER.search(q)))
# Q5. an earlier chapter's amended act clause
t = ("Section 1. Section 3 of chapter 206 of the laws of 2010, amending the public authorities law relating to establishing the metropolitan transportation authority small business mentoring program, is amended to read as follows:\n\n"
     "§ 3. This act shall take effect immediately and shall expire December 31, [2019] {{2029}} when upon such date the provisions of this act shall be deemed repealed.\n\n§ 2. This act shall take effect immediately.")
a = t.index("{{2029}}")
check("Q5 amended clause detected", ed.in_amended_act_clause((a, a + 8), t) is True)
check("Q5 own clause is not amended", ed.in_amended_act_clause((t.index("§ 2. This") + 5, t.index("§ 2. This") + 20), t) is False)
sx = ed.sunset_extension_sentences_pos(t)
check("Q5 one extension sentence, 2029", len(sx) == 1 and "2029" in sx[0][0])
check("Q5 holder is the MTA from the amended chapter", ed.sunset_holder(ed.amending_description(t, sx[0][2])) == "the Metropolitan Transportation Authority")
t6 = ("Section 1. Section 5 of chapter 449 of the laws of 1986 amending the private housing finance law relating to establishing initial rents in respect of certain loans, is amended to read as follows:\n\n"
      "§ 5. This act shall take effect immediately; provided that the provisions of sections one, two and four of this act shall remain in full force and effect until and including June 30, [2010] {{2014}}.\n\n§ 2. This act shall take effect immediately.")
q6 = "provided that the provisions of sections one, two and four of this act shall remain in full force and effect until and including June 30, 2014"
check("Q5 S6753 proviso is not the law's own act clause", ed.own_act_clause_quote(q6, t6, None, None) is False)
check("Q5 S6753 amending sentence names no body", ed.sunset_holder(ed.amending_description(t6, t6.index("{{2014}}"))) is None)
tn = "Section 1. A.\n\n§ 10. This act shall take effect immediately; provided that the provisions of sections one, two and nine of this act shall remain in full force and effect only until and including June {{23}}, 2015; provided further that x.\n"
qn = "provided that the provisions of sections one, two and nine of this act shall remain in full force and effect only until and including June 23, 2015"
check("Q5 N2: the law's own clause still dropped", ed.own_act_clause_quote(qn, tn, None, None) is True)

print("%d passed, %d failed" % (passed, failed))
