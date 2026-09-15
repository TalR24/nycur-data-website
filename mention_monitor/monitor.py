#!/usr/bin/env python3
"""Weekly mention monitor for Tal Roded / NYCuriosity.

Polls Google News RSS, Bing News RSS, the Bluesky public search API, and
Reddit search for the queries in config.json, drops results from Tal's own
properties, dedupes against a local SQLite db, and writes a markdown digest
sorted by source quality (news outlets, then newsletters/blogs, then social).
Citizens Union Searchlight results (Tal's own column) are routed to a
separate section rather than dropped.

Usage:
  python3 monitor.py                  # fetch, write dated digest, print to stdout
  python3 monitor.py --email          # same, plus email the digest (see env below)
  python3 monitor.py --backfill       # seed the seen-db from ~90 days back;
                                      #   no digest, no email

Email (only used with --email; all optional otherwise):
  GMAIL_USER / GMAIL_APP_PASSWORD     # same secrets the other repo pipelines use
  MENTION_DIGEST_TO                   # recipient; defaults to GMAIL_USER

Dedup notes: Google News RSS links are opaque redirects that can't be decoded
offline, and the same article often surfaces through both Google and Bing, so
each item is keyed on BOTH its normalized URL and an outlet-domain + title
fingerprint. An item counts as new only if no key has been seen before.
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
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import feedparser
import requests

HERE = Path(__file__).resolve().parent
SESSION = requests.Session()
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
BING_NEWS_RSS = "https://www.bing.com/news/search"
BSKY_SEARCH = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
REDDIT_SEARCH = "https://www.reddit.com/search.json"

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


def _is_tracking_param(k):
    k = k.lower()
    return k.startswith("utm_") or k in {
        "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src",
        "smid", "cmpid", "r", "s", "sk", "share",
    }


def unwrap_bing(url):
    """Bing news RSS wraps article links in an apiclick redirect."""
    p = urlparse(url)
    if norm_domain(p.netloc).endswith("bing.com") and "apiclick" in p.path:
        real = parse_qs(p.query).get("url", [None])[0]
        if real:
            return real
    return url


def normalize_url(url):
    """Canonical form used only for dedup keys; displayed URLs stay raw."""
    url = unwrap_bing((url or "").strip())
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
    if item["url"]:
        keys.add("u:" + hashlib.sha1(normalize_url(item["url"]).encode()).hexdigest())
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
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def http_get(url, params=None, timeout=30, retries=3):
    """GET with retry/backoff on rate limits and transient server errors."""
    last = None
    for attempt in range(retries):
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
        "published": published,
        "text": text,
    }


# ----------------------------------------------------------------- fetchers

def fetch_google_news(query, cfg, since):
    q = query["q"] + (f" after:{since:%Y-%m-%d}" if since else "")
    r = http_get(GOOGLE_NEWS_RSS, params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    items = []
    for e in feedparser.parse(r.content).entries:
        src = e.get("source") or {}
        outlet = src.get("title") or ""
        domain = norm_domain(urlparse(src.get("href") or "").netloc) or "news.google.com"
        title = e.get("title") or ""
        # Google appends " - Outlet" to titles; strip it so title fingerprints
        # line up with the same article coming from Bing.
        if outlet and title.endswith(" - " + outlet):
            title = title[: -len(" - " + outlet)]
        # Google's RSS "summary" is usually just the headline + outlet again;
        # drop it when it adds nothing so context snippets aren't doubled.
        summary = strip_html(e.get("summary"))
        if summary.startswith(title):
            leftover = summary[len(title):].strip(" -–—.")
            summary = "" if leftover in ("", outlet) else leftover
        items.append(make_item(
            "google_news", query["id"], outlet or domain, domain, title,
            e.get("link") or "", parse_feed_date(e), summary,
        ))
    return items


def fetch_bing_news(query, cfg, since):
    # Bing's RSS has no date operator; backfill depth is whatever it returns.
    r = http_get(BING_NEWS_RSS, params={"q": query["q"], "format": "rss"})
    items = []
    for e in feedparser.parse(r.content).entries:
        url = unwrap_bing(e.get("link") or "")
        domain = norm_domain(urlparse(url).netloc)
        items.append(make_item(
            "bing_news", query["id"], domain, domain, e.get("title") or "",
            url, parse_feed_date(e), strip_html(e.get("summary")),
        ))
    return items


def fetch_bluesky(query, cfg, since):
    excluded = {h.lower() for h in cfg.get("exclude_bluesky_handles", [])}
    params = {"q": query["q"], "limit": 100, "sort": "latest"}
    if since:
        params["since"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    r = http_get(BSKY_SEARCH, params=params)
    items = []
    for p in r.json().get("posts", []):
        author = p.get("author") or {}
        handle = author.get("handle") or ""
        if handle.lower() in excluded:
            continue
        rkey = (p.get("uri") or "").rsplit("/", 1)[-1]
        record = p.get("record") or {}
        text = record.get("text") or ""
        display = author.get("displayName") or handle
        items.append(make_item(
            "bluesky", query["id"], f"{display} (@{handle})", "bsky.app",
            text[:120], f"https://bsky.app/profile/{handle}/post/{rkey}",
            parse_iso(record.get("createdAt")), text,
        ))
    return items


def fetch_reddit(query, cfg, since):
    excluded = {a.lower() for a in cfg.get("exclude_reddit_authors", [])}
    # No 90-day window on reddit search; t=year is the closest superset.
    params = {"q": query["q"], "sort": "new", "limit": 100,
              "t": "year" if since else "month"}
    r = http_get(REDDIT_SEARCH, params=params)
    items = []
    for child in (r.json().get("data") or {}).get("children", []):
        d = child.get("data") or {}
        if (d.get("author") or "").lower() in excluded:
            continue
        title = d.get("title") or ""
        body = (d.get("selftext") or "")[:1500]
        published = (datetime.fromtimestamp(d["created_utc"], tz=timezone.utc)
                     if d.get("created_utc") else None)
        items.append(make_item(
            "reddit", query["id"], f"r/{d.get('subreddit', '')}", "reddit.com",
            title, "https://www.reddit.com" + (d.get("permalink") or ""),
            published, f"{title} {body}".strip(),
        ))
    return items


FETCHERS = {
    "google_news": fetch_google_news,
    "bing_news": fetch_bing_news,
    "bluesky": fetch_bluesky,
    "reddit": fetch_reddit,
}


# ------------------------------------------------------- filters & classify

def is_excluded(item, cfg):
    if any(domain_matches(item["domain"], d) for d in cfg.get("exclude_domains", [])):
        return True
    nu = normalize_url(item["url"]).lower()
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


def passes_require_terms(item, queries_by_id):
    """Keep the item if ANY matching query is satisfied: a query with no
    require_terms always passes; one with require_terms needs at least one
    term present in the item's title/text (kills '$7.5 billion' noise)."""
    hay = f'{item["title"]} {item["text"]}'.lower()
    for qid in item["queries"]:
        terms = queries_by_id.get(qid, {}).get("require_terms") or []
        if not terms or any(t.lower() in hay for t in terms):
            return True
    return False


