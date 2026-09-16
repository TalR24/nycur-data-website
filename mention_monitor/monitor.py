#!/usr/bin/env python3
"""Mention monitor for Tal Roded / NYCuriosity.

Daily: fetches Google News RSS for the name/brand/tracker queries, scans a
fixed list of outlet RSS feeds (full text) for the figure queries and for
any link back to nycuriosity.com, dedupes against a local SQLite db, and
queues newly-flagged items as "pending". Sunday (or --digest): builds a
digest from everything pending, writes it to digests/YYYY-MM-DD.md, marks
those items digested, and optionally emails it. Tal's own bylines
(Streetsblog, Vital City guest posts, Searchlight columns, etc.) are
routed to a separate "My own pieces" section rather than dropped, so a real
outside citation is never missed because it looked like an own-property
hit. Real third-party citations of Tal's academic work (NBER, Cato, Fed
research banks, etc.) get their own "Research citations" section instead
of being dropped as noise or mistaken for a name collision.

Usage:
  python3 monitor.py                  # daily collect only: fetch, dedupe,
                                      #   queue newly-flagged items as pending
  python3 monitor.py --digest         # collect, then build+write the digest
                                      #   from all pending items, mark them
                                      #   digested
  python3 monitor.py --digest --email # same, plus email the digest
  python3 monitor.py --backfill       # seed the seen-db from ~90 days back;
                                      #   no pending items, no digest, no email
  python3 monitor.py --referrers-only # run only the Cloudflare referrer
                                      #   source; print rows or the exact
                                      #   GraphQL error, no db writes

Email (only used with --digest --email; all optional otherwise):
  GMAIL_USER / GMAIL_APP_PASSWORD     # same secrets the other repo pipelines use
  MENTION_DIGEST_TO                   # recipient; defaults to GMAIL_USER

Cloudflare Web Analytics referrer report (dormant until both secrets exist):
  CF_ANALYTICS_TOKEN / CF_ACCOUNT_ID  # optional; silently skipped without them
  CF_WA_SITE_TAG                      # optional: scope to one Web Analytics site

Dedup notes: Google News RSS links are opaque redirects that can't be decoded
offline, so each item is keyed on BOTH its normalized URL and an
outlet-domain + title fingerprint. An item counts as new only if no key has
been seen before.
"""

import argparse
import calendar
import hashlib
import html as html_mod
import json
import os
import re
import smtplib
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

import feedparser
import requests

HERE = Path(__file__).resolve().parent
SESSION = requests.Session()
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# One shared per-run wall-clock deadline (item P1.3), set by main() from
# `run_time_budget_seconds` (default 900s) before any source runs. None
# means "no shared budget" (e.g. in unit tests that never set it).
RUN_DEADLINE = None


class RunBudgetExceeded(RuntimeError):
    pass


def set_run_budget(cfg, start=None):
    """Set the shared per-run deadline. Call once at the top of a run."""
    global RUN_DEADLINE
    start = start or time.monotonic()
    RUN_DEADLINE = start + float(cfg.get("run_time_budget_seconds", 900))


def clear_run_budget():
    global RUN_DEADLINE
    RUN_DEADLINE = None


def check_run_budget():
    """Raise RunBudgetExceeded if the shared per-run deadline has passed.
    Called before every network call (http_get, plus the few raw SESSION
    calls), so no source can run past the shared budget."""
    if RUN_DEADLINE is not None and time.monotonic() > RUN_DEADLINE:
        raise RunBudgetExceeded(
            f"run_time_budget_seconds exceeded (deadline was {RUN_DEADLINE:.0f} "
            "monotonic seconds)")

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
# Google News opaque links no longer HTTP-redirect (200 at the same URL as
# of Sep 2026); resolve_google_news_url decodes the page's batchexecute
# payload instead, which requires a browser User-Agent.
GOOGLE_NEWS_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
CF_GRAPHQL = "https://api.cloudflare.com/client/v4/graphql"

TIER_ORDER = [
    ("news", "News outlets"),
    ("newsletter", "Newsletters & blogs"),
    ("social", "Social"),
]


# ---------------------------------------------------------------- utilities

def norm_domain(netloc):
    d = (netloc or "").lower().split(":")[0]
    return d[4:] if d.startswith("www.") else d


def domain_matches(domain, base):
    return domain == base or domain.endswith("." + base)


def host_ignored(host, ignore_list):
    """True if `host` matches an entry in `ignore_list`. An entry is either
    a full host / parent domain (matched via domain_matches, so "t.co" or
    "substack.com" also covers its subdomains), or a label prefix like
    "google." which matches any host whose dot-split labels include that
    label at any position (www.google.com, google.co.uk, but not
    notgoogle.com)."""
    host = (host or "").lower()
    if not host:
        return False
    labels = host.split(".")
    for entry in ignore_list:
        entry = entry.lower().strip()
        if not entry:
            continue
        if entry.endswith("."):
            if entry[:-1] in labels:
                return True
        elif domain_matches(host, entry):
            return True
    return False


def normalize_title(title):
    """Casefold, strip punctuation/curly quotes and a leading "OPINION:"
    label, collapse whitespace. Used only for own-byline title matching."""
    t = (title or "")
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = re.sub(r"^\s*opinion\s*:\s*", "", t, flags=re.I)
    t = re.sub(r"[^\w\s]", " ", t.casefold())
    return re.sub(r"\s+", " ", t).strip()


def _is_tracking_param(k):
    k = k.lower()
    return k.startswith("utm_") or k in {
        "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src",
        "smid", "cmpid", "r", "s", "sk", "share",
    }


def normalize_url(url):
    """Canonical form used only for dedup keys; displayed URLs stay raw."""
    url = (url or "").strip()
    try:
        p = urlparse(url)
    except ValueError:
        return url.lower()
    domain = norm_domain(p.netloc)
    path = re.sub(r"/+$", "", p.path) or "/"
    kept = sorted(
        (k, v)
        for k, vs in parse_qs(p.query, keep_blank_values=True).items()
        if not _is_tracking_param(k)
        for v in vs
    )
    query = urlencode(kept)
    return f"{domain}{path}" + (f"?{query}" if query else "")


def title_fingerprint(domain, title):
    t = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    return "t:" + hashlib.sha1(f"{domain}|{t}".encode()).hexdigest()


