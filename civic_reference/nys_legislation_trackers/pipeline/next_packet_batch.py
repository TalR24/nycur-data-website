#!/usr/bin/env python3
"""Pick the next batch of unanswered signed-law packets for a paced Max run (Tal, Oct 7 2026).

Tal chose to extract the full history on the Max plan, spread over nightly runs so a run never
uses up his session or weekly limits. Each run answers at most --chunks chunks (<= 400 KB and
<= 30 laws each; one Sonnet subagent per chunk, about 105,000 subagent tokens a chunk measured
on the 2009 session). The 52 audited pilot laws and laws already answered are skipped.

    python3 pipeline/next_packet_batch.py --chunks 30
prints {"tag": ..., "chunks": [list files], "laws": n, "left_after": n} and writes the lists to
pipeline/cache/packets/batches/<tag>/.
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", type=int, default=30, help="chunks this run (one subagent each)")
    ap.add_argument("--max-bytes", type=int, default=400_000)
    ap.add_argument("--max-laws", type=int, default=30)
    a = ap.parse_args()
    skip = deferred_skipped()
    todo = unanswered(skip)
    n_skipped = sum(1 for y in SESSIONS for f in (PACKETS / str(y)).glob("*.txt") if f.stem in skip and not (PACKETS / str(y) / "results" / f"{f.stem}.json").exists())
    chunks, cur, size = [], [], 0
    for f in todo:
        s = f.stat().st_size
        if cur and (size + s > a.max_bytes or len(cur) >= a.max_laws):
            chunks.append(cur)
            cur, size = [], 0
            if len(chunks) >= a.chunks:
                break
        cur.append(f)
        size += s
    if cur and len(chunks) < a.chunks:
        chunks.append(cur)
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    out = PACKETS / "batches" / tag
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, c in enumerate(chunks):
        p = out / f"{i:03d}.lst"
        p.write_text("\n".join(str(x) for x in c) + "\n")
        paths.append(str(p))
    laws = sum(len(c) for c in chunks)
    print(json.dumps({"tag": tag, "chunks": paths, "laws": laws, "left_after": len(todo) - laws, "skipped_deferred": n_skipped}))


if __name__ == "__main__":
    main()
