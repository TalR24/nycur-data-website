"""Plain script: long laws answered window by window (Nov 12 2026). Emit windows, merge hand-written window answers, deferred lists, nightly draw.
No model call; everything runs in a scratch dir. Prints 'N passed, M failed'. With LONG_E2E=1 it also runs the real ingest CLI against a scratch copy of data/."""
import json, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime, timedelta
from pathlib import Path
HERE = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(HERE))
import logging
logging.disable(logging.CRITICAL)
import extract_duties as ed
import extract_obligations as eo
import next_packet_batch as nb

KEY_LONG = "2011-A4002"                    # a small long law (25 KB, 3 windows) stands in for the budget bills in the live deferred_long.json, which the nightly merges empty (Nov 13 2026)
KEY_LONG2 = "2013-S2602"                   # second fixture entry of deferred_long, never answered, so the nightly draw has a candidate from that list
KEY_SKIP = "2015-A7645"                    # in deferred_skipped.json ("too long, domestic relations")
if not all((ed.TEXT_MARKED / (k + ".txt")).exists() for k in (KEY_LONG, KEY_LONG2, KEY_SKIP)):      # CI has no cached texts
    print("0 passed, 0 failed (skipped: long-law texts are not cached here)")
    sys.exit(0)
passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name)

ed.MAX_CHARS = 20_000                      # the small fixture laws count as long (the real limit is 120,000)
tmp = Path(tempfile.mkdtemp())
data = tmp / "data"; shutil.copytree(ed.DATA, data, ignore=shutil.ignore_patterns("bills", "site"))
DEFERRED_LONG = data / "deferred_long.json"          # fixture, never the live file
json.dump({"laws": [{"key": k, "chapter": 0, "year": int(k.split("-")[0]), "chars": len((ed.TEXT_MARKED / (k + ".txt")).read_text()), "title": "fixture"} for k in (KEY_LONG, KEY_LONG2)]}, open(DEFERRED_LONG, "w"))
packets = tmp / "packets"
ed.EXTRACTED = tmp / "extracted"
laws = {}
for y in sorted({int(k.split("-")[0]) for k in (KEY_LONG, KEY_SKIP)}):
    laws.update({l["key"]: l for l in json.load(open(ed.DATA / "signed" / ("%d.json" % y)))})
texts = {k: (ed.TEXT_MARKED / (k + ".txt")).read_text() for k in (KEY_LONG, KEY_SKIP)}
ed.EFFECTIVE = ed.effective_table([laws[k] for k in texts])

def quote_in(window):
    """25 words of this window from inside new matter, free of markers and brackets, so the gates can verify it."""
    for m in re.finditer(r"\bshall\b", window):
        seg = window[max(0, m.start() - 120): m.start() + 200]
        seg = re.sub(r"\s+", " ", seg)
        words = seg.split(" ")[3:28]
        q = " ".join(words)
        if len(words) >= 20 and not re.search(r"[\[\]{}]", q) and q in re.sub(r"\s+", " ", window):
            return q
    return None

def fake(window):
    q = quote_in(window)
    if not q:
        return None
    return {"effective_clause": {"kind": "other", "offset": None, "fixed_date": None, "text": "x"},
            "obligations": [{"actor_raw": "the commissioner", "actor_resolved": "commissioner", "actor_unit": None, "action_summary": "Do the thing.",
                             "deliverable_type": "other", "citation": "Test Law § 1", "quote": q, "deadline": {"kind": "none", "fixed_date": None, "offset": None, "text": None},
                             "recurrence": "one-time", "provision_kind": "duty", "affected_groups": [], "extends_existing": False}],
            "excluded_sentences": []}

# 1. windows: sizes, footers, manifest
for k in (KEY_LONG, KEY_SKIP):
    law, text = laws[k], texts[k]
    d = packets / k.split("-")[0] / "long"
    made = ed.emit_long_packets(d, [(law, text)])[k]
    sizes = [f.stat().st_size for f in made]
    print("%s: text %d chars, %d windows, packet bytes min %d max %d" % (k, len(text), len(made), min(sizes), max(sizes)))
    check(k + " split into several windows", len(made) >= 2)
    check(k + " every packet under 60 KB", max(sizes) < 60_000)
    check(k + " footers name the absolute results path", all(("%s/results/%s.json" % (d.resolve(), f.stem)) in f.read_text() for f in made))
    check(k + " window note present", all(ed.LONG_NOTE in f.read_text() for f in made))
    windows = ed.split_long(text)
    check(k + " windows cover the whole law", all(w.strip() for w in windows) and len(windows) == len(made))
    check(k + " no answers yet", not ed.long_answered(k, packets) and ed.long_state(k, packets)[1] == [])

