"""Plain script: long-law windows through the Batches API (Nov 12 2026), with a fake client. NO API call, nothing written outside a scratch dir.
Prints 'N passed, M failed'."""
import json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from types import SimpleNamespace as NS
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import logging
logging.disable(logging.CRITICAL)
import extract_duties as ed
if not (ed.TEXT_MARKED / "2015-A7645.txt").exists() or not (ed.DATA / "deferred_long.json").exists():      # CI has no cached texts
    print("0 passed, 0 failed (skipped: long-law texts are not cached here)")
    sys.exit(0)
try:
    import anthropic  # noqa: F401
except ImportError:
    print("0 passed, 0 failed (skipped: anthropic package not installed)")
    sys.exit(0)
import next_packet_batch as nb
import api_long_windows as al
import import_long_answers as il

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

tmp = Path(tempfile.mkdtemp())
KEY = "2015-A7645"
cands_all = nb.long_candidates()
cands = [c for c in cands_all if c["key"] == KEY] or cands_all[:1]
KEY = cands[0]["key"]
law, text = cands[0]["law"], cands[0]["text"]
n_win = len(ed.split_long(text))

OK = {"effective_clause": {"kind": "other", "offset": None, "fixed_date": None, "text": "x"}, "obligations": [], "excluded_sentences": []}
class FakeBatches:
    def __init__(self, answers): self.sent = []; self.answers = answers
    def create(self, requests):
        self.sent.append(requests); return NS(id="batch_fake%d" % len(self.sent))
    def retrieve(self, bid): return NS(processing_status="ended", request_counts=NS(succeeded=len(self.sent[-1]), errored=0, expired=0, canceled=0))
    def results(self, bid):
        for r in self.sent[int(bid[-1]) - 1]:
            cid = r["custom_id"]
            kind = self.answers(cid)
            if kind == "ok":
                msg = NS(content=[NS(type="text", text=json.dumps(OK))], stop_reason="end_turn", usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0))
            elif kind == "cut":
                msg = NS(content=[NS(type="text", text="{")], stop_reason="max_tokens", usage=NS(input_tokens=10, output_tokens=5))
            else:
                msg = NS(content=[NS(type="text", text="not json")], stop_reason="end_turn", usage=NS(input_tokens=10, output_tokens=5))
            yield NS(custom_id=cid, result=NS(type="succeeded", message=msg))
def fake_client(answers): return NS(messages=NS(batches=FakeBatches(answers)))

os.environ["NYS_THINKING"] = "medium"
sd, od = tmp / "state", tmp / "out"; sd.mkdir()
fixed = ed.build_prompt(2)[0]

