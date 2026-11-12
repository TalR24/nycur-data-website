"""Nov 12 2026 B50: U1 reads sunset extensions inside amended earlier-chapter sections (header naming a subdivision, paragraph or Part;
body 'This {{act}} ...'); the law's own final act clause and a shortened sunset never make a record."""
import sys, json
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
if not (HERE / "cache" / "text_marked").is_dir():
    print("0 passed, 0 failed (skipped: cache/text_marked is not present here)"); sys.exit(0)
import extract_duties as ed
passed = failed = 0
def check(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1; print("FAIL", name)

def real_law(key):
    p = HERE / "cache" / "text_marked" / (key + ".txt")
    sp = HERE.parent / "data" / "signed" / (key[:4] + ".json")
    if not (p.exists() and sp.exists()):
        return None, None
    law = next((l for l in json.load(open(sp)) if l["key"] == key), None)
    return law, p.read_text()

def build(key):
    law, text = real_law(key)
    if law is None:
        return None
    ed.EFFECTIVE.update(ed.effective_table([law]))
    recs, _ = ed.sunset_extension_records(law, text, ed.EFFECTIVE[key], [], {"obligations": [], "model": "t"})
    return recs

def one(recs, frag):
    return [r for r in recs if frag in r["quote"]]

ed.APPLY_B50 = True
for key, frag in (("2009-A157", "June 30, 2010"), ("2009-A156", "September 1, 2011"), ("2011-S2808", "June 30, 2012")):
    recs = build(key)
    if recs is None:
        print("skip", key, "(no cached text)"); continue
    hit = one(recs, frag)
    check(key + " record built", bool(hit))
    check(key + " is a power", bool(hit) and hit[0]["kind"] == "power" and hit[0]["provision_kind"] == "power")
    check(key + " extends_existing", bool(hit) and hit[0]["extends_existing"] is True)

HEAD = "Section 1. %s of chapter 12 of the laws of 1990, relating to the town of Islip, as amended by chapter 5 of the laws of 2015, is amended to read as follows:\n\n"
def sents(head, body, tail="\n\n§ 2. This act shall take effect immediately."):
    return ed.sunset_extension_sentences_pos(head + body + tail)

# new header forms and the '{{act}}' body
old = sents(HEAD % "Section 4", "§ 4. This act shall take effect immediately and shall expire and be deemed repealed June 30, [2020] {{2022}}.")
check("old header form still read", len(old) == 1)
sub = sents(HEAD % "Subdivision (c) of section 4", "(c) This act shall take effect immediately and shall expire and be deemed repealed June 30, [2020] {{2022}}.")
check("subdivision (c) of section header read", len(sub) == 1 and sub[0][1].endswith("§ 4"))
part = sents("Section 1. Section 2 of part O of chapter 56 of the laws of 2015, amending the labor law, is amended to read as follows:\n\n", "§ 2. This {{act}} shall take effect immediately and shall remain in full force and effect only until September 1, [2012] {{2014}}.")
check("part-of-chapter header and '{{act}}' body read", len(part) == 1 and part[0][1] == "Chapter 56 of the Laws of 2015, § 2")
ed.APPLY_B50 = False
check("flag off keeps the old header only", len(sents(HEAD % "Subdivision (c) of section 4", "(c) This act shall take effect immediately and shall expire and be deemed repealed June 30, [2020] {{2022}}.")) == 0)
ed.APPLY_B50 = True

# own-act clause control: the law's final section, no amending header above it
own = ed.sunset_extension_sentences_pos("Section 1. The town board may adopt a local law.\n\n§ 2. This act shall take effect immediately and shall expire and be deemed repealed January 31, [2012] {{2013}}.")
check("own final act clause makes no record", own == [])
own2 = ed.sunset_extension_sentences_pos("Section 1. The town board may adopt a local law.\n\n§ 2. This act shall take effect immediately and shall expire and be deemed repealed January 31, {{2013}}.")
check("own final clause with braces only makes no record", own2 == [])

# shortened sunset control
short = sents(HEAD % "Paragraph d of section 4", "§ 4. This act shall take effect immediately and shall expire and be deemed repealed June 30, [2022] {{2020}}.")
check("shortened sunset makes no record", short == [])
ed.APPLY_B50 = False
check("flag off leaves the old code path (shortened still read)", len(sents(HEAD % "Section 4", "§ 4. This act shall take effect immediately and shall expire and be deemed repealed June 30, [2022] {{2020}}.")) == 1)
ed.APPLY_B50 = True

# AG9 keeps a clause whose swapped date belongs to the repeal part
check("AG9 keeps 'take effect ..., and shall be deemed repealed on June 30, 2010'", not ed.ag9_effective_date_only("This act shall take effect July 1, 1992, and shall be deemed repealed on June 30, 2010."))
eff = sents(HEAD % "Paragraph d of section 4", "§ 4. This act shall take effect on the [ninetieth] {{eightieth}} day after it shall have become a law; provided that section two of this act shall expire and be deemed repealed June 30, 2030.")
check("a swapped effective date with an unmarked expiry makes no record", eff == [])
brace = sents(HEAD % "Section 4", "§ 4. This act shall take effect immediately [and]{{; provided, however that sections one and two of this act}} shall expire and be deemed repealed September 30, 2025.")
check("an expiry clause opened by braced new matter is kept", len(brace) == 1)
print("%d passed, %d failed" % (passed, failed))
