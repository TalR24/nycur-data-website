#!/usr/bin/env python3
"""
Shared helpers for the NYCuriosity SEO tooling (build_sitemap.py, seo_check.py,
gsc_pull.py, backfill_head.py).

Three static sites share these scripts. Each is a sibling repo under the nycur
workspace and deploys from `main` via GitHub Pages, so "a page" means a
git-tracked .html file and its URL is its repo path.

    python3 seo/build_sitemap.py --site data
    python3 seo/seo_check.py --site personal
    python3 seo/seo_check.py --site sce --live

Head-tag contract every live (indexable) page must satisfy, in order of
severity:

    ERROR   <title>, <meta name="description">, <link rel="canonical"> that
            equals the page's own URL, listed in sitemap.xml, non-empty file
    WARN    og:title / og:description / og:url / og:image, twitter:card,
            description length 50-160 chars, at least one inbound internal link

Redirect stubs (noindex + http-equiv refresh) are exempt from everything and
must stay out of the sitemap.
"""

import json
import os
import re
import smtplib
import subprocess
from email.mime.text import MIMEText
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

WORKSPACE = Path(__file__).resolve().parents[2]

SITES = {
    "data": {
        "repo": "data_website",
        "base": "https://data.nycuriosity.com",
        "og_image": "/website_logo.png",
        # paths (prefix match on the repo-relative path) never listed or checked
        "exclude": ("members/", "new/", "tiktok-callback/", "site_health/",
                    "pipeline/", "seo/", ".github/"),
        "gsc_host": "data.nycuriosity.com",
    },
    "personal": {
        "repo": "personal_website",
        "base": "https://talroded.nycuriosity.com",
        "og_image": "/og_card.png",
        "exclude": ("scripts/", ".github/"),
        "gsc_host": "talroded.nycuriosity.com",
    },
    "sce": {
        "repo": "statecapacityecosystem",
        "base": "https://statecapacityecosystem.com",
        "og_image": "/assets/sce_logo.png",
        "exclude": ("404.html", ".github/"),
        "gsc_host": "statecapacityecosystem.com",
    },
}

ALERT_TO = "troded24@gmail.com"

EMPTY_PAGE_BYTES = 200  # anything smaller is a broken/blank page, not content


def site_config(key):
    if key not in SITES:
        raise SystemExit(f"unknown site '{key}'; choose from {', '.join(SITES)}")
    return SITES[key]


def repo_path(key, override=None):
    if override:
        return Path(override).resolve()
    return WORKSPACE / SITES[key]["repo"]


def site_for_path(path):
    """Which site key a local file belongs to, or None."""
    p = Path(path).resolve()
    for key, cfg in SITES.items():
        try:
            p.relative_to(WORKSPACE / cfg["repo"])
            return key
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- pages ----

def tracked_html(repo):
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.html"],
        cwd=repo, capture_output=True, check=True,
    ).stdout.decode()
    return sorted(p for p in out.split("\0") if p)


def is_excluded(rel, cfg):
    return any(rel.startswith(pref) for pref in cfg["exclude"])


def url_path_for(rel):
    """Repo-relative file path -> URL path (`/dir/` for index.html)."""
    rel = rel.replace(os.sep, "/")
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


def git_lastmod(repo, rel):
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", rel],
        cwd=repo, capture_output=True, text=True,
    ).stdout.strip()
    return out or None


