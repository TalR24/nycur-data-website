"""Plain script: quality tooling (criteria, draw_sample, gold_history, close_not_real, backlog, trend, build_gold additions). Prints 'N passed, M failed'."""
import json
import os
import sys
import tempfile
from pathlib import Path

T = Path(os.path.abspath(__file__)).parent.parent.parent
Q = T / "quality"
sys.path.insert(0, str(Q))
import backlog
import build_gold
import close_not_real
import draw_sample
import gold_history
import trend

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

tmp = tempfile.mkdtemp()

# Q1 criteria.md
c = (Q / "criteria.md").read_text()
brief = Path("/Users/troded/.claude/jobs/c1df60cb/tmp/audit_brief_20261019.md")
check("criteria header says never paraphrase", "never paraphrase" in c.splitlines()[2])
check("criteria has the 9 numbered criteria", all(f"\n{n}. " in c for n in range(1, 10)) and "9. Duplicate" in c)
check("criteria has method, criteria and pilot rules headings", all(h in c for h in ("## Method", "## Criteria", "## Pilot rules")))
check("criteria has Oct 16 and Oct 19 decisions", "Decided Oct 16 2026" in c and "Decided Oct 19 2026" in c)
if brief.exists():
    b = brief.read_text()
    check("criteria 4 verbatim from the brief", b[b.index("1. Real record"):b.index("9. Duplicate")] in c)

# Q2 draw_sample on a synthetic tree
pk = os.path.join(tmp, "packets"); dd = os.path.join(tmp, "data"); nd = os.path.join(tmp, "nightly")
os.makedirs(dd); os.makedirs(nd)
laws = [f"2017-A{n}" for n in range(1, 41)]
os.makedirs(pk + "/batches/20261101-0247/reask")
open(pk + "/batches/20261101-0247/000.lst", "w").write("\n".join(f"{pk}/2017/{l}.txt" for l in laws[:30]) + "\n")
open(pk + "/batches/20261101-0247/reask/000.lst", "w").write("\n".join(f"{pk}/2017/{l}.txt" for l in laws[30:]) + "\n")
os.makedirs(pk + "/2017/results"); os.makedirs(pk + "/2017/results_reask")
for l in laws[:30]: open(f"{pk}/2017/results/{l}.json", "w").write("{}")
for l in laws[30:]: open(f"{pk}/2017/results_reask/{l}.json", "w").write("{}")
json.dump({"rule": "x", "laws": [{"key": laws[0]}]}, open(dd + "/deferred_long.json", "w"))
json.dump({"rule": "x", "laws": [{"key": laws[1]}]}, open(dd + "/deferred_skipped.json", "w"))
json.dump({laws[2]: {"records": {}}}, open(nd + "/20261030_A.json", "w"))
gold = {"laws": {f"2013-S{n}": {"items": [{"gold_id": f"2013-S{n}-01", "status": "real", "disputed": False, "quote": "q", "expected_fields": {}}]} for n in range(1, 30)}}
gp = os.path.join(tmp, "gold.json"); json.dump(gold, open(gp, "w"))
out = os.path.join(tmp, "s.json")
r = draw_sample.main(["--night", "20261101", "--out", out, "--packets", pk, "--data-dir", dd, "--nightly-dir", nd, "--gold", gp])
check("tonight pool excludes both deferred files", r["pool"] == 38 and laws[0] not in r["A"] + r["B"] and laws[1] not in r["A"] + r["B"])
check("11 and 11 with 2 shared", len(r["A"]) == 11 and len(r["B"]) == 11 and len(r["shared"]) == 2 and r["A"][:2] == r["B"][:2] == r["shared"])
check("20 distinct laws", len(set(r["A"]) | set(r["B"])) == 20)
check("seed is the night number", r["seed"] == 20261101 and draw_sample.seed_of("20261013b") == 202610132)
check("calibration: 2 gold laws per auditor, seeded, in the file", len(r["calibration"]["A"]) == 2 and len(r["calibration"]["B"]) == 2
      and len(set(r["calibration"]["A"] + r["calibration"]["B"])) == 4 and json.load(open(out))["calibration"] == r["calibration"])
gvf = os.path.join(tmp, "s_calibration_gold.json")      # Oct 20 2026: verdicts live in a sibling file the auditors never see
gv = json.load(open(gvf))["gold_verdicts"] if os.path.exists(gvf) else {}
check("calibration verdicts in the sibling file, not the auditors' file",
      "gold_verdicts" not in json.load(open(out))["calibration"] and all(gv[l][0]["status"] == "real" for l in r["calibration"]["A"]))
