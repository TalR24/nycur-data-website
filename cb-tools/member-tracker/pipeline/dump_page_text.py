"""Dump each board's cached pages as stripped text to cache/text/<cd>.txt.

Convenience for manual/in-session extraction passes; extract_rosters.py
does the same stripping internally. Run after fetch_board_pages.py:
    python3 pipeline/dump_page_text.py
"""
from __future__ import annotations

import json
from pathlib import Path

from extract_rosters import page_text  # same stripping + page cap

CACHE = Path(__file__).resolve().parent / "cache"


def main() -> None:
    index = json.loads((CACHE / "pages_index.json").read_text())
    out_dir = CACHE / "text"
    out_dir.mkdir(exist_ok=True)
    for cd, entry in sorted(index.items()):
        if not entry["pages"]:
            continue
        (out_dir / f"{cd}.txt").write_text(page_text(entry))
    print(f"wrote {len(list(out_dir.glob('*.txt')))} text files to {out_dir}")


if __name__ == "__main__":
    main()
