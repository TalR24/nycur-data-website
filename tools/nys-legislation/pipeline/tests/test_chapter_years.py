"""Nov 12 2026: chapters signed in January or February that continue the previous year's numbering keep that year."""
import json, os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import fetch_bills as fb
passed = failed = 0
def check(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1; print("FAIL", name)
laws = [{"session": 2019, "print_no": "S6265", "chapter_number": 758, "chapter_year": 2020, "signed_date": "2020-02-07", "law_number_display": "Chapter 758 of 2020"},
        {"session": 2019, "print_no": "S1", "chapter_number": 22, "chapter_year": 2020, "signed_date": "2020-02-20", "law_number_display": "Chapter 22 of 2020"},
        {"session": 2019, "print_no": "S2", "chapter_number": 600, "chapter_year": 2020, "signed_date": "2020-07-01", "law_number_display": "Chapter 600 of 2020"},
        {"session": 2021, "print_no": "A1", "chapter_number": 700, "chapter_year": 2021, "signed_date": "2021-01-10", "law_number_display": "Chapter 700 of 2021"}]
cols = ["base_print_no", "signed", "chapter_year"]; rows = [["S6265", True, 2020], ["S1", True, 2020]]
ch = fb.fix_carry_over_years(laws, rows, cols)
check("carry-over relabelled", laws[0]["chapter_year"] == 2019 and laws[0]["law_number_display"] == "Chapter 758 of 2019")
check("new-year chapter kept", laws[1]["chapter_year"] == 2020)
check("summer chapter kept", laws[2]["chapter_year"] == 2020)
check("never before the session's first year", laws[3]["chapter_year"] == 2021)
check("index row relabelled", rows[0][2] == 2019 and rows[1][2] == 2020)
check("returns changed keys", ch == ["2019-S6265"])
check("idempotent", fb.fix_carry_over_years(laws) == [])
d = HERE.parent / "data" / "signed"
if d.is_dir():
    import collections
    by = collections.defaultdict(list)
    for f in d.glob("*.json"):
        for l in json.load(open(f)): by[int(l["chapter_year"])].append(int(l["chapter_number"]))
    check("no duplicate chapter number in any year", all(len(c) == len(set(c)) for c in by.values()))
print("%d passed, %d failed" % (passed, failed))