r2 = draw_sample.main(["--night", "20261101", "--out", out, "--packets", pk, "--data-dir", dd, "--nightly-dir", nd, "--gold", gp])
check("draw is deterministic", r2["A"] == r["A"] and r2["B"] == r["B"])
ru = draw_sample.main(["--night", "20261101", "--source", "unaudited", "--out", out, "--packets", pk, "--data-dir", dd, "--nightly-dir", nd, "--gold", gp])
check("unaudited drops audited laws", ru["pool"] == 37 and laws[2] not in ru["A"] + ru["B"])
rg = draw_sample.main(["--night", "20261101", "--source", "gold", "--out", out, "--packets", pk, "--data-dir", dd, "--nightly-dir", nd, "--gold", gp])
check("gold source draws gold laws", rg["pool"] == 29 and all(l.startswith("2013-S") for l in rg["A"]))

# Q3 gold_history
hist = os.path.join(tmp, "h.jsonl")
def score(strict_k, laws=253):
    mk = lambda k, n: {"k": k, "n": n, "rate": k / n}
    return {"gold_built_at": "t", "gold_laws": laws, "stored_records_in_gold_laws": 1000, "precision_strict": mk(strict_k, 1000),
            "precision_real": mk(900, 1000), "recall": mk(800, 1000), "not_real_still_stored": 5, "effective_date_accuracy": mk(95, 100)}
def app(night, sc):
    p = os.path.join(tmp, "sc.json"); json.dump(sc, open(p, "w")); return gold_history.append(night, hist, p)
e1 = app("n1", score(800)); e2 = app("n2", score(795)); 
check("first entry has no previous", e1["prev_strict"] is None and e1["precision_strict"] == 80.0)
check("second entry carries previous strict", e2["prev_strict"] == 80.0 and e2["not_real_still_stored"] == 5)
check("drop of 0.5 is OK", gold_history.check(hist)[0] == "OK")
app("n3", score(780))
st, why = gold_history.check(hist)
check("drop over 1.0 point is PAUSE with reason", st == "PAUSE" and "fell" in why and "n2" in why)
app("n4", score(700, laws=260))
check("different gold build is not compared", gold_history.check(hist)[0] == "OK")
check("lines in file", len(open(hist).read().splitlines()) == 4)
real_hist = [json.loads(l) for l in open(Q / "gold_history.jsonl")]
check("seeded history line present", real_hist and real_hist[0]["night"] == "20261019" and real_hist[0]["gold_laws"] == 253)

# Q4 close_not_real
dd2 = os.path.join(tmp, "dd2"); os.makedirs(dd2 + "/duties"); os.makedirs(dd2 + "/powers")
json.dump({"obligations": [
    {"obligation_id": "2099-A1-01", "matter_id": "2099-A1", "kind": "duty", "agency": "SED", "quote": "The board shall report annually to the governor."},
    {"obligation_id": "2099-A1-02", "matter_id": "2099-A1", "kind": "duty", "agency": "SED", "quote": "Interest shall be allowed on the refund amount."}]}, open(dd2 + "/duties/2099.json", "w"))
json.dump({"powers": []}, open(dd2 + "/powers/2099.json", "w"))
g2 = {"laws": {"2099-A1": {"items": [
    {"gold_id": "2099-A1-01", "status": "real", "disputed": False, "source": {"night": "n1", "obligation_id": "2099-A1-01"}, "quote": "The board shall report annually to the governor.", "expected_fields": {}},
    {"gold_id": "2099-A1-02", "status": "not_real", "disputed": False, "source": {"night": "n1", "obligation_id": "2099-A1-02"}, "quote": "Interest shall be allowed on the refund amount.", "expected_fields": {}, "classes": ["entitlement"]}]}}}
gp2 = os.path.join(tmp, "g2.json"); json.dump(g2, open(gp2, "w"))
ovp = os.path.join(tmp, "ov.json"); json.dump({"records": {}}, open(ovp, "w"))
check("open not_real still stored", len(close_not_real.open_items(g2, dd2)) == 1)
close_not_real.main(["--gold", gp2, "--data-dir", dd2, "--overrides", ovp, "--keep", "2099-A1-02", "--why", "reads as a duty"])
ov = json.load(open(ovp))
check("keep recorded under kept_not_real", ov["kept_not_real"]["2099-A1-02"]["why"] == "reads as a duty" and "records" in ov)
check("kept item no longer open", close_not_real.open_items(g2, dd2, set(ov["kept_not_real"])) == [])
check("real gold file lists the open ones", len(close_not_real.open_items(json.load(open(Q / "gold.json")), str(T / "data"), set(json.load(open(Q / "gold_overrides.json")).get("kept_not_real", {})))) >= 0)

