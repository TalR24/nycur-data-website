#!/usr/bin/env python3
"""
SEO checker for the NYCuriosity static sites: the pre-deploy gate and the
post-deploy production check in one script.

    python3 seo/seo_check.py --site data                 # local repo audit
    python3 seo/seo_check.py --file path/to/index.html   # one page (the hook)
    python3 seo/seo_check.py --site data --live          # production check
    python3 seo/seo_check.py --all --live --email        # weekly Action

Local mode reads git-tracked pages and reports, per page, the head-tag
contract (see common.py docstring), duplicate titles/descriptions, sitemap
coverage and stale sitemap entries, orphan pages (no inbound link from any
page, site.js menu, or related_work.json), and empty files.

Live mode fetches robots.txt, sitemap.xml and every sitemap URL from
production and verifies the served HTML: HTTP 200, title, description,
canonical equal to the URL, og:image, twitter:card. When the repo is present
locally it also confirms production title/description/canonical match the
source, which catches un-deployed or stale-cache pages.

Exit 1 when any ERROR-level finding exists (WARN-only runs exit 0).
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (SITES, inbound_links, load_pages, parse_head, repo_path,  # noqa: E402
                    send_email, site_config, site_for_path, sitemap_locs, url_path_for)

DESC_MIN, DESC_MAX = 50, 160


class Findings:
    def __init__(self):
        self.items = []  # (level, page, message)

    def error(self, page, msg):
        self.items.append(("ERROR", page, msg))

    def warn(self, page, msg):
        self.items.append(("WARN", page, msg))

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "ERROR"]

    def render(self, heading):
        if not self.items:
            return f"{heading}: OK\n"
        lines = [f"{heading}: {len(self.errors)} error(s), {len(self.items) - len(self.errors)} warning(s)"]
        for level, page, msg in sorted(self.items, key=lambda i: (i[0] != "ERROR", i[1], i[2])):
            lines.append(f"  {level:5} {page}: {msg}")
        return "\n".join(lines) + "\n"


# ------------------------------------------------------------ page checks ---

def check_head(head, url, cfg, f, page_label):
    """The head-tag contract for one live page. `url` is the absolute URL."""
    if not head.title:
        f.error(page_label, "missing <title>")
    desc = head.meta.get("description")
    if not desc:
        f.error(page_label, "missing meta description")
    elif not (DESC_MIN <= len(desc) <= DESC_MAX):
        f.warn(page_label, f"description is {len(desc)} chars (aim for {DESC_MIN}-{DESC_MAX})")
    canon = head.links.get("canonical")
    if not canon:
        f.error(page_label, "missing <link rel=\"canonical\">")
    elif canon != url:
        f.error(page_label, f"canonical is {canon}, expected {url}")
    for tag in ("og:title", "og:description", "og:url", "og:image"):
        if not head.meta.get(tag):
            f.warn(page_label, f"missing {tag}")
    if head.meta.get("og:url") and head.meta["og:url"] != url:
        f.warn(page_label, f"og:url is {head.meta['og:url']}, expected {url}")
    if head.meta.get("og:image") and not head.meta["og:image"].startswith("http"):
        f.warn(page_label, "og:image must be an absolute URL")
    if not head.meta.get("twitter:card"):
        f.warn(page_label, "missing twitter:card")
    if not head.h1:
        f.warn(page_label, "no <h1>")


def check_file(path, f):
    """Hook mode: one file, contract only. Returns False if the file is not a
    site page (excluded path, stub, unknown repo)."""
    key = site_for_path(path)
    if not key:
        return False
    cfg = site_config(key)
    rel = str(Path(path).resolve().relative_to(repo_path(key))).replace("\\", "/")
    if any(rel.startswith(p) for p in cfg["exclude"]):
        return False
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    head = parse_head(html)
    from common import classify
    kind = classify(html, head)
    if kind == "empty":
        f.error(rel, "empty file: this serves as a blank page")
        return True
    if kind == "stub":
        return False
    check_head(head, cfg["base"] + url_path_for(rel), cfg, f, rel)
    return True


def check_site_local(key, repo=None, f=None):
    f = f or Findings()
    cfg = site_config(key)
    repo = repo_path(key, repo)
    pages = load_pages(key, repo)
    live = [p for p in pages if p["kind"] == "live"]

    for p in pages:
        if p["kind"] == "empty":
            f.error(p["rel"], "empty file: this serves as a blank page (make it a redirect stub or delete it)")
    for p in live:
        check_head(p["head"], p["abs"], cfg, f, p["rel"])

    # uniqueness
    for field, getter in (("title", lambda p: p["head"].title),
                          ("description", lambda p: p["head"].meta.get("description"))):
        seen = {}
        for p in live:
            v = getter(p)
            if v:
                seen.setdefault(v, []).append(p["rel"])
        for v, rels in seen.items():
            if len(rels) > 1:
                for r in rels:
                    f.warn(r, f"duplicate {field} shared with {len(rels) - 1} other page(s): \"{v[:60]}\"")

    # sitemap coverage
    smap = repo / "sitemap.xml"
    if not smap.exists():
        f.error("sitemap.xml", "missing (run seo/build_sitemap.py)")
    else:
        locs = set(sitemap_locs(smap.read_text(encoding="utf-8")))
        expected = {p["abs"] for p in live}
        for u in sorted(expected - locs):
            f.error("sitemap.xml", f"live page not listed: {u} (run seo/build_sitemap.py)")
        for u in sorted(locs - expected):
            f.error("sitemap.xml", f"stale entry (not a live page): {u} (run seo/build_sitemap.py)")
    robots = repo / "robots.txt"
    if not robots.exists():
        f.error("robots.txt", "missing")
    elif "sitemap:" not in robots.read_text(encoding="utf-8").lower():
        f.warn("robots.txt", "has no Sitemap: line")

    # orphans
    inbound = inbound_links(key, pages, repo)
    for p in live:
        if p["url"] != "/" and not inbound.get(p["url"]):
            f.warn(p["rel"], "orphan: no inbound link from any page, site.js menu, or related_work.json")
    return f


# ------------------------------------------------------------- live mode ---

def fetch(session, url):
    try:
        r = session.get(url, timeout=25, headers={"User-Agent": "nycuriosity-seo-check/1.0"})
        return r.status_code, r.text
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def check_site_live(key, repo=None, f=None):
    import requests
    f = f or Findings()
    cfg = site_config(key)
    base = cfg["base"]
    session = requests.Session()

    status, robots = fetch(session, base + "/robots.txt")
    if status != 200:
        f.error("robots.txt", f"HTTP {status}")
    elif "sitemap:" not in robots.lower():
        f.warn("robots.txt", "has no Sitemap: line")
    if status == 200 and "disallow: /\n" in robots.lower().replace("\r", ""):
        f.error("robots.txt", "Disallow: / blocks the whole site")

    status, smap = fetch(session, base + "/sitemap.xml")
    if status != 200:
        f.error("sitemap.xml", f"HTTP {status}")
        return f
    locs = sitemap_locs(smap)
    if not locs:
        f.error("sitemap.xml", "no <loc> entries")
        return f

    local = {}
    rp = repo_path(key, repo)
    if rp.exists():
        for p in load_pages(key, rp):
            local[p["abs"]] = p
        local_xml = rp / "sitemap.xml"
        if local_xml.exists() and set(sitemap_locs(local_xml.read_text(encoding="utf-8"))) != set(locs):
            f.error("sitemap.xml", "production sitemap differs from the repo (deploy pending or stale cache)")

    def one(url):
        status, html = fetch(session, url)
        return url, status, html

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(one, locs))

    for url, status, html in results:
        label = url.replace(base, "") or "/"
        if status != 200:
            f.error(label, f"HTTP {status}")
            continue
        if len(html.strip()) < 200:
            f.error(label, "blank page served")
            continue
        head = parse_head(html)
        check_head(head, url, cfg, f, label)
        lp = local.get(url)
        if lp:
            for field, live_v, src_v in (
                ("title", head.title, lp["head"].title),
                ("description", head.meta.get("description"), lp["head"].meta.get("description")),
                ("canonical", head.links.get("canonical"), lp["head"].links.get("canonical")),
            ):
                if src_v and live_v != src_v:
                    f.error(label, f"production {field} differs from repo (deploy pending or stale cache)")
    return f


# ------------------------------------------------------------------ main ---

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", choices=list(SITES))
    ap.add_argument("--all", action="store_true", help="every site")
    ap.add_argument("--file", help="check one HTML file (hook mode)")
    ap.add_argument("--repo", help="repo path override")
    ap.add_argument("--live", action="store_true", help="check production instead of the repo")
    ap.add_argument("--email", action="store_true", help="email the report to Tal when there are errors")
    ap.add_argument("--subject", default="SEO check: problems on the live sites")
    args = ap.parse_args()

    if args.file:
        f = Findings()
        if check_file(args.file, f):
            sys.stdout.write(f.render(args.file))
        sys.exit(1 if f.errors else 0)

    keys = list(SITES) if args.all else ([args.site] if args.site else None)
    if not keys:
        ap.error("--site, --all, or --file is required")

    report, any_errors = [], False
    for key in keys:
        cfg = site_config(key)
        f = check_site_live(key, args.repo) if args.live else check_site_local(key, args.repo)
        report.append(f.render(f"{cfg['base']} ({'live' if args.live else 'repo'})"))
        any_errors = any_errors or bool(f.errors)
    text = "\n".join(report)
    sys.stdout.write(text)
    if any_errors and args.email:
        send_email(args.subject, text)
    sys.exit(1 if any_errors else 0)


if __name__ == "__main__":
    main()
