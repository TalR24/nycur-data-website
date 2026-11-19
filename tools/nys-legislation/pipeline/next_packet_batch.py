#!/usr/bin/env python3
"""Pick the next batch of unanswered signed-law packets for a paced Max run (Tal, Oct 7 2026).

Tal chose to extract the full history on the Max plan, spread over nightly runs so a run never
uses up his session or weekly limits. Each run answers at most --chunks chunks (<= 400 KB and
<= 30 laws each; one Sonnet subagent per chunk, about 105,000 subagent tokens a chunk measured
on the 2009 session). The 52 audited pilot laws and laws already answered are skipped.

    python3 pipeline/next_packet_batch.py --chunks 30
prints {"tag": ..., "chunks": [list files], "laws": n, "left_after": n} and writes the lists to
pipeline/cache/packets/batches/<tag>/.

Re-ask (Max path, Oct 15 2026): --reask N [--extract] writes packets/{Y}/reask/{LAW}.txt and lists under
batches/<tag>/reask/NNN.lst (listed first); answers go to packets/{Y}/results_reask/, which --ingest prefers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKETS = HERE / "cache" / "packets"
DATA = HERE.parent / "data"
SESSIONS = (2009, 2011, 2013, 2015, 2017, 2019, 2021, 2023, 2025)


def pilot_keys() -> set[str]:
    pb = json.load(open(DATA / "bills.json"))
    pb = pb.get("bills", pb) if isinstance(pb, dict) else pb
    keys = set()
    for b in pb:
        if b.get("signed"):
            for p in (b["print_no"], b.get("base_print_no") or b["print_no"]):
                keys.add(f"{b['session']}-{re.sub(r'[A-Z]$', '', p)}")
    return keys


def deferred_skipped(path: Path | None = None) -> set[str]:
    """Keys in data/deferred_skipped.json: laws agents skipped as too long, omnibus or empty; not redrawn each night."""
    p = path or DATA / "deferred_skipped.json"
    return {x["key"] for x in json.load(open(p))["laws"]} if p.exists() else set()


def unanswered(skip: set[str] | None = None) -> list[Path]:
    pilot = pilot_keys()
    skip = deferred_skipped() if skip is None else skip
    out = []
    for y in SESSIONS:
        d = PACKETS / str(y)
        for f in sorted(d.glob("*.txt")):
            key = f.stem
            if key in skip or re.sub(r"[A-Z]$", "", key) in pilot or (d / "results" / f"{key}.json").exists():
                continue
            out.append(f)
    return out


def make_chunks(files: list[Path], n_chunks: int, max_bytes: int, max_laws: int) -> list[list[Path]]:
    """Greedy chunks of at most max_bytes and max_laws files, at most n_chunks of them."""
    chunks, cur, size = [], [], 0
    for f in files:
        s = f.stat().st_size
        if cur and (size + s > max_bytes or len(cur) >= max_laws):
            chunks.append(cur)
            cur, size = [], 0
            if len(chunks) >= n_chunks:
                break
        cur.append(f)
        size += s
    if cur and len(chunks) < n_chunks:
        chunks.append(cur)
    return chunks


def live_reasons(entry: dict) -> list[dict]:
    """Reasons that still queue a re-ask (the mechanical checks, which old reask files may still hold, do not)."""
    import extract_duties as ed
    return [r for r in entry["reasons"] if r.get("check") not in ed.MECHANICAL_CHECKS]


def reask_priority(key: str, entry: dict) -> tuple:
    """0 audit_confirmed_miss, 1 sunset_extension_unnamed_holder, 2 three or more remaining reasons, 3 the rest; then key."""
    rs = live_reasons(entry)
    checks = {r.get("check") for r in rs}
    tier = 0 if "audit_confirmed_miss" in checks else 1 if "sunset_extension_unnamed_holder" in checks else 2 if len(rs) >= 3 else 3
    return (tier, key)


def reask_candidates(skip: set[str], data_dir: Path | None = None, packets_dir: Path | None = None,
                     sessions: tuple | None = None) -> list[tuple[str, dict]]:
    """Laws in data/reask/{Y}.json that can still be re-asked, in reask_priority order. A law whose only reasons are mechanical checks is not a candidate.
    Skips deferred/skipped laws, laws without an original packet, and laws whose results_reask answer is not yet ingested
    (its mtime differs from the history's `answered`); an ingested answer may be re-asked again when apply_reask_history keeps a reason
    (Oct 30 2026: before this, 565 queued 2017/2019 laws were never looked at and 446 second-round laws were blocked by the answer file)."""
    import extract_duties as ed
    data_dir, packets_dir = data_dir or DATA, packets_dir or PACKETS
    hist = ed.load_reask_history(data_dir / "reask_history.json")
    out = []
    if sessions is None:
        sessions = tuple(sorted(int(f.stem) for f in (data_dir / "reask").glob("20??.json")))
    for y in sessions:
        f = data_dir / "reask" / f"{y}.json"
        if not f.exists():
            continue
        for key, entry in json.load(open(f))["laws"].items():
            if key in skip or not live_reasons(entry) or not (packets_dir / str(y) / f"{key}.txt").exists():
                continue
            ans = packets_dir / str(y) / "results_reask" / f"{key}.json"
            if ans.exists() and int(ans.stat().st_mtime) != (hist.get(key) or {}).get("answered"):
                continue                                                              # answered but not ingested yet: never draw it twice in one cycle
            kept, _ = ed.apply_reask_history(live_reasons(entry), hist.get(key))     # reasons already suppressed by the re-ask history never draw a law
            if not kept:
                continue
            out.append((key, dict(entry, reasons=kept)))
    out.sort(key=lambda kv: reask_priority(*kv))
    return out


def _tag_time(tag: str) -> float:
    """Epoch seconds of a batch tag YYYYMMDD-HHMM (local time); 0 when the tag is not in that form."""
    import time as _t
    try:
        return _t.mktime(_t.strptime(tag[:13], "%Y%m%d-%H%M"))
    except ValueError:
        return 0.0


def defer_twice_skipped(packets_dir: Path | None = None, draws_path: Path | None = None, deferred_path: Path | None = None) -> list[str]:
    """A law drawn for re-ask in two different batches with no results_reask file afterwards was skipped by an agent twice:
    add it to data/deferred_skipped.json (reason "re-ask skipped twice") so it is not redrawn. Returns the keys added."""
    packets_dir = packets_dir or PACKETS
    draws_path = draws_path or packets_dir / "reask_draws.json"
    deferred_path = deferred_path or DATA / "deferred_skipped.json"
    draws = json.load(open(draws_path)) if draws_path.exists() else {}
    dj = json.load(open(deferred_path)) if deferred_path.exists() else {"rule": "laws agents skipped as too long, omnibus or empty text; retried in a later phase", "laws": []}
    have = {x["key"] for x in dj["laws"]}
    added = []
    for key, tags in sorted(draws.items()):
        if key in have or len(set(tags)) < 2:
            continue
        ans = packets_dir / key.split("-")[0] / "results_reask" / f"{key}.json"
        if ans.exists() and ans.stat().st_mtime >= _tag_time(sorted(set(tags))[-2]):
            continue                      # answered after the second-to-last draw: not a double skip (Nov 1 2026: an older answer used to hide three omnibus laws skipped every night)
        dj["laws"].append({"key": key, "reason": "re-ask skipped twice"})
        added.append(key)
    if added:
        json.dump(dj, open(deferred_path, "w"), indent=2, ensure_ascii=False)
    return added


def record_draws(keys: list[str], tag: str, draws_path: Path | None = None) -> None:
    draws_path = draws_path or PACKETS / "reask_draws.json"
    draws = json.load(open(draws_path)) if draws_path.exists() else {}
    for k in keys:
        if tag not in draws.setdefault(k, []):
            draws[k].append(tag)
    draws_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(draws, open(draws_path, "w"), indent=0)


def write_reask_packets(picks: list[tuple[str, dict]], tag: str, data_dir: Path | None = None, packets_dir: Path | None = None) -> list[Path]:
    """Write packets/{Y}/reask/{LAW}.txt (+ a .tag sidecar the ingest reads) for each pick; returns the packet paths in order."""
    import extract_duties as ed
    data_dir, packets_dir = data_dir or DATA, packets_dir or PACKETS
    paths = []
    for key, entry in picks:
        y = key.split("-")[0]
        base = packets_dir / y
        (base / "reask").mkdir(parents=True, exist_ok=True)
        (base / "results_reask").mkdir(parents=True, exist_ok=True)
        text = ed.reask_packet_text((base / f"{key}.txt").read_text(), key, entry, ed.stored_records(key, data_dir), base / "results_reask" / f"{key}.json")
        p = base / "reask" / f"{key}.txt"
        p.write_text(text)
        (base / "reask" / f"{key}.tag").write_text(tag + "\n")
        paths.append(p)
    return paths


LONG_LIMIT = 5              # long laws drawn a night
LONG_PENDING_HOURS = 20     # a law drawn within this many hours is pending: not drawn again
LONG_MAX_DRAWS = 3          # a law whose windows are still unanswered after this many draws is left alone (agents skipped it)


LONG_NOT_FIXABLE = re.compile(r"truncated|empty|list item|no quotable|only new matter|section heading", re.I)    # skipped for a reason windows do not fix


def long_candidates(data_dir: Path | None = None, packets_dir: Path | None = None, text_dir: Path | None = None) -> list[dict]:
    """Long laws that can still be drawn, as {key, law, text, windows, answered}: every law in data/deferred_long.json, and every law in
    data/deferred_skipped.json whose marked text is longer than a window, unless the reason is truncated, empty or list-only text (windows cannot fix that).
    Laws with every window answered (waiting for the ingest) or needing more than LONG_MAX_WINDOWS are left out.
    Order: laws already part-answered, then fewest windows, then key."""
    import extract_duties as ed
    data_dir, packets_dir, text_dir = data_dir or DATA, packets_dir or PACKETS, text_dir or TEXT_MARKED
    keys = []
    for name in ("deferred_long.json", "deferred_skipped.json"):
        f = data_dir / name
        if f.exists():
            keys += [x["key"] for x in json.load(open(f))["laws"] if x["key"] not in keys and not LONG_NOT_FIXABLE.search(x.get("reason", ""))]
    laws = {}
    for y in sorted({int(k.split("-")[0]) for k in keys}):
        sg = data_dir / "signed" / f"{y}.json"
        if sg.exists():
            laws.update({l["key"]: l for l in json.load(open(sg))})
    out = []
    for k in keys:
        tp = text_dir / f"{k}.txt"
        if k not in laws or not tp.exists():
            continue
        text = tp.read_text()
        if len(text) <= ed.LONG_MIN:
            continue
        n_win = len(ed.split_long(text))
        if n_win > ed.LONG_MAX_WINDOWS:
            continue
        n, done = ed.long_state(k, packets_dir)
        if n and len(done) == n:
            continue
        out.append({"key": k, "law": laws[k], "text": text, "windows": n_win, "answered": len(done) if n == n_win else 0})
    out.sort(key=lambda c: (c["answered"] == 0, c["windows"], c["key"]))
    return out


def long_draws(path: Path | None = None) -> dict:
    p = path or PACKETS / "long_draws.json"
    return json.load(open(p)) if p.exists() else {}


def draw_long(limit: int = LONG_LIMIT, now: datetime | None = None, draws_path: Path | None = None, **kw) -> list[dict]:
    """Up to `limit` candidate long laws, skipping laws pending (drawn within LONG_PENDING_HOURS) and laws already drawn LONG_MAX_DRAWS times."""
    now = now or datetime.now()
    draws = long_draws(draws_path)
    picks = []
    for c in long_candidates(**kw):
        tags = draws.get(c["key"], [])
        if len(tags) >= LONG_MAX_DRAWS:
            continue
        if tags and (now.timestamp() - _tag_time(tags[-1])) < LONG_PENDING_HOURS * 3600:
            continue
        picks.append(c)
        if len(picks) >= limit:
            break
    return picks


def write_long_packets(picks: list[dict], packets_dir: Path | None = None) -> list[Path]:
    """Window packets of the picks under packets/{Y}/long/; returns only the packets of windows not yet answered, in law then window order."""
    import extract_duties as ed
    packets_dir = packets_dir or PACKETS
    files = []
    for c in picks:
        y = c["key"].split("-")[0]
        d = packets_dir / y / "long"
        made = ed.emit_long_packets(d, [(c["law"], c["text"])])[c["key"]]
        n, done = ed.long_state(c["key"], packets_dir)
        files += [f for i, f in enumerate(made, 1) if i not in done]
    return files


def record_long_draws(keys: list[str], tag: str, path: Path | None = None) -> None:
    p = path or PACKETS / "long_draws.json"
    draws = long_draws(p)
    for k in keys:
        if tag not in draws.setdefault(k, []):
            draws[k].append(tag)
    p.parent.mkdir(parents=True, exist_ok=True)
    json.dump(draws, open(p, "w"), indent=0)


def write_lists(chunks: list[list[Path]], out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, c in enumerate(chunks):
        p = out / f"{i:03d}.lst"
        p.write_text("\n".join(str(x) for x in c) + "\n")
        paths.append(str(p))
    return paths


def relative_footers(files: list[Path]) -> list[Path]:
    """Listed packets whose ANSWER FORMAT footer does not name an absolute results path."""
    bad = []
    for f in files:
        t = f.read_text()
        foot = t[t.rfind("\n\nANSWER FORMAT:"):] if "\n\nANSWER FORMAT:" in t else ""
        if not re.search(r"to (?:the exact path )?/\S*\.json", foot.split(":\n", 1)[0] + ":"):
            bad.append(f)
    return bad


PREPARE_CAP = 150           # laws prepared (text fetched, packet emitted) per run, so a big signing week cannot stall the night
GAP_DAYS = 10
MAX_CHARS = 120_000         # same limit as extract_duties.MAX_CHARS: longer laws are deferred and get no packet
TEXT_MARKED = HERE / "cache" / "text_marked"


def _excluded_keys() -> set[str]:
    """Pilot laws, laws agents skipped, and laws over the length limit: none of them gets a packet from the nightly draw."""
    ex = pilot_keys() | deferred_skipped()
    dl = DATA / "deferred_long.json"
    if dl.exists():
        ex |= {x["key"] for x in json.load(open(dl))["laws"]}
    return ex


def laws_lacking_packet(sessions=SESSIONS, data_dir: Path | None = None, packets_dir: Path | None = None,
                        text_dir: Path | None = None, excluded: set[str] | None = None) -> list[dict]:
    """Signed laws (data/signed/{Y}.json) with no packet and no answer. Each is returned as its law dict plus "has_text"."""
    data_dir, packets_dir, text_dir = data_dir or DATA, packets_dir or PACKETS, text_dir or TEXT_MARKED
    excluded = _excluded_keys() if excluded is None else excluded
    out = []
    for y in sessions:
        sg = data_dir / "signed" / f"{y}.json"
        if not sg.exists():
            continue
        for law in json.load(open(sg)):
            k = law["key"]
            if k in excluded or re.sub(r"[A-Z]$", "", k) in excluded:
                continue
            d = packets_dir / str(y)
            if (d / f"{k}.txt").exists() or (d / "results" / f"{k}.json").exists():
                continue
            tp = text_dir / f"{k}.txt"
            if tp.exists() and len(tp.read_text()) > MAX_CHARS:
                continue                                  # deferred long, by rule
            out.append(dict(law, has_text=tp.exists()))
    return out


def prepare(cap: int = PREPARE_CAP, fetch_text=None, emit=None, **kw) -> dict:
    """Self-heal before the draw: for signed laws without a packet, fetch the text if missing (OpenLeg only, never a model) and emit
    their packets. fetch_text(session, base_print_no) -> bool and emit(session, [law dicts]) -> int are injectable for tests.
    A failure on one law is logged and skipped; nothing here raises into the draw."""
    if fetch_text is None:
        import fetch_signed_texts
        fetch_text = fetch_signed_texts.ensure_marked_text
    if emit is None:
        emit = _emit_packets
    need = laws_lacking_packet(**kw)
    todo, failed = need[:cap], 0
    ready: dict[int, list[dict]] = {}
    for law in todo:
        ok = law["has_text"]
        if not ok:
            try:
                ok = fetch_text(law["session"], law["print_no"])
            except Exception as e:           # network, key, API: log and carry on with what exists
                print("prepare: %s could not be fetched: %s" % (law["key"], str(e)[:100]), file=sys.stderr)
                ok = False
        if ok:
            ready.setdefault(law["session"], []).append(law)
        else:
            failed += 1
    made = 0
    for y, laws in sorted(ready.items()):
        try:
            made += emit(y, laws)
        except Exception as e:
            print("prepare: packet emit failed for %d: %s" % (y, str(e)[:100]), file=sys.stderr)
            failed += len(laws)
    res = {"lacking": len(need), "tried": len(todo), "prepared": made, "not_fetched": failed, "left_over_cap": max(len(need) - cap, 0)}
    print("prepare: %d laws prepared, %d could not be fetched or emitted (%d lacked a packet, cap %d)" % (made, failed, len(need), cap))
    return res


def _emit_packets(session: int, laws: list[dict]) -> int:
    """Packets for exactly these laws, with the production emit code (version-2 prompt), under cache/packets/{Y}/."""
    import extract_duties as ed
    keys = {l["key"] for l in laws}
    todo = []
    for law in ed.signed_laws([session]):
        if law["key"] in keys:
            text = (ed.TEXT_MARKED / (law["key"] + ".txt")).read_text()
            if len(text) <= ed.MAX_CHARS:
                todo.append((law, text))
    if not todo:
        return 0
    d = PACKETS / str(session)
    (d / "results").mkdir(parents=True, exist_ok=True)
    mf = d / "manifest.json"
    before = json.loads(mf.read_text()) if mf.exists() else {}      # Nov 12 2026: emit writes a manifest of only these laws; keep the session's other entries
    ed.emit_absolute_packets(d, todo, fixed_prompt=ed.build_prompt(2)[0], render=ed.render_variable_prompt, schema=ed.SCHEMA_V2)
    merged = {**before, **json.loads(mf.read_text())}
    mf.write_text(json.dumps(merged, indent=1))
    return len(todo)


def gap_problems(today=None, days: int = GAP_DAYS, **kw) -> list[str]:
    """Signed laws older than `days` days with no packet and no answer. Skipped cleanly where the packet cache is absent (CI)."""
    from datetime import date, timedelta
    packets_dir = kw.get("packets_dir") or PACKETS
    if not packets_dir.exists():
        return []
    cutoff = ((today or date.today()) - timedelta(days=days)).isoformat()
    old = [l for l in laws_lacking_packet(**kw) if (l.get("signed_date") or "9999") <= cutoff]
    if not old:
        return []
    return ["%d signed laws older than %d days have no packet and no answer (first %s, signed %s)" % (len(old), days, old[0]["key"], old[0]["signed_date"])]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", type=int, default=30, help="chunks this run (one subagent each)")
    ap.add_argument("--max-bytes", type=int, default=400_000)
    ap.add_argument("--max-laws", type=int, default=30)
    ap.add_argument("--reask", type=int, metavar="N", help="draw up to N laws from data/reask/*.json as re-ask packets (Max path; default 250 with --extract since Nov 12 2026); their chunks come first")
    ap.add_argument("--extract", action="store_true", help="with --reask: also fill the remaining chunks with never-answered laws")
    ap.add_argument("--long", action=argparse.BooleanOptionalAction, default=True, help="with --extract: also draw the windows of long laws (deferred_long, deferred_skipped) after the re-asks and new laws; --no-long turns it off (Nov 12 2026)")
    ap.add_argument("--long-limit", type=int, default=LONG_LIMIT, help="long laws drawn this run")
    ap.add_argument("--long-reserve", type=int, default=6, help="chunks held back from the re-asks for new laws and long-law windows (default 6 since Nov 12 2026: room for the last new laws and 5 long laws a night; 250 re-asks alone would fill 25 chunks)")
    ap.add_argument("--no-prepare", action="store_true", help="skip fetching texts and emitting packets for newly signed laws")
    ap.add_argument("--prepare-only", action="store_true", help="prepare, print, and stop: no draw, no batch consumed")
    ap.add_argument("--check", action="store_true", help="exit 1 if signed laws older than 10 days have no packet and no answer (skips without the packet cache)")
    a = ap.parse_args()
    if a.check:
        probs = gap_problems()
        for p in probs:
            print("GAP:", p)
        print("%d gap problem(s)" % len(probs) if probs else "no packet gap (or no local packet cache)")
        sys.exit(1 if probs else 0)
    if not a.no_prepare or a.prepare_only:
        try:
            prepare()
        except Exception as e:               # preparation never stops the night's draw
            print("prepare failed, drawing from what exists: %s" % str(e)[:120], file=sys.stderr)
    if a.prepare_only:
        return
    if a.reask is None and a.extract:
        a.reask = 250          # Nov 12 2026 (Tal): new-law extraction is done, so re-asks may fill all 25 chunks; the chunk cap still bounds the night
    if a.reask:
        for k in defer_twice_skipped():
            print("deferred (re-ask skipped twice): " + k, file=sys.stderr)
    skip = deferred_skipped()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    out = PACKETS / "batches" / tag
    all_paths, reask_chunks, reask_laws, reask_left = [], [], 0, None
    if a.reask:
        cands = reask_candidates(skip)
        picks = cands[:a.reask]
        packets = write_reask_packets(picks, tag)
        reask_chunks = make_chunks(packets, a.chunks - (a.long_reserve if a.long and a.extract else 0), a.max_bytes, a.max_laws)
        record_draws([f.stem for c in reask_chunks for f in c], tag)
        reask_laws = sum(len(c) for c in reask_chunks)
        reask_left = len(cands) - reask_laws
        all_paths += write_lists(reask_chunks, out / "reask")
    if a.reask and not a.extract:
        print(json.dumps({"tag": tag, "chunks": all_paths, "laws": reask_laws, "reask_left_after": reask_left}))
        return
    todo = unanswered(skip)
    n_skipped = sum(1 for y in SESSIONS for f in (PACKETS / str(y)).glob("*.txt") if f.stem in skip and not (PACKETS / str(y) / "results" / f"{f.stem}.json").exists())
    chunks = make_chunks(todo, max(a.chunks - len(reask_chunks), 0), a.max_bytes, a.max_laws) if a.chunks > len(reask_chunks) else []
    all_paths += write_lists(chunks, out)
    laws = sum(len(c) for c in chunks)
    long_chunks, long_keys, long_windows_n = [], [], 0
    left_chunks = a.chunks - len(reask_chunks) - len(chunks)
    if a.long and a.extract and left_chunks > 0 and a.long_limit > 0:
        picks = draw_long(a.long_limit)
        wfiles = write_long_packets(picks)
        long_chunks = make_chunks(wfiles, left_chunks, a.max_bytes, a.max_laws)
        in_chunks = {f.stem.split("__w")[0] for c in long_chunks for f in c}
        long_keys = [c["key"] for c in picks if c["key"] in in_chunks]
        record_long_draws(long_keys, tag)
        long_windows_n = sum(len(c) for c in long_chunks)
        all_paths += write_lists(long_chunks, out / "long")
    listed = [f for c in chunks for f in c] + [f for c in reask_chunks for f in c] + [f for c in long_chunks for f in c]
    rel = relative_footers(listed)
    if rel:
        print("WARNING: %d listed packets have a relative results path in the footer, first %s (run extract_duties.py --fix-footers)" % (len(rel), rel[0]), file=sys.stderr)
    res = {"tag": tag, "chunks": all_paths, "laws": laws + reask_laws, "left_after": len(todo) - laws, "skipped_deferred": n_skipped, "relative_footers": len(rel)}
    if long_keys:
        res.update({"long_laws": len(long_keys), "long_windows": long_windows_n})
    if a.reask:
        res.update({"reask_laws": reask_laws, "reask_left_after": reask_left})
    print(json.dumps(res))


if __name__ == "__main__":
    main()
