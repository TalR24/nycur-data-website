"""Nov 12 2026 rulings (Tal, criterion 4): B52 a cap on what an official or body may do is a power with extends_existing true (bond and
issuance caps stay duties); B58 in a list whose lead mixes powers and duties each item takes its own modal, a modal-less item takes the
modal of the clause that ends at the colon (AG14 walk-back over ';' sibling items included)."""
import sys, json, os, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
if not (HERE / "cache" / "text_marked").is_dir() or not (HERE / "cache" / "extracted").is_dir():
    print("0 passed, 0 failed (skipped: cache/text_marked or cache/extracted is not present here)"); sys.exit(0)
import extract_duties as ed
passed = failed = 0
def check(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1; print("FAIL", name)

# ---- B52 unit
check("B52 flag on", ed.APPLY_B52 is True)
check("per-holder quota is a cap", ed.b52_cap("Nominations are limited to ten per elected official per term."))
check("cost recovery ceiling is a cap", ed.b52_cap("Exclusive of fines and penalties, the state shall only recover its actual cost of administration and enforcement."))
check("bond issuance cutoff is not", not ed.b52_cap("No bonds shall be issued pursuant to this section after July 1, 2030."))
check("bond cap with 'shall not exceed' is not", not ed.b52_cap("The authority shall not issue notes in an aggregate principal amount exceeding ten million dollars."))
check("a plain duty is not", not ed.b52_cap("The commissioner shall report annually to the governor."))
ed.APPLY_B52 = False
check("flag off: nothing is a cap", not ed.b52_cap("Nominations are limited to ten per elected official per term."))
ed.APPLY_B52 = True

def run(keys, **flags):
    saved = {k: getattr(ed, k) for k in flags}
    for k, v in flags.items(): setattr(ed, k, v)
    d = tempfile.mkdtemp()
    for k in keys:
        os.symlink(str(HERE / "cache" / "extracted" / (k + ".json")), d + "/" + k + ".json")
    old = ed.EXTRACTED
    ed.EXTRACTED = Path(d)
    try:
        laws = [l for y in sorted({int(k[:4]) for k in keys}) for l in ed.signed_laws([y]) if l["key"] in keys]
        ed.EFFECTIVE = ed.effective_table(laws)
        du, po, _ = ed.build_records(laws)
        return {o["obligation_id"]: ("duty", o) for o in du} | {o["obligation_id"]: ("power", o) for o in po}, list(ed.DROPPED)
    finally:
        ed.EXTRACTED = old
        for k, v in saved.items(): setattr(ed, k, v)

_ra = HERE / "cache" / "packets" / "2021" / "results_reask" / "2021-A9279.json"          # Nov 14 2026: 2021-A9279 re-asked; its cost-cap sentence checks are skipped
_A9279_REASKED = _ra.exists() and _ra.stat().st_mtime > 1794589200
if all((HERE / "cache" / "extracted" / (k + ".json")).exists() and (HERE / "cache" / "text_marked" / (k + ".txt")).exists() for k in ("2023-A4822", "2021-A9279", "2009-A3661")):
    recs, dropped = run(["2023-A4822", "2021-A9279"], APPLY_B52=True)
    four = [recs.get("2023-A4822-0%d" % i) for i in range(1, 5)]
    check("A4822 four records kept", all(four))
    check("A4822 all powers, extends_existing", all(r and r[0] == "power" and r[1]["extends_existing"] is True for r in four))
    check("A4822 none dropped", not [d for d in dropped if d["matter_id"] == "2023-A4822"])
    check("A4822 holders are the nominators", {r[1]["actor_raw"] for r in four if r} == {"assembly members", "senators", "the governor", "the lieutenant governor"})
    cost = [r for r in recs.values() if "actual cost of administration" in r[1]["quote"]]
    check("A9279 cost-recovery cap is a power, extends_existing", _A9279_REASKED or len(cost) == 1 and cost[0][0] == "power" and cost[0][1]["extends_existing"] is True)
    recs0, dropped0 = run(["2023-A4822", "2021-A9279"], APPLY_B52=False)
    check("A4822 flag off: the old split (two dropped)", len([d for d in dropped0 if d["rule"] == "designation_no_actor"]) >= 1 or any(recs0.get("2023-A4822-0%d" % i, ("",))[0] == "duty" for i in range(1, 5)))
    check("A9279 cost cap flag off is a duty", _A9279_REASKED or any(r[0] == "duty" for r in recs0.values() if "actual cost of administration" in r[1]["quote"]))

    # ---- B58
    recs, _ = run(["2009-A3661"], APPLY_B58=True)
    grants = [r for r in recs.values() if r[1]["quote"].startswith("Provide grants")]
    check("A3661 'Provide grants' under 'The commissioner shall:' is a duty", len(grants) == 1 and grants[0][0] == "duty")
    recs0, _ = run(["2009-A3661"], APPLY_B58=False)
    grants0 = [r for r in recs0.values() if r[1]["quote"].startswith("Provide grants")]
    check("A3661 flag off keeps the old power", len(grants0) == 1 and grants0[0][0] == "power")

# ---- B58 unit
check("B58 flag off after the Nov 12 blind judge (16/32)", ed.APPLY_B58 is False)
mixed = "The board shall adopt rules and, where appropriate, may also impose the following:"
check("mixed lead, item with its own may is a power", ed.item_lead_kind("The board shall adopt rules and may also:", "may waive the fee") == "power")
check("mixed lead, item with its own shall is a duty", ed.item_lead_kind("The board may adopt rules and shall also:", "the board shall file a report") == "duty")
check("mixed lead, no modal takes the last clause (may)", ed.item_lead_kind("The board shall adopt rules and may also:", "Waive the fee") == "power")
check("mixed lead, no modal takes the last clause (shall)", ed.item_lead_kind("The board may adopt rules and shall also:", "File a report") == "duty")
check("single-modal lead is unchanged", ed.item_lead_kind("The commissioner shall:", "Provide grants") == "duty" and ed.item_lead_kind("The board may:", "Waive the fee") == "power")
check("relative 'shall' is not the item's own modal", ed.item_lead_kind("The board shall adopt rules and may also:", "Review the plans which shall be filed") == ed.lead_kind("The board shall adopt rules and may also:", "Review the plans which shall be filed"))
ed.APPLY_B58 = False
check("flag off: lead kind only", ed.item_lead_kind("The board may adopt rules and shall also:", "the board shall file a report") == "duty" and ed.item_lead_kind("The board shall adopt rules and may also:", "File a report") == "power")
ed.APPLY_B58 = True
txt = "§ 14. {{The commissioner shall:}}\n\n1. {{Provide direction, which may include model policies;}}\n\n2. {{Provide grants to districts; And}}\n\n"
sp = (txt.index("Provide grants"), txt.index("Provide grants") + 20)
check("walk-back finds 'The commissioner shall:' over a ';' sibling", "commissioner shall:" in (ed.list_lead_in(sp, txt) or ""))
ed.APPLY_B58 = False
check("flag off: the ';' sibling is the lead", "commissioner shall:" not in (ed.list_lead_in(sp, txt) or ""))
ed.APPLY_B58 = True

print("%d passed, %d failed" % (passed, failed))
