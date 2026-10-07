"""Plain script: python3 tests/test_effective_date.py  ->  'N passed, M failed'. Clauses are copied from the pilot's signed laws."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from effective_date import parse_effective, words_to_int

CASES = [  # (law key, signed date, clause, effective, rule, expires)
 ("2009-A6565", "2009-07-11", "§ 2. This act shall take effect immediately.", "2009-07-11", "immediately", None),
 ("2009-S5536", "2009-10-06", "§ 3. This act shall take effect on the first of November next succeeding the date on which it shall have become a law.", "2009-11-01", "first_of_month_next_succeeding", None),
 ("synthetic Jan", "2010-03-01", "This act shall take effect on the first of January next succeeding the date on which it shall have become a law.", "2011-01-01", "first_of_month_next_succeeding", None),
 ("2011-A8823", "2011-08-01", "§ 193. This act shall take effect on the sixtieth day after it shall have become a law; provided, however, that section one hundred ninetyone of this act shall be deemed to have been in full force and effect on and after January 1, 2002.", "2011-09-30", "nth_day_after_law", None),
 ("2011-S1007", "2012-06-01", "§ 2. This act shall take effect December 1, 2012 and shall apply to sales made or uses occurring on or after such date although made or occurring under a prior contract; provided, that the commissioner of taxation and finance shall be authorized on and after the date this act shall have become a law to adopt and amend any rules or regulations.", "2012-12-01", "fixed_date", None),
 ("2013-A8963", "2013-12-01", "§ 3. This act shall take effect on the one hundred eightieth day after it shall have become a law.", "2014-05-30", "nth_day_after_law", None),
 ("2013-S3912", "2013-11-20", "§ 2. This act shall take effect immediately; provided that the amendments to section 4403-f of the public health law made by section one of this act shall not affect the expiration and repeal of such section, and shall expire and be deemed repealed therewith.", "2013-11-20", "immediately", None),
 ("2015-A6961", "2015-12-01", "§ 2. This act shall take effect on the one hundred eightieth day after it shall have become a law; provided, however, that effective immediately, the commissioner of education is authorized to promulgate any and all rules and regulations and take any other measures necessary to implement this act on its effective date on or before such date.", "2016-05-29", "nth_day_after_law", None),
 ("2015-S2486", "2015-04-01", "§ 3. This act shall take effect immediately; provided that if this act shall not have become a law on or before March 27, 2015, this act shall be deemed to have been in full force and effect on and after March 27, 2015.", "2015-04-01", "immediately", None),
 ("2015-S6381", "2015-10-01", "§ 3. This act shall take effect on the same date and in the same manner as a chapter of the laws of 2015, amending the arts and cultural affairs law relating to establishing the Edward Hopper citation of merit for visual artists, as proposed in legislative bills numbers A.2121-a and S.4235-a, takes effect.", None, "same_as_chapter", None),
 ("2017-A10605", "2018-07-20", "§ 2. This act shall take effect immediately; provided, however, that if this act shall have become law after June 30, 2018, this act shall take effect immediately and shall be retroactive to and deemed to have been in full force and effect on and after June 30, 2018.", "2018-07-20", "immediately", None),
 ("2019-A8096", "2020-01-10", "§ 2. This act shall take effect on the sixtieth day after it shall have become a law.", "2020-03-10", "nth_day_after_law", None),
 ("2019-S3360", "2020-11-02", "§ 4. This act shall take effect on the ninetieth day after it shall have become a law. Effective immediately, the addition, amendment and/or repeal of any rule or regulation necessary for the implementation of this act on its effective date are authorized to be made and completed on or before such effective date.", "2021-01-31", "nth_day_after_law", None),
 ("2019-S7846", "2020-12-01", "§ 4. This act shall take effect on the ninetieth day after it shall have become a law; provided, however, that section three of this act shall take effect immediately.", "2021-03-01", "nth_day_after_law", None),
 ("2021-S7111", "2022-12-10", "§ 5. This act shall take effect on the one hundred eightieth day after it shall have become a law. Effective immediately, the addition, amendment and/or repeal of any rule or regulation necessary for the implementation of this act on its effective date are authorized to be made and completed on or before such effective date.", "2023-06-08", "nth_day_after_law", None),
 ("2021-A8826", "2021-12-01", "§ 3. This act shall take effect immediately; provided, however, that section one of this act shall take effect on the same date and in the same manner as a chapter of the laws of 2021 amending the public health law relating to competency exams offered to qualified home care services workers residing outside this state, as proposed in legislative bills numbers S. 1201-A and A. 4662-A, takes effect.", "2021-12-01", "immediately", None),
 ("2023-A4038", "2024-12-20", "§ 2. This act shall take effect immediately and shall expire and be deemed repealed 3 years after such date.", "2024-12-20", "immediately", "2027-12-20"),
 ("2025-S10544", "2026-05-01", "§ 15. This act shall take effect immediately and shall be deemed to have been in full force and effect on and after April 1, 2026; provided, however, that upon the transfer of expenditures and disbursements by the comptroller as provided in section thirteen of this act, the appropriations made by this act and subject to such section shall be deemed repealed.", "2026-05-01", "immediately", None),
 ("2025-A7385", "2025-12-01", "§ 3. This act shall take effect immediately and shall apply to all contracts entered into, renewed, modified or amended on or after such effective date.", "2025-12-01", "immediately", None),
 ("synthetic 90 days", "2020-02-01", "This act shall take effect ninety days after it shall have become a law.", "2020-05-01", "n_days_after_law", None),
 ("synthetic expire date", "2019-06-01", "This act shall take effect immediately and shall expire December 1, 2019 when upon such date the provisions of this act shall be deemed repealed.", "2019-06-01", "immediately", "2019-12-01"),
]
passed = failed = 0
for key, signed, clause, eff, rule, exp in CASES:
    r = parse_effective(clause, signed)
    ok = r["effective_date"] == eff and r["rule"] == rule and r["expires_date"] == exp
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", key, "->", r["effective_date"], r["rule"], r["expires_date"], "expected", eff, rule, exp)
# multi-date and retroactive detail
r = parse_effective(CASES[13][2], "2020-12-01")
if len(r["other_dates"]) == 1 and r["other_dates"][0]["effective_date"] == "2020-12-01":
    passed += 1
else:
    failed += 1; print("FAIL other_dates", r["other_dates"])
r = parse_effective(CASES[10][2], "2018-07-20")
passed, failed = (passed + 1, failed) if r["retroactive_to"] == "2018-06-30" else (passed, failed + 1)
r = parse_effective(CASES[17][2], "2026-05-01")
passed, failed = (passed + 1, failed) if r["retroactive_to"] == "2026-04-01" else (passed, failed + 1)
for w, n in [("sixtieth", 60), ("one hundred eightieth", 180), ("ninetieth", 90), ("one hundred twentieth", 120), ("thirtieth", 30)]:
    if words_to_int(w) == n:
        passed += 1
    else:
        failed += 1; print("FAIL words", w, words_to_int(w))
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