def classify(item, cfg):
    override = cfg.get("tier_overrides", {}).get(item["domain"])
    if override in dict(TIER_ORDER):
        return override
    if item["sources"] & {"bluesky", "reddit"}:
        return "social"
    if any(domain_matches(item["domain"], d) for d in cfg.get("newsletter_domains", [])):
        return "newsletter"
    return "news"


def extract_context(item, queries_by_id, width=340):
    """The sentence-ish window around the first matched term, so a real
    citation is distinguishable from a passing mention at a glance. RSS
    summaries are often just the headline, so this is best-effort."""
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
    return conn


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


# ------------------------------------------------------------------- digest

def md_escape(s):
    return (s or "").replace("[", r"\[").replace("]", r"\]")


def format_item(item, queries_by_id):
    date_str = f' — {item["published"]:%Y-%m-%d}' if item["published"] else ""
    lines = [
        f'**{md_escape(item["outlet"]) or item["domain"]}** — '
        f'[{md_escape(item["title"]) or "(untitled)"}]({item["url"]}){date_str}',
        f"> {extract_context(item, queries_by_id)}",
        f'_(via {", ".join(sorted(item["sources"]))}; '
        f'matched: {", ".join(sorted(item["queries"]))})_',
        "",
    ]
    return lines


def build_digest(new_items, own_items, errors, cfg, run_date):
    queries_by_id = {q["id"]: q for q in cfg["queries"]}
    tiers = {t: [] for t, _ in TIER_ORDER}
    for item in new_items:
        tiers[classify(item, cfg)].append(item)

    lines = [f"# NYCuriosity mention digest — {run_date}", ""]
    total = len(new_items)
    lines.append(
        f"{total} new mention{'s' if total != 1 else ''}"
        + (f", plus {len(own_items)} from your own columns" if own_items else "")
        + "."
    )
    lines.append("")

    if not new_items and not own_items:
        lines += ["_No new mentions this week._", ""]

    for tier, heading in TIER_ORDER:
        items = sorted(tiers[tier], key=lambda i: i["published"] or EPOCH, reverse=True)
        if not items:
            continue
        lines += [f"## {heading} ({len(items)})", ""]
        for item in items:
            lines += format_item(item, queries_by_id)

    if own_items:
        own_items = sorted(own_items, key=lambda i: i["published"] or EPOCH, reverse=True)
        lines += [f"## My own columns — Citizens Union Searchlight ({len(own_items)})", ""]
        for item in own_items:
            lines += format_item(item, queries_by_id)

    if errors:
        lines += ["## Source errors", "",
                  "These sources failed this run; anything they would have "
                  "caught will surface next week (the dedup db only records "
                  "what was actually fetched).", ""]
        lines += [f"- {e}" for e in errors]
        lines.append("")

    return "\n".join(lines)


