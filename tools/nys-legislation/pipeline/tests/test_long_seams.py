"""Plain script: window seam duplicates of long laws (Nov 13 2026, B64). Prints 'N passed, M failed'. No model call."""
import json, os, sys, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import logging
logging.disable(logging.CRITICAL)
import extract_duties as ed

if not (ed.TEXT_MARKED / "2013-S4552.txt").exists():      # CI has no cached texts
    print("0 passed, 0 failed (skipped: texts are not cached here)")
    sys.exit(0)
passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

S1 = "The commissioner shall submit a report to the governor and the legislature on the progress of the program no later than January first, two thousand twenty-six."
S2 = "The department shall establish a hotline for complaints about the program and publish its telephone number on its website."
S3 = "The commissioner shall issue guidance to every school district within ninety days."
TEXT = "Section 1. " + S1 + " Section 2. " + S2 + " Section 3. " + S3 + " Section 4. Nothing here."
def rec(i, q, agency="DOH", **kw):
    r = {"obligation_id": "L-%02d" % i, "matter_id": "L", "quote": q, "agency": agency, "agency_unit": None, "jurisdiction": "state", "actor_raw": "the commissioner",
         "deadline_date": None, "recurrence": None, "quote_verified": True}
    r.update(kw)
    return r

ed.DROPPED.clear()
a, b, c = rec(1, S1), rec(2, S1[:-20], deadline_date="2026-01-01", recurrence="one-time"), rec(3, S2, agency="DOHMH")
lst = [a, b, c]
gone = ed.collapse_window_seams(lst, TEXT, "L")
check("one duplicate collapsed", len(gone) == 1 and len(lst) == 2)
check("keeps the record with deadline and recurrence", b in lst and a not in lst)
check("distinct provision stays", c in lst)
check("dropped file row", [d["rule"] for d in ed.DROPPED] == ["window_seam_duplicate"] and ed.DROPPED[0]["kept_id"] == "L-02" and ed.DROPPED[0]["obligation_id"] == "L-01")

ed.DROPPED.clear()
lst = [rec(1, S1, agency="Unspecified"), rec(2, S1)]
ed.collapse_window_seams(lst, TEXT, "L")
check("resolved agency beats Unspecified", len(lst) == 1 and lst[0]["agency"] == "DOH")

lst = [rec(1, S1, agency="DOH"), rec(2, S1, agency="DOE")]
ed.collapse_window_seams(lst, TEXT, "L")
check("different agencies stay apart", len(lst) == 2)

lst = [rec(1, S1), rec(2, S3)]
ed.collapse_window_seams(lst, TEXT, "L")
check("different spans stay apart", len(lst) == 2)

lst = [rec(1, S1)]
check("single record untouched", ed.collapse_window_seams(lst, TEXT, "L") == [] and len(lst) == 1)

# a sentence that occurs twice in the law is a repeat, not a seam
T2 = TEXT + " " + S3
lst = [rec(1, S3), rec(2, S3)]
ed.collapse_window_seams(lst, T2, "L")
check("repeated sentence is not collapsed", len(lst) == 2)

# an ordinary (single-window) law is unchanged by the flag
k = "2013-S4552"
laws = {l["key"]: l for l in ed.signed_laws()}
ed.EFFECTIVE = ed.effective_table([laws[k]])
ed.EXTRACTED = Path(tempfile.mkdtemp()) / "extracted"
src = ed.HERE / "cache" / "extracted" / (k + ".json")
if src.exists():
    ed.EXTRACTED.mkdir(parents=True)
    res = json.loads(src.read_text()); res["windows"] = 1
    (ed.EXTRACTED / (k + ".json")).write_text(json.dumps(res))
    out = {}
    for flag in (False, True):
        ed.APPLY_LONG_SEAM = flag
        d, p, _ = ed.build_records([laws[k]])
        out[flag] = sorted(o["obligation_id"] for o in d + p)
    check("ordinary law: same records with the flag on or off", out[False] == out[True] and len(out[True]) > 0)
    check("ordinary law: no seam rule fired", not any(x["rule"] == "window_seam_duplicate" for x in ed.DROPPED))
    ed.APPLY_LONG_SEAM = True
else:
    print("skip ordinary-law check: extracted cache absent")
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