# 1. requests: one per window, custom ids, prompt and parameter shape
wins = al.pick_windows(cands, None, od, tmp / "nopackets")
check("one request per window", len(wins) == n_win and n_win >= 2)
reqs = [al.build_window_request(l, i, w, fixed) for l, k, i, w in wins]
check("custom ids are <key>__w<i>", [c for c, _ in reqs] == ["%s__w%d" % (KEY, i) for i in range(1, n_win + 1)])
p = reqs[0][1]
blocks = p["messages"][0]["content"]
check("fixed v2 prompt first, cached 1h", blocks[0]["text"] == fixed and blocks[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"})
check("window prompt carries the window note and text", blocks[1]["text"].startswith(ed.LONG_NOTE) and wins[0][3] in blocks[1]["text"])
check("model, max tokens, schema v2, effort", p["model"] == ed.MODEL and p["max_tokens"] == ed.MAX_TOKENS and p["output_config"]["format"]["schema"] == ed.SCHEMA_V2 and p["output_config"]["effort"] == "medium")

# 2. spend guard: refuses over the cap, submits nothing
proj = al.project(wins, fixed)
c = fake_client(lambda cid: "ok")
try:
    al.main(["--max-usd", "0.0001"], client=c, cands=cands, state_dir=sd, out_dir=od)
    refused = False
except SystemExit as e:
    refused = "exceeds --max-usd" in str(e)
check("guard refuses over the cap", refused and not c.messages.batches.sent and not list(sd.iterdir()))
check("projection positive and dearer at default than medium", proj > 0 and al.project(wins, fixed, "default") > proj > al.project(wins, fixed, "low"))

# 3. a canary: first N windows in one batch; saves valid answers, counts the unusable, leaves them unanswered
answers = lambda cid: "bad" if cid.endswith("__w2") else ("cut" if cid.endswith("__w3") else "ok")
c = fake_client(answers)
saved, bad, left = al.main(["--canary", "3", "--max-usd", "5"], client=c, cands=cands, state_dir=sd, out_dir=od)
check("canary sent 3 windows in one batch", len(c.messages.batches.sent) == 1 and len(c.messages.batches.sent[0]) == 3)
res = sorted(f.name for f in (od / "results").glob("*.json"))
check("only the valid answer saved", res == ["%s__w1.json" % KEY] and (saved, bad) == (1, 2) and not left)
check("state files cleared once collected", not list(sd.glob("batch_state_long*.json")))
wins2 = al.pick_windows(cands, None, od, tmp / "nopackets")
check("answered window not sent again, unusable ones stay unanswered", [i for _, _, i, _ in wins2] == list(range(2, n_win + 1)))

# 4. resume: a pending chunk is collected without a new submit
c = fake_client(lambda cid: "ok")
class Slow(FakeBatches):
    ended = False
    def retrieve(self, bid): return NS(processing_status="ended" if self.ended else "in_progress", request_counts=NS(succeeded=0, errored=0, expired=0, canceled=0))
c.messages.batches = Slow(lambda cid: "ok")
al.main(["--limit-windows", "2", "--max-wait-min", "0"], client=c, cands=cands, state_dir=sd, out_dir=od)
check("pending batch kept in the long state file", (sd / "batch_state_long.json").exists() and len(list(sd.glob("batch_state_long_0*.json"))) == 1)
c.messages.batches.ended = True
al.main(["--resume"], client=c, cands=cands, state_dir=sd, out_dir=od)
check("resume collected without a second submit", len(c.messages.batches.sent) == 1 and not list(sd.glob("batch_state_long*.json")))
check("resume saved the answers", (od / "results" / ("%s__w2.json" % KEY)).exists() and (od / "results" / ("%s__w3.json" % KEY)).exists())

# 5. fill the remaining windows, then import into a scratch packets dir
c = fake_client(lambda cid: "ok")
al.main([], client=c, cands=cands, state_dir=sd, out_dir=od)
check("every window answered", len(list((od / "results").glob("*.json"))) == n_win)
packets = tmp / "packets"
(od / "results" / "junk__w1.json").write_text("{}")
(od / "results" / ("%s__w1.json" % KEY)).write_text(json.dumps(OK))
pre = packets / KEY.split("-")[0] / "long" / "results"; pre.mkdir(parents=True)
(pre / ("%s__w1.json" % KEY)).write_text('{"keep": "me"}')            # an existing answer is never overwritten
r = il.import_answers(od, packets, ed.TEXT_MARKED)
check("import copied all but the existing one", r["copied"] == n_win - 1 and r["existing"] == 1 and not r["mismatch"])
check("existing answer untouched", json.loads((pre / ("%s__w1.json" % KEY)).read_text()) == {"keep": "me"})
d = ed.long_dir(KEY, packets)
check("manifest entry matches emit_long_packets", json.loads((d / "manifest.json").read_text()) == {KEY: {"windows": n_win}})
(pre / ("%s__w1.json" % KEY)).write_text(json.dumps(OK))          # the real answer for window 1 (the placeholder above was not schema-valid)
check("law fully answered, ingest_long can see it", ed.long_answered(KEY, packets))
r2 = il.import_answers(od, packets, ed.TEXT_MARKED)
check("second import copies nothing", r2["copied"] == 0)

# 6. ingest_long merges the law (scratch extracted dir; --data-dir scratch for the CLI)
ed.EXTRACTED = tmp / "extracted"
ed.EFFECTIVE = ed.effective_table([law])
done, left = ed.ingest_long([(law, text)], packets, ed.LOOKUP, ed.BY_CANON, "test")
check("ingest_long merged one law", done == [KEY] and not left and (ed.EXTRACTED / (KEY + ".json")).exists())
data = tmp / "data"; shutil.copytree(ed.DATA, data, ignore=shutil.ignore_patterns("bills", "site"))
y = KEY.split("-")[0]
(packets / y / "results").mkdir(exist_ok=True); (packets / y / "manifest.json").write_text("{}")
cli = subprocess.run([sys.executable, str(HERE / "extract_duties.py"), "--ingest", str(packets / y), "--per-session", "--session", y, "--data-dir", str(data)], capture_output=True, text=True)
check("CLI ingest on the scratch dir merges the law", "long laws merged from windows" in cli.stdout and KEY in cli.stdout and (data / "cache" / "extracted" / (KEY + ".json")).exists())
if "long laws merged" not in cli.stdout: print(cli.stdout[-600:], cli.stderr[-400:])

# 7. projection for every candidate
allw = al.pick_windows(cands_all, None, tmp / "none", tmp / "nopackets")
print("candidates: %d laws, %d windows" % (len(cands_all), len(allw)))
for mode in ("default", "medium"):
    print("projection, thinking %s: $%.2f" % (mode, al.project(allw, fixed, mode)))
shutil.rmtree(tmp, ignore_errors=True)
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