def send_email(subject, body):
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and password):
        print("WARNING: --email set but GMAIL_USER/GMAIL_APP_PASSWORD missing; "
              "skipping email.", file=sys.stderr)
        return False
    to = os.environ.get("MENTION_DIGEST_TO", user)
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, password)
        s.send_message(msg)
    print(f"Emailed digest to {to}.", file=sys.stderr)
    return True


# --------------------------------------------------------------------- main

def collect(cfg, since):
    """Fetch every (query, source) pair, merging duplicates across queries
    and sources. One dead source is recorded as an error, never fatal."""
    delay = float(cfg.get("request_delay_seconds", 2.0))
    default_sources = cfg.get("sources", list(FETCHERS))
    merged, index, errors = [], {}, []

    for query in cfg["queries"]:
        for source in query.get("sources", default_sources):
            fetcher = FETCHERS.get(source)
            if fetcher is None:
                errors.append(f"{query['id']}: unknown source '{source}'")
                continue
            try:
                fetched = fetcher(query, cfg, since)
            except Exception as e:  # noqa: BLE001 — isolate every source
                errors.append(f"{source} / {query['id']}: {e}")
                fetched = []
            time.sleep(delay)
            for item in fetched:
                keys = item_keys(item)
                if not keys:
                    continue
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
    return merged, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--db", default=str(HERE / "seen.db"))
    ap.add_argument("--outdir", default=str(HERE / "digests"))
    ap.add_argument("--backfill", action="store_true",
                    help="seed the seen-db from ~90 days back; no digest/email")
    ap.add_argument("--email", action="store_true",
                    help="email the digest when there are new items")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)
    SESSION.headers["User-Agent"] = cfg.get(
        "user_agent", "nycuriosity-mention-monitor/1.0")
    queries_by_id = {q["id"]: q for q in cfg["queries"]}

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=90) if args.backfill else None

    items, errors = collect(cfg, since)

    conn = db_connect(args.db)
    now_iso = now.isoformat(timespec="seconds")
    new_items, own_items = [], []
    n_seen = n_excluded = n_filtered = 0
    for item in items:
        seen = any_seen(conn, item["keys"])
        # Everything fetched is marked seen — including excluded and
        # require-term-filtered items — so nothing resurfaces week after week.
        mark_seen(conn, item, now_iso)
        if seen:
            n_seen += 1
        elif is_excluded(item, cfg):
            n_excluded += 1
        elif not passes_require_terms(item, queries_by_id):
            n_filtered += 1
        elif is_own_column(item, cfg):
            own_items.append(item)
        else:
            new_items.append(item)
    conn.commit()
    conn.close()

    summary = (f"fetched {len(items)} unique items: {len(new_items)} new, "
               f"{len(own_items)} own-column, {n_seen} already seen, "
               f"{n_excluded} own-property, {n_filtered} failed require-terms, "
               f"{len(errors)} source errors")

    if args.backfill:
        print(f"Backfill complete — {summary}.")
        for e in errors:
            print(f"  error: {e}", file=sys.stderr)
        return

    run_date = now.strftime("%Y-%m-%d")
    digest = build_digest(new_items, own_items, errors, cfg, run_date)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    outpath = outdir / f"{run_date}.md"
    outpath.write_text(digest)

    print(digest)
    print(f"---\nDigest written to {outpath} ({summary}).", file=sys.stderr)

    if args.email and (new_items or own_items):
        n = len(new_items)
        send_email(
            f"NYCuriosity mention digest — {n} new mention"
            f"{'s' if n != 1 else ''} ({run_date})",
            digest,
        )
    elif args.email:
        print("No new mentions; skipping email.", file=sys.stderr)


if __name__ == "__main__":
    main()
