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


def reask_candidates(skip: set[str], data_dir: Path | None = None, packets_dir: Path | None = None,
                     sessions: tuple = (2009, 2011, 2013, 2015)) -> list[tuple[str, dict]]:
    """Laws in data/reask/{Y}.json that can still be re-asked, best first: an audit_confirmed_miss reason, then more reasons, then key.
    Skips deferred/skipped laws, laws without an original packet, and laws that already have a results_reask answer."""
    data_dir, packets_dir = data_dir or DATA, packets_dir or PACKETS
    out = []
    for y in sessions:
        f = data_dir / "reask" / f"{y}.json"
        if not f.exists():
            continue
        for key, entry in json.load(open(f))["laws"].items():
            if key in skip or not (packets_dir / str(y) / f"{key}.txt").exists() or (packets_dir / str(y) / "results_reask" / f"{key}.json").exists():
                continue
            out.append((key, entry))
    out.sort(key=lambda kv: (0 if any(r.get("check") == "audit_confirmed_miss" for r in kv[1]["reasons"]) else 1, -len(kv[1]["reasons"]), kv[0]))
    return out


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", type=int, default=30, help="chunks this run (one subagent each)")
    ap.add_argument("--max-bytes", type=int, default=400_000)
    ap.add_argument("--max-laws", type=int, default=30)
    ap.add_argument("--reask", type=int, metavar="N", help="draw up to N laws from data/reask/*.json as re-ask packets (Max path); their chunks come first")
    ap.add_argument("--extract", action="store_true", help="with --reask: also fill the remaining chunks with never-answered laws")
    a = ap.parse_args()
    skip = deferred_skipped()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    out = PACKETS / "batches" / tag
    all_paths, reask_chunks, reask_laws, reask_left = [], [], 0, None
    if a.reask:
        cands = reask_candidates(skip)
        picks = cands[:a.reask]
        packets = write_reask_packets(picks, tag)
        reask_chunks = make_chunks(packets, a.chunks, a.max_bytes, a.max_laws)
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
    res = {"tag": tag, "chunks": all_paths, "laws": laws + reask_laws, "left_after": len(todo) - laws, "skipped_deferred": n_skipped}
    if a.reask:
        res.update({"reask_laws": reask_laws, "reask_left_after": reask_left})
    print(json.dumps(res))


if __name__ == "__main__":
    main()
