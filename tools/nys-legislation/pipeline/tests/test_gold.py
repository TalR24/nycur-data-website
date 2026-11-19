"""Plain script: gold regression set builder and scorer. Prints 'N passed, M failed'."""
import glob
import json
import os
import sys
import tempfile
from pathlib import Path

T = Path(os.path.abspath(__file__)).parent.parent.parent
Q = T / "quality"
sys.path.insert(0, str(Q))
import build_gold
import score_gold
from gold_lib import agency_code, agency_equal, is_act_clause, is_sunset_extension, quotes_match, wilson

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

tmp = tempfile.mkdtemp()
out = os.path.join(tmp, "gold.json")
g = build_gold.main(["--out", out])
check("gold file written", os.path.exists(out))

audited = set()
for f in glob.glob(str(Q / "nightly" / "*_[AB].json")):
    d = json.load(open(f))
    if "stored" in d and "auditor" in d:
        audited |= {k[:k.rindex("-")] for k in d["stored"]}
        audited |= {m["law"] for m in d["missed"] if m.get("law")}
    else:
        audited |= {k for k, v in d.items() if not k.startswith("_") and isinstance(v, dict)}
check("law count = audited minus exclusions", len(g["laws"]) == len(audited) - len(g["excluded_laws"]) and len(g["laws"]) > 100)

item = next((i for l in g["laws"].values() for i in l["items"] if i["gold_id"] == "2011-A7511-01"), None)
check("2011-A7511-01 present", item is not None)
check("2011-A7511-01 real", item and item["status"] == "real" and not item["disputed"] and not item.get("excluded"))
check("2011-A7511-01 no corrections", item and "other_fields" not in item and "verdicts_seen" not in item)
check("reviewed_as_if override excluded", any(i["gold_id"] == "2015-A5521-02" and i.get("excluded") for l in g["laws"].values() for i in l["items"]))
check("commission items excluded", all(i.get("excluded") for l in g["laws"].values() for i in l["items"] if "legislative bill drafting commission" in (i["quote"] or "").lower()))

check("matcher: containment", quotes_match("The commissioner shall adopt rules", "the commissioner shall adopt rules by January 1, 2015"))
check("matcher: jaccard", quotes_match("a b c d e f", "a b c d e g h"))
check("matcher: unrelated", not quotes_match("the board shall report annually", "licensee may sell stock"))
check("wilson bounds", wilson(5, 10)[0] < 0.5 < wilson(5, 10)[1])

res = score_gold.main(["--gold", out, "--json", os.path.join(tmp, "score.json")])
check("scorer ran", res["gold_laws"] == len(g["laws"]) and res["stored_records_in_gold_laws"] > 0)
check("rates sane", 0 <= res["precision_strict"]["rate"] <= res["precision_real"]["rate"] <= 1)

for exp, st in (("Education Department", "SED"),
                ("Department of Parks and Recreation (NYC, via Council crosswalk)", "DPR"),
                ("public bodies, State and local (not Municipalities (all))", "State and local bodies"),
                ("Retirement Board of the New York State Teachers' Retirement System", "Teachers' Retirement System Board"),
                ("Office of the State Comptroller", "OSC")):
    check("agency normalises: " + exp[:30], agency_equal(st, exp))
check("agency mismatch detected", not agency_equal("DOH", "Education Department"))
check("act clause detected", is_act_clause("This act shall take effect immediately.") and not is_act_clause("The board shall adopt rules"))

# excluded items absorb matching records; new detail lists present
gold_x = {"built_at": "t", "laws": {"2099-A1": {"items": [
    {"gold_id": "2099-A1-01", "source": {"obligation_id": "x"}, "quote": "the board shall report annually to the governor", "status": "real", "disputed": False,
     "expected_fields": {"agency": "Education Department"}},
    {"gold_id": "2099-A1-02", "source": {"obligation_id": "y"}, "quote": "If accepted the application shall be reviewed as if received earlier", "status": "not_real",
     "disputed": False, "excluded": True, "expected_fields": {}}]}}}
dd = os.path.join(tmp, "dd")
os.makedirs(dd + "/duties"); os.makedirs(dd + "/powers")
base = {"matter_id": "2099-A1", "actor_raw": "a", "agency": "SED", "kind": "duty"}
json.dump({"obligations": [
    dict(base, obligation_id="2099-A1-91", quote="The board shall report annually to the governor."),
    dict(base, obligation_id="2099-A1-92", quote="If accepted, the application shall be reviewed as if received earlier."),
    dict(base, obligation_id="2099-A1-93", quote="Something entirely different about licences."),
    dict(base, obligation_id="2099-A1-94", quote="This act shall take effect immediately.")]}, open(dd + "/duties/2099.json", "w"))
json.dump({"powers": []}, open(dd + "/powers/2099.json", "w"))
rx = score_gold.score(gold_x, dd)
check("excluded absorbs record", rx["records_ignored_disputed_or_excluded"] == 1 and rx["stored_records_in_gold_laws"] == 2)
check("act clause counted apart", rx["act_clause_records"] == 1)
check("new detail lists", all(k in rx for k in ("unmatched_stored", "field_mismatches", "unmatched_real_items")) and len(rx["unmatched_stored"]) == 1)
check("agency match via normalisation", rx["field_accuracy"]["agency"]["k"] == 1 and rx["field_mismatches"] == [])

# Nov 1 2026: NYC labels resolve through the Council crosswalk
check("NYC label equals its Council code", agency_equal("DOF", "Department of Finance of New York City"))
check("NYC code never equals a different group", not agency_equal("HPD", "Cities"))

