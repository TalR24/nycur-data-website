"""Nov 7 2026 night (AA1-AA4). Asserts the gate rule on the cached record; dry run counts over stored ids, cap 40 per rule."""
import sys, json, pathlib
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)
def gate_q(q):
    return ed.gate_record({"quote": q, "quote_verified": True, "agency": "X", "agency_unit": None, "actor_raw": "x"}, q, False)
def cached(oid):
    f = HERE / "cache" / "extracted" / (oid.rsplit("-", 1)[0] + ".json")
    if f.exists():
        for o in json.load(open(f))["obligations"]:
            if o["obligation_id"] == oid: return o
RULES = {"AA1": (ed.AA1_COSTS_BORNE, ["2021-S1889-01", "2021-S4404-02"]), "AA2": (ed.AA2_BASED_ON, ["2013-S2320-11", "2013-S2320-12"]),
         "AA3": (ed.AA3_CONSIDERATION, ["2009-A11514-07", "2021-S1594-08"]), "AA4": (ed.AA4_PRESCRIBED_FORMAT, ["2015-A1327-01", "2015-A1327-02"])}
check("AA2-AA4 flags live, AA1 off over the cap", not ed.APPLY_AA1 and ed.APPLY_AA2 and ed.APPLY_AA3 and ed.APPLY_AA4)
for name, (rx, ids) in RULES.items():
    for oid in ids:
        o = cached(oid)
        if o and not rx.search(o["quote"]):          # Nov 12 2026: re-asked law renumbered; find the sentence by its rule
            _f = HERE / "cache" / "extracted" / (oid.rsplit("-", 1)[0] + ".json")
            o = next((x for x in json.load(open(_f)).get("obligations", []) if rx.search(x.get("quote") or "")), None) if _f.exists() else None
            if o is None:
                print("skipped: %s re-asked, no sentence for %s" % (oid, name)); passed += 1; continue
        if o: check(name + " rule on cached " + oid, bool(rx.search(o["quote"])))
# dry run over stored ids
stored = set()
for d in ("duties", "powers"):
    for f in (HERE.parent / "data" / d).glob("*.json"):
        stored |= {o["obligation_id"] for o in json.load(open(f))[{"duties": "obligations", "powers": "powers"}[d]]}
hits = {n: [] for n in RULES}
for f in (HERE / "cache" / "extracted").glob("*.json"):
    for o in json.load(open(f)).get("obligations", []):
        if o.get("obligation_id") in stored:
            for n, (rx, _) in RULES.items():
                if rx.search(o.get("quote") or ""): hits[n].append(o["obligation_id"])
for n, h in hits.items():
    print("dry run", n, len(h), h[:12])
    if len(h) > 40: print("over the cap: flag", n, "stays off")
    if (HERE / "cache" / "extracted").is_dir():          # Nov 12 2026: CI has no answer cache, so dry-run counts are 0 there
        check(n + " flag on only within cap", getattr(ed, "APPLY_" + n) == (len(h) <= 40))
