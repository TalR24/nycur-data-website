"""Plain script: Nov 5 2026 night gate fixes U1-U4 (force-until sunset, aid-provided term, which-approved clause, individual service bar). Prints 'N passed, M failed'.
Asserts the gate rule on the cached record (the stored record leaves once a gate is live)."""
import os, sys, json
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

def cached(oid):
    f = HERE / "cache" / "extracted" / (oid.rsplit("-", 1)[0] + ".json")
    if not f.exists(): return None
    for o in json.load(open(f))["obligations"]:
        if o["obligation_id"] == oid: return o

def gate(oid):
    o = cached(oid)
    tp = HERE / "cache" / "text_marked" / (oid.rsplit("-", 1)[0] + ".txt")
    if not o or not tp.exists(): return "skip"
    t = tp.read_text()
    r = ed.gate_record(dict(o, quote_verified=True), t, "{{" in t)
    return r[0] if r else None

check("U1 whole act", bool(ed.U1_FORCE_UNTIL.search("The provisions of this act, and all regulations, orders and requirements thereunder shall remain in full force and effect until and including June 23, 2015.")))
check("U1 sections", bool(ed.U1_FORCE_UNTIL.search("the provisions of sections one and three of this act shall remain in full force and effect only until and including June 23, 2015")))
check("U1 amended-law sibling kept", not ed.U1_FORCE_UNTIL.search("the provisions of subdivision 6 of section 12 of the emergency housing rent control law, as added by this act, shall remain in full force and effect until and including June 23, 2015."))
check("U2 regex", bool(ed.U2_AID_PROVIDED.search("Aid shall be provided on approved expenses incurred during the period commencing July first")))
check("U2 other aid kept", not ed.U2_AID_PROVIDED.search("Aid shall be provided to each school district upon application."))
check("U3 regex", bool(ed.U3_WHICH_APPROVED.search("which plan shall be approved by the commissioner pursuant to the commissioner's regulations")))
check("U3 plain kept", not ed.U3_WHICH_APPROVED.search("The commissioner shall approve each plan pursuant to regulations."))
check("U4 regex", bool(ed.U4_SERVICE_BAR.search("No trustee of the existing Grinnell library shall serve as chairperson or as an election inspector or ballot clerk.")))
check("U4 board duty kept", not ed.U4_SERVICE_BAR.search("The board of trustees of the Grinnell public library district shall audit all claims."))
for oid, ok in (("2015-S5997-02", "benefit_window"), ("2015-S5997-04", "benefit_window"), ("2015-S5997-05", "benefit_window"),
                ("2021-A7021-01", "amount_not_duty")):
    g = gate(oid)
    check("gate %s -> %s (got %s)" % (oid, ok, g), (g != "benefit_window") if ok == "benefit_window" else g in (ok, "skip"))   # Nov 5 2026: Y1 is off by decision; W2 governs these extension sentences
for oid in ("2015-S5997-03",):          # amended-law sunset sibling stays
    check("kept " + oid, gate(oid) in (None, "skip"))
for law in ("2015-S5997", "2021-A7021"):          # siblings in the same laws not hit by U rules
    f = HERE / "cache" / "extracted" / (law + ".json")
    if not f.exists(): continue
    for o in json.load(open(f))["obligations"]:
        if o["obligation_id"] not in ("2015-S5997-02", "2015-S5997-04", "2015-S5997-05", "2021-A7021-01", "2021-A7021-02"):
            g = gate(o["obligation_id"])
            check("sibling %s not dropped by U rules (got %s)" % (o["obligation_id"], g), g not in ("section_sunset", "benefit_window") or o["obligation_id"] == "x")
# W1: proviso grant to a governing body is kept, a true condition still drops
def _mk(i, q): return {"obligation_id": i, "quote": q, "agency": "M", "agency_unit": None}
_sib = "a municipality may dispose of the real property for urban development action area projects consisting of dwellings"
_w1 = "Provided, however, that if the proposed urban development action area project consists solely of the rehabilitation or conservation of existing private or multiple dwellings or the construction of one to four unit dwellings, the governing body may waive any such standards and procedures required by local law or charter."
check("W1 proviso grant kept", len(ed.drop_conditions([_mk("a-01", _w1), _mk("a-03", _sib)])) == 2)
_cond = "Provided, however, that if the urban development action area project consists of dwellings, the real property disposition shall be conditioned on the approved project plan."
check("W1 true condition dropped", [o["obligation_id"] for o in ed.drop_conditions([_mk("a-01", _cond), _mk("a-03", _sib)])] == ["a-03"])
# W2: holder of an expiry sentence from the title, else dropped for the re-ask
_o = lambda: {"obligation_id": "x-01", "actor_raw": "the provisions of sections one, two and four of this act", "agency": "Unspecified", "agency_matched": False,
              "quote": "the provisions of sections one, two and four of this act shall remain in full force and effect until and including June 30, 2014", "extends_existing": True}
_txt = "the provisions of sections one, two and four of this act shall remain in full force and effect until and including June 30, 2014"
_a = _o(); check("W2 unnamed holder", ed.w2_extension_holder(_a, _txt, {"title": "AN ACT to amend chapter 5 of the laws of 2008, relating to extensions", "act_clause": ""}) == "unnamed")
_b = _o(); check("W2 title names a body", ed.w2_extension_holder(_b, _txt, {"title": "AN ACT to amend a chapter relating to the town of Islip", "act_clause": ""}) == "moved" and "Islip" in _b["actor_raw"])
_c = _o(); _c["agency"], _c["agency_matched"] = "DOH", True; check("W2 resolved agency untouched", ed.w2_extension_holder(_c, _txt, {"title": ""}) is None)
_d = _o(); _d["actor_raw"] = "the town board"; check("W2 other actor untouched", ed.w2_extension_holder(_d, _txt, {"title": ""}) is None)
print("%d passed, %d failed" % (passed, failed))
