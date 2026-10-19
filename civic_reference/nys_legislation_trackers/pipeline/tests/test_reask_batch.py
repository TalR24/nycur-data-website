"""Plain script: Max-plan re-ask packets, chunking, ordering and the ingest overlay. Temp dirs only; no model call."""
import json, os, sys, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed
import next_packet_batch as nb

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("FAIL:", name)

FOOT = "\n\nANSWER FORMAT: write ONLY a JSON object matching this schema to results/%s.json:\n" + json.dumps(ed.SCHEMA)
def packet(key, text="The commissioner shall report yearly."):
    return "FIXED PROMPT\n\nLAW METADATA\n\nLAW TEXT:\n" + text + (FOOT % key)

tmp = Path(tempfile.mkdtemp())
pk, dd = tmp / "packets", tmp / "data"
(dd / "reask").mkdir(parents=True); (dd / "duties").mkdir()
(dd / "powers").mkdir()
keys = {"2011-A1": ["x"], "2011-A2": ["x", "y"], "2011-A3": ["audit_confirmed_miss"], "2011-A4": ["x", "y", "z"], "2009-A5": ["x"], "2011-A6": ["x"]}
laws = {}
for k, checks in keys.items():
    laws.setdefault(k.split("-")[0], {})[k] = {"reasons": [{"check": c, "detail": "d", "sentences": ["The board must meet."]} for c in checks]}
    (pk / k.split("-")[0]).mkdir(parents=True, exist_ok=True)
    (pk / k.split("-")[0] / (k + ".txt")).write_text(packet(k))
for y, l in laws.items():
    (dd / "reask" / (y + ".json")).write_text(json.dumps({"laws": l}))
(dd / "duties" / "2011.json").write_text(json.dumps({"obligations": [{"matter_id": "2011-A3", "obligation_id": "2011-A3-01", "actor_raw": "the commissioner", "kind": "duty", "deadline_text": "within 30 days", "extends_existing": True, "quote": "The commissioner shall report yearly."}]}))
(dd / "powers" / "2011.json").write_text(json.dumps({"powers": []}))
(pk / "2011" / "results_reask").mkdir()
(pk / "2011" / "results_reask" / "2011-A6.json").write_text("{}")

c = nb.reask_candidates({"2011-A1"}, dd, pk)
order = [k for k, _ in c]
check("audit_confirmed_miss first, then 3+ reasons, then the rest by key", order == ["2011-A3", "2011-A4", "2009-A5", "2011-A2"])
check("skipped and already re-asked laws are left out", "2011-A1" not in order and "2011-A6" not in order)

ps = nb.write_reask_packets(c[:1], "T1", dd, pk)
t = ps[0].read_text()
check("packet has the RE-ASK block before the law text", "RE-ASK. " in t and t.index("RE-ASK. ") < t.index("LAW TEXT:"))
check("block lists the stored record fields", "2011-A3-01" in t and "the commissioner" in t and "within 30 days" in t and "extends existing law: yes" in t)
check("block carries the check sentences", "The board must meet." in t and "ADDITIONAL INSTRUCTION" in t)
want = str(pk / "2011" / "results_reask" / "2011-A3.json")
check("footer writes to results_reask, never results/", want in t.split("ANSWER FORMAT:")[1] and "to results/" not in t.split("ANSWER FORMAT:")[1].split(":\n")[0].replace("never to results/", ""))
check("footer keeps the schema", t.rstrip().endswith(json.dumps(ed.SCHEMA)))
check("tag sidecar written", (pk / "2011" / "reask" / "2011-A3.tag").read_text().strip() == "T1")

# chunk caps
big = []
for i in range(7):
    f = tmp / ("p%d.txt" % i); f.write_text("x" * 100); big.append(f)
ch = nb.make_chunks(big, 10, 250, 30)
check("byte cap respected", all(sum(f.stat().st_size for f in c1) <= 250 for c1 in ch) and sum(map(len, ch)) == 7)
ch = nb.make_chunks(big, 10, 10_000, 3)
check("law cap respected", [len(c1) for c1 in ch] == [3, 3, 1])
check("chunk count cap respected", len(nb.make_chunks(big, 2, 10_000, 3)) == 2)
lst = nb.write_lists(ch, tmp / "b" / "reask")
check("lists are NNN.lst, one path per line", Path(lst[0]).name == "000.lst" and len(Path(lst[0]).read_text().split()) == 3)

# ingest overlay
d = tmp / "sess"; (d / "results").mkdir(parents=True); (d / "results_reask").mkdir(); (d / "reask").mkdir()
(d / "manifest.json").write_text("{}")
good = {"effective_clause": {"kind": "immediate", "offset": None, "fixed_date": None, "text": "t"}, "obligations": []}
orig = dict(good, effective_clause=dict(good["effective_clause"], text="ORIGINAL"))
new = dict(good, effective_clause=dict(good["effective_clause"], text="REASK"))
todo = [({"key": k}, "") for k in ("2011-A1", "2011-A2", "2011-A3")]
for k in ("2011-A1", "2011-A2", "2011-A3"):
    (d / "results" / (k + ".json")).write_text(json.dumps(orig))