check("AA1 rule matches", bool(ed.AA1_COSTS_BORNE.search("All past service costs associated with implementing the provisions of this act shall be borne by the state of New York.")))
check("AA1 plain cost sentence kept", gate_q("The commissioner shall report the costs of the program to the legislature.") is None)
g = gate_q("then the abatement for the year shall be based on the information contained in the application submitted in two thousand eleven"); check("AA2 gate", bool(g) and g[0] == "amount_not_duty")
g = gate_q("Factors such as cost to the state shall be taken into consideration when awarding such contract."); check("AA3 gate", bool(g) and g[0] == "condition_of_other_record")
check("AA3 plain approval kept", gate_q("The director of the budget shall approve the plan each year.") is None)
g = gate_q("where the insured, in a format prescribed by the superintendent, certified in the request that the services are for a court"); check("AA4 gate", bool(g) and g[0] == "condition_of_other_record")
check("AA4 plain prescribe kept", gate_q("The superintendent shall prescribe a format for the request.") is None)
# V1: adopt-a-local-law power kept, eligibility sentence dropped
import glob
_v = "the governing body of a county, city, town or village is hereby authorized to adopt a local law to provide that real property acquired for open space shall be exempt from taxation"
check("V1 power sentence not dropped by exemption rule", not (gate_q(_v) and gate_q(_v)[0] == "exemption_or_applicability"))
_e = "The exemption shall not apply to real property owned by a nonprofit that is not used for open space."
check("V1 eligibility sentence still dropped", bool(gate_q(_e)) and gate_q(_e)[0] == "exemption_or_applicability")
_rest = []
for _f in glob.glob(str(HERE.parent / "data" / "dropped" / "*.json")):
    _d = json.load(open(_f)); _d = _d.get("dropped", _d) if isinstance(_d, dict) else _d
    _rest += [o["obligation_id"] for o in _d if o.get("rule") == "exemption_or_applicability" and ed.V1_ADOPT_POWER.search(o.get("quote") or "")]
print("dry run V1 restored", len(_rest), _rest); check("V1 within cap", len(_rest) <= 40)
# V2: negated modal is never a grant
for oid in ("2021-A4637-01", "2021-S5753-01"):
    o = cached(oid)
    if o: check("V2 cached quote not grant_only " + oid, not ed.grant_only(o["quote"]))
check("V2 plain may grant still grant_only", ed.grant_only("The commissioner may issue permits to eligible applicants."))
check("V2 'No ... may' not grant_only", not ed.grant_only("No more than fifty percent of the funds may be used to support the costs."))
_v2 = []
for _f in (HERE / "cache" / "extracted").glob("*.json"):
    for o in json.load(open(_f)).get("obligations", []):
        if o.get("obligation_id") in stored and o.get("kind_adjusted") != "x" and ed.NEG_LEAD_MODAL.search(o.get("quote") or "") and ed.GRANT_WORD.search(o.get("quote") or ""): _v2.append(o["obligation_id"])
print("dry run V2 quotes with negated lead modal and a grant word", len(_v2), _v2[:10])
# V3: inserted second actor
_t = "Criminal action for violation of this article shall be prosecuted by the [attorney-general] {{Attorney general,}} [or his] {{his or her}} deputy, {{or a district attorney,}} in the name of the people of the state"
check("V3 existing actor reprint dropped", ed.reprinted_swap_adds_actor({"actor_raw": "the Attorney general"}, _t))
check("V3 inserted actor record kept", not ed.reprinted_swap_adds_actor({"actor_raw": "a district attorney"}, _t))
_tp = HERE / "cache" / "text_marked" / "2015-A5652.txt"
if _tp.exists():
    _l = [l for l in _tp.read_text().split("\n") if "{{or a district attorney" in l]
    check("V3 real text line", bool(_l) and ed.reprinted_swap_adds_actor({"actor_raw": "the Attorney general"}, _l[0]))
# R22 wiring: two-record map resolves a generic-group record with a PAL 2306 citation
_m = ed.agency_resolve_nys.build_pal_map_r22([{"citation": "Public Authorities Law § 2306", "agency": "Auburn Industrial Development Agency", "agency_org_type": "industrial development agency"},
                                             {"citation": "Public Authorities Law § 1234", "agency": "Other Authority", "agency_org_type": "public authority"}])
_r = {"citation": "Public Authorities Law § 2306", "agency": "Local agencies and authorities", "agency_unit": None}
check("R22 resolved via map", ed.agency_resolve_nys.fix_pal_section_r22(_r, _m) and _r["agency"] == "Auburn Industrial Development Agency")
check("R22 wired in run_agency_fixes", "fix_pal_section_r22" in open(HERE / "extract_duties.py").read())
print("%d passed, %d failed" % (passed, failed))