# Nov 1 2026 (B19): siblings sharing a quote each match their own gold item
dq = tempfile.mkdtemp(); os.makedirs(dq + "/duties"); os.makedirs(dq + "/powers")
SQ = "The commissioner and the board shall jointly adopt rules governing licences."
json.dump({"obligations": [
    {"matter_id": "2098-A1", "obligation_id": "2098-A1-01", "actor_raw": "a", "agency": "DOL", "kind": "duty", "quote": SQ},
    {"matter_id": "2098-A1", "obligation_id": "2098-A1-02", "actor_raw": "b", "agency": "SED", "kind": "duty", "quote": SQ}]}, open(dq + "/duties/2098.json", "w"))
json.dump({"powers": []}, open(dq + "/powers/2098.json", "w"))
def gi(gid, ag):
    return {"gold_id": gid, "source": {"obligation_id": "zz"}, "quote": SQ, "status": "real", "disputed": False, "classes": [], "expected_fields": {"agency": ag, "kind": "duty"}}
gq = {"built_at": "t", "laws": {"2098-A1": {"items": [gi("g1", "SED"), gi("g2", "DOL")]}}}
rq = score_gold.score(gq, dq)
check("siblings match own gold item", rq["field_accuracy"]["agency"]["k"] == 2 and rq["field_mismatches"] == [])
check("aliases resolve", agency_equal("Loft", "Loft Board of New York City") and agency_equal("Loft Board", "Loft Board of New York City") and agency_equal("DHSES", "State Office of Emergency Management"))

# Nov 12 2026: act-clause sunset extensions are scored, the law's own effective-date boilerplate is still skipped
AQ = "This act shall take effect immediately and shall expire and be deemed repealed June 30, 2015."
check("sunset ext: record_source", is_sunset_extension({"record_source": "sunset_extension_from_title", "quote": AQ}))
check("sunset ext: holder_unnamed", is_sunset_extension({"holder_unnamed": True, "quote": AQ}))
check("sunset ext: extends_existing with expiry date", is_sunset_extension({"extends_existing": True, "quote": AQ}))
check("boilerplate stays skipped", not is_sunset_extension({"extends_existing": False, "quote": "This act shall take effect immediately."})
      and not is_sunset_extension({"extends_existing": True, "quote": "This act shall take effect on the ninetieth day after it shall have become a law."}))
ds = tempfile.mkdtemp(); os.makedirs(ds + "/duties"); os.makedirs(ds + "/powers")
json.dump({"obligations": []}, open(ds + "/duties/2097.json", "w"))
json.dump({"powers": [
    {"matter_id": "2097-A1", "obligation_id": "2097-A1-01", "actor_raw": "a", "agency": "Unspecified", "kind": "power", "quote": AQ, "record_source": "sunset_extension_holder_unnamed", "holder_unnamed": True, "extends_existing": True},
    {"matter_id": "2097-A1", "obligation_id": "2097-A1-02", "actor_raw": "a", "agency": "Unspecified", "kind": "power", "quote": "This act shall take effect immediately."}]}, open(ds + "/powers/2097.json", "w"))
gs = {"built_at": "t", "laws": {"2097-A1": {"items": [{"gold_id": "s1", "source": {"obligation_id": "q"}, "quote": AQ, "status": "real", "disputed": False, "expected_fields": {}}]}}}
rs = score_gold.score(gs, ds)
check("sunset extension scored and matched", rs["act_clause_records"] == 1 and rs["stored_records_in_gold_laws"] == 1 and rs["recall"]["k"] == 1)

# Nov 12 2026: gold items for one provision (same quote, same agency, same kind) collapse to the best-sourced one
def gd(gid, night, ag, quote="The commissioner shall adopt rules governing licences within ninety days.", exp=True, kind="duty", status="real"):
    it = {"gold_id": gid, "kind": kind, "status": status, "source": {"night": night, "auditor": "A" if night != "bulk_verification" else night, "obligation_id": gid}, "quote": quote, "disputed": False,
          "expected_fields": {"agency": ag, "kind": kind} if exp else {}}
    if not exp:
        it["agency_hint"] = ag
    return it
kept, mg = build_gold.dedupe_items([gd("L-01", "bulk_verification", "DOH", exp=False), gd("L-02", "20261019", "DOH"), gd("L-03", "20261105", "DOH"),
                                    gd("L-04", "20261105", "SED"), gd("L-05", "20261105", "DOH", kind="power"), gd("L-06", "20261105", "DOH", quote="Something else entirely about fees.")])
ids = {i["gold_id"] for i in kept}
check("dedupe keeps newest audit item", "L-03" in ids and "L-02" not in ids and "L-01" not in ids)
check("dedupe keeps other agency, kind and quote", {"L-04", "L-05", "L-06"} <= ids and len(kept) == 4)
check("dedupe records merged ids", sorted(next(i for i in kept if i["gold_id"] == "L-03")["merged_duplicates"]) == ["L-01", "L-02"] and len(mg) == 2)
check("dedupe leaves excluded items", len(build_gold.dedupe_items([gd("E-1", "20261019", "DOH"), dict(gd("E-2", "20261019", "DOH"), excluded="x")])[0]) == 2)
check("built gold has no same-provision pairs", all(not build_gold.same_provision(a_, b_) for l_ in g["laws"].values()
      for n_, a_ in enumerate([i for i in l_["items"] if not i.get("excluded") and not i["disputed"]]) for b_ in [i for i in l_["items"] if not i.get("excluded") and not i["disputed"]][n_ + 1:]))
check("build counts merged duplicates", g["counts"]["duplicates_merged"] > 0)

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
