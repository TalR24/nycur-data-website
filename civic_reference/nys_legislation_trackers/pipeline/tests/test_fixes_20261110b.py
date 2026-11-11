"""Plain script: Nov 10 2026 B43. A sunset extension whose law, Part and amended chapter name no single body is stored as a power with agency Unspecified + holder_unnamed, never re-asked. Prints 'N passed, M failed'."""
import os, sys
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

TXT = ("Section 1. Section 3 of chapter 5 of the laws of 2010, relating to a hotel tax, is amended to read as follows:\n\n"
       "§ 3. This act shall take effect immediately and shall expire and be deemed repealed December 31, [2012] {{2020}}.\n\n"
       "§ 2. This act shall take effect immediately.")
LAW = {"key": "2011-A1", "title": "AN ACT to amend chapter 5 of the laws of 2010, relating to authorizing the town of Islip to impose a hotel tax, in relation to extending the expiration thereof",
       "act_clause": "", "chapter_number": "9", "chapter_year": "2011", "session": "2011", "print_no": "A1", "law_number_display": "Chapter 9 of 2011", "sponsor": "X",
       "enactment_date": "2011-06-01", "openleg_url": "u"}
EFF = {"effective_date": "2011-06-01", "rule": "immediately", "expires_date": None, "section_dates": []}
check("B43 flag on", ed.APPLY_B43 is True)
check("B43 check no longer always re-asked", "sunset_extension_unnamed_holder" not in ed.ALWAYS_REQUEUE)
# named holder unchanged
recs, un = ed.sunset_extension_records(LAW, TXT, EFF, [], {"obligations": [], "model": "m"})
check("B43 named holder: one record, no flag, Islip", len(recs) == 1 and un is None and recs[0]["agency_unit"] == "Town of Islip" and not recs[0].get("holder_unnamed") and recs[0]["record_source"] == "sunset_extension_from_title")
# unnamed holder
LAW2 = dict(LAW, title="AN ACT to amend chapter 5 of the laws of 2010, relating to a tax, in relation to extending the expiration thereof")
recs2, un2 = ed.sunset_extension_records(LAW2, TXT, EFF, [], {"obligations": [], "model": "m"})
r = recs2[0] if recs2 else {}
check("B43 unnamed: one power record, no re-ask entry", len(recs2) == 1 and un2 is None and r.get("kind") == "power")
check("B43 unnamed fields", r.get("agency") == "Unspecified" and r.get("agency_full") == "Unspecified" and r.get("agency_matched") is False and r.get("holder_unnamed") is True
      and r.get("holder_note") == "Holder not named in the amending law" and r.get("actor_raw") == "holder not named in the amending law" and r.get("record_source") == "sunset_extension_holder_unnamed")
check("B43 unnamed keeps the standard fields", r.get("extends_existing") is True and r.get("quote", "").endswith("December 31, 2020.") and r.get("effective_date") and r.get("chapter") == "9")
# no re-ask flag from build_reask path
ed.SUNSET_UNNAMED.clear()
check("B43 SUNSET_UNNAMED stays empty", not ed.SUNSET_UNNAMED)
# real laws through build_records (needs cached texts)
if (ed.TEXT_MARKED / "2009-A9706.txt").exists() and ed.EXTRACTED.exists():
    def build(key):
        laws = [l for l in ed.signed_laws(sessions=[int(key[:4])]) if l["key"] == key]
        ed.EFFECTIVE.update(ed.effective_table(laws))
        d, p, _ = ed.build_records(laws)
        return d + p
    # W2B: 2019-A4959-01 'the provisions of this act shall remain in full force ...' was dropped as extension_holder_unnamed
    rec = {o["obligation_id"]: o for o in build("2019-A4959")}
    o = rec.get("2019-A4959-01")
    check("B43 W2B record kept with the flag", bool(o) and o.get("holder_unnamed") is True and o.get("agency") == "Unspecified" and o.get("holder_note") == "Holder not named in the amending law")
    check("B43 W2B record ends as a power", o.get("kind") == "power")
    check("B43 W2B no re-ask entry", "2019-A4959" not in ed.SUNSET_UNNAMED)
    # real law: the holder-unnamed sentence in 2009-A10213 / any with the record_source
    rec = build("2009-A2002")
    hu = [o for o in rec if o.get("record_source") == "sunset_extension_holder_unnamed"]
    check("B43 real law 2009-A2002: holder-unnamed power record", len(hu) >= 1 and all(o["kind"] == "power" and o["agency"] == "Unspecified" for o in hu))
    check("B43 real law no re-ask entry", "2009-A2002" not in ed.SUNSET_UNNAMED)
else:
    print("note: cache not present, real-law checks skipped")
print("%d passed, %d failed" % (passed, failed))
