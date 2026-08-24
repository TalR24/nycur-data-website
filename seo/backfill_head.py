#!/usr/bin/env python3
"""
One-time (and idempotent) head-tag backfill: add the tags the SEO contract
requires to every live page that lacks them, deriving values from what the
page already has.

    python3 seo/backfill_head.py --site data           # dry run: what would change
    python3 seo/backfill_head.py --site data --apply   # write the files

Adds, only when missing:
    <link rel="canonical" href="<page URL>">
    <meta property="og:type" content="website">
    <meta property="og:url" content="<page URL>">
    <meta property="og:title" content="<title>">
    <meta property="og:description" content="<meta description>">   (only if the page has one)
    <meta property="og:image" content="<site default card>">
    <meta name="twitter:card" content="summary_large_image">

Never rewrites an existing tag, never invents a description (those are written
by hand: see the report of pages lacking one). Tags go right after the meta
description, else after <title>, using the page's own indentation.
"""

import argparse
import re
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_pages, repo_path, site_config  # noqa: E402

DESC_RE = re.compile(r"""^([ \t]*)<meta\s+name=["']description["'][^>]*>[ \t]*$""", re.M | re.I)
TITLE_RE = re.compile(r"""^([ \t]*)<title>.*?</title>[ \t]*$""", re.M | re.I | re.S)


def plan_for(page, cfg):
    head, url = page["head"], page["abs"]
    tags = []
    if not head.links.get("canonical"):
        tags.append(f'<link rel="canonical" href="{url}">')
    if not head.meta.get("og:type"):
        tags.append('<meta property="og:type" content="website">')
    if not head.meta.get("og:url"):
        tags.append(f'<meta property="og:url" content="{url}">')
    if not head.meta.get("og:title") and head.title:
        tags.append(f'<meta property="og:title" content="{escape(head.title, quote=True)}">')
    if not head.meta.get("og:description") and head.meta.get("description"):
        tags.append(f'<meta property="og:description" content="{escape(head.meta["description"], quote=True)}">')
    if not head.meta.get("og:image"):
        tags.append(f'<meta property="og:image" content="{cfg["base"]}{cfg["og_image"]}">')
    if not head.meta.get("twitter:card"):
        tags.append('<meta name="twitter:card" content="summary_large_image">')
    return tags


def inject(html, tags):
    m = DESC_RE.search(html) or TITLE_RE.search(html)
    if not m:
        return None
    indent = m.group(1)
    block = "".join(f"\n{indent}{t}" for t in tags)
    return html[: m.end()] + block + html[m.end():]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True, choices=["data", "personal", "sce"])
    ap.add_argument("--repo")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cfg = site_config(args.site)
    repo = repo_path(args.site, args.repo)
    changed, tag_counts, no_desc, no_anchor, wrong = 0, {}, [], [], []
    for p in load_pages(args.site, repo):
        if p["kind"] != "live":
            continue
        if not p["head"].meta.get("description"):
            no_desc.append(p["rel"])
        canon = p["head"].links.get("canonical")
        if canon and canon != p["abs"]:
            wrong.append(f"{p['rel']}: canonical {canon}")
        tags = plan_for(p, cfg)
        if not tags:
            continue
        new_html = inject(p["html"], tags)
        if new_html is None:
            no_anchor.append(p["rel"])
            continue
        changed += 1
        for t in tags:
            key = re.search(r'(?:rel|property|name)="([^"]+)"', t).group(1)
            tag_counts[key] = tag_counts.get(key, 0) + 1
        if args.apply:
            (repo / p["rel"]).write_text(new_html, encoding="utf-8")

    verb = "updated" if args.apply else "would update"
    print(f"{cfg['base']}: {verb} {changed} page(s)")
    for k, n in sorted(tag_counts.items(), key=lambda kv: -kv[1]):
        print(f"  +{k}: {n}")
    if no_desc:
        print(f"  pages with NO meta description (write by hand): {len(no_desc)}")
        for r in no_desc:
            print(f"    {r}")
    if wrong:
        print("  existing canonical does not match the URL (fix by hand):")
        for w in wrong:
            print(f"    {w}")
    if no_anchor:
        print("  no <title> or description line to anchor on (fix by hand):")
        for r in no_anchor:
            print(f"    {r}")


if __name__ == "__main__":
    main()
