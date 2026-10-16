"""Plain script: python3 tests/test_effective_date_parts.py  ->  'N passed, M failed'. E1 Part-level dates, E2 section-bound repeal, E3 lookups.
No network: chapter_lookup is only used through cached/local data."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from effective_date import parse_effective, part_dates, section_bound_expiry

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", name, detail)


# ---- E1 synthetic, marked text: the next Part's heading rides at the end of the previous Part's clause paragraph
SYN = ("Section 1. This act enacts into law components in Parts A through C. {{Part}} A\n\n"
       "Section 1. Text of part A.\n\n"
       "§ 2. This act shall take effect immediately. S. 1 12 A. 2 {{Part}} B\n\n"
       "Section 1. Text of part B.\n\n"
       "§ 3. This act shall take effect on the ninetieth day after it shall have become a law. {{Part}} C\n\n"
       "Section 1. Text of part C.\n\n"
       "§ 2. This act shall take effect January 1, 2015.\n\n"
       "§ 2. Severability clause. Text.\n\n"
       "§ 3. This act shall take effect immediately; provided, however, that the applicable effective date of Parts A through C of this act shall be as specifically set forth in the last section of such Parts.")
r = parse_effective(SYN, "2014-01-10")
ps = [e for e in r["section_dates"] if e.get("part")]
check("E1 three parts", [e["part"] for e in ps] == ["A", "B", "C"], ps)
check("E1 dates", [e["effective_date"] for e in ps] == ["2014-01-10", "2014-04-10", "2015-01-01"], [e["effective_date"] for e in ps])
check("E1 rules", [e["rule"] for e in ps] == ["immediately", "nth_day_after_law", "fixed_date"])
check("E1 act-level stays the law date", r["effective_date"] == "2014-01-10" and r["rule"] == "immediately", (r["effective_date"], r["rule"]))
check("E1 spans contiguous and cover the Part", ps[0]["span_end"] == ps[1]["span_start"] and ps[1]["span_end"] == ps[2]["span_start"]
      and SYN.index("Text of part C") in range(ps[2]["span_start"], ps[2]["span_end"]) and SYN.index("Text of part A") in range(ps[0]["span_start"], ps[0]["span_end"]))
check("E1 Part C span stops before the act-level clause", SYN[ps[2]["span_end"]:].startswith("§ 3. This act shall take effect immediately; provided"), SYN[ps[2]["span_end"]:][:50])
check("E1 raw_clause clean of heading and page header", ps[0]["raw_clause"] == "§ 2. This act shall take effect immediately." and "Part" not in ps[1]["raw_clause"], [e["raw_clause"] for e in ps])
# plain text headings
PLAIN = ("                                 PART A\n\nSection 1. x.\n\n§ 2. This act shall take effect immediately.\n\n"
         "                                 PART B\n\nSection 1. y.\n\n§ 2. This act shall take effect on the sixtieth day after it shall have become a law.\n\n"
         "§ 3. This act shall take effect immediately; provided that Parts A and B take effect as set forth in the last section of such Parts.")
pp = part_dates(PLAIN, "2012-06-01")
check("E1 plain PART headings", [(e["part"], e["effective_date"]) for e in pp] == [("A", "2012-06-01"), ("B", "2012-07-31")], pp)
# not an omnibus: one clause, or clauses without Part headings
check("E1 single clause gives none", part_dates("Section 1. x.\n\n§ 2. This act shall take effect immediately.", "2012-06-01") == [])
check("E1 two clauses, no headings gives none", part_dates("§ 2. This act shall take effect immediately.\n\n§ 3. This act shall take effect immediately.", "2012-06-01") == [])

# ---- E1 real text 2013-A8113 (signed 2013-06-24): auditor B said Part C 2013-08-23
tp = os.path.join(HERE, "..", "cache", "text_marked", "2013-A8113.txt")
if os.path.exists(tp):
    t = open(tp).read()
    r = parse_effective(t, "2013-06-24")
    ps = {e["part"]: e for e in r["section_dates"] if e.get("part")}
    check("A8113 Parts A B C", sorted(ps) == ["A", "B", "C"], sorted(ps))
    check("A8113 Part C 2013-08-23 (60th day after 2013-06-24)", ps["C"]["effective_date"] == "2013-08-23" and ps["C"]["rule"] == "nth_day_after_law", ps["C"])
    check("A8113 Parts A and B immediately", ps["A"]["effective_date"] == "2013-06-24" and ps["B"]["effective_date"] == "2013-06-24")
    check("A8113 law date stays the act-level clause", r["effective_date"] == "2013-06-24" and "Parts A through C" in r["raw_clause"], r["raw_clause"][:90])
    q = "Penalties for fraud in the start-up ny program"       # a Part A quote, a Part C quote
    pos_a, pos_c = t.index(q), t.index("Section 359 of the economic development law, as amended by section 6 of part G")
    check("A8113 quote spans land in the right Part", ps["A"]["span_start"] <= pos_a < ps["A"]["span_end"] and ps["C"]["span_start"] <= pos_c < ps["C"]["span_end"])
else:
    print("skip A8113 (no cached text)")

# ---- E2 section-bound repeal
SAME = "§ 2. This act shall take effect immediately; provided that the amendments to section 4 of the foo law made by section one of this act shall expire and be deemed repealed on the same date as such section expires."
THERE = "§ 2. This act shall take effect immediately, provided that the amendments to section 2590-h of the education law, made by section two of this act, shall not affect the expiration of such section and shall be deemed repealed therewith."
r1, r2 = parse_effective(SAME, "2013-01-01"), parse_effective(THERE, "2013-01-01")
check("E2 same date as such section", r1["expires_rule"] == "with_referenced_section" and r1["expires_date"] is None, (r1["expires_rule"], r1["expires_date"]))
check("E2 of such section ... therewith", r2["expires_rule"] == "with_referenced_section" and r2["expires_date"] is None, (r2["expires_rule"], r2["expires_date"]))
check("E2 no wording, no rule", parse_effective("§ 2. This act shall take effect immediately.", "2013-01-01")["expires_rule"] is None)
check("E2 fixed act expiry wins, no rule", parse_effective("§ 2. This act shall take effect immediately and shall expire December 1, 2019.", "2013-01-01")["expires_rule"] is None)
NAMED = ("§ 2. This act shall take effect immediately, provided that the amendments to section 1 of chapter 192 of the laws of 2011, made by section one of this act, "
         "shall not affect the expiration of such section and shall be deemed repealed therewith.")
seen = []
def stub(bills=None, chapter=None, year=None):
    seen.append((chapter, year))
    return {"chapter": 192, "year": 2011, "expires_date": "2016-06-30", "section_dates": []} if (chapter, year) == (192, 2011) else None
r3 = parse_effective(NAMED, "2013-01-01", resolver=stub)
check("E2 named chapter resolved fills the date", r3["expires_rule"] == "with_referenced_section" and r3["expires_date"] == "2016-06-30" and (192, 2011) in seen, (r3["expires_rule"], r3["expires_date"], seen))
r4 = parse_effective(NAMED, "2013-01-01", resolver=lambda **k: None)
check("E2 named chapter unresolved leaves it null", r4["expires_rule"] == "with_referenced_section" and r4["expires_date"] is None, (r4["expires_rule"], r4["expires_date"]))
def stub_sec(bills=None, chapter=None, year=None):
    return {"expires_date": None, "section_dates": [{"applies_to": "section 1 of this act", "rule": "section_expiry", "expires_date": "2014-03-31"}]}
check("E2 chapter section-level sunset", parse_effective(NAMED, "2013-01-01", resolver=stub_sec)["expires_date"] == "2014-03-31")
sb = section_bound_expiry("shall not affect the repeal of such section pursuant to section 12 of chapter 907 of the laws of 1984, as amended, and shall be deemed repealed therewith.", stub)
check("E2 'of such section pursuant to ... and shall be deemed repealed therewith'", sb and sb["reference"] == {"section": "12", "chapter": 907, "year": 1984}, sb)

# ---- E3
r = parse_effective("§ 4. This act shall take effect July 1, 2014: provided, however, that if section 3 of part D of chapter 501 of the laws of 2012 is not in effect on such date, then section 12 of this act shall take effect on the same date and in the same manner as such chapter of the laws of 2012, takes effect.", "2014-01-10")
check("E3 colon proviso does not turn the act into same_as_chapter", r["effective_date"] == "2014-07-01" and r["rule"] == "fixed_date", (r["effective_date"], r["rule"]))
import chapter_lookup as cl
check("E3 January carry-over chapter detected", cl._carry_over(2013, 557) and not cl._carry_over(2013, 5))
rec = cl._local_chapter(2013, 557)
check("E3 chapter 557 of 2013 found in the signed index (signed 2014-01-10)", rec and rec["signed_date"] == "2014-01-10" and rec["bill"] == "2013-S5504", rec and rec["bill"])
u = cl.resolve(chapter=553, year=2008)
check("E3 pre-2009 chapter stays unresolved with a tried note", u and u.get("unresolved") and "returned 0 items" in u["tried"] and "404" in u["tried"], u)
r = parse_effective("§ 2. This act shall take effect on the same date and in the same manner as chapter 553 of the laws of 2008 takes effect.", "2009-10-09", resolver=cl.resolve)
check("E3 law keeps same_as_chapter_unresolved and carries the tried note", r["rule"] == "same_as_chapter_unresolved" and "tried" in r["reference"], r.get("reference"))
r = parse_effective('§ 2. This act shall take effect on the same date and in the same manner as a "concurrent resolution of the senate and assembly proposing an amendment to section 1 of article 14 of the constitution" takes effect.', "2013-12-18", resolver=cl.resolve)
check("E3 concurrent resolution records what was tried", r["rule"] == "same_as_chapter_unresolved" and "tried" in (r.get("reference") or {}), r.get("reference"))

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