def item_keys(item):
    keys = set()
    eff_url = effective_url(item)
    if eff_url:
        keys.add("u:" + hashlib.sha1(normalize_url(eff_url).encode()).hexdigest())
    if item["title"]:
        keys.add(title_fingerprint(item["domain"], item["title"]))
    return keys


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html_mod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_feed_date(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t:
        return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


def parse_iso(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return to_utc(dt)


def to_utc(dt):
    """Normalize any parsed datetime to UTC-aware. Naive datetimes (e.g. from
    OpenAlex publication_date, which is date-only) are assumed UTC. This is
    the single place every source's date must pass through before it is
    stored, compared, or sorted, so mixed naive/aware datetimes never reach
    a sort key (see the digest-sort TypeError this fixes)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sort_key_published(item):
    """Sort key for digest ordering: robust to None and to any datetime that
    slipped through without tz info."""
    dt = item.get("published")
    if dt is None:
        return EPOCH
    return to_utc(dt)


def http_get(url, params=None, timeout=30, retries=3):
    """GET with retry/backoff on rate limits and transient server errors."""
    last = None
    for attempt in range(retries):
        check_run_budget()
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = RuntimeError(f"HTTP {r.status_code} from {urlparse(url).netloc}")
            try:
                wait = float(r.headers.get("Retry-After", ""))
            except ValueError:
                wait = 4.0 * (attempt + 1)
            time.sleep(min(wait, 30))
            continue
        r.raise_for_status()
        return r
    raise last


def make_item(source, query_id, outlet, domain, title, url, published, text):
    return {
        "sources": {source},
        "queries": {query_id},
        "outlet": outlet,
        "domain": domain,
        "title": title,
        "url": url,
        # For most sources this is just `url`; for google_news it is the
        # real outlet URL resolved from the opaque news.google.com
        # redirect (see resolve_google_news_url / effective_url).
        "resolved_url": url,
        "published": published,
        "text": text,
    }


def effective_url(item):
    """The URL to use for dedupe keys, exclusions, own-byline matching,
    never_feature, already-listed checks, and the digest link: the
    resolved real-outlet URL when one exists, otherwise `url` itself."""
    return item.get("resolved_url") or item["url"]


# ------------------------------------------------------- query text matching

def query_matches_text(query, text_lower):
    """True if a query's match_terms are present, its require_terms (if any)
    are satisfied, and none of its exclude_terms are present. All checks are
    OR-within-list, case-insensitive, against already-lowercased text."""
    match_terms = [t.lower() for t in query.get("match_terms", [])]
    if match_terms and not any(t in text_lower for t in match_terms):
        return False
    require = [t.lower() for t in query.get("require_terms", [])]
    if require and not any(t in text_lower for t in require):
        return False
    exclude = [t.lower() for t in query.get("exclude_terms", [])]
    if exclude and any(t in text_lower for t in exclude):
        return False
    return True


def passes_require_terms(item, queries_by_id):
    """Second-pass gate applied to every item regardless of source: keep it
    if ANY of its matched queries is satisfied (require_terms present,
    exclude_terms absent) against the item's own title/text."""
    hay = f'{item["title"]} {item["text"]}'.lower()
    for qid in item["queries"]:
        q = queries_by_id.get(qid, {})
        exclude = [t.lower() for t in q.get("exclude_terms", [])]
        if exclude and any(t in hay for t in exclude):
            continue
        require = [t.lower() for t in q.get("require_terms", [])]
        if not require or any(t in hay for t in require):
            return True
    return False


# ----------------------------------------------------------------- fetchers

def resolve_google_news_url(url, timeout=15, conn=None):
    """Google News RSS links are opaque news.google.com redirects. As of
    Sep 2026 they no longer HTTP-redirect (200 at the same URL), so decode
    the article page's embedded signature/timestamp and replay Google's
    own batchexecute call to get the real outlet URL. Returns
    (resolved_url, error_or_None); on any failure (this is an undocumented,
    unstable flow) the caller keeps using the original opaque URL and the
    error is returned, never raised and never treated as a source error by
    the caller. Resolutions are cached in `conn` (google_news_url_cache) so
    a given link is only decoded once, ever."""
    if not url or "news.google.com" not in url:
        return url, None
    cached = cached_google_news_resolution(conn, url)
    if cached:
        return cached, None
    headers = {"User-Agent": GOOGLE_NEWS_BROWSER_UA}
    try:
        check_run_budget()
        aid = urlparse(url).path.split("/")[-1]
        r = SESSION.get(f"https://news.google.com/articles/{aid}", timeout=timeout,
                         headers=headers)
        sg = re.search(r'data-n-a-sg="([^"]+)"', r.text)
        ts = re.search(r'data-n-a-ts="([^"]+)"', r.text)
        if not (sg and ts):
            return url, "could not find data-n-a-sg/data-n-a-ts on article page"
        inner = [
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None,
              None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            aid, int(ts.group(1)), sg.group(1),
        ]
        req = [[["Fbv4je", json.dumps(inner), None, "generic"]]]
        check_run_budget()
        p = SESSION.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={**headers,
                     "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data="f.req=" + quote(json.dumps(req)), timeout=timeout,
        )
        m = re.search(r'\[\\"garturlres\\",\\"(https?://[^\\"]+)', p.text)
        if not m:
            return url, "batchexecute response did not contain garturlres"
        resolved = m.group(1)
        cache_google_news_resolution(conn, url, resolved,
                                      datetime.now(timezone.utc).isoformat())
        return resolved, None
    except Exception as e:  # noqa: BLE001
        return url, str(e)


def fetch_google_news(query, cfg, since, errors=None, conn=None, delay=0.0):
    q = query["q"] + (f" after:{since:%Y-%m-%d}" if since else "")
    r = http_get(GOOGLE_NEWS_RSS, params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    items = []
    for e in feedparser.parse(r.content).entries:
        src = e.get("source") or {}
        outlet = src.get("title") or ""
        domain = norm_domain(urlparse(src.get("href") or "").netloc) or "news.google.com"
        title = e.get("title") or ""
        # Google appends " - Outlet" to titles; strip it so title fingerprints
        # line up with the same article coming from another source.
        if outlet and title.endswith(" - " + outlet):
            title = title[: -len(" - " + outlet)]
        summary = strip_html(e.get("summary"))
        if summary.startswith(title):
            leftover = summary[len(title):].strip(" -–—.")
            summary = "" if leftover in ("", outlet) else leftover
        link = e.get("link") or ""
        # Resolution is undocumented and may break; a failure is never a
        # source error (must-fix 2), only counted in the run summary line
        # (see collect()'s "google_news: N links unresolved").
        resolved, _resolve_err = resolve_google_news_url(link, conn=conn)
        if delay:
            time.sleep(delay)
        item = make_item(
            "google_news", query["id"], outlet or domain, domain, title,
            link, parse_feed_date(e), summary,
        )
        item["resolved_url"] = resolved
        items.append(item)
    return items


FETCHERS = {
    "google_news": fetch_google_news,
}


# --------------------------------------------------------- outlet full-text

def extract_author(entry, html_text=""):
    """Best-effort author from a feedparser entry (dc:creator / author /
    authors[]) or, failing that, an article page's <meta name="author"> or
    a naive JSON-LD Person.name match."""
    author = ""
    if entry is not None:
        author = entry.get("author") or ""
        if not author and entry.get("authors"):
            try:
                author = entry["authors"][0].get("name", "")
            except (IndexError, AttributeError, TypeError):
                author = ""
    if not author and html_text:
        m = re.search(
            r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)["\']',
            html_text, re.I,
        )
        if m:
            author = m.group(1)
        else:
            m2 = re.search(r'"author"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"', html_text)
            if m2:
                author = m2.group(1)
    return html_mod.unescape(author).strip()


def find_own_links(html_text, own_link_domains):
    """Every href in the page/feed HTML whose host is one of
    own_link_domains (or a subdomain of one), in document order, deduped.
    Tracker targeting needs every own link on the page (item 14), not just
    the first, since a piece can link both a tracker page and something
    else of Tal's."""
    if not html_text or not own_link_domains:
        return []
    seen, links = set(), []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html_text):
        href = html_mod.unescape(m.group(1))
        domain = norm_domain(urlparse(href).netloc)
        if domain and any(domain_matches(domain, d) for d in own_link_domains) and href not in seen:
            seen.add(href)
            links.append(href)
    return links


def find_own_link(html_text, own_link_domains):
    """First own-domain href, or None. Kept for the single-link snippet/
    dedupe-signal use sites; see find_own_links for tracker targeting."""
    links = find_own_links(html_text, own_link_domains)
    return links[0] if links else None


def context_from_html(html_text, own_link_domains, match_terms, width=340):
    """Context snippet around the first own-domain link anchor, or (failing
    that) around the first matched term. Extracted from the stripped text
    only: the anchor's own href/HTML never contributes characters to a
    returned snippet, so a snippet can never contain a stray "<" or an
    attribute fragment cut out of raw markup."""
    text = strip_html(html_text)
    low = text.lower()

    def snippet_at(i, n):
        start = max(0, i - width // 2)
        end = min(len(text), i + n + width // 2)
        return text[start:end]

    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                          html_text, re.I | re.S):
        href = html_mod.unescape(m.group(1))
        domain = norm_domain(urlparse(href).netloc)
        if not (domain and any(domain_matches(domain, d) for d in own_link_domains)):
            continue
        anchor_text = strip_html(m.group(2)).strip()
        if anchor_text:
            i = low.find(anchor_text.lower())
            if i >= 0:
                return snippet_at(i, len(anchor_text))
        break  # own-domain anchor found but its text isn't locatable in the
        # stripped text (e.g. an image link); fall through to term matching
        # rather than ever touching the raw HTML.

    for term in sorted(set(match_terms), key=len, reverse=True):
        i = low.find(term.lower())
        if i >= 0:
            return snippet_at(i, len(term))
    return text[:220]


def extract_article_body_text(html_text):
    """Stripped text of just the article body: a JSON-LD "articleBody"
    value if present, else the first <article> or <main> element, else the
    whole page as a last resort (some sites use neither). Paywall
    detection must measure the article itself, not the whole page (nav,
    footer, and a paywall's own "subscribe" copy can easily clear a
    whole-page length threshold even when the actual article is blocked)."""
    m = re.search(r'"articleBody"\s*:\s*"((?:[^"\\]|\\.)*)"', html_text, re.S)
    if m:
        body = m.group(1).encode("utf-8").decode("unicode_escape")
        return strip_html(body)
    m = re.search(r'<article\b[^>]*>(.*?)</article>', html_text, re.I | re.S)
    if not m:
        m = re.search(r'<main\b[^>]*>(.*?)</main>', html_text, re.I | re.S)
    if m:
        return strip_html(m.group(1))
    return strip_html(html_text)


RELATED_BLOCK_RE = re.compile(
    r'<(div|section|ul|li)\b[^>]*\b(?:class|id)\s*=\s*["\'][^"\']*'
    r'(?:related|recommended|jp-relatedposts|sharedaddy)[^"\']*["\'][^>]*>.*?</\1>',
    re.I | re.S,
)
ASIDE_RE = re.compile(r'<aside\b[^>]*>.*?</aside>', re.I | re.S)


def strip_related_blocks(html_text):
    """Drop related-posts / recommended / sharing sidebar blocks before
    matching, so a feed's "you might also like" links to Tal's own op-ed
    don't get an unrelated article flagged as an outside citation. Covers
    both the class/id-named convention (Jetpack's jp-relatedposts,
    sharedaddy) and plain semantic <aside> wrappers (e.g. Streetsblog's
    "Recommended" block, whose heading text says "Recommended" but whose
    own tag/class carries no such keyword)."""
    if not html_text:
        return html_text
    text = ASIDE_RE.sub(" ", html_text)
    for _ in range(5):  # a couple of passes handles adjacent/nested blocks
        new = RELATED_BLOCK_RE.sub(" ", text)
        if new == text:
            break
        text = new
    return text


def fetch_outlets(cfg, queries, delay, conn=None, cap_override=None):
    """Scan every configured outlet feed once (not per query). An item is
    flagged when a link back to nycuriosity.com/nycuriosity.substack.com is
    found in the page/feed HTML, or when any of `queries` matches the full
    text. Article pages are fetched (politely, capped) when the feed entry
    has no usable full text (content:encoded missing or under 800 chars);
    an outlet's `fetch_article: false` disables fetching even then, and
    `fetch_article: true` forces it. URLs already recorded in the `scanned`
    table are skipped entirely (this is what stops a daily re-fetch of the
    same feed entries once a feed's window has been scanned before).
    Returns (items, errors, outlet_stats) where outlet_stats maps outlet
    name -> {"available": n, "scanned": n, "skipped_prescanned": n}."""
    own_link_domains = cfg.get("own_link_domains", [])
    own_byline_urls = {normalize_url(u) for u in cfg.get("own_byline_urls", [])}
    cap = cap_override if cap_override is not None else cfg.get("max_article_fetches", 60)
    # Hard wall-clock budget on top of the fetch cap: a slow/hanging outlet
    # must not stall the whole run. Checked before every article fetch, so
    # the worst case is one in-flight request past the deadline, never an
    # unbounded loop.
    deadline = time.monotonic() + float(cfg.get("outlet_time_budget_seconds", 90))
    budget_hit = False
    fetched_articles = 0
    items, errors = [], []
    outlet_stats = {}
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    outlets = cfg.get("outlets", [])
    # Rotate the start each day so a feed near the end of the list isn't
    # permanently starved when the cap/budget runs out before reaching it.
    if outlets:
        start = datetime.now(timezone.utc).timetuple().tm_yday % len(outlets)
        outlets = outlets[start:] + outlets[:start]

    for outlet in outlets:
        stats = outlet_stats.setdefault(
            outlet["name"], {"available": 0, "scanned": 0, "skipped_prescanned": 0})
        # The deadline only ever gates article fetches below (needs_fetch);
        # a feed whose entries already carry full text costs no fetch
        # budget and must always be processed, even past the deadline.
        try:
            r = http_get(outlet["feed"], timeout=15, retries=2)
        except Exception as e:  # noqa: BLE001 (one dead feed, never fatal)
            errors.append(f"outlets/{outlet['name']}: {e}")
            stats["errored"] = True
            continue
        parsed = feedparser.parse(r.content)
        cap_skipped = 0
        discovered_cap = outlet.get("discovered_cap")
        processed_this_outlet = 0
        for e in parsed.entries:
            link = e.get("link") or ""
            if not link:
                continue
            stats["available"] += 1
            if conn is not None and is_scanned(conn, link):
                stats["skipped_prescanned"] += 1
                continue
            if discovered_cap is not None and processed_this_outlet >= discovered_cap:
                # A discovered high-volume outlet cannot blow the shared
                # run/fetch budget: cap its per-run entries, not marked
                # scanned so it's retried (not lost) next run.
                cap_skipped += 1
                continue
            processed_this_outlet += 1
            domain = norm_domain(urlparse(link).netloc)
            title = e.get("title") or ""
            published = parse_feed_date(e)
            content_list = e.get("content") or []
            full_html = content_list[0].get("value", "") if content_list else ""
            if not full_html:
                full_html = e.get("summary") or ""
            author = extract_author(e)

            needs_fetch = len(strip_html(full_html)) < 800
            should_fetch = outlet.get("fetch_article", needs_fetch) and needs_fetch
            if should_fetch:
                # Not marked scanned on any of these three skip paths: we
                # never saw the full article text, so the entry must be
                # retried (not permanently skipped) on a later run.
                if fetched_articles >= cap:
                    cap_skipped += 1
                    continue
                if time.monotonic() > deadline:
                    budget_hit = True
                    cap_skipped += 1
                    continue
                try:
                    time.sleep(delay)
                    ar = http_get(link, timeout=15, retries=2)
                    full_html = ar.text
                    fetched_articles += 1
                    if not author:
                        author = extract_author(e, full_html)
                except Exception as ex:  # noqa: BLE001
                    errors.append(f"outlets/{outlet['name']} article {link}: {ex}")
                    continue

            full_html = strip_related_blocks(full_html)
            if conn is not None:
                mark_scanned(conn, link, outlet["name"], now_iso)
            stats["scanned"] += 1

            text_low = strip_html(full_html).lower()
            own_link = find_own_link(full_html, own_link_domains)
            if own_link and normalize_url(own_link) in own_byline_urls:
                # A sidebar/"recommended" link to one of Tal's own bylines,
                # not an editorial citation of this article.
                own_link = None
            matched_queries = [q["id"] for q in queries if query_matches_text(q, text_low)]
            if not own_link and not matched_queries:
                continue

            signal = []
            if own_link:
                signal.append("link")
            if matched_queries:
                signal.append("term:" + "+".join(matched_queries))

            match_terms = []
            for qid in matched_queries:
                q = next(qq for qq in queries if qq["id"] == qid)
                match_terms += q.get("match_terms", [])
            snippet = (context_from_html(full_html, own_link_domains, match_terms)
                       if full_html else "")

            primary_qid = matched_queries[0] if matched_queries else "own-link"
            item = make_item("outlets", primary_qid, outlet["name"], domain,
                              title, link, published, snippet)
            item["queries"] = set(matched_queries) if matched_queries else {"own-link"}
            item["signal"] = "+".join(signal)
            item["author"] = author
            item["own_link_url"] = own_link or ""
            item["own_link_urls"] = find_own_links(full_html, own_link_domains)
            items.append(item)

        if cap_skipped:
            errors.append(
                f"outlets/{outlet['name']}: hit max_article_fetches cap "
                f"({cap}); {cap_skipped} entr{'y' if cap_skipped == 1 else 'ies'} "
                "skipped and will be retried next run"
            )

    if budget_hit:
        errors.append(
            "outlets: hit outlet_time_budget_seconds "
            f"({cfg.get('outlet_time_budget_seconds', 90)}s); some article "
            "fetches were skipped and will be retried next run"
        )

    return items, errors, outlet_stats


def flag_text(full_html, queries, own_link_domains, own_byline_urls):
    """Shared link/term flagging used by wp_search, sitemap_scan and any
    other article-fetching source (fetch_outlets keeps its own inline copy
    to avoid touching already-reviewed code)."""
    text_low = strip_html(full_html).lower()
    own_link = find_own_link(full_html, own_link_domains)
    if own_link and normalize_url(own_link) in own_byline_urls:
        own_link = None
    matched_queries = [q["id"] for q in queries if query_matches_text(q, text_low)]
    return own_link, matched_queries


def _outlet_style_item(source, queries, own_link_domains, own_link, matched_queries,
                        outlet_name, domain, title, url, published, full_html, author):
    signal = []
    if own_link:
        signal.append("link")
    if matched_queries:
        signal.append("term:" + "+".join(matched_queries))
    match_terms = []
    for qid in matched_queries:
        q = next(qq for qq in queries if qq["id"] == qid)
        match_terms += q.get("match_terms", [])
    snippet = context_from_html(full_html, own_link_domains, match_terms) if full_html else ""
    primary_qid = matched_queries[0] if matched_queries else "own-link"
    item = make_item(source, primary_qid, outlet_name, domain, title, url, published, snippet)
    item["queries"] = set(matched_queries) if matched_queries else {"own-link"}
    item["signal"] = "+".join(signal)
    item["author"] = author
    item["own_link_url"] = own_link or ""
    item["own_link_urls"] = find_own_links(full_html, own_link_domains)
    return item


# --------------------------------------------------------------- wp_search

def fetch_wp_search(cfg, queries, delay, conn=None, cap_override=None):
    """WordPress REST search on `wp_search_sites` for `wp_search_terms`.
    Pages with `page=` until an empty page or HTTP 400 (WordPress returns
    400 past the last page). Returns (items, errors, site_hit_counts)."""
    sites = cfg.get("wp_search_sites", [])
    terms = cfg.get("wp_search_terms", ["nycuriosity"])
    own_link_domains = cfg.get("own_link_domains", [])
    own_byline_urls = {normalize_url(u) for u in cfg.get("own_byline_urls", [])}
    cap = cap_override if cap_override is not None else cfg.get("max_article_fetches", 60)
    fetched_articles = 0
    items, errors = [], []
    site_hits = {}
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        for site in sites:
            hits = 0
            errored = False
            cap_skipped = 0
            for term in terms:
                page = 1
                while page <= 20:  # safety wall; WordPress should 400 well before this
                    check_run_budget()
                    try:
                        r = SESSION.get(
                            f"https://{site}/wp-json/wp/v2/search",
                            params={"search": term, "per_page": 100, "page": page},
                            timeout=15,
                        )
                    except requests.RequestException as e:
                        errors.append(f"wp_search/{site}: {e}")
                        errored = True
                        break
                    if r.status_code == 400:
                        break  # past the last page
                    if r.status_code != 200:
                        errors.append(f"wp_search/{site}: HTTP {r.status_code}")
                        errored = True
                        break
                    try:
                        results = r.json()
                    except ValueError:
                        errors.append(f"wp_search/{site}: non-JSON response")
                        break
                    if not results:
                        break
                    for hit in results:
                        link = hit.get("url") or ""
                        if not link:
                            continue
                        hits += 1
                        if conn is not None and is_scanned(conn, link):
                            continue
                        if fetched_articles >= cap:
                            cap_skipped += 1
                            continue
                        check_run_budget()
                        try:
                            time.sleep(delay)
                            ar = http_get(link, timeout=15, retries=2)
                            full_html = ar.text
                            fetched_articles += 1
                        except RunBudgetExceeded:
                            raise
                        except Exception as e:  # noqa: BLE001
                            errors.append(f"wp_search/{site} article {link}: {e}")
                            continue
                        full_html = strip_related_blocks(full_html)
                        if conn is not None:
                            mark_scanned(conn, link, site, now_iso)
                        own_link, matched_queries = flag_text(
                            full_html, queries, own_link_domains, own_byline_urls)
                        if not own_link and not matched_queries:
                            continue  # scanned, recorded, but not reported
                        title = strip_html(hit.get("title") or "")
                        domain = norm_domain(urlparse(link).netloc)
                        author = extract_author(None, full_html)
                        items.append(_outlet_style_item(
                            "wp_search", queries, own_link_domains, own_link, matched_queries,
                            site, domain, title, link, None, full_html, author))
                    page += 1
            if cap_skipped:
                errors.append(
                    f"wp_search/{site}: hit max_article_fetches cap ({cap}); "
                    f"{cap_skipped} hit{'s' if cap_skipped != 1 else ''} skipped and "
                    "will be retried next run"
                )
            site_hits[site] = {"hits": hits, "errored": errored}
    except RunBudgetExceeded as e:
        errors.append(
            f"wp_search: {e}; stopping, {len(items)} item(s) collected so far returned")
    return items, errors, site_hits


# ------------------------------------------------------------ sitemap_scan

def get_sitemap_watermark(conn, name):
    row = conn.execute(
        "SELECT watermark FROM sitemap_watermark WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def set_sitemap_watermark(conn, name, watermark_iso):
    conn.execute(
        "INSERT INTO sitemap_watermark (name, watermark) VALUES (?,?) "
        "ON CONFLICT(name) DO UPDATE SET watermark = excluded.watermark",
        (name, watermark_iso),
    )


def parse_sitemap_urls(xml_text):
    """[(loc, lastmod_or_None), ...], tolerant of tag order inside <url>."""
    urls = []
    for block in re.findall(r"<url>(.*?)</url>", xml_text, re.S):
        m_loc = re.search(r"<loc>(.*?)</loc>", block, re.S)
        if not m_loc:
            continue
        m_lm = re.search(r"<lastmod>(.*?)</lastmod>", block, re.S)
        urls.append((html_mod.unescape(m_loc.group(1).strip()),
                     m_lm.group(1).strip() if m_lm else None))
    return urls


def fetch_sitemap_scan(cfg, queries, delay, conn=None, now=None, cap_override=None,
                        deadline=None):
    """Ghost-style `sitemap-posts.xml` outlets (`sitemap_scan` config).

    The stored `sitemap_watermark` value is the timestamp of the last run
    that scanned every in-window entry for an outlet (a *successful-scan*
    marker, not a lastmod cutoff). The scan window is 90 days back on an
    outlet's first run (or a backfill), or since that last successful scan
    minus a 2-day overlap otherwise. Every entry inside the window is a
    candidate every run, oldest first; the per-URL `scanned` table (not the
    window) is what keeps an already-fetched URL from being refetched, so a
    URL skipped this run for cap/budget reasons is still a candidate next
    run and is never silently dropped. A fetched page with no usable body
    (Hell Gate's paywall) is recorded scanned with a note, not an error."""
    now = now or datetime.now(timezone.utc)
    default_since = now - timedelta(days=90)
    own_link_domains = cfg.get("own_link_domains", [])
    own_byline_urls = {normalize_url(u) for u in cfg.get("own_byline_urls", [])}
    cap = cap_override if cap_override is not None else cfg.get("max_article_fetches", 60)
    fetched_articles = 0
    items, errors = [], []
    stats = {}
    now_iso = now.isoformat(timespec="seconds")

    sitemaps = cfg.get("sitemap_scan", [])
    max_failures = cfg.get("sitemap_max_fetch_failures", 3)
    for index, entry in enumerate(sitemaps):
        name = entry["name"]
        # Equal share of what's left of the cap, so an early sitemap with a
        # large backlog (Vital City) can't starve the ones after it; unused
        # share rolls forward because it's recomputed from the remainder.
        share = max(1, (cap - fetched_articles) // (len(sitemaps) - index))
        fetched_this_sitemap = 0
        stats[name] = {"available": 0, "scanned": 0, "remaining": 0, "paywalled": 0,
                        "errored": False}
        try:
            r = http_get(entry["sitemap"], timeout=15, retries=2)
        except Exception as e:  # noqa: BLE001
            errors.append(f"sitemap_scan/{name}: {e}")
            stats[name]["errored"] = True
            continue
        last_success = get_sitemap_watermark(conn, name) if conn is not None else None
        last_success_dt = parse_iso(last_success) if last_success else None
        window_start = (last_success_dt - timedelta(days=2)) if last_success_dt else default_since

        candidates = []
        for loc, lastmod in parse_sitemap_urls(r.text):
            lm_dt = parse_iso(lastmod) if lastmod else None
            if lm_dt and window_start and lm_dt < window_start:
                continue
            candidates.append((loc, lm_dt))
        candidates.sort(key=lambda c: c[1] or EPOCH)  # oldest first
        stats[name]["available"] = len(candidates)

        discovered_cap = entry.get("discovered_cap")
        processed_this_sitemap = 0
        cut_short = False
        for loc, lm_dt in candidates:
            if conn is not None and is_scanned(conn, loc):
                continue
            if (fetched_articles >= cap or fetched_this_sitemap >= share
                    or (deadline is not None and time.monotonic() > deadline)):
                stats[name]["remaining"] += 1
                cut_short = True
                continue
            if discovered_cap is not None and processed_this_sitemap >= discovered_cap:
                stats[name]["remaining"] += 1
                cut_short = True  # unscanned entries: don't narrow the window
                continue
            processed_this_sitemap += 1
            try:
                time.sleep(delay)
                ar = http_get(loc, timeout=15, retries=2)
                full_html = ar.text
                fetched_articles += 1
                fetched_this_sitemap += 1
            except Exception as e:  # noqa: BLE001
                failures = record_fetch_failure(conn, loc) if conn is not None else 1
                if failures >= max_failures:
                    # Give up on a URL that fails every run, so it can't hold
                    # the window open (and re-error) forever.
                    mark_scanned(conn, loc, f"{name} (failed)", now_iso)
                    errors.append(f"sitemap_scan/{name}: gave up on {loc} after "
                                  f"{failures} failed fetches: {e}")
                else:
                    errors.append(f"sitemap_scan/{name} article {loc}: {e}")
                    cut_short = True
                continue
            if conn is not None:
                mark_scanned(conn, loc, name, now_iso)
            stats[name]["scanned"] += 1

            if len(extract_article_body_text(full_html)) < 200:
                stats[name]["paywalled"] += 1
                continue  # scanned, noted, not an error

            full_html = strip_related_blocks(full_html)
            own_link, matched_queries = flag_text(
                full_html, queries, own_link_domains, own_byline_urls)
            if not own_link and not matched_queries:
                continue
            title_m = re.search(r"<title>(.*?)</title>", full_html, re.I | re.S)
            title = strip_html(title_m.group(1)) if title_m else ""
            domain = norm_domain(urlparse(loc).netloc)
            author = extract_author(None, full_html)
            items.append(_outlet_style_item(
                "sitemap_scan", queries, own_link_domains, own_link, matched_queries,
                name, domain, title, loc, lm_dt, full_html, author))

        if cut_short and stats[name]["remaining"]:
            remaining = stats[name]["remaining"]
            errors.append(
                f"sitemap_scan/{name}: hit cap/budget; {remaining} article"
                f"{'s' if remaining != 1 else ''} still to scan, carries over "
                "to the next run")
        if not cut_short and conn is not None:
            # Every in-window entry was either already scanned or scanned
            # just now: advance the successful-scan marker so the window
            # narrows next run.
            set_sitemap_watermark(conn, name, now_iso)

    return items, errors, stats


# ------------------------------------------------------------------ openalex

OPENALEX_WORKS = "https://api.openalex.org/works"


def _openalex_work_id(w):
    return (w.get("id") or "").rsplit("/", 1)[-1]


def _openalex_item(kind, w, cites_ids):
    title = w.get("title") or w.get("display_name") or ""
    primary = w.get("primary_location") or {}
    venue = (primary.get("source") or {}).get("display_name") or "OpenAlex"
    url = primary.get("landing_page_url") or w.get("doi") or w.get("id") or ""
    published = parse_iso(w.get("publication_date"))
    text = f"Venue: {venue}."
    if cites_ids:
        text += " Cites Tal's work: " + ", ".join(cites_ids) + "."
    domain = norm_domain(urlparse(url).netloc) if url else "openalex.org"
    item = make_item("openalex", kind, venue, domain, title, url, published, text)
    item["queries"] = {kind}
    item["openalex_kind"] = "own" if kind == "openalex-own" else "citing"
    return item


def _openalex_paginate(params, mailto, errors, error_label):
    results = []
    cursor = "*"
    while cursor:
        p = dict(params, cursor=cursor)
        if mailto:
            p["mailto"] = mailto
        try:
            check_run_budget()
            r = SESSION.get(OPENALEX_WORKS, params=p, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            errors.append(f"openalex/{error_label}: {e}")
            return results
        page_results = data.get("results") or []
        results += page_results
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not page_results:
            break
    return results


def fetch_openalex(cfg):
    """Author's own works plus works citing any of them, via OpenAlex
    (no key; `mailto` for the polite pool). Dedup against already-seen
    items happens the same way as every other source, in main()'s loop.
    Returns (items, errors, stats)."""
    author_ids = cfg.get("openalex_author_ids", [])
    if not author_ids:
        return [], [], {}
    mailto = cfg.get("mailto", "")
    errors = []
    ids_filter = "|".join(author_ids)
    own_works = _openalex_paginate(
        {"filter": f"authorships.author.id:{ids_filter}", "per_page": 200},
        mailto, errors, "author-works")

    work_ids = {_openalex_work_id(w) for w in own_works if w.get("id")}
    own_items = [_openalex_item("openalex-own", w, []) for w in own_works]

    citing_items = []
    if work_ids:
        cites_filter = "|".join(work_ids)
        citing_works = _openalex_paginate(
            {"filter": f"cites:{cites_filter}", "per_page": 200},
            mailto, errors, "citing-works")
        for w in citing_works:
            cites_ids = sorted({
                _openalex_work_id({"id": rid}) for rid in w.get("referenced_works", [])
                if _openalex_work_id({"id": rid}) in work_ids
            })
            citing_items.append(_openalex_item("openalex-citing", w, cites_ids))

    stats = {"author_works": len(own_works), "citing_works": len(citing_items)}
    return own_items + citing_items, errors, stats


# --------------------------------------------------------------- alert_feeds

def unwrap_google_alert_link(link):
    """A Google Alerts entry link is `google.com/url?...&url=<real>`; unwrap
    it, else return the link unchanged."""
    try:
        p = urlparse(link)
    except ValueError:
        return link
    if "google." in (p.netloc or "").lower() and p.path in ("/url", "/alerts/url"):
        qs = parse_qs(p.query)
        real = qs.get("url") or qs.get("q")
        if real:
            return html_mod.unescape(real[0])
    return link


def strip_alert_highlight_tags(s):
    return re.sub(r"</?b>", "", s or "", flags=re.I)


def fetch_alert_feeds(cfg, delay):
    """Google Alerts Atom feeds: config `alert_feeds` (stays empty in the
    committed config) merged with newline/whitespace-separated URLs from
    env `GOOGLE_ALERT_FEEDS`, so the account-specific feed URL never lands
    in a public file. Never logs a full feed URL, only its own <title>.
    No term match required (Google already matched); own-byline/exclusion
    classification still applies downstream in main()."""
    feeds = [(f.get("name"), f["url"]) for f in cfg.get("alert_feeds", []) or [] if f.get("url")]
    for url in os.environ.get("GOOGLE_ALERT_FEEDS", "").split():
        feeds.append((None, url.strip()))
    if not feeds:
        return [], [], {}

    items, errors, stats = [], [], {}
    for name, url in feeds:
        try:
            r = http_get(url, timeout=15, retries=2)
        except Exception as e:  # noqa: BLE001
            errors.append(f"alert_feeds/{name or '(unnamed alert)'}: {type(e).__name__}")
            continue
        parsed = feedparser.parse(r.content)
        feed_title = name or parsed.feed.get("title") or "Google Alert"
        n = 0
        for e in parsed.entries:
            real_link = unwrap_google_alert_link(e.get("link") or "")
            title = strip_alert_highlight_tags(strip_html(e.get("title") or ""))
            summary = strip_alert_highlight_tags(strip_html(e.get("summary") or ""))
            domain = norm_domain(urlparse(real_link).netloc)
            item = make_item("alert_feeds", "alert", domain, domain, title,
                              real_link, parse_feed_date(e), summary)
            item["queries"] = {"alert"}
            items.append(item)
            n += 1
        stats[feed_title] = n
        time.sleep(delay)
    return items, errors, stats


# ------------------------------------------------------- filters & classify

def is_excluded(item, cfg):
    if any(domain_matches(item["domain"], d) for d in cfg.get("exclude_domains", [])):
        return True
    nu = normalize_url(effective_url(item)).lower()
    for prefix in cfg.get("exclude_url_prefixes", []):
        p = prefix if "://" in prefix else "https://" + prefix
        if nu.startswith(normalize_url(p).lower().rstrip("/")):
            return True
    return False


def is_own_column(item, cfg):
    oc = cfg.get("own_columns", {})
    if any(domain_matches(item["domain"], d) for d in oc.get("domains", [])):
        return True
    hay = f'{item["outlet"]} {item["title"]}'.lower()
    return any(kw.lower() in hay for kw in oc.get("keywords", []))


def is_own_byline(item, cfg):
    """Own-property bylines that happen to run in an outside outlet
    (Streetsblog op-eds, Vital City guest posts, etc.): matched by author
    name, by an explicit seeded URL, or by normalized title, since author
    metadata isn't present on a Google News item (no author field, and its
    URL is an opaque news.google.com redirect that can't be matched)."""
    names = {n.strip().lower() for n in cfg.get("own_author_names", [])}
    if (item.get("author") or "").strip().lower() in names:
        return True
    urls = {normalize_url(u) for u in cfg.get("own_byline_urls", [])}
    if normalize_url(effective_url(item)) in urls:
        return True
    seed_titles = [normalize_title(t) for t in cfg.get("own_byline_titles", [])]
    item_title = normalize_title(item.get("title"))
    if item_title and seed_titles:
        return any(item_title in s or s in item_title for s in seed_titles if s)
    return False


def is_research_citation(item, cfg):
    """Real third-party citations of Tal's academic work (NBER Digest,
    Cato, Fed research banks, etc.), which must never be dropped as a name
    collision or lumped in with a news outside-citation."""
    domain = item["domain"]
    for d in cfg.get("research_domains", []):
        d = d.lower()
        if domain_matches(domain, d):
            return True
    # Fed research banks use inconsistent domain styles (frbsf.org,
    # frbatlanta.org, philadelphiafed.org already listed explicitly); catch
    # the "frb*" family generically too.
    return bool(re.search(r"(^|\.)frb[a-z]*\.", domain))


def is_unverified_name_match(item):
    """True for a google_news 'name' query item whose title/text doesn't
    actually contain the name string: Google matched on page text we can't
    see (opaque redirect, RSS gives only title+snippet)."""
    if "google_news" not in item["sources"] or "name" not in item["queries"]:
        return False
    hay = f'{item["title"]} {item["text"]}'.lower()
    return "tal roded" not in hay


def classify_pending_kind(item, cfg):
    """Which pending bucket a flagged item lands in: "own", "research", or
    "outside". The same precedence main() applies, factored out so a test
    can call the real classification end to end (item 8) instead of
    reimplementing it. Callers handle the openalex special case (always
    "research") before reaching here."""
    if is_own_column(item, cfg) or is_own_byline(item, cfg):
        return "own"
    if is_research_citation(item, cfg):
        return "research"
    return "outside"


def is_roundup(item, cfg):
    """True when the item's title matches one of `roundup_title_patterns`
    (case-insensitive substring match), e.g. Streetsblog's "Monday's
    Headlines" or "Friday's Headlines: ... Edition". Roundup items are a
    real mention, but there's no single article to cite or link into a
    tracker, so they're reported separately with no website-update
    suggestion."""
    patterns = cfg.get("roundup_title_patterns", [])
    title_low = (item.get("title") or "").lower()
    return any(p.lower() in title_low for p in patterns)


def matched_terms_str(item, queries_by_id):
    terms = []
    for qid in item["queries"]:
        terms += queries_by_id.get(qid, {}).get("match_terms") or []
    return ", ".join(sorted(set(terms))) or "unknown term"


def is_term_only_match(item, cfg):
    """True when an item was matched only by a tracker/figure term (e.g.
    "$7.5 billion") with no own-property link and no name/brand match
    (Tal Roded / NYCuriosity). These are not confident citations of Tal's
    own work, just a shared number or phrase, so they must never get a
    "Featured in" / "In the press" prompt, only a manual-verify note."""
    if item.get("own_link_url") or "own-link" in item["queries"]:
        return False
    name_brand_ids = set(cfg.get("name_brand_query_ids", ["name", "brand"]))
    return not (item["queries"] & name_brand_ids)


def classify(item, cfg):
    override = cfg.get("tier_overrides", {}).get(item["domain"])
    if override in dict(TIER_ORDER):
        return override
    if any(domain_matches(item["domain"], d) for d in cfg.get("newsletter_domains", [])):
        return "newsletter"
    return "news"


def extract_context(item, queries_by_id, width=340):
    """The sentence-ish window around the first matched term. Outlet items
    already carry a pre-extracted snippet in item['text']; this narrows it
    further when a term is findable, otherwise returns it (or the RSS
    summary for other sources) as-is."""
    text = f'{item["title"]}. {item["text"]}'.strip()
    terms = []
    for qid in item["queries"]:
        terms += queries_by_id.get(qid, {}).get("match_terms") or []
    low = text.lower()
    for term in sorted(set(terms), key=len, reverse=True):
        i = low.find(term.lower())
        if i < 0:
            continue
        start = max(0, i - width // 2)
        end = min(len(text), i + len(term) + width // 2)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "…" + snippet.lstrip(".…, ")
        if end < len(text):
            snippet = snippet + "…"
        return snippet
    fallback = text[:220].strip()
    return fallback + ("…" if len(text) > 220 else "")


# ----------------------------------------------------------------- database

def db_connect(path):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            key        TEXT PRIMARY KEY,
            url        TEXT,
            title      TEXT,
            sources    TEXT,
            queries    TEXT,
            first_seen TEXT
        )
    """)
    # Added for the pending -> digest -> digested flow. Additive only, so an
    # existing seen.db keeps every row it already had.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            item_key  TEXT,
            kind      TEXT,
            payload   TEXT,
            digested  INTEGER DEFAULT 0,
            created   TEXT
        )
    """)
    # referrers' key must include the destination host: Tal runs more than
    # one nycuriosity.com property, and (date, referrer, path) alone
    # collided across them, silently dropping rows via INSERT OR REPLACE.
    # This feature is still dormant (no CF secrets exist yet), so there is
    # no real data to migrate; recreate the table if an old-schema copy is
    # found so the new key takes effect.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(referrers)").fetchall()}
    if cols and "dest_host" not in cols:
        conn.execute("DROP TABLE referrers")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrers (
            date      TEXT,
            host      TEXT,
            dest_host TEXT,
            path      TEXT,
            requests  INTEGER,
            PRIMARY KEY (date, host, dest_host, path)
        )
    """)
    # Every article URL fetch_outlets has actually looked at (flagged or
    # not), so a later run skips re-fetching it instead of re-scanning the
    # same feed entries every day.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scanned (
            url          TEXT PRIMARY KEY,
            outlet       TEXT,
            first_scanned TEXT
        )
    """)
    # Source errors persist across collect-only runs; the Sunday digest
    # loads and clears everything accumulated since the last digest.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_errors (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            created TEXT
        )
    """)
    # Round 6 item 2: routine cap/budget carry-over notices, kept separate
    # from source_errors (real failures). One row per unit, overwritten with
    # the latest notice rather than accumulated, since only the newest
    # remaining-count matters.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backlog_notices (
            unit    TEXT PRIMARY KEY,
            message TEXT,
            created TEXT
        )
    """)
    # sitemap_scan's per-outlet high-water mark (newest lastmod actually
    # scanned), so a later run only looks at newer entries.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sitemap_watermark (
            name      TEXT PRIMARY KEY,
            watermark TEXT
        )
    """)
    # One row per run per scanned unit (outlet feed, wp_search site, sitemap
    # outlet, google_news query id), feeding the Sunday "Suggested removals"
    # section (item 8).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_yield (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT,
            unit          TEXT,
            ran           INTEGER,
            items_fetched INTEGER,
            items_flagged INTEGER,
            errored       INTEGER
        )
    """)
    # Discovery probe results, so a candidate domain is only re-probed every
    # 30 days (item 9).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS probed_domains (
            domain    TEXT PRIMARY KEY,
            probed_at TEXT,
            passed    INTEGER,
            type      TEXT,
            url       TEXT
        )
    """)
    # Item 7: discovery can run on a backfill (no digest produced that
    # run), so its added/reviewed results must be persisted here and
    # picked up by whichever run next builds a digest, exactly like
    # source_errors above.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS discovery_pending (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            kind    TEXT,
            payload TEXT,
            created TEXT
        )
    """)
    # Google News opaque url -> resolved real-outlet url, so each link is
    # decoded (batchexecute) at most once ever, not once per run.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS google_news_url_cache (
            url          TEXT PRIMARY KEY,
            resolved_url TEXT,
            resolved_at  TEXT
        )
    """)
    return conn


def cached_google_news_resolution(conn, url):
    if conn is None:
        return None
    row = conn.execute(
        "SELECT resolved_url FROM google_news_url_cache WHERE url = ?", (url,)
    ).fetchone()
    return row[0] if row else None


def cache_google_news_resolution(conn, url, resolved_url, now_iso=""):
    if conn is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO google_news_url_cache (url, resolved_url, resolved_at) "
        "VALUES (?,?,?)",
        (url, resolved_url, now_iso),
    )


def is_scanned(conn, url):
    return conn.execute(
        "SELECT 1 FROM scanned WHERE url = ? LIMIT 1", (url,)
    ).fetchone() is not None


def mark_scanned(conn, url, outlet, now_iso):
    conn.execute(
        "INSERT OR IGNORE INTO scanned (url, outlet, first_scanned) VALUES (?,?,?)",
        (url, outlet, now_iso),
    )


def record_fetch_failure(conn, url):
    """Increment and return the failed-fetch count for a sitemap URL."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fetch_failures (url TEXT PRIMARY KEY, count INTEGER)")
    conn.execute(
        "INSERT INTO fetch_failures (url, count) VALUES (?, 1) "
        "ON CONFLICT(url) DO UPDATE SET count = count + 1", (url,))
    return conn.execute(
        "SELECT count FROM fetch_failures WHERE url = ?", (url,)).fetchone()[0]


