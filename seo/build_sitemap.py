#!/usr/bin/env python3
"""
Regenerate a site's sitemap.xml from its git-tracked HTML pages.

    python3 seo/build_sitemap.py --site data            # rewrite sitemap.xml
    python3 seo/build_sitemap.py --site data --check    # exit 1 if it is stale
    python3 seo/build_sitemap.py --site personal --print

Included: every tracked .html page that is not excluded in common.SITES, not a
redirect stub (noindex / http-equiv refresh), and not an empty file.
<lastmod> is the file's last commit date. No <changefreq>/<priority>: Google
ignores both and they only invited hand-editing.

Run this whenever a page is added, removed, or renamed (the seo_check.py
"sitemap" check fails until you do).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import git_lastmod, load_pages, repo_path, site_config, sitemap_locs  # noqa: E402


def expected_entries(key, repo=None):
    """[(abs_url, lastmod)] for every page that belongs in the sitemap, and the
    list of empty pages found along the way."""
    pages = load_pages(key, repo)
    repo = repo_path(key, repo)
    entries, empty = [], []
    for p in pages:
        if p["kind"] == "empty":
            empty.append(p["rel"])
        if p["kind"] != "live":
            continue
        entries.append((p["abs"], git_lastmod(repo, p["rel"])))
    entries.sort(key=lambda e: (e[0].count("/"), e[0]))
    return entries, empty


def render(entries):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, lastmod in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>{url}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def diff_against_existing(key, entries, repo=None):
    """(missing, stale) URL lists relative to the sitemap on disk."""
    path = repo_path(key, repo) / "sitemap.xml"
    existing = set(sitemap_locs(path.read_text(encoding="utf-8"))) if path.exists() else set()
    expected = {u for u, _ in entries}
    return sorted(expected - existing), sorted(existing - expected)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True, choices=["data", "personal", "sce"])
    ap.add_argument("--repo", help="repo path override (default: sibling folder in the nycur workspace)")
    ap.add_argument("--check", action="store_true", help="report drift, do not write; exit 1 if stale")
    ap.add_argument("--print", action="store_true", help="print the sitemap instead of writing it")
    args = ap.parse_args()

    cfg = site_config(args.site)
    entries, empty = expected_entries(args.site, args.repo)
    for rel in empty:
        print(f"WARNING: {rel} is an empty file (served as a blank page); excluded from the sitemap", file=sys.stderr)

    missing, stale = diff_against_existing(args.site, entries, args.repo)
    if args.check:
        for u in missing:
            print(f"MISSING from sitemap: {u}")
        for u in stale:
            print(f"STALE in sitemap:    {u}")
        print(f"{cfg['base']}: {len(entries)} expected, {len(missing)} missing, {len(stale)} stale")
        sys.exit(1 if (missing or stale) else 0)

    xml = render(entries)
    if args.print:
        sys.stdout.write(xml)
        return
    out = repo_path(args.site, args.repo) / "sitemap.xml"
    out.write_text(xml, encoding="utf-8")
    print(f"wrote {out} ({len(entries)} URLs; +{len(missing)} added, -{len(stale)} removed)")


if __name__ == "__main__":
    main()