(d / "results_reask" / "2011-A1.json").write_text(json.dumps(new))
(d / "results_reask" / "2011-A2.json").write_text("{not json")
(d / "reask" / "2011-A1.tag").write_text("T9\n")
view, reasked = ed.reask_overlay(d, todo, tmp / "view")
rd = lambda k: json.loads((view / "results" / (k + ".json")).read_text())["effective_clause"]["text"]
check("valid results_reask replaces results", rd("2011-A1") == "REASK" and reasked == {"2011-A1": "T9"})
check("invalid results_reask falls back to the original", rd("2011-A2") == "ORIGINAL")
check("no results_reask keeps the original", rd("2011-A3") == "ORIGINAL")
check("originals on disk untouched", json.loads((d / "results" / "2011-A1.json").read_text())["effective_clause"]["text"] == "ORIGINAL")
ex = tmp / "ex"; ex.mkdir(); (ex / "2011-A1.json").write_text(json.dumps({"matter_id": "2011-A1", "obligations": []}))
check("mark_reasked stamps the cache file", ed.mark_reasked(reasked, {"2011-A1"}, ex) == 1 and json.loads((ex / "2011-A1.json").read_text())["reask_tag"] == "T9")
check("--api path still imports", callable(ed.run_batches) and callable(ed.merge_reask) and callable(ed.load_reask) and callable(ed.build_request))
# P3 ordering: audit miss, sunset holder, 3+ remaining reasons (mechanical ones do not count), rest by key
E = lambda *cs: {"reasons": [{"check": c, "detail": "d", "sentences": ["s"]} for c in cs]}
ents = {"2011-Z": E("x"), "2011-B": E("x", "y", "z"), "2011-C": E("sunset_extension_unnamed_holder"), "2011-D": E("audit_confirmed_miss"),
        "2011-E": E("x", "quote_outside_new_matter", "imperative_item_no_lead_in"), "2011-F": E("quote_outside_new_matter"), "2011-A": E("x")}
(dd / "reask" / "2011.json").write_text(json.dumps({"laws": ents}))
for k in ents:
    (pk / "2011" / (k + ".txt")).write_text(packet(k))
o = [k for k, _ in nb.reask_candidates(set(), dd, pk, sessions=(2011,))]
check("P3 order tiers", o == ["2011-D", "2011-C", "2011-B", "2011-A", "2011-E", "2011-Z"])
check("P2 mechanical-only law is not a candidate", "2011-F" not in o)

# P2 pruned checks go to mechanical_flags, not reask
keep, mech = ed.split_mechanical({"k1": E("x", "local_body_unresolved"), "k2": E("state_as_single_agency"), "k3": E("audit_confirmed_miss")})
check("P2 only-mechanical law leaves the queue", set(keep) == {"k1", "k3"} and set(mech) == {"k1", "k2"})
check("P2 split keeps the real reason and moves the mechanical one", [r["check"] for r in keep["k1"]["reasons"]] == ["x"] and [r["check"] for r in mech["k1"]["reasons"]] == ["local_body_unresolved"])
check("P2 the five pruned names", ed.MECHANICAL_CHECKS == {"quote_outside_new_matter", "imperative_item_no_lead_in", "state_as_single_agency", "local_body_unresolved", "mandatory_lead_in_item_dropped"})
check("P2 recall, sunset and actor checks are not pruned", not ({"b_modal_sentence_coverage", "c_list_items_fewer_records", "e_window_or_timing_power", "sunset_extension_unnamed_holder", "passive_subject_actor", "audit_confirmed_miss"} & ed.MECHANICAL_CHECKS))

# P4 skip memory
dp, drp = tmp / "deferred.json", tmp / "draws.json"
dp.write_text(json.dumps({"rule": "r", "laws": [{"key": "2009-OLD", "reason": "omnibus"}]}))
nb.record_draws(["2011-A1", "2011-A2", "2011-A3"], "T1", drp)
check("P4 one draw defers nothing", nb.defer_twice_skipped(pk, drp, dp) == [])
nb.record_draws(["2011-A1", "2011-A2"], "T1", drp)
nb.record_draws(["2011-A1", "2011-A2"], "T2", drp)
(pk / "2011" / "results_reask" / "2011-A2.json").write_text("{}")
added = nb.defer_twice_skipped(pk, drp, dp)
check("P4 two batches without an answer defers the law; an answered one stays", added == ["2011-A1"])
d = json.load(open(dp))["laws"]
check("P4 deferred_skipped.json entry has the reason and keeps old rows", {"key": "2011-A1", "reason": "re-ask skipped twice"} in d and len(d) == 2)
check("P4 not added twice", nb.defer_twice_skipped(pk, drp, dp) == [] and nb.deferred_skipped(dp) == {"2009-OLD", "2011-A1"})

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