# Round 6 item 2: cap/budget carry-over notices are routine backlog, not a
# failure; they share these substrings across outlets/wp_search/sitemap_scan/
# collect() and get routed to a separate "Scan progress" category instead of
# "Source errors".
BACKLOG_MARKERS = (
    "hit max_article_fetches cap",
    "hit outlet_time_budget_seconds",
    "hit cap/budget",
    "hit query_time_budget_seconds",
)


def is_backlog_notice(message):
    return any(marker in message for marker in BACKLOG_MARKERS)


def backlog_unit(message):
    """Grouping key for a backlog message, e.g. 'sitemap_scan/Vital City'
    from 'sitemap_scan/Vital City: hit cap/budget; ...'."""
    return message.split(":", 1)[0].strip()


def backlog_display(message):
    """Readable one-liner for the Scan progress section, e.g. 'Vital City
    sitemap: 414 articles still to scan'."""
    unit = backlog_unit(message)
    kind, _, name = unit.partition("/")
    label = {"sitemap_scan": f"{name} sitemap", "outlets": f"{name} feed" if name else "Outlet feeds",
             "wp_search": f"{name} site search"}.get(kind, unit)
    m = re.search(r"(\d+) (?:articles still to scan|entries skipped|remaining)", message)
    if m:
        return f"{label}: {m.group(1)} articles still to scan"
    return f"{label}: more to scan on the next run"


