"""Plain test script: prints 'N passed, M failed', exit 1 on failure. Run: python3 tests/test_parse.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fetch_bills import parse_chapter, chamber_from_print_no, map_status, normalize

CASES = [
    (parse_chapter("SIGNED CHAP.151"), 151), (parse_chapter("SIGNED CHAP.1"), 1),
    (parse_chapter("signed chap. 22"), 22), (parse_chapter("SIGNED  CHAP.  409 "), 409),
    (parse_chapter("SIGNED CHAPTER 7"), 7), (parse_chapter("SIGNED CHAP.1234"), 1234),
    (parse_chapter("DELIVERED TO GOVERNOR"), None), (parse_chapter("VETOED MEMO.12"), None),
    (parse_chapter(None), None), (parse_chapter(""), None),
    (chamber_from_print_no("S2508"), "Senate"), (chamber_from_print_no("A3985B"), "Assembly"),
    (chamber_from_print_no("a1"), "Assembly"), (chamber_from_print_no("J100"), None), (chamber_from_print_no(None), None),
    (map_status("SIGNED_BY_GOV"), "signed"), (map_status("IN_ASSEMBLY_COMM"), "in_committee"),
    (map_status("VETOED"), "vetoed"), (map_status("NOT_A_STATUS"), "other"), (map_status(None), "other"),
]
# normalize: chapter year is the action's calendar year, last SIGNED CHAP action wins
rec = normalize({"session": 2019, "basePrintNo": "A3985", "printNo": "A3985", "billType": {"chamber": "ASSEMBLY", "resolution": False},
                 "activeVersion": "", "signed": True, "status": {"statusType": "SIGNED_BY_GOV", "actionDate": "2019-08-08"},
                 "actions": {"items": [{"date": "2019-08-08", "chamber": "ASSEMBLY", "text": "SIGNED CHAP.151"}]},
                 "amendments": {"items": {"": {"sameAs": {"items": [{"printNo": "S2508", "session": 2019}]}}}}})
CASES += [(rec["chapter"], {"number": 151, "year": 2019, "signed_date": "2019-08-08"}), (rec["chamber"], "Assembly"),
          (rec["same_as"], [{"print_no": "S2508", "session": 2019}]), (rec["status"]["stage"], "signed"),
          (rec["openleg_url"], "https://www.nysenate.gov/legislation/bills/2019/A3985")]

passed = sum(1 for got, want in CASES if got == want)
for got, want in CASES:
    if got != want:
        print("FAIL: got %r want %r" % (got, want))
print("%d passed, %d failed" % (passed, len(CASES) - passed))
sys.exit(0 if passed == len(CASES) else 1)