# 2. a long law joins the ingest todo only when every window is answered; MAX_CHARS deferral stays otherwise
k = KEY_LONG
n, _ = ed.long_state(k, packets)
wins = ed.split_long(texts[k])
d = packets / k.split("-")[0] / "long"
names = ed.window_names(k, n)
answers = {}
for i, (nm, w) in enumerate(zip(names, wins)):
    a = fake(w)
    if a is None:
        a = {"effective_clause": {"kind": "other", "offset": None, "fixed_date": None, "text": "x"}, "obligations": [], "excluded_sentences": []}
    else:
        answers[i] = a
    if i < n - 1:
        (d / "results" / (nm + ".json")).write_text(json.dumps(a))
y = int(k.split("-")[0])
_, deferred = ed.load_todo([y], packets)
check("one window missing: law stays deferred", k in {x["key"] for x in deferred} and not ed.long_answered(k, packets))
nm, w = names[-1], wins[-1]
a = fake(w) or {"effective_clause": {"kind": "other", "offset": None, "fixed_date": None, "text": "x"}, "obligations": [], "excluded_sentences": []}
if fake(w): answers[n - 1] = a
(d / "results" / (nm + ".json")).write_text(json.dumps(a))
check("all windows answered", ed.long_answered(k, packets))
todo, deferred = ed.load_todo([y], packets)
check("answered long law is in todo, not deferred", k in {l["key"] for l, _ in todo} and k not in {x["key"] for x in deferred})

# 3. merge: both laws, records survive build_records and the quote gate
d2 = packets / KEY_SKIP.split("-")[0] / "long"
n2, _ = ed.long_state(KEY_SKIP, packets)
w2 = ed.split_long(texts[KEY_SKIP]); ans2 = {}
for i, (nm, w) in enumerate(zip(ed.window_names(KEY_SKIP, n2), w2)):
    a = fake(w) or {"effective_clause": {"kind": "other", "offset": None, "fixed_date": None, "text": "x"}, "obligations": [], "excluded_sentences": []}
    if a["obligations"]: ans2[i] = a
    (d2 / "results" / (nm + ".json")).write_text(json.dumps(a))
sel = [(laws[k], texts[k]) for k in (KEY_LONG, KEY_SKIP)]
done, left = ed.ingest_long(sel, packets, ed.LOOKUP, ed.BY_CANON, "test")
check("both long laws merged", sorted(done) == sorted([KEY_LONG, KEY_SKIP]) and not left)
for k, ans in ((KEY_LONG, answers), (KEY_SKIP, ans2)):
    res = json.loads((ed.EXTRACTED / (k + ".json")).read_text())
    ids = [o["obligation_id"] for o in res["obligations"]]
    print("%s: %d window answers with a record -> %d merged records" % (k, len(ans), len(ids)))
    distinct = {eo.normalize_quote(o["obligations"][0]["quote"])[:160] for o in ans.values()}      # windows overlap, so a quote seen twice merges once
    check(k + " one merged record per distinct window quote", len(ids) == len(distinct) and len(ans) >= 2)
    check(k + " ids numbered across windows", ids == ["%s-%02d" % (k, i) for i in range(1, len(ids) + 1)])
    check(k + " model fields kept after renumbering", set(res.get("extends_model", {})) == set(ids) and set(res.get("actor_model", {})) == set(ids))
    check(k + " window count stored", res["windows"] == len(ed.split_long(texts[k])))
    check(k + " no window error", not res.get("extraction_error"))