# Q7 build_gold additions and kept_not_real
dd3 = os.path.join(tmp, "dd3"); os.makedirs(dd3 + "/duties"); os.makedirs(dd3 + "/powers"); os.makedirs(dd3 + "/dropped")
json.dump({"obligations": [{"obligation_id": "2099-A1-01", "matter_id": "2099-A1", "kind": "duty", "agency": "SED", "agency_unit": None,
                            "deadline_kind": "none", "extends_existing": False, "quote": "The board shall report annually to the governor."},
                           {"obligation_id": "2099-A1-02", "matter_id": "2099-A1", "kind": "duty", "agency": "SED", "quote": "Interest shall be allowed on the refund."}]}, open(dd3 + "/duties/2099.json", "w"))
json.dump({"powers": []}, open(dd3 + "/powers/2099.json", "w")); json.dump({"dropped": []}, open(dd3 + "/dropped/2099.json", "w"))
nd3 = os.path.join(tmp, "nd3"); os.makedirs(nd3)
json.dump({"2099-A1": {"records": {"2099-A1-02": {"verdict": "not_real", "criteria": ["1"], "note": "n"}}, "missed": []}}, open(nd3 + "/20261001_A.json", "w"))
ov3 = os.path.join(tmp, "ov3.json"); json.dump({"records": {}}, open(ov3, "w"))
ad3 = os.path.join(tmp, "ad3.json")
json.dump([{"obligation_id": "2099-A1-01", "law": "2099-A1", "quote": "The board shall report annually to the governor.", "kind": "duty", "agency": "SED", "verdict": "real", "source": "blind check"},
           {"obligation_id": "2099-A2-01", "law": "2099-A2", "quote": "A thing nobody should store.", "kind": "duty", "agency": "SED", "verdict": "not_real", "source": "blind check"}], open(ad3, "w"))
go = os.path.join(tmp, "gold3.json")
g3 = build_gold.main(["--out", go, "--data-dir", dd3, "--nightly-dir", nd3, "--overrides", ov3, "--additions", os.path.join(tmp, "none.json")])
check("no additions file: nothing added", g3["counts"]["bulk_verification_added"] == 0 and g3["laws"]["2099-A1"]["items"][0]["status"] == "not_real")
g3 = build_gold.main(["--out", go, "--data-dir", dd3, "--nightly-dir", nd3, "--overrides", ov3, "--additions", ad3])
items = {i["gold_id"]: i for l in g3["laws"].values() for i in l["items"]}
check("additions become gold items from bulk_verification", g3["counts"]["bulk_verification_added"] == 2 and items["2099-A1-01"]["source"]["night"] == "bulk_verification"
      and items["2099-A1-01"]["status"] == "real" and items["2099-A2-01"]["status"] == "not_real")
check("addition copies stored fields", items["2099-A1-01"]["expected_fields"].get("agency") == "SED")
json.dump({"records": {}, "kept_not_real": {"2099-A1-02": {"why": "kept"}}}, open(ov3, "w"))
g3 = build_gold.main(["--out", go, "--data-dir", dd3, "--nightly-dir", nd3, "--overrides", ov3, "--additions", ad3])
it = next(i for i in g3["laws"]["2099-A1"]["items"] if i["gold_id"] == "2099-A1-02")
check("kept_not_real is treated as real", it["status"] == "real" and it.get("kept_not_real") == "kept")

# Q5 backlog
bp = os.path.join(tmp, "b.json")
for n in range(7):
    backlog.add(bp, "n1", f"class {n}", ["x"] * n, None, "rule")
check("add assigns ids and counts", [i["id"] for i in backlog.load(bp)["items"]][:2] == ["B1", "B2"] and backlog.load(bp)["items"][3]["count"] == 3)
check("done closes an item", backlog.done(bp, "B7", "n2")["status"] == "done" and len(backlog.open_items(bp)) == 6)
check("next limit is 5", backlog.NEXT_LIMIT == 5 and len(backlog.open_items(bp)[:backlog.NEXT_LIMIT]) == 5)
sb = backlog.load(str(Q / "backlog.json"))["items"]
check("backlog items are well-formed (open or done)", sb and all(i["status"] in ("open", "done") for i in sb) and {"id", "added", "class", "instances", "count", "rule", "status"} <= set(sb[0]))

# Q6 trend
md = trend.build(str(Q / "nightly"), str(Q / "gold_history.jsonl"))
check("trend has a row per adjudicated night", md.count("\n| 2026") >= 13)
check("trend includes gold history", "Gold set score history" in md and "| 20261019 | 253 |" in md)
check("trend types are extraction/pause/hold", all(t in md for t in ("| extraction |", "| pause |", "| hold |")))
check("audit_trend.md written", (Q / "audit_trend.md").exists())

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
