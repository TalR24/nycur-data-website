"""Plain script: additive re-ask merge (REASK_MODE merge vs replace). Temp dirs only; no model call."""
import json, os, sys, tempfile
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import extract_duties as ed

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        print("FAIL:", name)

def rec(quote, actor="counties", kind="duty", ext=False):
    return {"actor_raw": actor, "actor_resolved": actor, "actor_unit": None, "action_summary": "x", "deliverable_type": "other", "provision_kind": kind,
            "citation": "L 1", "quote": quote, "deadline": {"kind": "none", "fixed_date": None, "offset": None, "text": None},
            "recurrence": "one-time", "affected_groups": [], "extends_existing": ext}
EC = {"kind": "immediate", "offset": None, "fixed_date": None, "text": "This act shall take effect immediately"}
Q1 = "The board of elections shall publish the roll every year in each county of the state"
Q2 = "The commissioner of health shall adopt rules governing licensing of clinics in the state"
Q3 = "Each county treasurer shall remit the collected tax to the comptroller within thirty days"
Q4 = "The superintendent shall report annually to the governor on all insured plans"
Q5 = "The department of transportation shall post signs along every state highway segment"
key = "2011-A1"
orig = {"effective_clause": EC, "obligations": [rec(Q1), rec(Q2, ext=True), rec(Q3)]}
reask = {"effective_clause": {**EC, "text": "different"}, "obligations": [rec(Q1, "cities", ext=True), rec(Q2, "towns", ext=False), rec(Q4)]}
entry = {"reasons": [{"check": "passive_subject_actor", "detail": "d", "sentences": [Q2 + "."]},
                     {"check": "b_modal_sentence_coverage", "detail": "d", "sentences": [Q1]}]}

m, tags, removed = ed.merge_reask_answer(key, orig, reask, entry)
by = {" ".join(ed._qwords(o["quote"])): o for o in m["obligations"]}
k = lambda q: by[" ".join(ed._qwords(q))]
check("3 kept/overridden + 1 added + missing kept = 4 records", len(m["obligations"]) == 4)
check("unflagged match keeps original actor", k(Q1)["actor_raw"] == "counties" and k(Q1)["extends_existing"] is False)
check("unflagged match tagged kept_original", tags[" ".join(ed._qwords(Q1))] == "kept_original")
check("flagged match takes the re-ask fields", k(Q2)["actor_raw"] == "towns" and k(Q2)["extends_existing"] is False)
check("flagged match tagged reask_fields", tags[" ".join(ed._qwords(Q2))] == "reask_fields")
check("new re-ask record added", Q4 in [o["quote"] for o in m["obligations"]] and tags[" ".join(ed._qwords(Q4))] == "added")
check("original missing from the re-ask is kept", Q3 in [o["quote"] for o in m["obligations"]] and tags[" ".join(ed._qwords(Q3))] == "kept_original")
check("nothing removed", removed == [])
check("effective_clause from the original", m["effective_clause"]["text"] == EC["text"])
m2, _, _ = ed.merge_reask_answer(key, {**orig, "effective_clause": {"kind": "other", "text": ""}}, reask, entry)
check("effective_clause from the re-ask when the original was unparsed", m2["effective_clause"]["text"] == "different")
# flagged original omitted by the re-ask is dropped
entry2 = {"reasons": [{"check": "approver_as_actor", "detail": "d", "sentences": [Q3]}]}
m3, tags3, removed3 = ed.merge_reask_answer(key, orig, reask, entry2)
check("flagged original omitted is dropped as reask_removed", Q3 not in [o["quote"] for o in m3["obligations"]] and removed3 == [Q3])
# id naming in a reason also flags
entry3 = {"reasons": [{"check": "joint_actor_single", "detail": "record 2011-A1-01 names one", "sentences": []}]}
m4, t4, _ = ed.merge_reask_answer(key, orig, reask, entry3)
check("obligation id in a reason flags the original", t4[" ".join(ed._qwords(Q1))] == "reask_fields")

# overlay on disk, both modes, plus mark_reasked
tmp = Path(tempfile.mkdtemp())
d = tmp / "pk"
(d / "results").mkdir(parents=True); (d / "results_reask").mkdir(); (d / "reask").mkdir()
(d / "manifest.json").write_text("{}")
(d / "results" / (key + ".json")).write_text(json.dumps(orig))
(d / "results_reask" / (key + ".json")).write_text(json.dumps(reask))
(d / "reask" / (key + ".tag")).write_text("T1")
todo = [({"key": key}, "")]
ov = tmp / "ov1"
_, reasked = ed.reask_overlay(d, todo, ov, mode="merge", entries={key: entry})
got = json.loads((ov / "results" / (key + ".json")).read_text())
check("overlay merge writes 4 records", len(got["obligations"]) == 4 and reasked == {key: "T1"})
ov2 = tmp / "ov2"
ed.reask_overlay(d, todo, ov2, mode="replace", entries={key: entry})
got2 = json.loads((ov2 / "results" / (key + ".json")).read_text())
check("replace mode still replaces", got2 == reask)
check("default mode is replace until the span-based merge lands (backlog B14)", ed.REASK_MODE == "replace")
ed.reask_overlay(d, todo, tmp / "ov3", mode="merge", entries={key: entry})
ex = tmp / "ex"; ex.mkdir()
(ex / (key + ".json")).write_text(json.dumps({"obligations": [dict(rec(Q1)), dict(rec(Q4))]}))
check("mark_reasked stamps", ed.mark_reasked(reasked, {key}, ex) == 1)
res = json.loads((ex / (key + ".json")).read_text())
check("obligations stamped with reask_merge", [o["reask_merge"] for o in res["obligations"]] == ["kept_original", "added"] and all(o["reasked"] for o in res["obligations"]))
print("%d passed, %d failed" % (passed, failed))