class HeadParser(HTMLParser):
    """Collects the head tags that matter. Only looks inside <head>; if a page
    has no <head> tag it collects until <body>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_head = False
        self.seen_head = False
        self.done = False
        self._in_title = False
        self.title = None
        self.meta = {}      # name/property -> content (first wins)
        self.links = {}     # rel -> href (first wins)
        self.refresh = False
        self.h1 = []
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self._in_h1 = True
            self.h1.append("")
            return
        if self.done:
            return
        a = dict(attrs)
        if tag == "head":
            self.in_head = True
            self.seen_head = True
            return
        if tag == "body":
            self.in_head = False
            self.done = True
            return
        if not self.in_head and self.seen_head:
            return
        if tag == "title":
            self._in_title = True
            if self.title is None:
                self.title = ""
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").strip().lower()
            if key and key not in self.meta:
                self.meta[key] = (a.get("content") or "").strip()
            if (a.get("http-equiv") or "").lower() == "refresh":
                self.refresh = True
        elif tag == "link":
            rel = (a.get("rel") or "").strip().lower()
            if rel and rel not in self.links:
                self.links[rel] = (a.get("href") or "").strip()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self.in_head = False
            self.done = True
        elif tag == "h1":
            self._in_h1 = False

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
        if self._in_h1 and self.h1:
            self.h1[-1] += data


def parse_head(html):
    p = HeadParser()
    try:
        p.feed(html)
    except Exception:
        pass
    if p.title is not None:
        p.title = re.sub(r"\s+", " ", p.title).strip()
    p.h1 = [re.sub(r"\s+", " ", h).strip() for h in p.h1 if h.strip()]
    return p


def classify(html, head=None):
    """'stub' for noindex/refresh redirect pages, 'empty' for blank files,
    else 'live'."""
    if len(html.strip()) < EMPTY_PAGE_BYTES:
        return "empty"
    head = head or parse_head(html)
    robots = (head.meta.get("robots") or "").lower()
    if "noindex" in robots or head.refresh:
        return "stub"
    return "live"


def load_pages(key, repo=None):
    """All tracked, non-excluded HTML pages of a site.

    Returns list of dicts: rel, url (path), abs (full URL), kind
    (live/stub/empty), head (HeadParser), html.
    """
    cfg = site_config(key)
    repo = repo_path(key, repo)
    pages = []
    for rel in tracked_html(repo):
        if is_excluded(rel, cfg):
            continue
        html = (repo / rel).read_text(encoding="utf-8", errors="replace")
        head = parse_head(html)
        pages.append({
            "rel": rel,
            "url": url_path_for(rel),
            "abs": cfg["base"] + url_path_for(rel),
            "kind": classify(html, head),
            "head": head,
            "html": html,
        })
    return pages


# ---------------------------------------------------------------- links ----

HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#]+)""", re.I)
JS_HREF_RE = re.compile(r"""href\s*:\s*['"](/[^'"]*)['"]""")


def normalize_internal(href, page_url, base):
    """Resolve an href found on `page_url` to a site URL path, or None if it
    points off-site / to a non-page."""
    href = href.strip()
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    full = urljoin(base + page_url, href)
    parts = urlsplit(full)
    if parts.netloc and parts.netloc != urlsplit(base).netloc:
        return None
    path = parts.path or "/"
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    if not path.startswith("/"):
        path = "/" + path
    return path


def inbound_links(key, pages, repo=None):
    """Map url path -> set of referring url paths (or 'site.js' /
    'related_work.json' for the shared chrome registries)."""
    cfg = site_config(key)
    repo = repo_path(key, repo)
    base = cfg["base"]
    inbound = {p["url"]: set() for p in pages}
    for p in pages:
        for href in HREF_RE.findall(p["html"]):
            target = normalize_internal(href, p["url"], base)
            if target in inbound and target != p["url"]:
                inbound[target].add(p["url"])
    site_js = repo / "assets" / "site.js"
    if site_js.exists():
        for href in JS_HREF_RE.findall(site_js.read_text(encoding="utf-8")):
            t = normalize_internal(href, "/", base)
            if t in inbound:
                inbound[t].add("site.js")
    related = repo / "assets" / "related_work.json"
    if related.exists():
        try:
            data = json.loads(related.read_text(encoding="utf-8"))
            for entries in data.values():
                for e in entries:
                    t = normalize_internal(e.get("href", ""), "/", base)
                    if t in inbound:
                        inbound[t].add("related_work.json")
        except json.JSONDecodeError:
            pass
    return inbound


# -------------------------------------------------------------- sitemap ----

LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def sitemap_locs(text):
    return [loc.strip() for loc in LOC_RE.findall(text)]


# ---------------------------------------------------------------- email ----

def send_email(subject, body, to=ALERT_TO):
    """Gmail SMTP, same secrets as site_health/check_site.py. Returns True when
    sent, False (with a note on stderr) when credentials are absent."""
    user = os.environ.get("GMAIL_USER")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and pw):
        print("EMAIL NOT SENT: GMAIL_USER / GMAIL_APP_PASSWORD not set", flush=True)
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())
    return True
