"""Nov 19 2026 night: B69 (conforming-word reprints) and B70 (a bare defined term resolves through the law's own named body).
Each flag is switched on only for the check and restored. Plain script; prints 'N passed, M failed'. Skips when the law caches are absent (CI)."""
import logging, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
if not (HERE / "cache" / "text_marked").is_dir() or not (HERE / "cache" / "extracted").is_dir():
    print("0 passed, 0 failed (skipped: cache/text_marked or cache/extracted is not present here)"); sys.exit(0)
logging.disable(logging.CRITICAL)
import extract_duties as ed
passed = failed = 0
def check(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1; print("FAIL", name)

saved = {f: getattr(ed, f) for f in ("APPLY_B69", "APPLY_B70")}
try:
    for o, n in [("justice", "justices"), ("he", "she"), ("he or she", "they"), ("chairman", "chairperson"), ("section", "subdivision"), ("paragraph (a)", "subdivision (b)"), ("county", "counties")]:
        check("B69 conforming pair %s -> %s" % (o, n), ed.b69_pair_conforming(o, n))
    for o, n in [("employees", "persons"), ("municipal", "international"), ("board", "commission"), ("ten days", "thirty days")]:
        check("B69 real substitution %s -> %s" % (o, n), not ed.b69_pair_conforming(o, n))
    check("B69 bare number swap is not conforming", not ed.b69_conforming_swap("within [six] {{seven}} months the board shall act"))
    check("B69 citation number swap is conforming", ed.b69_conforming_swap("pursuant to section [six] {{seven}} of the law"))
    S = "The [justice] {{justices}} of the court shall hear the matter"
    ed.APPLY_B69 = False
    check("B69 off: a plural swap stays new matter", not ed.af3_trivial_reprint(S))
    ed.APPLY_B69 = True
    check("B69 on: a plural swap is no new matter", ed.af3_trivial_reprint(S))
    check("B69 on: employees to persons stays new matter", not ed.af3_trivial_reprint("The [employees] {{persons}} of the board shall report"))
    check("B69 on: a mixed block (conforming swap plus a new clause) stays new matter", not ed.af3_trivial_reprint("The [justice] {{justices}} shall report {{within ten days}}"))
    check("B70 bare-term regex", all(ed.B70_BARE_TERM.match(t) for t in ("the agency", "The authority", "the corporation", "the board", "the office")) and not ed.B70_BARE_TERM.match("the state agency"))
finally:
    for f, v in saved.items(): setattr(ed, f, v)

_cache = {}
def build(key, flag):
    if (key, flag) not in _cache:
        sess = int(key.split("-")[0])
        laws = [l for l in ed.signed_laws(sessions=[sess]) if l["key"] == key]
        ed.EFFECTIVE.update(ed.effective_table(laws))
        tmp = Path(tempfile.mkdtemp()); (tmp / (key + ".json")).symlink_to(ed.EXTRACTED / (key + ".json"))
        real, old = ed.EXTRACTED, getattr(ed, flag)
        ed.EXTRACTED = tmp; setattr(ed, flag, True)
        try:
            ed.DROPPED.clear(); dd, pp, _ = ed.build_records(laws)
        finally:
            ed.EXTRACTED = real; setattr(ed, flag, old)
        _cache[(key, flag)] = ({o["obligation_id"]: o for o in dd + pp}, list(ed.DROPPED))
    return _cache[(key, flag)]
def have(key): return (ed.EXTRACTED / (key + ".json")).exists()

if have("2013-A9021"):
    r, _d = build("2013-A9021", "APPLY_B70")
    for oid in ("2013-A9021-06", "2013-A9021-08", "2013-A9021-10", "2013-A9021-15"):
        if oid in r:
            check("B70 %s 'the agency' resolves to the Medical Care Facilities Finance Agency" % oid, "Medical Care Facilities Finance Agency" in (r[oid].get("agency") or ""))
    check("B70 2013-A9021 no record still resolves to State agencies", not any(o.get("agency") == "State agencies" and (o.get("actor_raw") or "").strip().lower() == "the agency" for o in r.values()))
if have("2011-S5571"):
    r, d = build("2011-S5571", "APPLY_B69")
    check("B69 2011-S5571 conforming reprints drop as reprinted_gender_neutral", sum(1 for x in d if x["rule"] == "reprinted_gender_neutral") >= 1)
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
