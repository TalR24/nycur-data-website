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
        if key in have or len(set(tags)) < 2 or (packets_dir / key.split("-")[0] / "results_reask" / f"{key}.json").exists():
            continue
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", type=int, default=30, help="chunks this run (one subagent each)")
    ap.add_argument("--max-bytes", type=int, default=400_000)
    ap.add_argument("--max-laws", type=int, default=30)
    ap.add_argument("--reask", type=int, metavar="N", help="draw up to N laws from data/reask/*.json as re-ask packets (Max path; default 100 with --extract); their chunks come first")
    ap.add_argument("--extract", action="store_true", help="with --reask: also fill the remaining chunks with never-answered laws")
    a = ap.parse_args()
    if a.reask is None and a.extract:
        a.reask = 100
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
        reask_chunks = make_chunks(packets, a.chunks, a.max_bytes, a.max_laws)
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
    listed = [f for c in chunks for f in c] + [f for c in reask_chunks for f in c]
    rel = relative_footers(listed)
    if rel:
        print("WARNING: %d listed packets have a relative results path in the footer, first %s (run extract_duties.py --fix-footers)" % (len(rel), rel[0]), file=sys.stderr)
    res = {"tag": tag, "chunks": all_paths, "laws": laws + reask_laws, "left_after": len(todo) - laws, "skipped_deferred": n_skipped, "relative_footers": len(rel)}
    if a.reask:
        res.update({"reask_laws": reask_laws, "reask_left_after": reask_left})
    print(json.dumps(res))


if __name__ == "__main__":
    main()
