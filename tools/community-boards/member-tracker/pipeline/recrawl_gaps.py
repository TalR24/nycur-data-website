"""Second-pass crawl: follow links FROM cached candidate pages (depth 2).

The first crawl only followed links from each board's homepage; many boards
link their Members/Committees pages from section nav that only appears on
inner pages, so this pass re-scans every cached page for matching links and
fetches the ones not yet cached (up to EXTRA_MAX new pages per board).

Also overrides Brooklyn CB5's start page to the real nyc.gov site: the CAU
dataset's website URL for it points at a hijacked domain.

Usage: python3 pipeline/recrawl_gaps.py [cd ...]   (default: all boards)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.parse
from pathlib import Path

from fetch_board_pages import CACHE, PAGES, LinkParser, LINK_RE, SKIP_RE, get

EXTRA_MAX = 10

HOME_OVERRIDES = {
    "305": "https://www.nyc.gov/site/brooklyncb5/index.page",
}


def links_from(html: str, base_url: str) -> list[str]:
    p = LinkParser()
    try:
        p.feed(html)
    except Exception:
        pass
    out = []
    for href, text in p.links:
        if SKIP_RE.search(href):
            continue
        if not (LINK_RE.search(text) or LINK_RE.search(href)):
            continue
        absu = urllib.parse.urljoin(base_url, href)
        if urllib.parse.urlparse(absu).netloc != urllib.parse.urlparse(base_url).netloc:
            continue
        out.append(absu.split("#")[0])
    return out


def main() -> None:
    index = json.loads((CACHE / "pages_index.json").read_text())
    only = set(sys.argv[1:])

    for cd, entry in sorted(index.items()):
        if only and cd not in only:
            continue
        cached_urls = {p["url"].rstrip("/") for p in entry["pages"]}
        candidates: list[str] = []

        override = HOME_OVERRIDES.get(cd)
        if override:
            body = get(override)
            if body and len(body) > 500:
                bdir = PAGES / cd
                bdir.mkdir(parents=True, exist_ok=True)
                slug = re.sub(r"[^a-z0-9]+", "-", override.split("//", 1)[-1].lower())[-80:]
                fname = f"{len(entry['pages']):02d}_{slug}.html"
                (bdir / fname).write_text(body)
                entry["pages"].append(
                    {"url": override, "file": f"{cd}/{fname}",
                     "sha256": hashlib.sha256(body.encode()).hexdigest()[:16]})
                cached_urls.add(override.rstrip("/"))
                entry["home"] = override
                candidates.extend(links_from(body, override))

        for p in list(entry["pages"]):
            f = CACHE / "pages" / p["file"]
            if not f.exists():
                continue
            candidates.extend(links_from(f.read_text(errors="replace"), p["url"]))

        fresh = []
        seen = set()
        for u in candidates:
            key = u.rstrip("/")
            if key in cached_urls or key in seen:
                continue
            seen.add(key)
            fresh.append(u)
        if not fresh:
            continue

        print(f"[{cd}] fetching {min(len(fresh), EXTRA_MAX)} of {len(fresh)} new candidate pages")
        bdir = PAGES / cd
        bdir.mkdir(parents=True, exist_ok=True)
        added = 0
        for u in fresh:
            if added >= EXTRA_MAX:
                break
            body = get(u)
            if body is None or len(body) < 500:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", u.split("//", 1)[-1].lower())[-80:]
            fname = f"{len(entry['pages']):02d}_{slug}.html"
            (bdir / fname).write_text(body)
            entry["pages"].append(
                {"url": u, "file": f"{cd}/{fname}",
                 "sha256": hashlib.sha256(body.encode()).hexdigest()[:16]})
            added += 1
        print(f"    added {added}")

    (CACHE / "pages_index.json").write_text(json.dumps(index, indent=1))
    total = sum(len(e["pages"]) for e in index.values())
    print(f"done: {total} pages total")


if __name__ == "__main__":
    main()
