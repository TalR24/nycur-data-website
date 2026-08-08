#!/usr/bin/env python3
"""Flag obligations extracted from text a law only reprints, not enacts.

When a local law amends a code section, Legistar publishes the whole section
with the NEW text underlined and the DELETED text in [brackets]. The plain-text
cache threw the underline away, so a duty carried over from a 2009 law looked
exactly like one this law created. Every audit round from Aug 2026 found
records of this class; it was the single largest residual defect.

`fetch_enacted_laws._strip_text_html` now preserves underlined runs as {{...}}.
This script re-fetches the laws that restate an amended section, rewrites their
cached text with markers, and reports every obligation whose quote lies wholly
outside the marked runs. Those are candidates for removal: the law reprinted
the duty, it did not create it.

Findings are candidates, not verdicts. A law can strike a duty and re-enact it
verbatim a few sections later, which leaves the quote unmarked but the duty
real, so each hit still needs checking against the source.

Usage:
    python3 pipeline/sweep_restated_duties.py                # full sweep
    python3 pipeline/sweep_restated_duties.py --limit 40     # sample first
    python3 pipeline/sweep_restated_duties.py --no-fetch     # use cached text

No Anthropic API calls. Only Legistar page fetches.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fetch_enacted_laws import _strip_text_html  # noqa: E402

DATA = HERE.parent / "data"
TEXT_CACHE = HERE / "cache" / "text"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
DIV_TEXT = re.compile(
    r'id="ctl00_ContentPlaceHolder1_divText"[^>]*>(.*)</div>\s*'
    r'(?:<div|<!--|</td)', re.S)
AMENDED = re.compile(r"(is|are) amended to read as follows", re.I)


def fetch_marked_text(session: requests.Session, url: str) -> str | None:
    for attempt in range(3):
        try:
            r = session.get(url + "&Options=&Search=", timeout=60)
            if r.status_code != 200:
                time.sleep(2 * (attempt + 1))
                continue
            m = DIV_TEXT.search(r.text)
            if not m:
                return None
            return _strip_text_html(m.group(1))
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
    return None


def split_markers(marked: str) -> tuple[str, list[bool]]:
    """Return (plain_text, is_new_matter_per_char)."""
    plain, flags, depth, i = [], [], 0, 0
    while i < len(marked):
        if marked.startswith("{{", i):
            depth += 1
            i += 2
        elif marked.startswith("}}", i):
            depth = max(0, depth - 1)
            i += 2
        else:
            plain.append(marked[i])
            flags.append(depth > 0)
            i += 1
    return "".join(plain), flags


# A restated block runs from "is amended to read as follows" to the start of the
# next bill section. Only inside such a block does the absence of a marker mean
# "pre-existing law": the law's own freestanding sections (effective-date and
# implementation clauses) are new law that Legistar never underlines.
SECTION_START = re.compile(r"(?:^|\n)\s*(?:§+\s*\d+|Section\s+\d+)\b", re.I)


def restated_spans(plain: str) -> list[tuple[int, int]]:
    spans = []
    for m in AMENDED.finditer(plain):
        nxt = SECTION_START.search(plain, m.end())
        spans.append((m.end(), nxt.start() if nxt else len(plain)))
    return spans


def _squash(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("–", "-").replace("—", "-")
    return s.lower()


def condense(plain: str) -> tuple[str, list[int]]:
    """Whitespace-free copy of the text plus a map back to original offsets.

    Built once per law: rebuilding it per obligation made the sweep quadratic
    in law length and took over an hour on the corpus.
    """
    cond, idx = [], []
    for i, ch in enumerate(_squash(plain)):
        if not ch.isspace():
            cond.append(ch)
            idx.append(i)
    return "".join(cond), idx


def locate(hay: str, idx: list[int], flags: list[bool], quote: str,
           spans: list[tuple[int, int]] | None = None) -> float | None:
    """Fraction of the quote's non-space characters that sit in new matter."""
    q = [c for c in _squash(quote) if not c.isspace()]
    if not q:
        return None
    needle = "".join(q)

    # Check EVERY occurrence, not just the first. A law often strikes a duty
    # and re-enacts it verbatim a few sections later, which puts the same
    # sentence in the text twice: once unmarked in the restated copy and once
    # marked as new. Judging only the first hit would condemn a live duty.
    best = None
    at = hay.find(needle)
    while at >= 0:
        span = idx[at:at + len(needle)]
        inside = spans is None or any(a <= span[0] < b for a, b in spans)
        if not inside:
            return None      # this copy is outside any restated block: new law
        frac = sum(1 for i in span if flags[i]) / len(span)
        best = frac if best is None else max(best, frac)
        if best > 0:
            return best      # marked somewhere; the duty is enacted here
        at = hay.find(needle, at + 1)
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--delay", type=float, default=0.6)
    ap.add_argument("--out", default=str(HERE / "restated_candidates.json"))
    args = ap.parse_args()

    data = json.loads((DATA / "obligations.json").read_text())
    laws = {l["matter_id"]: l for l in data["laws"]}
    by_matter: dict[str, list] = {}
    for o in data["obligations"]:
        by_matter.setdefault(o["matter_id"], []).append(o)

    targets = []
    for mid, obs in by_matter.items():
        cached = TEXT_CACHE / f"{mid}.txt"
        if cached.exists() and AMENDED.search(cached.read_text()):
            targets.append(mid)
    targets.sort()
    if args.limit:
        targets = targets[:args.limit]

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    candidates, unmarked_laws, failed = [], [], []
    for n, mid in enumerate(targets, 1):
        cached = TEXT_CACHE / f"{mid}.txt"
        marked = cached.read_text() if cached.exists() else None
        if not args.no_fetch and (marked is None or "{{" not in marked):
            url = laws[mid].get("legistar_url")
            fetched = fetch_marked_text(session, url) if url else None
            if fetched:
                marked = fetched
                cached.write_text(marked)
            elif marked is None:
                failed.append(mid)
                continue
            time.sleep(args.delay)

        if "{{" not in marked:
            # no underline styling on this page: cannot judge new vs restated
            unmarked_laws.append(mid)
            continue

        plain, flags = split_markers(marked)
        spans = restated_spans(plain)
        hay, idx = condense(plain)
        for o in by_matter[mid]:
            frac = locate(hay, idx, flags, o.get("quote") or "", spans)
            if frac is None:
                continue
            if frac == 0.0:
                candidates.append({
                    "obligation_id": o["obligation_id"],
                    "matter_id": mid,
                    "law": o.get("law_number_display"),
                    "agency": o.get("agency"),
                    "citation": o.get("citation"),
                    "action_summary": o.get("action_summary"),
                    "quote": o.get("quote"),
                    "legistar_url": laws[mid].get("legistar_url"),
                })
        if n % 25 == 0:
            print(f"  [{n}/{len(targets)}] candidates so far: {len(candidates)}",
                  flush=True)

    out = {
        "generated_for_laws": len(targets),
        "laws_without_underline_markup": len(unmarked_laws),
        "laws_failed_to_fetch": failed,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"\nchecked {len(targets)} laws; {len(candidates)} obligations quote "
          f"only reprinted text")
    print(f"laws with no underline markup (undecidable): {len(unmarked_laws)}")
    print(f"laws that failed to fetch: {len(failed)}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