def record_backlog_notices(conn, notices, now_iso):
    """Persist the latest backlog notice per unit (overwrite, not append,
    since only the most recent remaining-count matters for a carry-over
    notice)."""
    for message in notices:
        unit = backlog_unit(message)
        conn.execute(
            "INSERT INTO backlog_notices (unit, message, created) VALUES (?,?,?) "
            "ON CONFLICT(unit) DO UPDATE SET message=excluded.message, "
            "created=excluded.created",
            (unit, message, now_iso),
        )


def load_and_clear_backlog_notices(conn):
    rows = conn.execute(
        "SELECT message FROM backlog_notices ORDER BY unit").fetchall()
    conn.execute("DELETE FROM backlog_notices")
    return [m for (m,) in rows]


def record_source_errors(conn, errors, now_iso):
    for message in errors:
        conn.execute(
            "INSERT INTO source_errors (message, created) VALUES (?,?)",
            (message, now_iso),
        )


def load_and_clear_source_errors(conn):
    """All persisted source errors since the last digest, grouped by exact
    message with counts, then cleared so they don't repeat next digest."""
    rows = conn.execute("SELECT message FROM source_errors ORDER BY id").fetchall()
    counts = {}
    order = []
    for (message,) in rows:
        if is_backlog_notice(message):
            continue  # carry-over notices persisted by older runs; not errors
        if message not in counts:
            order.append(message)
        counts[message] = counts.get(message, 0) + 1
    conn.execute("DELETE FROM source_errors")
    return [f"{m} (x{counts[m]})" if counts[m] > 1 else m for m in order]


def record_discovery_results(conn, added, reviewed, now_iso):
    """Persist one run's discovery probe results (item 7), so a backfill
    run's results aren't lost before a digest ever sees them."""
    for entry in added:
        conn.execute(
            "INSERT INTO discovery_pending (kind, payload, created) VALUES (?,?,?)",
            ("added", json.dumps(entry), now_iso))
    for entry in reviewed:
        conn.execute(
            "INSERT INTO discovery_pending (kind, payload, created) VALUES (?,?,?)",
            ("reviewed", json.dumps(entry), now_iso))


def load_and_clear_discovery_results(conn):
    """Everything accumulated since the last digest (across any number of
    collect/backfill runs in between), then cleared."""
    rows = conn.execute(
        "SELECT kind, payload FROM discovery_pending ORDER BY id").fetchall()
    added = [json.loads(p) for k, p in rows if k == "added"]
    reviewed = [json.loads(p) for k, p in rows if k == "reviewed"]
    conn.execute("DELETE FROM discovery_pending")
    return added, reviewed


def any_seen(conn, keys):
    keys = list(keys)
    marks = ",".join("?" * len(keys))
    return conn.execute(
        f"SELECT 1 FROM seen WHERE key IN ({marks}) LIMIT 1", keys
    ).fetchone() is not None


def mark_seen(conn, item, now_iso):
    for k in item["keys"]:
        conn.execute(
            "INSERT OR IGNORE INTO seen VALUES (?,?,?,?,?,?)",
            (k, item["url"], item["title"],
             ",".join(sorted(item["sources"])),
             ",".join(sorted(item["queries"])), now_iso),
        )


def serialize_item(item):
    d = {k: v for k, v in item.items() if k != "keys"}
    d["sources"] = sorted(item["sources"])
    d["queries"] = sorted(item["queries"])
    d["published"] = item["published"].isoformat() if item["published"] else None
    return d


def deserialize_item(d):
    item = dict(d)
    item["sources"] = set(d.get("sources") or [])
    item["queries"] = set(d.get("queries") or [])
    item["published"] = parse_iso(d.get("published"))
    return item


def pending_add(conn, item, kind, now_iso):
    payload = json.dumps(serialize_item(item))
    key = next(iter(item["keys"])) if item.get("keys") else ""
    conn.execute(
        "INSERT INTO pending (item_key, kind, payload, digested, created) "
        "VALUES (?,?,?,0,?)",
        (key, kind, payload, now_iso),
    )


def pending_load(conn):
    rows = conn.execute(
        "SELECT id, kind, payload FROM pending WHERE digested = 0"
    ).fetchall()
    outside, own, research, ids = [], [], [], []
    for row_id, kind, payload in rows:
        item = deserialize_item(json.loads(payload))
        if kind == "own":
            own.append(item)
        elif kind == "research":
            research.append(item)
        else:
            outside.append(item)
        ids.append(row_id)
    return outside, own, research, ids


def pending_mark_digested(conn, ids):
    if not ids:
        return
    marks = ",".join("?" * len(ids))
    conn.execute(f"UPDATE pending SET digested = 1 WHERE id IN ({marks})", ids)


def store_referrers(conn, date_str, rows):
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO referrers (date, host, dest_host, path, requests) "
            "VALUES (?,?,?,?,?)",
            (date_str, row["host"], row.get("dest_host", ""), row["path"], row["requests"]),
        )


def load_referrer_summary(conn, since_date):
    rows = conn.execute(
        "SELECT host, path, requests FROM referrers WHERE date >= ?", (since_date,)
    ).fetchall()
    if not rows:
        return None
    hosts = {}
    for host, path, requests_count in rows:
        h = hosts.setdefault(host, {"total": 0, "paths": {}})
        h["total"] += requests_count
        h["paths"][path] = h["paths"].get(path, 0) + requests_count
    return hosts


# ---------------------------------------------------- cloudflare referrers

def redact_ids(text, *secrets):
    """Digests are committed to a public repo and emailed: strip the zone id
    and any other 32+ char hex ids from error text."""
    for s in secrets:
        if s:
            text = text.replace(s, "<redacted>")
    return re.sub(r"\b[0-9a-f]{32,}\b", "<redacted>", text)


