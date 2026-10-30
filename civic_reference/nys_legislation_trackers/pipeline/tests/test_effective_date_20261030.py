"""Plain script: python3 tests/test_effective_date_20261030.py  ->  'N passed, M failed'. B15: day-of-month forms and same-date-as-reversion."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from effective_date import parse_effective

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", name, detail)


def eff(clause, signed="2020-03-15", resolver=None):
    e = parse_effective(clause, signed, resolver=resolver, _parts=False)
    return e["effective_date"], e["rule"], e


d, r, _ = eff("§ 3. This act shall take effect on the first of January, 2020, and shall apply to all policies.", "2019-06-01")
check("fixed first of January 2020", (d, r) == ("2020-01-01", "fixed_date"), (d, r))
d, r, _ = eff("§ 2. This act shall take effect on the first day of June 2021.")
check("first day of June 2021", d == "2021-06-01" and r == "fixed_date", (d, r))
d, r, _ = eff("§ 6. This act shall take effect on the first day of January next.", "2020-03-15")
check("first day of January next", (d, r) == ("2021-01-01", "day_of_month_next_succeeding"), (d, r))
d, r, _ = eff("§ 6. This act shall take effect on the first day of January next succeeding the date on which it shall have become a law.")
check("first day of January next succeeding", d == "2021-01-01", d)
d, r, _ = eff("§ 4. This act shall take effect on January first next succeeding the date on which it shall have become a law and shall apply to contracts.")
check("January first next succeeding", d == "2021-01-01", d)
d, r, _ = eff("§ 4. This act shall take effect on the fifteenth of December next succeeding the date on which it shall have become a law.")
check("fifteenth of December", d == "2020-12-15", d)
d, r, _ = eff("§ 2. This act shall take effect on the first of the month next succeeding the date on which it shall have become a law.")
check("first of the month next succeeding", (d, r) == ("2020-04-01", "day_of_month_next_succeeding"), (d, r))
d, r, _ = eff("§ 2. This act shall take effect on the second of January next succeeding the date on which it shall have become a law.")
check("second of January", d == "2021-01-02", d)
d, r, _ = eff("§ 1. This act shall take effect on the first day of January after it becomes a law.")
check("first day of January after it becomes a law", d == "2021-01-01", d)
d, r, _ = eff("§ 3. This act shall take effect on the first of January following the first of September next succeeding the date on which it shall have become a law.")
check("compound date stays unparsed", r == "unparsed" and d is None, (d, r))
d, r, _ = eff("§ 3. This act shall take effect on the first day of the eighteenth month after it shall have become a law.")
check("first day of the eighteenth month", (d, r) == ("2021-09-01", "first_of_nth_month_after_law"), (d, r))
d, r, _ = eff("§ 2. This act shall take effect immediately.")
check("immediately unchanged", r == "immediately", r)

REV = "§ 2. This act shall take effect on the same date as the reversion of subdivision 2 of section 591 of the labor law as provided in section 10 of chapter 413 of the laws of 2003, as amended."
seen = {}


def unresolved(bills=None, chapter=None, year=None):
    seen["call"] = (chapter, year)
    return {"unresolved": True, "bills": [], "chapter": chapter, "year": year, "tried": "no chapter in the API before 2009"}


d, r, e = eff(REV, "2019-06-01", unresolved)
check("reversion unresolved rule", d is None and r == "same_as_reversion_unresolved", (d, r))
check("reversion unresolved keeps reference", e.get("reference", {}).get("chapter") == 413 and e["reference"].get("year") == 2003, e.get("reference"))
check("reversion looked up chapter 413 of 2003", seen.get("call") == (413, 2003), seen)


def known(bills=None, chapter=None, year=None):
    return {"chapter": chapter, "year": year, "signed_date": "2019-01-10", "effective_date": "2019-01-10", "rule": "immediately", "expires_date": "2022-09-01"}


d, r, e = eff(REV, "2019-06-01", known)
check("reversion resolved to the chapter's expiry", (d, r) == ("2022-09-01", "same_as_reversion"), (d, r))
d, r, e = eff(REV, "2019-06-01", None)
check("reversion without resolver stays open", r == "same_as_reversion_unresolved", r)

# E1/E2/E3 (night 20261030)
C1 = "§ 3. This act shall take effect immediately, provided, however, that the amendments to section 500-c of the correction law made by section two of this act shall not affect the repeal of such section and shall be deemed to repeal therewith."
_, _, e = eff(C1)
check("E1 'deemed to repeal therewith' is section-bound", e.get("expires_rule") == "with_referenced_section", e.get("expires_rule"))
_, _, e = eff("§ 2. This act shall take effect immediately and shall be deemed to have been in full force on and after December 21, 2018.", "2019-03-01")
check("E2 retroactive without 'and effect'", e.get("retroactive_to") == "2018-12-21", e.get("retroactive_to"))
_, _, e = eff("§ 2. This act shall take effect immediately; provided that the amendments to section 4 of chapter 434 of the laws of 2022 made by section one of this act shall not affect the repeal of such chapter and shall be deemed repealed therewith.")
check("E3 'such chapter' is section-bound", e.get("expires_rule") == "with_referenced_section", e.get("expires_rule"))
_, _, e = eff("§ 5. This act shall take effect immediately, provided that: (a) the amendments to item (d) of section 11-0907 of the environmental conservation law, made by section one of this act, shall not affect the expiration and repeal of the amendments thereto, made by chapter 141 of the laws of 2014, and shall expire and be deemed repealed therewith, when upon such date section two of this act shall take effect.")
check("E3 'amendments thereto' is section-bound", e.get("expires_rule") == "with_referenced_section", e.get("expires_rule"))
_, _, e = eff("§ 2. This act shall take effect immediately; the amendments to section 1680 of the public authorities law shall not affect the expiration and repeal of such undesignated paragraphs pursuant to section 5 of chapter 371 of the laws of 1998, as amended, and shall expire and be deemed repealed therewith.")
check("E3 'such undesignated paragraphs' is section-bound", e.get("expires_rule") == "with_referenced_section", e.get("expires_rule"))

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
