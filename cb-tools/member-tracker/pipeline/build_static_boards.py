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
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE.parent.parent / "seo"))
from static_snapshot import inject  # noqa: E402

TOP_N = 10  # paywall rule: at most top-10 rows per table in static blocks
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


def esc(s):
    return escape("" if s is None else str(s))


def bronx_terms_block(boards):
    """Mirror of the #bronxTable markup openings/index.html builds in JS."""
    bronx = [b for b in boards if (b.get("term_clock") or {}).get("projected_expirations")]
    if not bronx:
        return '<p class="loading-note">No confirmed term data in the current build.</p>'
    dates = sorted({d for b in bronx for d in b["term_clock"]["projected_expirations"]})
    h = '<table><thead><tr><th>Board</th>'
    h += "".join('<th class="num">class of %s</th>' % esc(d) for d in dates)
    h += "</tr></thead><tbody>"
    for b in bronx[:TOP_N]:
        h += '<tr><td class="nm"><a href="../board/?cd=%d">%s</a></td>' % (b["cd"], esc(b["name"]))
        for d in dates:
            n = b["term_clock"]["projected_expirations"].get(d)
            h += '<td class="num">%s</td>' % (n if n else "—")
        h += "</tr>"
    h += ("</tbody></table><p class=\"loading-note\">Seats per next-expiration class, projected from the Bronx BP roster "
          "(roster year %s) by rolling each published term date forward in two-year terms, assuming reappointment.</p>"
          % esc(bronx[0]["term_clock"].get("bronx_roster_year") or ""))
    return h


def coverage_block(boards, members):
    """Mirror of the #covTable markup methodology/index.html builds in JS."""
    counts = {}
    for m in members:
        if m.get("source") != "cau":
            counts[m["cd"]] = counts.get(m["cd"], 0) + 1
    comm_map = {
        "assignments": '<span class="cov ok">full assignments</span>',
        "chairs": '<span class="cov ok">chairs named</span>',
        "list": '<span class="cov part">list only</span>',
        "none": '<span class="cov no">not published</span>',
    }
    rows = []
    for b in boards[:TOP_N]:
        cov = b["coverage"]
        n = counts.get(b["cd"], 0)
        if cov["roster"] == "full":
            roster = '<span class="cov ok">%d members</span>' % n
        elif cov["roster"] == "partial":
            roster = '<span class="cov part">leaders only (%d)</span>' % n
        else:
            roster = '<span class="cov no">not published</span>'
        terms = ('<span class="cov ok">confirmed dates</span>' if cov["terms"] == "confirmed"
                 else '<span class="cov no">modeled waves</span>')
        votes = '<span class="cov ok">✓</span>' if b.get("block_party") else '<span class="cov no">—</span>'
        rows.append('<tr><td class="nm"><a href="../board/?cd=%d">%s</a></td><td><span class="cov ok">✓ CAU</span></td>'
                    '<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                    % (b["cd"], esc(b["name"]), roster, comm_map[cov["committees"]], terms, votes))
    return ('<table><thead><tr><th>Board</th><th>Chair &amp; DM</th><th>Roster</th><th>Committees</th>'
            '<th>Term dates</th><th>Resolutions</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>")


def subpages():
    """Static snapshots for the subpages (board/ is a ?cd= template with no
    no-parameter content, so it is skipped)."""
    doc = json.loads(BOARDS.read_text(encoding="utf-8"))["boards"]
    members = json.loads((HERE / "data" / "members.json").read_text(encoding="utf-8"))["members"]
    for rel, bid, html in (
        ("openings/index.html", "bronx-terms", bronx_terms_block(doc)),
        ("methodology/index.html", "coverage", coverage_block(doc, members)),
    ):
        changed = inject(HERE / rel, bid, html)
        print(("wrote" if changed else "unchanged"), rel, bid)


def main():
    subpages()
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