def fetch_cloudflare_referrers(cfg, now, window_hours=24):
    """Dormant until CF_ANALYTICS_TOKEN and CF_ACCOUNT_ID both exist and
    `cloudflare_referrers_enabled` is true. Returns (rows, error_or_none,
    skipped_bool). Round 6 item 4: `httpRequestsAdaptiveGroups` isn't
    available on this zone's plan (no `clientRefererHost` field), so this
    queries Cloudflare Web Analytics (RUM) instead, account-scoped via
    `rumPageloadEventsAdaptiveGroups`. Verified against real data Sep 16
    2026 (6 referrer rows over 30 days); any GraphQL-reported error becomes
    a source error (message only, ids redacted) rather than a crash."""
    token = os.environ.get("CF_ANALYTICS_TOKEN")
    account_id = os.environ.get("CF_ACCOUNT_ID")
    site_tag = os.environ.get("CF_WA_SITE_TAG")
    if not (token and account_id) or not cfg.get("cloudflare_referrers_enabled", False):
        return [], None, True

    ignore = [h.lower() for h in cfg.get("referrer_ignore_hosts", [])]
    since = (now - timedelta(hours=window_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Web Analytics (RUM) is account-scoped, not zone-scoped, and exposes
    # referrer hosts on the free plan (unlike httpRequestsAdaptiveGroups on
    # this zone). Field/type names below follow Cloudflare's GraphQL
    # Analytics API docs' rumPageloadEventsAdaptiveGroups example shape,
    # confirmed against real data Sep 16 2026. Counts are RUM-sampled, so
    # they arrive in multiples of the sample rate.
    query = """
    query MentionReferrers($accountTag: string!, $since: Time!, $until: Time!, $siteTag: string) {
      viewer {
        accounts(filter: { accountTag: $accountTag }) {
          rumPageloadEventsAdaptiveGroups(
            limit: 1000
            orderBy: [count_DESC]
            filter: {
              datetime_geq: $since
              datetime_lt: $until
              refererHost_neq: ""
              siteTag: $siteTag
            }
          ) {
            count
            dimensions {
              refererHost
              requestHost
              requestPath
            }
          }
        }
      }
    }
    """
    variables = {"accountTag": account_id, "since": since, "until": until}
    if site_tag:
        variables["siteTag"] = site_tag
    try:
        check_run_budget()
        r = SESSION.post(
            CF_GRAPHQL,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return [], redact_ids(f"cloudflare_referrers: {e}", account_id, token), False
    if data.get("errors"):
        messages = "; ".join(str(err.get("message", err)) for err in data["errors"])
        return [], redact_ids(f"cloudflare_referrers: {messages}", account_id, token), False

    rows = []
    accounts = ((data.get("data") or {}).get("viewer") or {}).get("accounts") or []
    for a in accounts:
        for g in a.get("rumPageloadEventsAdaptiveGroups", []) or []:
            dims = g.get("dimensions") or {}
            host = (dims.get("refererHost") or "").lower()
            if not host:
                continue
            if domain_matches(norm_domain(host), "nycuriosity.com"):
                continue
            if host_ignored(host, ignore):
                continue
            rows.append({
                "host": host,
                "dest_host": (dims.get("requestHost") or "").lower(),
                "path": dims.get("requestPath") or "",
                "requests": g.get("count", 0),
            })
    return rows, None, False


# ------------------------------------------------------------- source_yield

def record_yield(conn, date_str, rows):
    """rows: [{unit, ran, items_fetched, items_flagged, errored}, ...]."""
    for row in rows:
        conn.execute(
            "INSERT INTO source_yield "
            "(date, unit, ran, items_fetched, items_flagged, errored) "
            "VALUES (?,?,?,?,?,?)",
            (date_str, row["unit"], int(row["ran"]), row["items_fetched"],
             row["items_flagged"], int(row["errored"])),
        )


def _iso_week(date_str):
    y, w, _ = datetime.strptime(date_str, "%Y-%m-%d").isocalendar()
    return (y, w)


def config_location_for_unit(unit, cfg):
    """The exact place to delete/edit in config to act on a removal
    suggestion, for the digest text."""
    kind, _, name = unit.partition(":")
    if kind == "outlets":
        return f'config.json → outlets[name="{name}"]'
    if kind == "wp_search":
        return f'config.json → wp_search_sites (remove "{name}")'
    if kind == "sitemap":
        return f'config.json → sitemap_scan[name="{name}"]'
    if kind == "google_news":
        return f'config.json → queries[id="{name}"].sources (remove "google_news")'
    for d in load_discovered_sources():
        if d.get("domain") == name:
            return f'discovered_sources.json (domain "{name}")'
    return f'config.json (unit "{unit}")'


def suggest_removals(conn, cfg):
    """Units with a zero-flagged streak of >= prune_after_weeks distinct
    ISO weeks that each had at least one successful (non-errored) run, or
    an all-error streak of >= prune_error_weeks distinct ISO weeks where
    every run in the week errored. Multiple daily rows in the same ISO
    week count as one week, not one row per week. Exempt units and units
    younger than the threshold are never suggested."""
    exempt = set(cfg.get("prune_exempt", []))
    after = cfg.get("prune_after_weeks", 8)
    err_after = cfg.get("prune_error_weeks", 3)
    rows = conn.execute(
        "SELECT unit, date, ran, items_fetched, items_flagged, errored "
        "FROM source_yield ORDER BY unit, date DESC"
    ).fetchall()
    by_unit = {}
    for unit, date, ran, fetched, flagged, errored in rows:
        by_unit.setdefault(unit, []).append(
            {"date": date, "ran": ran, "fetched": fetched, "flagged": flagged,
             "errored": errored})

    suggestions = []
    for unit, runs in by_unit.items():
        if unit in exempt:
            continue
        weeks = {}
        order = []
        for r in runs:
            wk = _iso_week(r["date"])
            if wk not in weeks:
                weeks[wk] = {"ran": False, "all_errored": True, "flagged": 0,
                             "fetched": 0, "last_date": r["date"]}
                order.append(wk)
            w = weeks[wk]
            w["ran"] = w["ran"] or bool(r["ran"])
            w["all_errored"] = w["all_errored"] and bool(r["errored"])
            w["flagged"] += r["flagged"]
            w["fetched"] += r["fetched"]
        week_list = [weeks[wk] for wk in order]  # already newest-first

        error_streak = 0
        for w in week_list:
            if not w["ran"] or not w["all_errored"]:
                break
            error_streak += 1
        zero_streak = 0
        for w in week_list:
            if not w["ran"] or w["all_errored"]:
                break
            if w["flagged"] != 0:
                break
            zero_streak += 1
        last_flagged = next((r["date"] for r in runs if r["flagged"] > 0), None)
        location = config_location_for_unit(unit, cfg)

        if error_streak >= err_after and len(week_list) >= err_after:
            span = week_list[:error_streak]
            suggestions.append({
                "unit": unit, "reason": "errored on every run", "weeks_silent": error_streak,
                "items_fetched": sum(w["fetched"] for w in span), "last_flagged": last_flagged,
                "config_location": location,
            })
        elif zero_streak >= after and len(week_list) >= after:
            span = week_list[:zero_streak]
            suggestions.append({
                "unit": unit, "reason": "zero flagged items", "weeks_silent": zero_streak,
                "items_fetched": sum(w["fetched"] for w in span), "last_flagged": last_flagged,
                "config_location": location,
            })
    return suggestions


# --------------------------------------------------------------- discovery

DISCOVERED_FILE = HERE / "discovered_sources.json"


def load_discovered_sources(path=None):
    path = path or DISCOVERED_FILE
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError):
            return []
    return []


def save_discovered_sources(rows, path=None):
    path = path or DISCOVERED_FILE
    path.write_text(json.dumps(rows, indent=2) + "\n")


def fetch_own_bylines_from_site(cfg):
    """Read Tal's Publications page and treat everything outside its "In the
    press" section as his own writing. Hand-keeping `own_byline_urls` means a
    piece he publishes elsewhere and forgets to add here comes back as
    outside coverage with a prompt to add it to his own site. Returns
    (urls, titles); on any fetch/parse failure returns ([], []) so the
    configured lists still stand."""
    page = cfg.get("own_byline_page")
    if not page:
        return [], []
    try:
        html = http_get(page, timeout=20, retries=2).text
    except Exception as e:  # noqa: BLE001
        print(f"own_byline_page: {e}", file=sys.stderr)
        return [], []
    own_hosts = cfg.get("own_link_domains", []) + ["nycuriosity.com"]
    urls, titles = [], []
    # Sections are "<p class="section-label">Name</p>" followed by their items;
    # "In the press" is outside coverage ABOUT him, not written by him.
    chunks = re.split(r'<p class="section-label">', html)[1:]
    for chunk in chunks:
        label = strip_html(chunk.split("</p>", 1)[0]).strip().lower()
        if "in the press" in label:
            continue
        # Only entries, never the page footer (which follows the last
        # section and links to his social profiles).
        for item in re.findall(r'<div class="pub-item">(.*?)</div>\s*</div>', chunk, re.S):
            m = re.search(r'<div class="pub-title">(.*?)</div>', item, re.S)
            title = strip_html(m.group(1)).strip() if m else ""
            if title:
                titles.append(title)
            for mu in re.finditer(r'href="(https?://[^"]+)"', item):
                url = mu.group(1)
                host = norm_domain(urlparse(url).netloc)
                if any(domain_matches(host, d) for d in own_hosts):
                    continue
                urls.append(url)
    return urls, titles


def apply_own_bylines(cfg):
    """Merge the Publications page's bylines into a copy of cfg."""
    urls, titles = fetch_own_bylines_from_site(cfg)
    if not (urls or titles):
        return cfg
    cfg = dict(cfg)
    cfg["own_byline_urls"] = list(dict.fromkeys(list(cfg.get("own_byline_urls", [])) + urls))
    cfg["own_byline_titles"] = list(dict.fromkeys(list(cfg.get("own_byline_titles", [])) + titles))
    print(f"own_byline_page: +{len(urls)} urls, +{len(titles)} titles from the live page",
          file=sys.stderr)
    return cfg


def apply_discovered_sources(cfg, path=None):
    """Merge discovered_sources.json into a copy of cfg's outlets /
    wp_search_sites / sitemap_scan lists, so a discovered source is scanned
    like a hand-configured one from the run after it was added. Never
    writes config.json."""
    cfg = dict(cfg)
    outlets = list(cfg.get("outlets", []))
    wp_sites = list(cfg.get("wp_search_sites", []))
    sitemaps = list(cfg.get("sitemap_scan", []))
    discovered_cap = cfg.get("discovered_max_fetches", 10)
    for d in load_discovered_sources(path):
        if d["type"] == "feed":
            outlets.append({"name": d["domain"], "feed": d["url"], "tier": "news",
                             "fetch_article": False, "discovered_cap": discovered_cap})
        elif d["type"] == "wp_search" and d["domain"] not in wp_sites:
            wp_sites.append(d["domain"])
        elif d["type"] == "sitemap":
            sitemaps.append({"sitemap": d["url"], "name": d["domain"], "tier": "news",
                              "discovered_cap": discovered_cap})
    cfg["outlets"], cfg["wp_search_sites"], cfg["sitemap_scan"] = outlets, wp_sites, sitemaps
    return cfg


# Multi-part public suffixes: a registrable domain under these needs the
# label before the suffix too (bbc.co.uk, not co.uk). Not exhaustive, just
# the common ones likely to show up as UK/AU/JP/NZ/BR outlets or referrers.
MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "net.uk", "sch.uk",
    "com.au", "net.au", "org.au", "gov.au",
    "co.jp", "or.jp", "ne.jp",
    "co.nz", "net.nz", "org.nz",
    "com.br", "net.br", "org.br",
}
# Hosting platforms where each subdomain is a separate publication
# (someone.substack.com), so the publication, not the platform, is the
# discovery candidate.
PLATFORM_SUFFIXES = {
    "substack.com", "medium.com", "beehiiv.com", "ghost.io", "wordpress.com",
    "blogspot.com", "github.io", "tumblr.com", "buttondown.email",
}
MULTI_PART_SUFFIXES |= PLATFORM_SUFFIXES


def registrable_domain(host):
    """The registrable domain (eTLD+1), aware of the common multi-part
    public suffixes above so "bbc.co.uk" doesn't collapse to "co.uk" while
    "nyc.streetsblog.org" still collapses to "streetsblog.org"."""
    host = norm_domain(host)
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_PART_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def covered_domains(cfg, discovered_path=None):
    """Full configured source hosts (not reduced to registrable domains),
    so coverage checks can do a parent/child comparison against the exact
    host a candidate item came from."""
    covered = set()
    for o in cfg.get("outlets", []):
        covered.add(norm_domain(urlparse(o["feed"]).netloc))
    for s in cfg.get("wp_search_sites", []):
        covered.add(norm_domain(s))
    for sm in cfg.get("sitemap_scan", []):
        covered.add(norm_domain(urlparse(sm["sitemap"]).netloc))
    for d in load_discovered_sources(discovered_path):
        covered.add(norm_domain(d.get("domain", "")))
    return covered


def is_covered_host(host, covered):
    """A host is covered if any configured source host equals it, or is a
    parent or child of it (so a configured "nyc.streetsblog.org" covers a
    candidate host of "streetsblog.org" or "www.nyc.streetsblog.org")."""
    return any(domain_matches(host, c) or domain_matches(c, host) for c in covered)


def extract_candidate_domains(items, cfg, discovered_path=None, referrer_hosts=None):
    """Registrable domains from google_news / alert_feeds / openalex items,
    plus Cloudflare referrer hosts, that aren't an own property, aren't a
    research domain or discovery-ignored domain, and aren't already
    covered (by full-host parent/child match) by a hand-configured or
    discovered source. research_domains and discovery_ignore_domains are
    filtered here, before any probe is attempted."""
    ignore = cfg.get("discovery_ignore_domains", []) + cfg.get("research_domains", [])
    own = cfg.get("own_link_domains", []) + cfg.get("exclude_domains", [])
    covered = covered_domains(cfg, discovered_path)
    found_via = {}

    def consider(host, via, url=""):
        host = norm_domain(host)
        if not host:
            return
        if any(domain_matches(host, d) for d in own):
            return
        if any(domain_matches(host, d) for d in ignore):
            return
        if is_covered_host(host, covered):
            return
        domain = registrable_domain(host)
        if domain in PLATFORM_SUFFIXES:
            return  # the platform itself (substack.com/home/post/...), not a publication
        found_via.setdefault(domain, {"via": via, "first_item_url": url})

    for item in items:
        via_sources = item["sources"] & {"google_news", "alert_feeds", "openalex"}
        if not via_sources:
            continue
        consider(item["domain"], sorted(via_sources)[0], effective_url(item))

    for host in referrer_hosts or []:
        consider(host, "cloudflare_referrers")

    return found_via


def _feed_has_entries(url):
    try:
        r = http_get(url, timeout=10, retries=1)
    except RunBudgetExceeded:
        raise
    except Exception:  # noqa: BLE001
        return False
    return len(feedparser.parse(r.content).entries) >= 1


def probe_domain(domain):
    """(passed, type, url) for the first working discovery method, in
    order: <link rel=alternate> feed, common feed paths, wp_search, Ghost
    sitemap. (False, None, None) if nothing works. Raises RunBudgetExceeded
    (never swallowed) so a budget hit mid-probe is never recorded as a
    failed probe (must not be suppressed for 30 days)."""
    home = f"https://{domain}/"
    try:
        r = http_get(home, timeout=10, retries=1)
        m = re.search(
            r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/'
            r'(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']', r.text, re.I)
        if m:
            feed_url = m.group(1)
            if feed_url.startswith("/"):
                feed_url = f"https://{domain}{feed_url}"
            if _feed_has_entries(feed_url):
                return True, "feed", feed_url
    except RunBudgetExceeded:
        raise
    except Exception:  # noqa: BLE001
        pass
    for path in ("/feed/", "/rss/", "/feed", "/rss.xml", "/atom.xml", "/index.xml"):
        url = f"https://{domain}{path}"
        if _feed_has_entries(url):
            return True, "feed", url
    try:
        r = http_get(f"https://{domain}/wp-json/wp/v2/search",
                      params={"search": "nycuriosity", "per_page": 1}, timeout=10, retries=1)
        if r.status_code == 200 and isinstance(r.json(), list):
            return True, "wp_search", f"https://{domain}/wp-json/wp/v2/search"
    except RunBudgetExceeded:
        raise
    except Exception:  # noqa: BLE001
        pass
    for path in ("/sitemap-posts.xml", "/sitemap.xml"):
        url = f"https://{domain}{path}"
        try:
            r = http_get(url, timeout=10, retries=1)
        except RunBudgetExceeded:
            raise
        except Exception:  # noqa: BLE001
            continue
        ok, found_url = _probe_sitemap_body(r.text, url)
        if ok:
            return True, "sitemap", found_url
    return False, None, None


def _probe_sitemap_body(xml_text, probed_url):
    """A passing sitemap probe requires <urlset> with at least one
    <lastmod>. A <sitemapindex> is not itself a posts sitemap: follow the
    first child <loc> one level (typically the newest/posts sub-sitemap)
    and require the same of that page, rather than accepting the index."""
    if "<sitemapindex" in xml_text:
        m = re.search(r"<loc>(.*?)</loc>", xml_text, re.S)
        if not m:
            return False, None
        child_url = html_mod.unescape(m.group(1).strip())
        try:
            r = http_get(child_url, timeout=10, retries=1)
        except Exception:  # noqa: BLE001
            return False, None
        if "<sitemapindex" in r.text:
            return False, None  # only follow one level
        if "<urlset" in r.text and "<lastmod>" in r.text:
            return True, child_url
        return False, None
    if "<urlset" in xml_text and "<lastmod>" in xml_text:
        return True, probed_url
    return False, None


def recently_probed(conn, domain, now, days=30):
    row = conn.execute(
        "SELECT probed_at FROM probed_domains WHERE domain = ?", (domain,)).fetchone()
    if not row:
        return False
    dt = parse_iso(row[0])
    return dt is not None and (now - dt) < timedelta(days=days)


def record_probe(conn, domain, now_iso, passed, ptype, url):
    conn.execute(
        "INSERT INTO probed_domains (domain, probed_at, passed, type, url) VALUES (?,?,?,?,?) "
        "ON CONFLICT(domain) DO UPDATE SET probed_at=excluded.probed_at, "
        "passed=excluded.passed, type=excluded.type, url=excluded.url",
        (domain, now_iso, int(passed), ptype, url),
    )


def run_discovery(cfg, conn, now, candidates, discovered_path=None):
    """Probe up to `new_probe_cap` un-probed candidates (skipping any probed
    within the last 30 days). Passing probes are appended to
    discovered_sources.json when `auto_add_discovered`; everything else is
    listed for manual review. Returns (added, reviewed)."""
    cap = cfg.get("new_probe_cap", 10)
    now_iso = now.isoformat(timespec="seconds")
    discovered = load_discovered_sources(discovered_path)
    existing = {d["domain"] for d in discovered}
    added, reviewed, n = [], [], 0
    for domain, info in sorted(candidates.items()):
        found_via = info["via"] if isinstance(info, dict) else info
        first_item_url = info.get("first_item_url", "") if isinstance(info, dict) else ""
        if domain in existing:
            continue
        if recently_probed(conn, domain, now):
            continue
        if n >= cap:
            break
        n += 1
        try:
            passed, ptype, url = probe_domain(domain)
        except RunBudgetExceeded:
            # Never record a budget-interrupted probe: that would suppress
            # this domain as "failed" for 30 days. Stop probing; it's
            # retried fresh next run.
            break
        record_probe(conn, domain, now_iso, passed, ptype, url)
        if passed and cfg.get("auto_add_discovered", True):
            entry = {"domain": domain, "type": ptype, "url": url,
                      "added_on": now.strftime("%Y-%m-%d"), "found_via": found_via,
                      "first_item_url": first_item_url}
            discovered.append(entry)
            added.append(entry)
        else:
            reviewed.append({"domain": domain, "passed": passed, "type": ptype,
                              "found_via": found_via})
    if added:
        save_discovered_sources(discovered, discovered_path)
    return added, reviewed


# ------------------------------------------------------------------- digest

def md_escape(s):
    return (s or "").replace("[", r"\[").replace("]", r"\]")


def format_item(item, queries_by_id):
    date_str = f' ({item["published"]:%Y-%m-%d})' if item["published"] else ""
    extra = f'; signal: {item["signal"]}' if item.get("signal") else ""
    note = ""
    if is_unverified_name_match(item):
        note = " (name match from Google News, not verified in text)"
    lines = [
        f'**{md_escape(item["outlet"]) or item["domain"]}**: '
        f'[{md_escape(item["title"]) or "(untitled)"}]({effective_url(item)}){date_str}{note}',
        f"> {extract_context(item, queries_by_id)}",
        f'_(via {", ".join(sorted(item["sources"]))}; '
        f'matched: {", ".join(sorted(item["queries"]))}{extra})_',
        "",
    ]
    return lines


def format_referrer_section(hosts):
    lines = ["## Sites sending visitors this week", ""]
    for host, info in sorted(hosts.items(), key=lambda kv: -kv[1]["total"]):
        top_paths = sorted(info["paths"].items(), key=lambda kv: -kv[1])[:3]
        paths_str = ", ".join(f"{p or '/'} ({n})" for p, n in top_paths)
        n = info["total"]
        lines.append(f"- **{host}**: {n} request{'s' if n != 1 else ''} ({paths_str})")
    lines.append("")
    return lines


def format_removal_section(suggestions):
    if not suggestions:
        return []
    lines = ["## Suggested removals", ""]
    for s in suggestions:
        weeks = s["weeks_silent"]
        lines.append(
            f"- **{s['unit']}**: {s['reason']} for {weeks} week{'s' if weeks != 1 else ''} "
            f"(fetched {s['items_fetched']} items in that span; last flagged "
            f"{s['last_flagged'] or 'never'}). Remove it at "
            f"{s.get('config_location', 'config.json')}."
        )
    lines.append("")
    return lines


def format_discovery_sections(added, reviewed):
    lines = []
    if added:
        lines += ["## Added this week", ""]
        for a in added:
            lines.append(
                f"- **{a['domain']}** ({a['type']}): found via {a['found_via']}. "
                "Remove: delete its entry from discovered_sources.json.")
        lines.append("")
    if reviewed:
        lines += ["## Candidates needing manual review", ""]
        for r in reviewed:
            status = "auto-add off" if r["passed"] else "probe failed"
            lines.append(f"- **{r['domain']}**: {status} (found via {r['found_via']}).")
        lines.append("")
    return lines


# ------------------------------------------------------ site update prompts

# Sentinel cached when a fetch was cut short by the shared run deadline,
# distinct from a real fetch failure (which is cached as None).
_UNKNOWN_PAGE = object()


def check_already_listed(file_key, item_url, cfg, cache, title=None):
    """Fetch the live page this file publishes to (config `site_pages`) and
    check whether the item's URL, or (for a Google News item whose opaque
    link never resolved) its normalized title, is already on it.
    Returns True, False, or "unknown" (the run deadline was hit before the
    page could be fetched; the caller must not treat that as "not listed"
    and must not prompt). False (recommend it) on any other fetch
    failure, never a crash."""
    rules = cfg.get("site_update_rules", {})
    pages = cfg.get("site_pages", {})
    page_url = {
        rules.get("personal_site_file"): pages.get("personal_publications"),
        rules.get("implementation_tracker_file"): pages.get("implementation_tracker"),
        rules.get("fiscal_tracker_file"): pages.get("fiscal_tracker"),
        rules.get("trackers_hub_file"): pages.get("trackers_hub"),
    }.get(file_key)
    if not page_url:
        return False
    if page_url not in cache:
        try:
            cache[page_url] = http_get(page_url, timeout=10, retries=1).text
        except RunBudgetExceeded:
            cache[page_url] = _UNKNOWN_PAGE
        except Exception:  # noqa: BLE001
            cache[page_url] = None
    page_text = cache[page_url]
    if page_text is _UNKNOWN_PAGE:
        return "unknown"
    if not page_text:
        return False
    if item_url in page_text or normalize_url(item_url) in page_text:
        return True
    norm_title = normalize_title(title) if title else ""
    return bool(norm_title) and norm_title in normalize_title(strip_html(page_text))


def site_update_targets(item, cfg):
    """[(file, target_label), ...] this outside citation should be added
    to, per config `site_update_rules`."""
    rules = cfg.get("site_update_rules", {})
    targets = [(rules.get("personal_site_file"), rules.get("personal_press_section"))]
    # Item 14: check every own link on the page, not just the first, since
    # a piece can cite more than one of Tal's properties.
    own_link_paths = [u.lower() for u in item.get("own_link_urls") or
                       ([item["own_link_url"]] if item.get("own_link_url") else [])]
    qids = item.get("queries", set())
    hits_impl = (any(p in path for path in own_link_paths
                      for p in rules.get("implementation_tracker_link_paths", []))
                 or bool(qids & set(rules.get("implementation_tracker_query_ids", []))))
    hits_fiscal = (any(p in path for path in own_link_paths
                        for p in rules.get("fiscal_tracker_link_paths", []))
                   or bool(qids & set(rules.get("fiscal_tracker_query_ids", []))))
    if hits_impl:
        targets.append((rules.get("implementation_tracker_file"), rules.get("implementation_tracker_target")))
    if hits_fiscal:
        targets.append((rules.get("fiscal_tracker_file"), rules.get("fiscal_tracker_target")))
    if hits_impl or hits_fiscal:
        targets.append((rules.get("trackers_hub_file"), rules.get("trackers_hub_target")))
    return targets


def build_update_prompt(item, targets, cfg, queries_by_id, is_own=False):
    title = item["title"] or "(untitled)"
    outlet = item["outlet"] or item["domain"]
    date_str = item["published"].strftime("%Y-%m-%d") if item["published"] else "date unknown"
    url = effective_url(item)
    note = ""
    if "google_news" in item["sources"] and "news.google.com" in url:
        # Resolution failed and we fell back to the opaque redirect.
        note = " (Google News link is opaque; resolve the real outlet URL first)"
    snippet = extract_context(item, queries_by_id)
    signals = item.get("signal") or ", ".join(sorted(item["queries"]))
    targets_str = "; ".join(f"{f} → {t}" for f, t in targets if f)
    lead = "Add my own piece" if is_own else "Add this outside mention"
    return (
        f'{lead} to my websites. Mention: "{title}", {outlet}, {date_str}, '
        f'{url}{note}. What it cites: "{snippet}" (matched: {signals}).\n'
        f"Targets: {targets_str}.\n"
        "Steps: git fetch && git pull in each repo first. Fetch the URL and confirm it is live "
        "and cites me as quoted; if not, stop and tell me. Match the format of the existing "
        'entries in each target exactly (for hero-press lines, extend the existing "Featured '
        'in" sentence; add the .hero-press CSS only if the page lacks it). Write entry copy in '
        "my voice per CLAUDE.md voice rules. Update personal_website/profile_facts.json "
        '"press" (outside) or "bylines" (own) if the outlet is new. Show me the entry text '
        "before committing; stage explicit paths only; then commit and push each repo."
    )


def site_update_entries(new_items, own_items, research_items, cfg, queries_by_id):
    """[(item, note_or_None, prompt_or_None), ...] for every outside/own item
    that has a site-update recommendation (skipped: never_feature_urls,
    social/referrer tiers; research citations get a note only, no prompt)."""
    never = {normalize_url(u) for u in cfg.get("never_feature_urls", [])}
    never_titles = [normalize_title(t) for t in cfg.get("never_feature_titles", [])]
    rules = cfg.get("site_update_rules", {})
    cache = {}
    entries = []
    for item in new_items:
        if classify(item, cfg) not in ("news", "newsletter"):
            continue
        if normalize_url(effective_url(item)) in never:
            continue
        item_title_norm = normalize_title(item["title"])
        if item_title_norm and any(
                item_title_norm in t or t in item_title_norm for t in never_titles if t):
            continue
        if is_term_only_match(item, cfg):
            entries.append((item, "Possible uncredited citation, verify manually "
                                   f"(matched: {matched_terms_str(item, queries_by_id)})", None))
            continue
        targets = site_update_targets(item, cfg)
        results = [check_already_listed(t[0], effective_url(item), cfg, cache,
                                         title=item["title"]) for t in targets]
        if any(r == "unknown" for r in results):
            entries.append((item, "could not check site pages this run", None))
            continue
        remaining = [t for t, r in zip(targets, results) if not r]
        if not remaining:
            entries.append((item, "already listed on all its targets", None))
        else:
            entries.append((item, None, build_update_prompt(item, remaining, cfg, queries_by_id)))
    for item in own_items:
        target = [(rules.get("personal_site_file"), rules.get("personal_own_section"))]
        result = check_already_listed(target[0][0], effective_url(item), cfg, cache,
                                       title=item["title"])
        if result == "unknown":
            entries.append((item, "could not check site pages this run", None))
        elif result:
            entries.append((item, "already listed", None))
        else:
            entries.append((item, None,
                             build_update_prompt(item, target, cfg, queries_by_id, is_own=True)))
    for item in research_items:
        if item.get("openalex_kind") == "own":
            continue
        entries.append((item, "research citation: optional, add to the research list if useful", None))
    return entries


def format_site_update_section(entries):
    if not entries:
        return []
    lines = ["## Suggested website updates", ""]
    for item, note, prompt in entries:
        label = (f'**{md_escape(item["title"]) or item["domain"]}** '
                 f'({md_escape(item["outlet"]) or item["domain"]})')
        if note:
            lines.append(f"- {label}: {note}.")
        else:
            lines.append(f"- {label}:")
            lines += ["```", prompt, "```"]
    lines.append("")
    return lines


def build_digest(new_items, own_items, research_items, ref_summary, errors, cfg, run_date,
                  removal_suggestions=None, discovery_added=None, discovery_reviewed=None,
                  backlog_notices=None):
    queries_by_id = {q["id"]: q for q in cfg["queries"]}
    roundups = [i for i in new_items if is_roundup(i, cfg)]
    new_items = [i for i in new_items if not is_roundup(i, cfg)]
    tiers = {t: [] for t, _ in TIER_ORDER}
    for item in new_items:
        tiers[classify(item, cfg)].append(item)
    # openalex_kind "own" = a new work of Tal's own, not a citation of it;
    # it gets its own "New research listings" section (item 4).
    research_citing = [i for i in research_items if i.get("openalex_kind") != "own"]
    research_listings = [i for i in research_items if i.get("openalex_kind") == "own"]

    lines = [f"# NYCuriosity mention digest: {run_date}", ""]
    total = len(new_items)
    extras = []
    if own_items:
        extras.append(f"{len(own_items)} from your own pieces")
    if research_citing:
        extras.append(f"{len(research_citing)} research citation"
                       f"{'s' if len(research_citing) != 1 else ''}")
    if research_listings:
        extras.append(f"{len(research_listings)} new research listing"
                       f"{'s' if len(research_listings) != 1 else ''}")
    if roundups:
        extras.append(f"{len(roundups)} mentioned in a roundup"
                       f"{'s' if len(roundups) != 1 else ''}")
    lines.append(
        f"{total} new mention{'s' if total != 1 else ''}"
        + (", plus " + " and ".join(extras) if extras else "")
        + "."
    )
    lines.append("")

    if not new_items and not own_items and not research_items and not roundups:
        lines += ["_No new mentions this cycle._", ""]

    for tier, heading in TIER_ORDER:
        items = sorted(tiers[tier], key=sort_key_published, reverse=True)
        if not items:
            continue
        lines += [f"## {heading} ({len(items)})", ""]
        for item in items:
            lines += format_item(item, queries_by_id)
        if tier == "news" and research_citing:
            # Placed right after News outlets: real citations of Tal's
            # academic work, kept separate so they're never mistaken for
            # an outside news citation or dropped as a name collision.
            research_sorted = sorted(
                research_citing, key=sort_key_published, reverse=True)
            lines += [f"## Research citations ({len(research_sorted)})", ""]
            for item in research_sorted:
                lines += format_item(item, queries_by_id)

    if research_citing and not tiers["news"]:
        # No News outlets section printed above (e.g. all-research run);
        # still surface the section rather than dropping it.
        research_sorted = sorted(
            research_citing, key=sort_key_published, reverse=True)
        lines += [f"## Research citations ({len(research_sorted)})", ""]
        for item in research_sorted:
            lines += format_item(item, queries_by_id)

    if research_listings:
        listings_sorted = sorted(
            research_listings, key=sort_key_published, reverse=True)
        lines += [f"## New research listings ({len(listings_sorted)})", ""]
        for item in listings_sorted:
            lines += format_item(item, queries_by_id)

    if own_items:
        own_items = sorted(own_items, key=sort_key_published, reverse=True)
        lines += [f"## My own pieces ({len(own_items)})", ""]
        for item in own_items:
            lines += format_item(item, queries_by_id)

    if roundups:
        roundups_sorted = sorted(roundups, key=sort_key_published, reverse=True)
        lines += [f"## Mentioned in roundups ({len(roundups_sorted)})", ""]
        for item in roundups_sorted:
            lines += format_item(item, queries_by_id)

    lines += format_site_update_section(
        site_update_entries(new_items, own_items, research_citing, cfg, queries_by_id))

    lines += format_removal_section(removal_suggestions or [])
    lines += format_discovery_sections(discovery_added or [], discovery_reviewed or [])

    if ref_summary:
        lines += format_referrer_section(ref_summary)

    if errors:
        lines += ["## Source errors", "",
                  "These sources failed since the last digest; anything they "
                  "would have caught will surface on a later run (the dedup "
                  "db only records what was actually fetched).", ""]
        lines += [f"- {e}" for e in errors]
        lines.append("")

    if backlog_notices:
        lines += ["## Scan progress", "",
                   "Routine cap/budget carry-over, not a failure; these "
                   "sources will keep working through the backlog on later "
                   "runs.", ""]
        lines += [f"- {backlog_display(n)}" for n in backlog_notices]
        lines.append("")

    return "\n".join(lines)


def _html_website_updates(entries, esc):
    """Round 6 item 1: real HTML for the "Suggested website updates" section
    (no raw markdown); only the Claude Code prompt text itself stays in a
    <pre> block so it's exactly copyable."""
    if not entries:
        return []
    parts = ['<h2 style="font-size:17px;">Suggested website updates</h2>']
    for item, note, prompt in entries:
        label = f'{esc(item["title"]) or esc(item["domain"])} ({esc(item["outlet"] or item["domain"])})'
        parts.append(f'<div style="margin:0 0 14px 0;"><strong>{label}</strong>')
        if note:
            parts.append(f'<p style="color:#444;font-size:13px;margin:4px 0;">{esc(note)}.</p>')
        else:
            parts.append(
                '<pre style="white-space:pre-wrap;font-size:13px;background:#f6f6f6;'
                'padding:10px;border-radius:6px;overflow-x:auto;margin:4px 0;">'
                + esc(prompt) + '</pre>')
        parts.append('</div>')
    return parts


def _html_removals(suggestions, esc):
    if not suggestions:
        return []
    parts = ['<h2 style="font-size:17px;">Suggested removals</h2>',
             '<ul style="font-size:13px;">']
    for s in suggestions:
        weeks = s["weeks_silent"]
        parts.append(
            f'<li><strong>{esc(s["unit"])}</strong>: {esc(s["reason"])} for {weeks} week'
            f'{"s" if weeks != 1 else ""} (fetched {s["items_fetched"]} items in that span; '
            f'last flagged {esc(s.get("last_flagged") or "never")}). Remove it at '
            f'{esc(s.get("config_location", "config.json"))}.</li>')
    parts.append('</ul>')
    return parts


def _html_discovery(added, reviewed, esc):
    parts = []
    if added:
        parts.append('<h2 style="font-size:17px;">Added this week</h2><ul style="font-size:13px;">')
        for a in added:
            parts.append(
                f'<li><strong>{esc(a["domain"])}</strong> ({esc(a["type"])}): found via '
                f'{esc(a["found_via"])}. Remove: delete its entry from discovered_sources.json.</li>')
        parts.append('</ul>')
    if reviewed:
        parts.append(
            '<h2 style="font-size:17px;">Candidates needing manual review</h2>'
            '<ul style="font-size:13px;">')
        for r in reviewed:
            status = "auto-add off" if r["passed"] else "probe failed"
            parts.append(
                f'<li><strong>{esc(r["domain"])}</strong>: {esc(status)} '
                f'(found via {esc(r["found_via"])}).</li>')
        parts.append('</ul>')
    return parts


def _html_scan_progress(notices, esc):
    if not notices:
        return []
    parts = ['<h2 style="font-size:14px;color:#888;margin-top:24px;">Scan progress</h2>',
             '<ul style="font-size:12px;color:#888;">']
    parts += [f'<li>{esc(backlog_display(n))}</li>' for n in notices]
    parts.append('</ul>')
    return parts


def build_digest_html(new_items, own_items, research_items, ref_summary, errors, cfg, run_date,
                       removal_suggestions=None, discovery_added=None, discovery_reviewed=None,
                       backlog_notices=None):
    """HTML companion to build_digest for the multipart email: rich per-item
    cards for the mention sections, and real HTML (not raw markdown) for
    every other section; only the Claude Code prompt text itself stays in a
    <pre> block so it's exactly copyable."""
    queries_by_id = {q["id"]: q for q in cfg["queries"]}
    roundups = [i for i in new_items if is_roundup(i, cfg)]
    new_items = [i for i in new_items if not is_roundup(i, cfg)]
    tiers = {t: [] for t, _ in TIER_ORDER}
    for item in new_items:
        tiers[classify(item, cfg)].append(item)
    research_citing = [i for i in research_items if i.get("openalex_kind") != "own"]
    research_listings = [i for i in research_items if i.get("openalex_kind") == "own"]

    def esc(s):
        return html_mod.escape(s or "", quote=True)

    def item_card(item):
        date_str = item["published"].strftime("%Y-%m-%d") if item["published"] else ""
        snippet = extract_context(item, queries_by_id)
        signals = esc(item.get("signal") or ", ".join(sorted(item["queries"])))
        meta = esc(item["outlet"] or item["domain"]) + (f" · {esc(date_str)}" if date_str else "")
        return (
            '<div style="margin:0 0 18px 0;">'
            f'<a href="{esc(effective_url(item))}" style="font-weight:600;color:#0b5cab;'
            f'text-decoration:none;">{esc(item["title"]) or "(untitled)"}</a>'
            f'<div style="color:#555;font-size:13px;margin:2px 0;">{meta}</div>'
            f'<p style="color:#444;font-size:14px;margin:4px 0;">{esc(snippet)}</p>'
            f'<div style="color:#888;font-size:11px;">matched: {signals}</div>'
            '</div>'
        )

    body = [f'<p style="font-size:15px;">{len(new_items)} new mention'
            f'{"s" if len(new_items) != 1 else ""}.</p>']
    for tier, heading in TIER_ORDER:
        items = sorted(tiers[tier], key=sort_key_published, reverse=True)
        if not items:
            continue
        body.append(f'<h2 style="font-size:17px;border-bottom:1px solid #ddd;'
                     f'padding-bottom:4px;">{esc(heading)} ({len(items)})</h2>')
        body += [item_card(i) for i in items]
    if research_citing:
        rs = sorted(research_citing, key=sort_key_published, reverse=True)
        body.append(f'<h2 style="font-size:17px;">Research citations ({len(rs)})</h2>')
        body += [item_card(i) for i in rs]
    if research_listings:
        rl = sorted(research_listings, key=sort_key_published, reverse=True)
        body.append(f'<h2 style="font-size:17px;">New research listings ({len(rl)})</h2>')
        body += [item_card(i) for i in rl]
    if own_items:
        os_ = sorted(own_items, key=sort_key_published, reverse=True)
        body.append(f'<h2 style="font-size:17px;">My own pieces ({len(os_)})</h2>')
        body += [item_card(i) for i in os_]
    if roundups:
        ru = sorted(roundups, key=sort_key_published, reverse=True)
        body.append(f'<h2 style="font-size:17px;">Mentioned in roundups ({len(ru)})</h2>')
        body += [item_card(i) for i in ru]

    body += _html_website_updates(
        site_update_entries(new_items, own_items, research_citing, cfg, queries_by_id), esc)
    body += _html_removals(removal_suggestions or [], esc)
    body += _html_discovery(discovery_added or [], discovery_reviewed or [], esc)

    if ref_summary:
        body.append('<h2 style="font-size:17px;">Sites sending visitors this week</h2>')
        for host, info in sorted(ref_summary.items(), key=lambda kv: -kv[1]["total"]):
            body.append(f'<p style="font-size:14px;"><b>{esc(host)}</b>: '
                         f'{info["total"]} request{"s" if info["total"] != 1 else ""}</p>')
    if errors:
        body.append('<h2 style="font-size:17px;">Source errors</h2>')
        body.append('<ul style="font-size:13px;color:#a00;">'
                     + "".join(f"<li>{esc(e)}</li>" for e in errors) + '</ul>')

    body += _html_scan_progress(backlog_notices or [], esc)

    return (
        '<html><body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,'
        'sans-serif;max-width:680px;margin:0 auto;padding:16px;color:#222;">'
        f'<h1 style="font-size:20px;">NYCuriosity mention digest: {esc(run_date)}</h1>'
        + "".join(body) +
        '</body></html>'
    )


def build_digest_subject(new_items, own_items, research_items, digest_errors,
                          removal_suggestions, discovery_added, cfg, run_date):
    """Item 13: the email subject line's counts, each included only when
    nonzero. new_items is split into outside vs. roundup the same way
    build_digest splits it."""
    n_roundups = sum(1 for i in new_items if is_roundup(i, cfg))
    n_outside = len(new_items) - n_roundups
    n_own = len(own_items)
    n_research = len(research_items)
    n_errors = len(digest_errors or [])
    parts = []
    if n_outside:
        parts.append(f"{n_outside} new mention{'s' if n_outside != 1 else ''}")
    if n_roundups:
        parts.append(f"{n_roundups} roundup{'s' if n_roundups != 1 else ''}")
    if n_own:
        parts.append(f"{n_own} own piece{'s' if n_own != 1 else ''}")
    if n_research:
        parts.append(f"{n_research} research item{'s' if n_research != 1 else ''}")
    if discovery_added:
        n_added = len(discovery_added)
        parts.append(f"{n_added} source{'s' if n_added != 1 else ''} added")
    if removal_suggestions:
        parts.append(f"{len(removal_suggestions)} removal suggestion"
                      f"{'s' if len(removal_suggestions) != 1 else ''}")
    if n_errors:
        parts.append(f"{n_errors} error{'s' if n_errors != 1 else ''}")
    return "NYCuriosity mention digest: " + (", ".join(parts) if parts else "update") \
        + f" ({run_date})"


def send_email(subject, text_body, html_body=None):
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and password):
        print("WARNING: --email set but GMAIL_USER/GMAIL_APP_PASSWORD missing; "
              "skipping email.", file=sys.stderr)
        return False
    # An unset repo secret comes through Actions as an empty string, not a
    # missing var, so `.get(..., user)` never falls back; `or` does.
    to = os.environ.get("MENTION_DIGEST_TO") or user
    if html_body:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
    else:
        msg = MIMEText(text_body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, password)
        s.send_message(msg)
    print(f"Emailed digest to {to}.", file=sys.stderr)
    return True


