#!/usr/bin/env python3
"""
Pre-render the 59 board cards into index.html so search engines see the board
names, neighborhoods and chairs without running JavaScript.

    python3 pipeline/build_static_boards.py        # from cb-tools/member-tracker/

Before Aug 25 2026 the #boardGrid held only "Loading boards..." until
buildGrid() filled it from data/boards.json, so the page had no crawlable
board text and drew zero Search Console impressions in 90 days. This script
writes the same card markup buildGrid() produces (minus the coverage chips)
between two marker comments inside #boardGrid; the JS still replaces the
grid on load, so users see the live version. refresh_cb_member_data.yml runs
this after build_tracker_data.py and commits index.html with the data.
"""

import json
import re
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
INDEX = HERE / "index.html"
BOARDS = HERE / "data" / "boards.json"
START, END = "<!-- static-boards:start -->", "<!-- static-boards:end -->"
PLACEHOLDER = '<p class="loading-note">Loading boards…</p>'


def card(b):
    chair = (b.get("chair") or {}).get("name") or "not published"
    return ('<a class="board-card" href="board/?cd=%d">'
            '<span class="bc-name">%s</span>'
            '<span class="bc-hood">%s</span>'
            '<span class="bc-chair">Chair: <b>%s</b></span>'
            '</a>' % (b["cd"], escape(b["name"]), escape(b.get("neighborhoods") or ""), escape(chair)))


def main():
    boards = json.loads(BOARDS.read_text(encoding="utf-8"))["boards"]
    boards.sort(key=lambda b: b["cd"])
    block = START + "\n" + "\n".join("      " + card(b) for b in boards) + "\n      " + END
    html = INDEX.read_text(encoding="utf-8")
    if START in html and END in html:
        new = re.sub(re.escape(START) + r"[\s\S]*?" + re.escape(END), lambda m: block, html, count=1)
    elif PLACEHOLDER in html:
        new = html.replace(PLACEHOLDER, "\n      " + block + "\n    ", 1)
    else:
        raise SystemExit("index.html has neither the static-boards markers nor the Loading boards placeholder")
    if new != html:
        INDEX.write_text(new, encoding="utf-8")
        print(f"wrote {len(boards)} static board cards into {INDEX.name}")
    else:
        print("static board cards unchanged")


if __name__ == "__main__":
    main()
