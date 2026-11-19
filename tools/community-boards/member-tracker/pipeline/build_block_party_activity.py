"""Summarize Block Party resolution activity for the Manhattan boards.

Reads the merged dashboard CSV in the private premium repo (the Block Party
resolution engine's spot-check export; Manhattan boards only) and writes
pipeline/extracted/block_party_activity.json with per-board totals,
resolutions per year, and the most recent decisions with source links.

Board-level only: the engine stores no per-member votes, so the tracker
shows what each board decided, not how individuals voted. Vote tallies and
committee attribution live in Supabase, whose credentials are not available
locally; extend this script if that changes.

Runs locally only (the premium repo is not checked out in the public
Action); the output JSON is committed. Re-run after Block Party re-exports.

Run from the member-tracker folder:
  python3 pipeline/build_block_party_activity.py [path/to/full_resolutions.csv]
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "extracted" / "block_party_activity.json"
DEFAULT_SRC = Path(
    "/Users/troded/nycur/nycur-data-premium/cb-resolutions/data/full_resolutions.csv"
)
RECENT_PER_BOARD = 8

csv.field_size_limit(10_000_000)


def clean_title(raw: str) -> str:
    t = re.sub(r"\s+", " ", raw or "").strip()
    if t.isupper():
        t = t.title()
    return t[:180]


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src.exists():
        sys.exit(f"source CSV not found: {src}")

    per_year: dict[int, Counter] = defaultdict(Counter)
    recent: dict[int, list[dict]] = defaultdict(list)
    totals: Counter = Counter()

    with src.open() as f:
        for row in csv.DictReader(f):
            m = re.match(r"MCB(\d+)$", row.get("board_id", ""))
            if not m:
                continue
            cd = 100 + int(m.group(1))
            totals[cd] += 1
            d = row.get("meeting_date") or ""
            if re.match(r"\d{4}-\d{2}-\d{2}", d):
                per_year[cd][int(d[:4])] += 1
                recent[cd].append(
                    {
                        "date": d,
                        "title": clean_title(row.get("title", "")),
                        "url": row.get("source_url") or None,
                    }
                )

    boards = {}
    for cd in sorted(totals):
        items = sorted(recent[cd], key=lambda r: r["date"], reverse=True)
        years = sorted(per_year[cd])
        boards[str(cd)] = {
            "total_resolutions": totals[cd],
            "first_year": years[0] if years else None,
            "last_year": years[-1] if years else None,
            "by_year": {str(y): per_year[cd][y] for y in years if y >= 2015},
            "recent": items[:RECENT_PER_BOARD],
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "as_of": date.fromtimestamp(src.stat().st_mtime).isoformat(),
                "source": "Block Party resolution engine export (Manhattan boards)",
                "boards": boards,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    print(
        f"Wrote {OUT}: {len(boards)} boards, "
        f"{sum(totals.values())} resolutions"
    )


if __name__ == "__main__":
    main()