def next_digest_path(outdir, run_date):
    """Never overwrite a same-day digest: a second --digest run on the same
    date gets `<date>-2.md`, a third `<date>-3.md`, and so on."""
    outpath = outdir / f"{run_date}.md"
    suffix = 1
    while outpath.exists():
        suffix += 1
        outpath = outdir / f"{run_date}-{suffix}.md"
    return outpath


# --------------------------------------------------------------------- main

def collect(cfg, since, conn=None, weekly=False, now=None):
    """Fetch every (query, source) pair for google_news, plus one pass over
    every outlet feed for the queries that list "outlets" as a source, plus
    (daily) sitemap_scan and alert_feeds, plus (only when `weekly` - a
    --digest or --backfill run) wp_search and openalex. Merges duplicates
    across queries and sources. One dead source is recorded as an error,
    never fatal. Returns (merged_items, errors, source_stats) where
    source_stats maps source name -> its own per-unit stats dict."""
    now = now or datetime.now(timezone.utc)
    delay = float(cfg.get("request_delay_seconds", 2.0))
    default_sources = cfg.get("sources", ["google_news", "outlets"])
    merged, index, errors = [], {}, []
    source_stats = {}
    gn_stats = {}
    # Same wall-clock safety net as the outlet scan: a slow/hanging API must
    # not stall the whole run past a bounded budget.
    deadline = time.monotonic() + float(cfg.get("query_time_budget_seconds", 120))
    budget_hit = False

    def merge_item(item):
        keys = item_keys(item)
        if not keys:
            return
        existing = next((index[k] for k in keys if k in index), None)
        if existing is not None:
            merged[existing]["queries"] |= item["queries"]
            merged[existing]["sources"] |= item["sources"]
            merged[existing]["keys"] |= keys
            keys = merged[existing]["keys"]
            target = existing
        else:
            item["keys"] = keys
            merged.append(item)
            target = len(merged) - 1
        for k in keys:
            index[k] = target

    for query in cfg["queries"]:
        if time.monotonic() > deadline:
            budget_hit = True
            break
        for source in query.get("sources", default_sources):
            if source == "outlets":
                continue
            fetcher = FETCHERS.get(source)
            if fetcher is None:
                errors.append(f"{query['id']}: unknown source '{source}'")
                continue
            gn_entry = None
            if source == "google_news":
                gn_entry = gn_stats.setdefault(
                    query["id"], {"fetched": 0, "errored": False, "unresolved": 0})
            n_errors_before = len(errors)
            try:
                if source == "google_news":
                    fetched = fetcher(query, cfg, since, errors=errors, conn=conn, delay=delay)
                else:
                    fetched = fetcher(query, cfg, since)
            except Exception as e:  # noqa: BLE001 (isolate every source)
                errors.append(f"{source} / {query['id']}: {e}")
                fetched = []
            if gn_entry is not None:
                gn_entry["fetched"] += len(fetched)
                if len(errors) > n_errors_before:
                    gn_entry["errored"] = True
                gn_entry["unresolved"] += sum(
                    1 for item in fetched
                    if "news.google.com" in (item.get("resolved_url") or item["url"]))
            time.sleep(delay)
            for item in fetched:
                merge_item(item)

    if budget_hit:
        errors.append(
            "google_news: hit query_time_budget_seconds "
            f"({cfg.get('query_time_budget_seconds', 120)}s); remaining "
            "queries were skipped and will be retried next run"
        )
    source_stats["google_news"] = gn_stats

    def run_source(label, fn, *fn_args, **fn_kwargs):
        """Isolate one source (including a shared run_time_budget_seconds
        hit, which raises RunBudgetExceeded) so it can never crash the
        whole collect() and always leaves a source error behind."""
        try:
            return fn(*fn_args, **fn_kwargs)
        except RunBudgetExceeded as e:
            errors.append(f"{label}: {e}")
            return [], [], {}
        except Exception as e:  # noqa: BLE001 (isolate every source)
            errors.append(f"{label}: {e}")
            return [], [], {}

    outlet_queries = [q for q in cfg["queries"]
                      if "outlets" in q.get("sources", default_sources)]
    if outlet_queries:
        outlet_items, outlet_errors, outlet_stats = run_source(
            "outlets", fetch_outlets, cfg, outlet_queries, delay, conn=conn)
        errors += outlet_errors
        source_stats["outlets"] = outlet_stats
        for item in outlet_items:
            merge_item(item)

    if cfg.get("sitemap_scan"):
        sm_items, sm_errors, sm_stats = run_source(
            "sitemap_scan", fetch_sitemap_scan, cfg, cfg["queries"], delay, conn=conn, now=now)
        errors += sm_errors
        source_stats["sitemap_scan"] = sm_stats
        for item in sm_items:
            merge_item(item)

    if cfg.get("alert_feeds") or os.environ.get("GOOGLE_ALERT_FEEDS"):
        al_items, al_errors, al_stats = run_source(
            "alert_feeds", fetch_alert_feeds, cfg, delay)
        errors += al_errors
        source_stats["alert_feeds"] = al_stats
        for item in al_items:
            merge_item(item)

    if weekly and cfg.get("wp_search_sites"):
        wp_items, wp_errors, wp_stats = run_source(
            "wp_search", fetch_wp_search, cfg, cfg["queries"], delay, conn=conn)
        errors += wp_errors
        source_stats["wp_search"] = wp_stats
        for item in wp_items:
            merge_item(item)

    if weekly and cfg.get("openalex_author_ids"):
        oa_items, oa_errors, oa_stats = run_source("openalex", fetch_openalex, cfg)
        errors += oa_errors
        source_stats["openalex"] = oa_stats
        for item in oa_items:
            merge_item(item)

    return merged, errors, source_stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--db", default=str(HERE / "seen.db"))
    ap.add_argument("--outdir", default=str(HERE / "digests"))
    ap.add_argument("--backfill", action="store_true",
                     help="seed the seen-db from ~90 days back; no pending "
                          "items, no digest, no email")
    ap.add_argument("--digest", action="store_true",
                     help="collect, then build+write the digest from all "
                          "pending items and mark them digested")
    ap.add_argument("--email", action="store_true",
                     help="email the digest when --digest produces one")
    ap.add_argument("--referrers-window-hours", type=int, default=24,
                     help="how far back --referrers-only looks (default 24); "
                          "a wider window tells 'no traffic yet' apart from a "
                          "broken query")
    ap.add_argument("--referrers-only", action="store_true",
                     help="run only the Cloudflare referrer source and print "
                          "its rows or the exact GraphQL error; no db writes")
    ap.add_argument("--discovered-path", default=None,
                     help="where to read/write discovered_sources.json "
                          "(default: next to this script, which CI commits)")
    args = ap.parse_args()
    if args.discovered_path:
        global DISCOVERED_FILE
        DISCOVERED_FILE = Path(args.discovered_path)

    with open(args.config) as f:
        cfg = json.load(f)
    SESSION.headers["User-Agent"] = cfg.get(
        "user_agent", "nycuriosity-mention-monitor/1.0")
    set_run_budget(cfg)

    now = datetime.now(timezone.utc)

    if args.referrers_only:
        rows, err, skipped = fetch_cloudflare_referrers(
            cfg, now, window_hours=args.referrers_window_hours)
        if skipped:
            print("cloudflare_referrers skipped: CF_ANALYTICS_TOKEN/CF_ACCOUNT_ID not set.")
        elif err:
            print(f"cloudflare_referrers error: {err}")
        else:
            print(f"cloudflare_referrers: {len(rows)} rows")
            for row in rows:
                print(f"  {row['host']} -> {row['dest_host']}{row['path']}: "
                      f"{row['requests']}")
        return

    since = now - timedelta(days=90) if args.backfill else None
    weekly = args.backfill or args.digest  # wp_search + openalex: item 1/4

    cfg_runtime = apply_discovered_sources(cfg)
    # Weekly (digest/backfill), refresh own bylines from the live
    # Publications page so the hand-kept list can't fall behind.
    if args.digest or args.backfill:
        cfg_runtime = apply_own_bylines(cfg_runtime)
    # Each outlet's (including discovered ones') configured tier drives
    # digest ordering the same way a manual tier_overrides entry would.
    overrides = cfg_runtime.setdefault("tier_overrides", {})
    for outlet in cfg_runtime.get("outlets", []):
        domain = norm_domain(urlparse(outlet["feed"]).netloc)
        overrides.setdefault(domain, outlet.get("tier", "news"))
    for sm in cfg_runtime.get("sitemap_scan", []):
        domain = norm_domain(urlparse(sm["sitemap"]).netloc)
        overrides.setdefault(domain, sm.get("tier", "news"))
    queries_by_id = {q["id"]: q for q in cfg_runtime["queries"]}

    conn = db_connect(args.db)
    items, errors, source_stats = collect(cfg_runtime, since, conn=conn, weekly=weekly, now=now)

    now_iso = now.isoformat(timespec="seconds")
    per_source_counts = {}
    n_seen = n_excluded = n_filtered = 0
    n_new_outside = n_new_own = n_new_research = 0
    for item in items:
        for s in item["sources"]:
            per_source_counts[s] = per_source_counts.get(s, 0) + 1
        seen = any_seen(conn, item["keys"])
        # Everything fetched is marked seen, including excluded and
        # require-term-filtered items, so nothing resurfaces run after run.
        mark_seen(conn, item, now_iso)
        if seen:
            n_seen += 1
            continue
        if is_excluded(item, cfg_runtime):
            n_excluded += 1
            continue
        if not passes_require_terms(item, queries_by_id):
            n_filtered += 1
            continue
        if args.backfill:
            continue  # seed the seen-db only; nothing queued for a digest
        if "openalex" in item["sources"]:
            # openalex_kind tells build_digest whether this is a citation of
            # Tal's work ("citing") or a new work of his own ("own"); both
            # go in the "research" pending bucket to keep pending_load's
            # 4-tuple shape stable.
            pending_add(conn, item, "research", now_iso)
            n_new_research += 1
        else:
            kind = classify_pending_kind(item, cfg_runtime)
            pending_add(conn, item, kind, now_iso)
            if kind == "own":
                n_new_own += 1
            elif kind == "research":
                n_new_research += 1
            else:
                n_new_outside += 1

    ref_rows, ref_err, ref_skipped = fetch_cloudflare_referrers(cfg_runtime, now)
    if ref_err:
        errors.append(ref_err)
    elif ref_skipped:
        print("info: cloudflare_referrers skipped "
              "(CF_ANALYTICS_TOKEN/CF_ACCOUNT_ID not set).", file=sys.stderr)
    elif ref_rows:
        store_referrers(conn, now.strftime("%Y-%m-%d"), ref_rows)

    # Item 8/9: record this run's per-unit yield, and (weekly) probe for new
    # candidate sources before the digest is built.
    date_str = now.strftime("%Y-%m-%d")
    yield_rows = []
    for outlet_name, s in (source_stats.get("outlets") or {}).items():
        yield_rows.append({"unit": f"outlets:{outlet_name}", "ran": True,
                            "items_fetched": s.get("scanned", 0),
                            "items_flagged": 0, "errored": bool(s.get("errored"))})
    for site, s in (source_stats.get("wp_search") or {}).items():
        yield_rows.append({"unit": f"wp_search:{site}", "ran": True,
                            "items_fetched": s.get("hits", 0), "items_flagged": 0,
                            "errored": bool(s.get("errored"))})
    for name, s in (source_stats.get("sitemap_scan") or {}).items():
        yield_rows.append({"unit": f"sitemap:{name}", "ran": True,
                            "items_fetched": s.get("scanned", 0),
                            "items_flagged": 0, "errored": bool(s.get("errored"))})
    for qid, s in (source_stats.get("google_news") or {}).items():
        yield_rows.append({"unit": f"google_news:{qid}", "ran": True,
                            "items_fetched": s.get("fetched", 0), "items_flagged": 0,
                            "errored": bool(s.get("errored"))})
    # items_flagged per unit: attribute each surfaced item to its source unit.
    for item in items:
        if "outlets" in item["sources"]:
            unit = f"outlets:{item['outlet']}"
        elif "wp_search" in item["sources"]:
            unit = f"wp_search:{item['outlet']}"
        elif "sitemap_scan" in item["sources"]:
            unit = f"sitemap:{item['outlet']}"
        elif "google_news" in item["sources"]:
            for qid in item["queries"]:
                for row in yield_rows:
                    if row["unit"] == f"google_news:{qid}":
                        row["items_flagged"] += 1
            continue
        else:
            continue
        for row in yield_rows:
            if row["unit"] == unit:
                row["items_flagged"] += 1
                break
    if weekly:
        referrer_hosts = [r["host"] for r in ref_rows] if ref_rows else []
        candidates = extract_candidate_domains(items, cfg_runtime, referrer_hosts=referrer_hosts)
        run_added, run_reviewed = run_discovery(cfg_runtime, conn, now, candidates)
        record_discovery_results(conn, run_added, run_reviewed, now_iso)
    if yield_rows:
        record_yield(conn, date_str, yield_rows)

    # Round 6 item 2: cap/budget carry-over notices are routine backlog, not
    # a failure; kept out of source_errors entirely.
    real_errors = [e for e in errors if not is_backlog_notice(e)]
    backlog = [e for e in errors if is_backlog_notice(e)]
    record_source_errors(conn, real_errors, now_iso)
    record_backlog_notices(conn, backlog, now_iso)
    conn.commit()

    counts_str = ", ".join(f"{k}: {v}" for k, v in sorted(per_source_counts.items()))
    summary = (f"fetched {len(items)} unique items ({counts_str}); "
               f"{n_new_outside} new outside, {n_new_own} new own, "
               f"{n_new_research} new research, "
               f"{n_seen} already seen, {n_excluded} own-property, "
               f"{n_filtered} failed require-terms, {len(errors)} source errors")

    for outlet_name, stats in (source_stats.get("outlets") or {}).items():
        print(f"  outlet {outlet_name}: scanned {stats['scanned']}/"
              f"{stats['available']} available "
              f"({stats['skipped_prescanned']} already scanned, skipped)",
              file=sys.stderr)
    for site, s in (source_stats.get("wp_search") or {}).items():
        print(f"  wp_search {site}: {s.get('hits', 0)} hits", file=sys.stderr)
    for name, stats in (source_stats.get("sitemap_scan") or {}).items():
        print(f"  sitemap_scan {name}: scanned {stats['scanned']}/{stats['available']} "
              f"available ({stats['remaining']} remaining, {stats['paywalled']} paywalled)",
              file=sys.stderr)
    if source_stats.get("openalex"):
        oa = source_stats["openalex"]
        print(f"  openalex: {oa.get('author_works', 0)} author works, "
              f"{oa.get('citing_works', 0)} new citing works", file=sys.stderr)
    if source_stats.get("alert_feeds"):
        for feed_title, n in source_stats["alert_feeds"].items():
            print(f"  alert_feeds {feed_title}: {n} entries", file=sys.stderr)
    gn_unresolved = sum(s.get("unresolved", 0)
                        for s in (source_stats.get("google_news") or {}).values())
    if gn_unresolved:
        print(f"  google_news: {gn_unresolved} links unresolved", file=sys.stderr)

    if args.backfill:
        print(f"Backfill complete: {summary}.")
        for e in errors:
            print(f"  error: {e}", file=sys.stderr)
        conn.close()
        return

    if not args.digest:
        print(f"Collected: {summary}.")
        for e in errors:
            print(f"  error: {e}", file=sys.stderr)
        conn.close()
        return

    new_items, own_items, research_items, pending_ids = pending_load(conn)
    ref_summary = load_referrer_summary(conn, (now - timedelta(days=7)).strftime("%Y-%m-%d"))
    digest_errors = load_and_clear_source_errors(conn)
    backlog_notices = load_and_clear_backlog_notices(conn)
    removal_suggestions = suggest_removals(conn, cfg_runtime)
    discovery_added, discovery_reviewed = load_and_clear_discovery_results(conn)

    run_date = now.strftime("%Y-%m-%d")
    digest = build_digest(new_items, own_items, research_items, ref_summary,
                           digest_errors, cfg_runtime, run_date,
                           removal_suggestions, discovery_added, discovery_reviewed,
                           backlog_notices)
    digest_html = build_digest_html(new_items, own_items, research_items, ref_summary,
                                     digest_errors, cfg_runtime, run_date,
                                     removal_suggestions, discovery_added, discovery_reviewed,
                                     backlog_notices)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    outpath = next_digest_path(outdir, run_date)
    outpath.write_text(digest)

    pending_mark_digested(conn, pending_ids)
    conn.commit()
    conn.close()

    print(digest)
    print(f"---\nDigest written to {outpath} ({summary}).", file=sys.stderr)

    has_content = bool(new_items or own_items or research_items or ref_summary
                        or removal_suggestions or discovery_added or discovery_reviewed
                        or digest_errors)

    if args.email and has_content:
        subject = build_digest_subject(new_items, own_items, research_items, digest_errors,
                                         removal_suggestions, discovery_added, cfg_runtime, run_date)
        send_email(subject, digest, digest_html)
    elif args.email:
        print("No new content; skipping email.", file=sys.stderr)


if __name__ == "__main__":
    main()