duties, powers, excluded = ed.build_records([laws[KEY_LONG], laws[KEY_SKIP]])
dropped = [x for x in ed.DROPPED if x["rule"] == "unverified_quote"]
print("build_records: %d duties, %d powers, %d dropped as unverified_quote, rules: %s" % (len(duties), len(powers), len(dropped), sorted({x["rule"] for x in ed.DROPPED})))
check("quote gate drops nothing from the merged answers", not dropped)
check("every merged record became a duty or power or a gate drop", len(duties) + len(powers) + len(ed.DROPPED) >= 2)
out = tmp / "recs"; out.mkdir()
(out / "d.json").write_text(json.dumps({"obligations": duties})); (out / "p.json").write_text(json.dumps({"powers": powers}))
vout = subprocess.run([sys.executable, str(HERE / "validate_duties.py"), "--duties", str(out / "d.json"), "--powers", str(out / "p.json")], capture_output=True, text=True).stdout
check("validator quote check passes", "quote_not_in_law_text" not in vout)

# 4. deferred_skipped loses a law only after its windows are ingested
ds = data / "deferred_skipped.json"
before = {x["key"] for x in json.load(open(ds))["laws"]}
check("test law starts in deferred_skipped", KEY_SKIP in before)
gone = ed.drop_from_deferred_skipped([KEY_SKIP], ds, ds)
after = {x["key"] for x in json.load(open(ds))["laws"]}
check("removed once ingested, others kept", gone == [KEY_SKIP] and after == before - {KEY_SKIP})
check("a law with unanswered windows is not removed", ed.drop_from_deferred_skipped([], ds, ds) == [] and before - {KEY_SKIP} == after)

# 5. the nightly draw
kw = dict(data_dir=data, packets_dir=packets, text_dir=ed.TEXT_MARKED)
cands = nb.long_candidates(**kw)
ck = [c["key"] for c in cands]
check("candidates come from both deferred lists", any(c in {x["key"] for x in json.load(open(DEFERRED_LONG))["laws"]} for c in ck) and any(c in before for c in ck))
check("answered laws are not candidates", KEY_LONG not in ck and KEY_SKIP not in ck)
now = datetime(2026, 11, 13, 2, 17)
dp = tmp / "long_draws.json"
picks = nb.draw_long(5, now=now, draws_path=dp, **kw)
check("at most 5 laws", len(picks) == 5)
nb.record_long_draws([c["key"] for c in picks], "20261113-0217", dp)
again = nb.draw_long(5, now=now + timedelta(hours=2), draws_path=dp, **kw)
check("a pending law is not redrawn", not ({c["key"] for c in picks} & {c["key"] for c in again}))
later = nb.draw_long(5, now=now + timedelta(hours=24), draws_path=dp, **kw)
check("an unanswered law is redrawn the next night", {c["key"] for c in picks} & {c["key"] for c in later})
files = nb.write_long_packets(picks, packets_dir=packets)
chunks = nb.make_chunks(files, 25, 400_000, 30)
check("window chunks respect the size cap", all(sum(f.stat().st_size for f in c) <= 400_000 + 60_000 for c in chunks))
order = [c["key"] for c in picks]
check("windows of a law stay together in order", [f.stem.split("__w")[0] for f in files] == sorted([f.stem.split("__w")[0] for f in files], key=order.index))

# 6. optional end to end through the CLI against a scratch copy of data/
if os.environ.get("LONG_E2E"):
    d = packets / str(y); (d / "results").mkdir(parents=True, exist_ok=True); (d / "manifest.json").write_text("{}")
    shutil.copy(ed.DATA / "deferred_skipped.json", data / "deferred_skipped.json")
    r = subprocess.run([sys.executable, str(HERE / "extract_duties.py"), "--ingest", str(d), "--per-session", "--session", str(y), "--data-dir", str(data)], capture_output=True, text=True)
    print(r.stdout[-900:], r.stderr[-400:])
    check("cli ingest merged the long law", "long laws merged from windows" in r.stdout and KEY_LONG in r.stdout)
    check("cli wrote the extracted cache in the scratch dir", (data / "cache" / "extracted" / (KEY_LONG + ".json")).exists())
    check("cli left deferred_long without the merged law", KEY_LONG not in {x["key"] for x in json.load(open(data / "deferred_long.json"))["laws"]})
shutil.rmtree(tmp, ignore_errors=True)
print("%d passed, %d failed" % (passed, failed))
