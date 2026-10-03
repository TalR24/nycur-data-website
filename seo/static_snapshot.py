#!/usr/bin/env python3
"""
Write pre-rendered HTML into a page between marker comments, so crawlers that
do not run JavaScript (most AI crawlers, and Google on a first pass) see a
page's real content instead of a "Loading..." placeholder.

The pattern, generalized from cb-tools/member-tracker/pipeline/build_static_boards.py:

    <div id="lawGrid">
      <!-- static:law-grid:start -->
      ...markup the page's JS would build, from the same JSON...
      <!-- static:law-grid:end -->
    </div>

Put the markers INSIDE the container the page's JS fills, so the JS replaces
the static copy on load and visitors see the live version. Never hide the
static block (no display:none, no off-screen tricks): it must be the same
content a visitor gets, or it reads as cloaking.

    from static_snapshot import inject
    inject(Path("index.html"), "law-grid", html_string)

Paywall rule (Tal, Oct 2 2026): static blocks carry headline counts and top-10
tables at most, never a full dataset; full data stays behind /members/.

Idempotent: rerunning replaces the block. Raises if the markers are missing,
so a template change cannot silently drop the block.
"""

import re
from pathlib import Path


def markers(block_id):
    return f"<!-- static:{block_id}:start -->", f"<!-- static:{block_id}:end -->"


def inject(path, block_id, html):
    """Replace the content between the block's markers in `path`. Returns True
    when the file changed."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    start, end = markers(block_id)
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"{path}: markers for static block '{block_id}' not found; add\n  {start}\n  {end}\n"
                         f"inside the container the page's JS fills")
    new = pattern.sub(lambda _m: f"{start}\n{html}\n{end}", text, count=1)
    if new != text:
        path.write_text(new, encoding="utf-8")
        return True
    return False
