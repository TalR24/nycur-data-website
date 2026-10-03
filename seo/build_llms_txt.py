#!/usr/bin/env python3
"""
Generate a site's /llms.txt: a plain Markdown map of the site for language
models and AI search (format: https://llmstxt.org). Built from the same pages
as the sitemap, using each page's own <title> and meta description, so it adds
no new copy and cannot drift from the pages.

    python3 seo/build_llms_txt.py --site data            # write llms.txt
    python3 seo/build_llms_txt.py --site sce --check     # exit 1 if stale
    python3 seo/build_llms_txt.py --site personal --print

build_sitemap.py calls this after writing sitemap.xml, so adding or renaming a
page updates both. Layout: the homepage title as H1, its meta description as
the summary, the tool and hub pages under named sections, deeper pages (chart
subpages, methodology, legal) under "Optional", which llms.txt readers may skip.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_pages, repo_path, site_config  # noqa: E402

# Standing decision (Tal, Aug 24 2026): no search attention on these until the post is out.
HOLD = ("/nycuriosity_substack_posts/medicaid_provider_spending/",)

# First path segment -> section heading; pages deeper than `depth` go to Optional.
LAYOUT = {
    "data": {"depth": 2, "sections": [
        ("civic_reference", "NYC civic reference tools"),
        ("cb-tools", "Community board tools"),
        ("nycuriosity_substack_posts", "Data behind NYCuriosity posts"),
    ], "related": [("NYCuriosity on Substack", "https://www.nycuriosity.com/",
                    "the newsletter these data pages accompany"),
                   ("Tal Roded", "https://talroded.nycuriosity.com/", "author's site")]},
    "personal": {"depth": 1, "sections": [
        ("services", "Services"),
        ("wiki", "Wiki"),
    ], "related": [("NYCuriosity on Substack", "https://www.nycuriosity.com/", "Tal's newsletter"),
                   ("NYCuriosity data", "https://data.nycuriosity.com/", "charts and civic data tools")]},
    "sce": {"depth": 2, "sections": [
        ("ecosystem", "Ecosystem directory and map"),
        ("community", "Community"),
        ("events", "Events"),
        ("databases", "Databases"),
    ], "related": [("SCE on Substack", "https://substack.statecapacityecosystem.com/", "posts and event recaps")]},
}
OPTIONAL_HINTS = ("methodology", "privacy", "terms", "sponsors-checklist")
SUFFIX_RE = re.compile(r"\s+[—|]\s+(NYCuriosity|State Capacity Ecosystem|Tal Roded).*$")


def clean_title(t):
    return SUFFIX_RE.sub("", (t or "").strip()) or None


def build(key, repo=None):
    cfg, layout = site_config(key), LAYOUT[key]
    pages = [p for p in load_pages(key, repo) if p["kind"] == "live" and not p["url"].startswith(HOLD)]
    home = next((p for p in pages if p["url"] == "/"), None)
    title = clean_title(home["head"].title) if home else cfg["base"]
    summary = (home["head"].meta.get("description") or "").strip() if home else ""

    named = {seg: [] for seg, _ in layout["sections"]}
    main, optional = [], []
    for p in sorted(pages, key=lambda p: p["url"]):
        if p["url"] == "/":
            continue
        segs = [s for s in p["url"].strip("/").split("/") if s]
        deep = len(segs) > layout["depth"] or any(h in p["url"] for h in OPTIONAL_HINTS) or p["url"].endswith(".html")
        if deep:
            optional.append(p)
        elif segs and segs[0] in named:
            named[segs[0]].append(p)
        else:
            main.append(p)

    def line(p):
        t = clean_title(p["head"].title) or p["url"]
        d = (p["head"].meta.get("description") or "").strip()
        return f"- [{t}]({p['abs']})" + (f": {d}" if d else "")

    out = [f"# {title}", ""]
    if summary:
        out += [f"> {summary}", ""]
    if main:
        out += ["## Pages", ""] + [line(p) for p in main] + [""]
    for seg, heading in layout["sections"]:
        if named[seg]:
            out += [f"## {heading}", ""] + [line(p) for p in named[seg]] + [""]
    if layout.get("related"):
        out += ["## Related", ""] + [f"- [{t}]({u}): {d}" for t, u, d in layout["related"]] + [""]
    if optional:
        out += ["## Optional", ""] + [line(p) for p in optional] + [""]
    return "\n".join(out)


def write(key, repo=None):
    path = repo_path(key, repo) / "llms.txt"
    text = build(key, repo)
    changed = not path.exists() or path.read_text(encoding="utf-8") != text
    if changed:
        path.write_text(text, encoding="utf-8")
    return path, changed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True, choices=sorted(LAYOUT))
    ap.add_argument("--repo", help="repo path override")
    ap.add_argument("--check", action="store_true", help="exit 1 if llms.txt is stale")
    ap.add_argument("--print", action="store_true")
    args = ap.parse_args()
    text = build(args.site, args.repo)
    if args.print:
        sys.stdout.write(text)
        return
    path = repo_path(args.site, args.repo) / "llms.txt"
    if args.check:
        stale = not path.exists() or path.read_text(encoding="utf-8") != text
        print(f"{path}: {'STALE' if stale else 'up to date'}")
        sys.exit(1 if stale else 0)
    path, changed = write(args.site, args.repo)
    print(f"wrote {path} ({text.count(chr(10) + '- [')} links)" if changed else f"{path} unchanged")


if __name__ == "__main__":
    main()
