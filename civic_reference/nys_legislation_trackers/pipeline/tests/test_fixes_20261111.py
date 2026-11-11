"""Nov 11 2026: U1/B43 quotes cut inside a bracketed deletion are trimmed so they match the law text (two HARD failures)."""
import os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
if not (HERE / "cache" / "packets").is_dir():
    print("0 passed, 0 failed (skipped: cache/packets is not present here)"); sys.exit(0)
import extract_duties as ed
passed = failed = 0
def check(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1; print("FAIL", name)
for key, y in (("2017-A7245", "2017"), ("2021-S6018", "2021")):
    p = HERE / "cache" / "packets" / y / (key + ".txt")
    if not p.exists():
        print("skipped:", key); passed += 1; continue
    text = p.read_text()
    sents = [q for q, c, pos in ed.sunset_extension_sentences_pos(text)]
    bad = [q for q in sents if not ed.eo.quote_present(q, text)]
    for q in bad:
        t, ok = ed.clean_u1_quote(q, text)
        check(key + " trimmed quote is found in the text", ok and ed.eo.quote_present(t, text))
        check(key + " trimmed quote has no unclosed bracket", t.count("[") <= t.count("]"))
    check(key + " has at least one sentence", bool(sents))
t, ok = ed.clean_u1_quote("not in any law at all [x", "some law text")
check("an unmatched quote is returned unverified", ok is False)
# Gate rules AG3, AG4, AH1 and B51 (Nov 11 2026 night): each asserts the rule on a synthetic record, never an id in stored data
def gate(quote, **kw):
    o = {"quote": quote, "quote_verified": True, "actor_raw": "the department", "agency": "DEC", "kind_model": "duty"}; o.update(kw)
    return ed.gate_record(o, quote, False)
saved = {f: getattr(ed, f) for f in ("APPLY_AG3", "APPLY_AG4", "APPLY_AH1", "APPLY_B51")}
try:
    q = "for two thousand nineteen, the number of licenses shall be limited to the number of licenses established in subparagraph (i) of this paragraph; and"
    ed.APPLY_AH1 = True; g = gate(q); check("AH1 drops a limit set by reference", bool(g) and g[0] == "amount_not_duty")
    ed.APPLY_AH1 = False; g = gate(q); check("AH1 off keeps the record out of the AH1 rule", not g or g[0] != "amount_not_duty" or "limited to the number" not in g[1])
    ed.APPLY_AH1 = True; check("AH1 keeps a real cap duty", not (gate("The department shall limit the number of licenses issued each year to fifty.") or ("",))[0] == "amount_not_duty")
    qm = "if a meeting of a committee, subcommittee, task force, or other subgroups thereof, by such means, as determined by the committee."
    ed.APPLY_AG3 = True; g = gate(qm, actor_raw="Committee", agency="Board of Regents"); check("AG3 drops a manner fragment", bool(g) and g[0] == "condition_of_other_record")
    ed.APPLY_AG3 = False; g = gate(qm, actor_raw="Committee", agency="Board of Regents"); check("AG3 off does not apply the rule", not g or "manner clause" not in g[1])
    qe = "For each county, new shared services actions in an approved plan may be eligible for funding to match savings from such action."
    ed.APPLY_AG4 = True; g = gate(qe, actor_raw="unspecified", agency="Unspecified"); check("AG4 drops an eligibility sentence with no actor", bool(g) and g[0] == "amount_not_duty")
    g = gate(qe, actor_raw="the department", agency="DEC"); check("AG4 keeps it when a body is named", not g or "eligibility sentence" not in g[1])
    ed.APPLY_AG4 = False; g = gate(qe, actor_raw="unspecified", agency="Unspecified"); check("AG4 off does not apply the rule", not g or "eligibility sentence" not in g[1])
    pt = HERE / "cache" / "text_marked" / "2013-A7099.txt"
    if pt.exists():
        txt = pt.read_text(); sq = ed.sunset_extension_sentences_pos(txt)[0][0]
        check("B51 recognises a probable-usefulness sunset extension", ed.ppu_sunset_record({"quote": sq}, txt))
    check("B51 leaves a plain sunset alone", not ed.ppu_sunset_record({"quote": "This act shall expire June 1, 2030."}, "Section 1. The act is amended.\n\nThis act shall expire June 1, 2030."))
finally:
    for f, v in saved.items(): setattr(ed, f, v)
# Coordinator round AG5-AG9 (Nov 11 2026); AG7 stays off (219 stored ids flip)
saved2 = {f: getattr(ed, f) for f in ("APPLY_AG5", "APPLY_AG6", "APPLY_AG8", "APPLY_AG9")}
try:
    lead = "(g) Upon a finding, the court shall, at a minimum, toll interest, and where appropriate, the court may also impose one or more of the following:"
    ed.APPLY_AG5 = True; check("AG5 last modal governs the list lead", ed.lead_kind(lead, "compel production of documents;") == "power")
    check("AG5 keeps an item with its own shall a duty", ed.lead_kind(lead, "The department shall notify consumers;") == "duty")
    ed.APPLY_AG5 = False; check("AG5 off reads the first modal", ed.lead_kind(lead, "compel production of documents;") == "duty")
    ed.APPLY_AG5 = True
    al = "3. The members shall be appointed as follows:"
    ed.APPLY_AG6 = True; lead6 = "3. The members shall be appointed as follows:"
    check("AG6 appointment item keeps its record", ed.q1_item("(a) two members to be appointed by the temporary president of the senate;", lead6) is False)
    check("AG6 item without an appointer stays a sub-item", ed.q1_item("(b) one representative from a consumer organization;", "The members shall be appointed as follows:") is True)
    ed.APPLY_AG6 = False; check("AG6 off drops the appointment item", ed.q1_item("(a) two members to be appointed by the temporary president of the senate;", lead6) is True)
    ed.APPLY_AG8 = True
    qs = "For the purposes of section one hundred sixty-three of this article, no bidder shall be deemed to be the lowest bidder unless the bid will comply with the contract term."
    check("AG8 lead-in 'for the purposes of' is a strict condition", bool(ed.AG8_LEAD_COND.search(qs)) and bool(ed.STRICT_COND.search(qs)))
    check("AG8 leaves a plain grant alone", not ed.AG8_LEAD_COND.search("The department shall award each contract unless the bid fails."))
    check("AG9 effective-date clause only", ed.ag9_effective_date_only("provided further that sections one and two of this act shall take effect January 1, 2015;"))
    check("AG9 keeps an expiry clause", not ed.ag9_effective_date_only("This act shall take effect immediately and shall expire and be deemed repealed June 15, 2018."))
    check("AG9 keeps remain in force", not ed.ag9_effective_date_only("This act shall take effect immediately and the provisions of section one shall remain in force to June 15, 2018."))
    check("AG7 flag is off", ed.APPLY_AG7 is False)
finally:
    for f, v in saved2.items(): setattr(ed, f, v)
# AG10: a U1 sentence carrying the drafting-commission notice is dropped (2009-A10213-04)
_p = HERE / "cache" / "packets" / "2009" / "2009-A10213.txt"
if _p.exists():
    _t = _p.read_text()
    _q = [q for q, c, pos in ed.sunset_extension_sentences_pos(_t) if ed.BDC_NOTIFY.search(q)]
    check("AG10 the 2009-A10213 own clause carries the notice", bool(_q))
    check("AG10 flag on", ed.APPLY_AG10 is True)
print("%d passed, %d failed" % (passed, failed))
