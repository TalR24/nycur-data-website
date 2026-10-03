#!/usr/bin/env python3
"""
Turns the Search Console numbers gathered by gsc_pull.py into a to-do list:
each action names the page, the number behind it, the steps, and the exact
prompt to paste into Claude Code (run from ~/nycur). Rendered twice, as a
branded HTML email and as Markdown (the archived report and the email's
plain-text part).

Rules are deterministic on purpose: no model calls, nothing billed. The
judgment (the actual rewrites) happens when Tal pastes a prompt into a session.

Action types, in priority order:
  host drop      clicks on a whole host fell 20%+ (seo skill step 1)
  page drop      a page lost half its clicks (step 1)
  revert         a change logged in changes.md made things clearly worse
  rewrite        impressions but a weak CTR for the position (step 2 / step 4)
  near page one  a real query where the page ranks but searchers do not click
  not seen       sitemap pages with zero impressions for both 28-day periods (step 3)

Checks folded in from the memo routine (Oct 2 2026): page drops list the page
file's recent commits, and long-unseen pages say whether their content is
rendered by JavaScript from JSON and how many pages link to them.

The same builder serves the State Capacity Ecosystem email (sce_monthly.py),
which adds site-health cards through `extra_actions` and renders with the SCE
palette through `theme`.
"""

import html
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit

from common import SITES, WORKSPACE, inbound_links, load_pages, parse_head

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAND_CSS = REPO_ROOT / "assets" / "brand.css"
CHANGES_REL = "nycur-data-premium/seo_reports/changes.md"

# Standing decision (Tal, Aug 24 2026): no search work on these until the post is out.
HOLD_PREFIXES = ("https://data.nycuriosity.com/nycuriosity_substack_posts/medicaid_provider_spending/",)
# Pages Tal reviewed and chose to leave as they are: no rewrite or query cards.
DECLINED = {
    "https://www.nycuriosity.com/p/west-4th-street-station": "keep current SEO title and description (Tal, Oct 2 2026)",
}
BRANDED = ("nycuriosity", "tal roded", "roded", "curiosity", "state capacity ecosystem", "statecapacity")
UNSEEN_SKIP = ("/privacy/", "/terms/")
NEW_PAGE_DAYS = 42      # sitemap lastmod newer than this: may simply be new, not a problem
JUDGE_WINDOW_DAYS = 60  # changes logged this long before the period end get judged
MAX_ACTIONS = 10
MAX_REWRITES = 4
MAX_QUERY_ACTIONS = 2
MAX_UNSEEN_GROUPS = 2

EXPECTED_CTR = {1: .25, 2: .14, 3: .10, 4: .07, 5: .055, 6: .045, 7: .035, 8: .03,
                9: .025, 10: .022, 11: .015, 12: .013, 13: .012, 14: .011, 15: .010,
                16: .009, 17: .008, 18: .007, 19: .006, 20: .005}


def expected_ctr(pos):
    return EXPECTED_CTR.get(max(1, round(pos)), .005)


def held(url):
    return url.startswith(HOLD_PREFIXES)


SCE_SUBSTACK = "substack.statecapacityecosystem.com"


def is_substack(host):
    return host in ("nycuriosity.com", "www.nycuriosity.com", "nycuriosity.substack.com", SCE_SUBSTACK)


def substack_apply(host):
    if host == SCE_SUBSTACK:
        return ("update the post's SEO title and description in the SCE Substack editor (post settings, SEO), "
                "or tell me the exact text to paste there if this session cannot reach that Substack; never the "
                "post title, subtitle or body")
    return ("update the post's SEO title and description through the Substack draft API (never the "
            "post title, subtitle or body)")


def norm(url):
    return url.split("#")[0].rstrip("/")


# ---------------------------------------------------------------- brand ---

def css_vars(text, prefix=""):
    raw = dict(re.findall(r"--(%s[\w-]+)\s*:\s*([^;]+);" % re.escape(prefix), text))
    raw = {k: re.sub(r"/\*.*?\*/", "", v).strip() for k, v in raw.items()}

    def resolve(v, depth=0):
        m = re.fullmatch(r"var\(--([\w-]+)\)", v)
        return resolve(raw.get(m.group(1), v), depth + 1) if m and depth < 5 else v
    return {k: resolve(v) for k, v in raw.items()}


def nycuriosity_theme():
    T = brand_tokens()
    return {
        "kicker": "NYCuriosity search report",
        "page": T["b-cream"], "surface": T["b-surface"], "soft": T["b-cream"],
        "ink": T["b-ink"], "ink2": T["b-ink-2"], "ink3": T["b-ink-3"], "line": T["b-line"],
        "link": T["b-tangerine-deep"], "accent": T["b-tangerine"], "dark": T["b-surface-dark"],
        "on_dark": T["b-cream"], "good": T["b-topic-transit-ink"], "bad": T["b-tangerine-deep"],
        "warm": T["b-brown"],
        "tags": {"Fix first": (T["b-tangerine-deep"], "#FFFFFF"), "Revert?": (T["b-tangerine-deep"], "#FFFFFF"),
                 "Quick win": (T["b-marigold"], T["b-ink"]), "Opportunity": (T["b-lightblue"], T["b-ink"]),
                 "Check": (T["b-line"], T["b-ink"]), "Review": (T["b-lightblue"], T["b-ink"])},
        "sans": T["b-sans"], "display": T["b-display"], "mono": T["b-mono"],
        # The drafting memo routine was retired Oct 3 2026: this email is the one
        # monthly SEO email; pasting a Quick win prompt makes Claude draft the rewrite.
        "memo_note": None,
        "footer": "Sent by the seo_monthly Action in TalR24/nycur-data-website (data_website/seo/gsc_pull.py). "
                  "How these rules work: the seo skill.",
    }


def sce_theme(sce_root):
    """The SCE site's own palette (it sits outside the NYCuriosity brand), read
    from the :root block of its homepage so the email follows the site."""
    T = css_vars((Path(sce_root) / "index.html").read_text(encoding="utf-8"))
    return {
        "kicker": "State Capacity Ecosystem monthly report",
        "page": T["bg"], "surface": T["surface"], "soft": T["blue-light"],
        "ink": T["text"], "ink2": T["text-mid"], "ink3": T["text-muted"], "line": T["border"],
        "link": T["blue-hover"], "accent": T["blue"], "dark": T["text"], "on_dark": T["bg"],
        "good": T["blue"], "bad": T["blue-hover"], "warm": T["blue"],
        "tags": {"Fix first": (T["blue-hover"], T["surface"]), "Revert?": (T["blue-hover"], T["surface"]),
                 "Quick win": (T["blue-mid"], T["text"]), "Opportunity": (T["blue-light"], T["text"]),
                 "Check": (T["border"], T["text"]), "Review": (T["blue-mid"], T["text"])},
        "sans": "Inter, -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif",
        "display": "Inter, -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif",
        "mono": "'Roboto Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
        "memo_note": None,
        "footer": "Sent by the sce_monthly Action in TalR24/nycur-data-website (data_website/seo/sce_monthly.py): "
                  "site health from statecapacityecosystem/data/site_health.py, search data from Google Search "
                  "Console, review from the SCE site health review routine.",
    }


def brand_tokens():
    """--b-* custom properties from assets/brand.css, var() references resolved.
    Email clients ignore stylesheets, so the values are inlined at render time
    from the one source of truth instead of being hardcoded here."""
    raw = dict(re.findall(r"--(b-[\w-]+)\s*:\s*([^;]+);", BRAND_CSS.read_text(encoding="utf-8")))
    raw = {k: re.sub(r"/\*.*?\*/", "", v).strip() for k, v in raw.items()}

    def resolve(v, depth=0):
        m = re.fullmatch(r"var\(--(b-[\w-]+)\)", v)
        return resolve(raw.get(m.group(1), v), depth + 1) if m and depth < 5 else v
    return {k: resolve(v) for k, v in raw.items()}


# -------------------------------------------------------------- helpers ---

def live_head(session, url):
    """Current <title> and meta description as Google sees them (production)."""
    try:
        r = session.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (NYCuriosity SEO report)"})
        r.raise_for_status()
        h = parse_head(r.text)
        return h.title or "", h.meta.get("description", "")
    except Exception:  # noqa: BLE001
        return None, None


def repo_file(url):
    """'data_website/a/b/index.html' for a site URL, None for Substack."""
    parts = urlsplit(url)
    site = next((c for c in SITES.values() if c["gsc_host"] == parts.netloc), None)
    if not site:
        return None
    path = parts.path.lstrip("/")
    if not path or path.endswith("/"):
        path += "index.html"
    return f"{site['repo']}/{path}"


def plural(n, word, plural_form=None):
    return f"{n:,} {word if n == 1 else (plural_form or word + 's')}"


def first_published(url):
    """Date of the page file's first commit, or None when the repo is not on
    disk. Sitemap lastmod cannot tell new pages from old ones: the Aug 24 2026
    head-tag backfill touched every page."""
    f = repo_file(url)
    if not f:
        return None
    repo, rel = f.split("/", 1)
    root = REPO_ROOT if repo == SITES["data"]["repo"] else WORKSPACE / repo
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "--diff-filter=A", "--follow", "--format=%cs",
                              "--", rel], capture_output=True, text=True, timeout=30).stdout.split()
        return date.fromisoformat(out[-1]) if out else None
    except Exception:  # noqa: BLE001
        return None


def site_root(key):
    return REPO_ROOT if key == "data" else WORKSPACE / SITES[key]["repo"]


def recent_commits(url, n=3):
    """['2026-09-14 Fix tracker copy', ...] for a site page's file, newest first."""
    f = repo_file(url)
    if not f:
        return []
    repo, rel = f.split("/", 1)
    key = next(k for k, c in SITES.items() if c["repo"] == repo)
    root = site_root(key)
    if not (root / ".git").exists():
        return []
    out = subprocess.run(["git", "-C", str(root), "log", f"-{n}", "--format=%cs %s", "--", rel],
                         capture_output=True, text=True, timeout=30).stdout
    return [l for l in out.splitlines() if l.strip()]


_PAGE_CACHE = {}


def page_facts(url):
    """{'js': bool, 'inbound': int} for a site page, or None when its repo is
    not on disk. 'js' means the page builds its content from a JSON fetch, so
    Google sees only the static text around it."""
    host = urlsplit(url).netloc
    key = next((k for k, c in SITES.items() if c["gsc_host"] == host), None)
    if not key or not (site_root(key) / ".git").exists():
        return None
    if key not in _PAGE_CACHE:
        try:
            pages = load_pages(key, site_root(key))
            _PAGE_CACHE[key] = ({p["url"]: p for p in pages}, inbound_links(key, pages, site_root(key)))
        except Exception:  # noqa: BLE001
            _PAGE_CACHE[key] = ({}, {})
    by_url, inbound = _PAGE_CACHE[key]
    path = urlsplit(url).path or "/"
    page = by_url.get(path)
    if not page:
        return None
    js = bool(re.search(r"fetch\([^)]*\.json", page["html"])) or "d3.json(" in page["html"]
    return {"js": js, "inbound": len(inbound.get(path, ()))}


def short_name(url, title=None):
    if title:
        return re.split(r"\s+[—|]\s+", title)[0].strip()
    parts = urlsplit(url)
    if "/p/" in parts.path:
        return parts.path.split("/p/")[1].strip("/").replace("-", " ").capitalize()
    return parts.path.strip("/") or parts.netloc


def inspect_link(prop, url):
    return ("https://search.google.com/search-console/inspect?resource_id="
            f"{quote(prop, safe='')}&id={quote(url, safe='')}")


def fmt_pct(x):
    return f"{x * 100:.1f}%"


def page_query_index(query_rows):
    """page -> [query rows sorted by impressions]."""
    out = {}
    for r in query_rows:
        page, q = r["keys"]
        out.setdefault(page, []).append({"query": q, "clicks": r["clicks"], "impressions": r["impressions"],
                                         "ctr": r["ctr"], "position": r["position"]})
    for v in out.values():
        v.sort(key=lambda q: -q["impressions"])
    return out


def queries_line(qs, n=4):
    return "; ".join(f'"{q["query"]}" ({q["impressions"]} imp, pos {q["position"]:.0f})' for q in qs[:n])


# ------------------------------------------------------- change log ---

CHANGE_LINE = re.compile(r"^- (https?://\S+) · (.*)$")
BASELINE = re.compile(r"baseline (\d[\d,]*) imp(?:ressions)?(?:, (\d+) clicks)?(?:, pos ([\d.]+))?")


def parse_changes(path):
    """[(date, url, baseline dict or None, text)] from seo_reports/changes.md."""
    if not path or not Path(path).exists():
        return []
    out, current = [], None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (\d{4}-\d{2}-\d{2})", line)
        if m:
            current = date.fromisoformat(m.group(1))
            continue
        m = CHANGE_LINE.match(line.strip())
        if m and current:
            b = BASELINE.search(m.group(2))
            base = None
            if b:
                base = {"impressions": int(b.group(1).replace(",", "")),
                        "clicks": int(b.group(2) or 0),
                        "position": float(b.group(3)) if b.group(3) else None}
            out.append((current, m.group(1), base, m.group(2)))
    return out


def judge(before, after):
    """(verdict, reason) for one logged change."""
    bi, bc, bp = before["impressions"], before["clicks"], before.get("position")
    ai, ac, ap = after["impressions"], after["clicks"], after.get("position")
    bctr = bc / bi if bi else 0
    actr = ac / ai if ai else 0
    if ai == 0:
        return "CHECK", "still zero impressions; run a URL inspection in Search Console"
    if bi < 30 and ai < 30:
        return "WAIT", "too few impressions to judge yet"
    if ac >= max(bc * 1.25, bc + 2):
        return "KEEP", f"clicks up {bc} → {ac}"
    if bc >= 4 and ac <= bc * 0.5 and bp and ap and ap > bp + 2:
        return "REVERT", f"clicks fell {bc} → {ac} and position slipped {bp:.1f} → {ap:.1f}"
    if bp and ap and ap < bp - 1 and actr < bctr:
        return "ITERATE", (f"ranks higher ({bp:.1f} → {ap:.1f}) but CTR fell "
                           f"{fmt_pct(bctr)} → {fmt_pct(actr)}; the title is not earning the click")
    if actr >= bctr:
        return "KEEP", f"CTR held or rose ({fmt_pct(bctr)} → {fmt_pct(actr)})"
    return "ITERATE", f"CTR fell {fmt_pct(bctr)} → {fmt_pct(actr)}"


def judged_changes(changes, sections, period_start, period_end):
    rows_by_url, prev_by_url = {}, {}
    for s in sections:
        for r in s["rows"]:
            rows_by_url[norm(r["keys"][0])] = r
        for r in s["prev_rows"]:
            prev_by_url[norm(r["keys"][0])] = r
    hosts = {s["host"] for s in sections}
    out = []
    for when, url, base, text in changes:
        if urlsplit(url).netloc not in hosts:
            continue  # another report's page (changes.md is shared by both reports)
        if when >= period_start or when < period_end - timedelta(days=JUDGE_WINDOW_DAYS):
            continue  # too early to judge, or already judged in earlier reports
        cur = rows_by_url.get(norm(url), {"clicks": 0, "impressions": 0, "position": None})
        before = base or prev_by_url.get(norm(url), {"clicks": 0, "impressions": 0, "position": None})
        verdict, reason = judge(before, cur)
        out.append({"date": when, "url": url, "before": before, "after": cur,
                    "verdict": verdict, "reason": reason})
    return out


# -------------------------------------------------------------- actions ---

def build(sections, period, session, changes_path=None, extra_actions=None):
    """Return {'actions', 'judged', 'wins', 'held', ...} for the renderers.
    `extra_actions` (site-health cards) go first and do not count against the
    search actions' cap."""
    start, end = period
    days = (end - start).days + 1
    span = f"{start:%b %-d} to {end:%b %-d}"
    actions = []

    # host drops
    for s in sections:
        t, p = s["totals"], s["prev_totals"]
        if p["clicks"] >= 10 and t["clicks"] <= p["clicks"] * 0.8:
            change = (t["clicks"] - p["clicks"]) / p["clicks"] * 100
            actions.append({
                "tag": "Fix first", "who": "Claude Code",
                "title": f"{s['label']} lost {abs(change):.0f}% of its search clicks ({p['clicks']} → {t['clicks']})",
                "why": "A drop this size usually traces to one or two pages; find them before rewriting anything.",
                "steps": ["Paste the prompt into Claude Code.",
                          "Read its KEEP / ITERATE / REVERT call for each page and approve the fixes."],
                "prompt": (f"Use the seo skill, monthly review step 1. Search clicks on {s['host']} fell "
                           f"{abs(change):.0f}% ({p['clicks']} → {t['clicks']}) in the {days} days ending {end}. "
                           f"Pull the latest report from nycur-data-premium/seo_reports/, find the pages and queries "
                           f"behind the drop, check each page's git history and live head tags, and recommend KEEP, "
                           f"ITERATE or REVERT per page. Change nothing until I approve."),
            })

    # page drops
    for s in sections:
        for d in s["drops"]:
            if held(d["page"]):
                continue
            pos = (f"position {d['prev_position']:.1f} → {d['position']:.1f}" if d["position"]
                   else "no longer appearing in results")
            f = repo_file(d["page"])
            commits = recent_commits(d["page"])
            actions.append({
                "tag": "Fix first", "who": "Claude Code",
                "title": f"{short_name(d['page'])} lost half its clicks ({d['prev_clicks']} → {d['clicks']})",
                "why": f"{pos}. {d['page']}"
                       + (f" Last edits to the file: {'; '.join(commits)}." if commits else ""),
                "steps": ["Paste the prompt into Claude Code.",
                          "If it finds a recent edit caused the drop, approve the revert."],
                "prompt": (f"Use the seo skill, monthly review step 1. {d['page']} fell from {d['prev_clicks']} to "
                           f"{d['clicks']} search clicks ({pos}) in the {days} days ending {end}. "
                           + (f"Check `git log` on {f} for edits around the drop, " if f else "")
                           + "compare its queries this period and last, and recommend KEEP, ITERATE or REVERT "
                             "with the evidence. Change nothing until I approve."),
            })

    # judged changes
    judged = judged_changes(parse_changes(changes_path), sections, start, end)
    for j in judged:
        if j["verdict"] == "REVERT":
            actions.append({
                "tag": "Revert?", "who": "Claude Code",
                "title": f"The {j['date']:%b %-d} change to {short_name(j['url'])} made it worse",
                "why": j["reason"] + ".",
                "steps": ["Paste the prompt into Claude Code.", "Approve the revert if the evidence holds."],
                "prompt": (f"Use the seo skill. The change logged on {j['date']} in {CHANGES_REL} for {j['url']} "
                           f"looks like it hurt: {j['reason']}. Confirm against Search Console, then restore the "
                           f"previous title and description (from changes.md) after I approve, and log the revert."),
            })

    # rewrite candidates, across hosts, by missed clicks
    rewrites = []
    for s in sections:
        pq = s["page_queries"]
        for r in s["rewrite"]:
            if not held(r["keys"][0]) and norm(r["keys"][0]) not in DECLINED:
                rewrites.append((r, s, pq.get(r["keys"][0], [])))
    rewrites.sort(key=lambda x: -x[0]["missed_clicks"])
    prior = {norm(j["url"]): j for j in judged}
    rewrite_urls = set()
    for r, s, qs in rewrites[:MAX_REWRITES]:
        url = r["keys"][0]
        rewrite_urls.add(url)
        title, desc = live_head(session, url)
        sub = is_substack(s["host"])
        f = repo_file(url)
        again = prior.get(norm(url))
        q_imps = sum(q["impressions"] for q in qs)
        hidden = q_imps < 20  # Google withholds rare queries; too few left to write from
        why = (f"{r['impressions']:,} impressions at average position {r['position']:.1f}, where about "
               f"{fmt_pct(r['expected_ctr'])} of searchers usually click; this page got {fmt_pct(r['ctr'])}. "
               f"That gap is about {r['missed_clicks']} clicks a month.")
        if again:
            why += (f" Its title was already rewritten on {again['date']:%b %-d} ({again['reason']}), "
                    f"so this is a second attempt.")
        apply = (substack_apply(s["host"]) if sub else
                 f"edit {f}, keeping og:title and og:description in step, run seo_check.py on it, commit and push")
        prompt = (f"Use the seo skill, monthly review step {4 if sub else 2}. Rewrite the search title and "
                  f"description for {url}. Last {days} days: {r['impressions']:,} impressions, {fmt_pct(r['ctr'])} "
                  f"CTR at position {r['position']:.1f} (expected about {fmt_pct(r['expected_ctr'])}). "
                  + (f"Top queries: {queries_line(qs)}. " if qs and not hidden else "")
                  + (f"Google withholds the queries for this page ("
                     + (f"none of its {r['impressions']:,} impressions come" if not q_imps else
                        f"only {q_imps} of {r['impressions']:,} impressions come")
                     + " with a query), so work from the page's subject and what someone "
                     f"searching for it would type. " if hidden else "")
                  + (f"The {again['date']} rewrite in {CHANGES_REL} did not fix it ({again['reason']}), so start "
                     f"from why searchers skip it. " if again else "")
                  + f"Read the page, propose a new title and description that answer {'those searches' if hidden else 'those queries'}, show me "
                    f"old → new, and after I approve, {apply}. Log the change in {CHANGES_REL}.")
        actions.append({
            "tag": "Quick win", "who": "Claude Code",
            "title": f"{short_name(url, title)}: {r['impressions']:,} searchers saw it, {r['clicks']} clicked",
            "why": why, "url": url,
            "current": (title, desc),
            "queries": [] if hidden else qs[:4],
            "steps": ["Paste the prompt into Claude Code.",
                      "Pick or edit the proposed title and description.",
                      "Claude applies it and logs it; next month's report judges it."],
            "prompt": prompt,
        })

    # near page one: real queries with impressions but few clicks
    near = []
    for s in sections:
        for page, qs in s["page_queries"].items():
            if held(page) or page in rewrite_urls or norm(page) in DECLINED:
                continue
            for q in qs:
                if (q["impressions"] >= 20 and 4.5 <= q["position"] <= 20
                        and q["ctr"] < expected_ctr(q["position"])
                        and not any(b in q["query"].lower() for b in BRANDED)):
                    near.append((q, page, s))
    near.sort(key=lambda x: -x[0]["impressions"])
    seen_pages = set()
    for q, page, s in near:
        if len(seen_pages) >= MAX_QUERY_ACTIONS:
            break
        if page in seen_pages:
            continue
        seen_pages.add(page)
        sub = is_substack(s["host"])
        pg = "page one" if q["position"] < 10.5 else "page two"
        actions.append({
            "tag": "Opportunity", "who": "Claude Code",
            "title": f'People searching "{q["query"]}" find you on {pg} and mostly scroll past',
            "why": (f'{plural(q["impressions"], "impression")}, {plural(q["clicks"], "click")}, average position '
                    f'{q["position"]:.1f}, landing on {page}.'),
            "steps": ["Paste the prompt into Claude Code.",
                      "Approve the edits you agree with." + (" Body text stays yours to write." if sub else "")],
            "prompt": (f'Use the seo skill. The query "{q["query"]}" brought {q["impressions"]} Google impressions '
                       f'and {plural(q["clicks"], "click")} to {page} in the {days} days ending {end}, at average position '
                       f'{q["position"]:.1f}. Read the page and tell me whether its title, description, h1 and '
                       f"opening text answer that query. "
                       + ("It is a Substack post: propose SEO title and description changes only, plus a note on "
                          "anything the body would need, which I will write myself. " if sub else
                          "Propose specific edits (title, description, a heading or a sentence of page text). ")
                       + f"Show me before changing anything, and log any applied change in {CHANGES_REL}."),
        })

    # not seen: zero impressions in both periods, grouped by folder
    groups, recent = {}, 0
    for s in sections:
        for u, lastmod in s.get("unseen") or []:
            if held(u) or any(x in u for x in UNSEEN_SKIP):
                continue
            prev_seen = {norm(r["keys"][0]) for r in s["prev_rows"]}
            if norm(u) in prev_seen:
                continue
            born = first_published(u) or lastmod
            if born and born > end - timedelta(days=NEW_PAGE_DAYS):
                recent += 1
                continue
            path = urlsplit(u).path.strip("/").split("/")
            key = "/".join(path[:2]) if path and path[0] in (
                "nycuriosity_substack_posts", "civic_reference", "cb-tools", "wiki", "services", "community",
                "events") else (path[0] if path and path[0] else "")
            groups.setdefault((s["host"], s["prop"], key), []).append(u)
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    for (host, prop, key), urls in ranked[:MAX_UNSEEN_GROUPS]:
        folder = f"https://{host}/{key}/" if key else f"https://{host}/"
        hub = next((u for u in urls if norm(u) == norm(folder)), urls[0])
        facts = {u: page_facts(u) for u in urls}
        known = [f for f in facts.values() if f]
        js_n = sum(1 for f in known if f["js"])
        orphan_n = sum(1 for f in known if f["inbound"] == 0)
        diag = ""
        if known and not js_n and not orphan_n:
            diag = (f" All {plural(len(known), 'page')} serve their content as HTML and have links from other "
                    f"pages, so the likely cause is indexing: start with URL Inspection.")
        elif known:
            diag = (f" Of the {plural(len(known), 'page')} checked in the repo, {js_n} build their content from a "
                    f"JSON fetch (Google sees only the intro text) and {orphan_n} have no links from other pages.")
        actions.append({
            "tag": "Check", "who": "Claude Code, then you in Search Console",
            "title": f"{plural(len(urls), 'page')} under /{key}/ drew zero Google impressions for {days * 2} days",
            "why": "Older than six weeks and still invisible: Google either has not indexed them or cannot read "
                   "their content (pages that render charts or tables from JSON show Google only the intro text)."
                   + diag,
            "urls": urls, "url_facts": facts,
            "steps": ["Paste the prompt into Claude Code; it checks what production serves and how the content renders.",
                      "Open the URL Inspection link, then click Request indexing if it says the page is not on Google.",
                      "Approve any fix it proposes (static text, internal links)."],
            "links": [("URL Inspection for " + short_name(hub), inspect_link(prop, hub))],
            "prompt": (f"Use the seo skill, monthly review step 3. {'This page has' if len(urls) == 1 else f'These {len(urls)} pages have'} had zero Google "
                       f"impressions for the {days * 2} days ending {end}: " + ", ".join(urls[:12])
                       + (f" and {len(urls) - 12} more" if len(urls) > 12 else "") + ". Run "
                       f"`python3 seo/seo_check.py --all --live` from data_website/ and report their results, check "
                       f"whether each page's main content is rendered by JavaScript from JSON, and count inbound "
                       f"links to each. Propose fixes (pre-rendered static text like cb-tools/member-tracker/, links "
                       f"from the hub or the post) for my approval, and tell me which ones I should inspect in "
                       f"Search Console."),
        })
    other_unseen = sum(len(v) for _, v in ranked[MAX_UNSEEN_GROUPS:])

    # wins and held pages
    wins, held_tot = [], {"clicks": 0, "impressions": 0}
    for s in sections:
        prev = {norm(r["keys"][0]): r for r in s["prev_rows"]}
        for r in s["rows"]:
            if held(r["keys"][0]):
                held_tot["clicks"] += r["clicks"]
                held_tot["impressions"] += r["impressions"]
                continue
            gain = r["clicks"] - prev.get(norm(r["keys"][0]), {"clicks": 0})["clicks"]
            if gain >= 3:
                wins.append((gain, r))
    wins.sort(key=lambda x: -x[0])

    return {"actions": list(extra_actions or []) + actions[:MAX_ACTIONS],
            "dropped": max(0, len(actions) - MAX_ACTIONS),
            "judged": judged, "wins": wins[:4], "held": held_tot, "recent_unseen": recent,
            "other_unseen": other_unseen, "period": period}


# ------------------------------------------------------------ markdown ---

def render_markdown(plan, sections, blocks_md=None):
    a = plan["actions"]
    out = ["## This month's actions", ""]
    if not a:
        out += ["Nothing needs doing this month: no drops, no rewrite candidates, no long-unseen pages.", ""]
    for i, x in enumerate(a, 1):
        out.append(f"### {i}. [{x['tag']}] {x['title']}")
        out.append(x["why"])
        if x.get("current"):
            t, d = x["current"]
            out.append(f"Current title: {t or '(could not read)'}")
            out.append(f"Current description: {d or '(none)'}")
        if x.get("queries"):
            out.append("Top queries: " + queries_line(x["queries"]))
        if x.get("urls"):
            for u in x["urls"][:15]:
                f = (x.get("url_facts") or {}).get(u)
                out.append("  " + u + (f" ({'JS-rendered, ' if f['js'] else ''}{plural(f['inbound'], 'inbound link')})"
                                       if f else ""))
        if x.get("findings"):
            out.extend("  - " + f_ for f_ in x["findings"][:15])
        out.append("Steps:")
        out.extend(f"  {n}. {st}" for n, st in enumerate(x["steps"], 1))
        for label, link in x.get("links", []):
            out.append(f"  {label}: {link}")
        if x.get("prompt"):
            out.append("Prompt for Claude Code (paste from ~/nycur):")
            out.append("```")
            out.append(x["prompt"])
            out.append("```")
        out.append("")
    if plan["dropped"]:
        out += [f"{plan['dropped']} lower-priority actions were cut to keep this list short; they will "
                f"resurface next month if still true.", ""]
    for heading, body in blocks_md or []:
        out += [f"## {heading}", "", body, ""]
    if plan["judged"]:
        out += ["## Earlier changes, judged", ""]
        for j in plan["judged"]:
            out.append(f"- {j['verdict']}: {j['url']} (changed {j['date']}): {j['reason']}")
        out.append("")
    if plan["wins"]:
        out += ["## Gaining clicks", ""]
        out += [f"- +{g} clicks ({r['clicks']} this period): {r['keys'][0]}" for g, r in plan["wins"]]
        out.append("")
    notes = []
    if plan["held"]["impressions"]:
        notes.append(f"Held by standing decision (medicaid_provider_spending): {plan['held']['impressions']:,} "
                     f"impressions, {plan['held']['clicks']} clicks. No action until the post is ready.")
    if plan["recent_unseen"]:
        notes.append(f"{plural(plan['recent_unseen'], 'unseen sitemap page')} first published in the last six "
                     f"weeks; they get time before counting as a problem.")
    if plan["other_unseen"]:
        notes.append(f"{plan['other_unseen']} more long-unseen pages in smaller folders are listed in the "
                     f"reference numbers below.")
    if notes:
        out += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- html ---

def render_html(plan, sections, report_md_name, theme=None, blocks=None, headline=None):
    """`blocks` = [(heading, html)] inserted after the to-do list (SCE site
    health summary, review findings). `headline` overrides the H1."""
    th = theme or nycuriosity_theme()
    e = html.escape
    start, end = plan["period"]
    verdict_colors = {"KEEP": th["good"], "ITERATE": th["warm"], "REVERT": th["bad"],
                      "CHECK": th["ink3"], "WAIT": th["ink3"]}
    sans, display, mono = th["sans"], th["display"], th["mono"]
    ink, ink2, ink3, line, link = th["ink"], th["ink2"], th["ink3"], th["line"], th["link"]

    def a(href, text):
        return f'<a href="{e(href)}" style="color:{link};text-decoration:underline;">{e(text)}</a>'

    def h2(text):
        return (f'<h2 style="font-family:{display};font-size:21px;line-height:1.2;color:{ink};'
                f'margin:32px 0 12px;font-weight:700;">{e(text)}</h2>')

    n = len(plan["actions"])
    out = [f'<!doctype html><html><body style="margin:0;padding:0;background:{th["page"]};">'
           f'<div style="max-width:660px;margin:0 auto;padding:24px 16px;font-family:{sans};'
           f'color:{ink2};font-size:15px;line-height:1.55;">']
    out.append(f'<div style="border-top:6px solid {th["accent"]};padding-top:14px;">'
               f'<div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{ink3};">'
               f'{e(th["kicker"])}</div>'
               f'<h1 style="font-family:{display};font-size:28px;line-height:1.15;color:{ink};margin:6px 0 4px;">'
               f'{e(headline or (plural(n, "thing") + " to do this month"))}</h1>'
               f'<div style="color:{ink3};font-size:13px;">Google Search Console, {start:%b %-d} to {end:%b %-d, %Y}, '
               f'compared with the 28 days before.</div></div>')

    # scoreboard
    out.append(f'<table role="presentation" style="width:100%;border-collapse:collapse;margin:20px 0 4px;'
               f'background:{th["surface"]};border:1px solid {line};font-size:14px;">'
               f'<tr style="color:{ink3};font-size:12px;text-align:left;">'
               f'<th style="padding:10px 12px;font-weight:600;">Site</th>'
               f'<th style="padding:10px 8px;font-weight:600;text-align:right;">Clicks</th>'
               f'<th style="padding:10px 8px;font-weight:600;text-align:right;">Impressions</th>'
               f'<th style="padding:10px 12px;font-weight:600;text-align:right;">Avg position</th></tr>')

    def delta(c, pv):
        if not pv:
            return f'<span style="color:{ink3};font-size:12px;"> new</span>' if c else ""
        d = (c - pv) / pv * 100
        col = th["good"] if d >= 0 else th["bad"]
        return f'<span style="color:{col};font-size:12px;"> {d:+.0f}%</span>'
    for s in sections:
        t, p = s["totals"], s["prev_totals"]
        if not t["impressions"] and not p["impressions"]:
            continue
        pos_note = (f'<span style="color:{ink3};font-size:12px;"> was {p["position"]:.1f}</span>'
                    if p["impressions"] else "")
        out.append(f'<tr style="border-top:1px solid {line};">'
                   f'<td style="padding:8px 12px;color:{ink};">{e(s["label"])}</td>'
                   f'<td style="padding:8px;text-align:right;color:{ink};font-weight:600;">{t["clicks"]:,}'
                   f'{delta(t["clicks"], p["clicks"])}</td>'
                   f'<td style="padding:8px;text-align:right;">{t["impressions"]:,}'
                   f'{delta(t["impressions"], p["impressions"])}</td>'
                   f'<td style="padding:8px 12px;text-align:right;">{t["position"]:.1f}{pos_note}</td></tr>')
    out.append('</table>')
    out.append(f'<div style="color:{ink3};font-size:12px;">Lower position is better; 1 to 10 is page one.</div>')

    # actions
    out.append(h2("Your to-do list"))
    if not plan["actions"]:
        out.append("<p>Nothing needs doing this month.</p>")
    else:
        out.append(f'<p style="margin:0 0 14px;color:{ink3};font-size:13px;">Work top to bottom. Each prompt '
                   f'is self-contained: open Claude Code in <code>~/nycur</code>, paste it, and approve what it '
                   f'proposes. Nothing changes until you say so.</p>')
    for i, x in enumerate(plan["actions"], 1):
        bg, fg = th["tags"].get(x["tag"], (line, ink))
        out.append(f'<div style="background:{th["surface"]};border:1px solid {line};border-radius:10px;'
                   f'padding:16px 18px;margin:0 0 14px;">')
        out.append(f'<div style="font-size:12px;margin-bottom:6px;"><span style="background:{bg};color:{fg};'
                   f'padding:2px 8px;border-radius:6px;font-weight:600;">{e(x["tag"])}</span>'
                   f'<span style="color:{ink3};"> &nbsp;{i} of {n} · {e(x["who"])}</span></div>')
        out.append(f'<div style="font-size:17px;font-weight:700;color:{ink};line-height:1.3;margin:0 0 6px;">'
                   f'{e(x["title"])}</div>')
        out.append(f'<div style="margin:0 0 10px;">{e(x["why"])}</div>')
        if x.get("url"):
            out.append(f'<div style="font-size:13px;margin:-4px 0 10px;">{a(x["url"], x["url"])}</div>')
        if x.get("current"):
            t, d = x["current"]
            out.append(f'<div style="background:{th["soft"]};border-radius:6px;padding:10px 12px;'
                       f'font-size:13px;margin:0 0 10px;">'
                       f'<div><span style="color:{ink3};">Google shows now:</span> '
                       f'<b style="color:{ink};">{e(t or "(could not read the live page)")}</b></div>'
                       f'<div style="margin-top:3px;">{e(d or "(no meta description)")}</div></div>')
        if x.get("queries"):
            qs = "".join(f'<li>"{e(q["query"])}": {plural(q["impressions"], "impression")}, '
                         f'{plural(q["clicks"], "click")}, position {q["position"]:.0f}</li>' for q in x["queries"])
            out.append(f'<div style="font-size:13px;margin:0 0 10px;"><span style="color:{ink3};">'
                       f'What people typed:</span><ul style="margin:4px 0 0;padding-left:20px;">{qs}</ul></div>')
        if x.get("urls"):
            facts = x.get("url_facts") or {}

            def fact(u):
                f = facts.get(u)
                if not f:
                    return ""
                bits = (["JS-rendered"] if f["js"] else []) + [plural(f["inbound"], "inbound link")]
                return f' <span style="color:{ink3};">({", ".join(bits)})</span>'
            us = "".join(f"<li>{a(u, urlsplit(u).path or u)}{fact(u)}</li>" for u in x["urls"][:12])
            more = (f'<li style="color:{ink3};">and {len(x["urls"]) - 12} more</li>'
                    if len(x["urls"]) > 12 else "")
            out.append(f'<ul style="font-size:13px;margin:0 0 10px;padding-left:20px;">{us}{more}</ul>')
        if x.get("findings"):
            fs = "".join(f"<li style='margin-bottom:2px;'>{e(f_)}</li>" for f_ in x["findings"][:10])
            more = (f'<li style="color:{ink3};">and {len(x["findings"]) - 10} more</li>'
                    if len(x["findings"]) > 10 else "")
            out.append(f'<ul style="font-size:13px;margin:0 0 10px;padding-left:20px;'
                       f'word-break:break-word;">{fs}{more}</ul>')
        steps = "".join(f"<li style='margin-bottom:2px;'>{e(st)}</li>" for st in x["steps"])
        out.append(f'<div style="font-size:14px;"><b style="color:{ink};">Steps</b>'
                   f'<ol style="margin:4px 0 10px;padding-left:22px;">{steps}</ol></div>')
        for label, href in x.get("links", []):
            out.append(f'<div style="font-size:13px;margin:0 0 10px;">{a(href, label)}</div>')
        if x.get("prompt"):
            out.append(f'<div style="font-size:12px;color:{ink3};margin-bottom:4px;">Prompt for Claude Code</div>'
                       f'<pre style="white-space:pre-wrap;word-wrap:break-word;margin:0;background:{th["dark"]};'
                       f'color:{th["on_dark"]};border-radius:6px;padding:12px 14px;font-family:{mono};'
                       f'font-size:12.5px;line-height:1.5;">{e(x["prompt"])}</pre>')
        out.append('</div>')
    if plan["dropped"]:
        out.append(f'<p style="font-size:13px;color:{ink3};">{plan["dropped"]} lower-priority search actions were '
                   f'cut to keep the list short; they come back next month if still true.</p>')

    for heading, body in blocks or []:
        out.append(h2(heading))
        out.append(body)

    if plan["judged"]:
        out.append(h2("Did the last changes work?"))
        out.append(f'<table role="presentation" style="width:100%;border-collapse:collapse;font-size:13px;'
                   f'background:{th["surface"]};border:1px solid {line};">')
        for j in plan["judged"]:
            out.append(f'<tr style="border-top:1px solid {line};vertical-align:top;">'
                       f'<td style="padding:8px 10px;font-weight:700;color:{verdict_colors.get(j["verdict"], ink)};'
                       f'white-space:nowrap;">{j["verdict"]}</td>'
                       f'<td style="padding:8px 10px;">{a(j["url"], short_name(j["url"]))}'
                       f'<div style="color:{ink3};">changed {j["date"]:%b %-d}: {e(j["reason"])}</div></td></tr>')
        out.append('</table>')

    if plan["wins"]:
        out.append(h2("Gaining clicks"))
        items = "".join(f'<li>{a(r["keys"][0], short_name(r["keys"][0]))}: +{g} clicks '
                        f'({r["clicks"]} this period)</li>' for g, r in plan["wins"])
        out.append(f'<ul style="padding-left:20px;margin:0;">{items}</ul>')

    notes = []
    if plan["held"]["impressions"]:
        notes.append(f'Medicaid provider spending pages: {plan["held"]["impressions"]:,} impressions, '
                     f'{plan["held"]["clicks"]} clicks. Held by your standing decision until the post is ready.')
    if plan["recent_unseen"]:
        notes.append(f'{plural(plan["recent_unseen"], "unseen page")} first published in the last six weeks, '
                     f'so they get more time.')
    if plan["other_unseen"]:
        notes.append(f'{plan["other_unseen"]} more long-unseen pages in smaller folders are in the reference below.')
    if th.get("memo_note"):
        notes.append(th["memo_note"])
    if notes:
        out.append(h2("Notes"))
        out.append('<ul style="padding-left:20px;margin:0;font-size:14px;">'
                   + "".join(f"<li>{e(x)}</li>" for x in notes) + "</ul>")

    out.append(h2("Reference numbers"))
    out.append(f'<p style="font-size:13px;color:{ink3};margin:0 0 8px;">Top pages and queries per site. The full '
               f'report with every list is filed as nycur-data-premium/seo_reports/{e(report_md_name)}.</p>')
    for s in sections:
        if not s["top_pages"]:
            continue
        out.append(f'<div style="font-weight:700;color:{ink};margin:18px 0 6px;">{e(s["label"])}</div>')
        for heading, rows, is_page in (("Top pages", s["top_pages"][:8], True),
                                       ("Top queries", s["top_queries"][:8], False)):
            rows = [r for r in rows if r["impressions"]]
            if not rows:
                continue
            out.append(f'<table role="presentation" style="width:100%;border-collapse:collapse;font-size:12.5px;'
                       f'margin-bottom:8px;"><tr style="color:{ink3};text-align:left;">'
                       f'<th style="padding:3px 4px;font-weight:600;">{heading}</th>'
                       f'<th style="padding:3px 4px;text-align:right;font-weight:600;">Clicks</th>'
                       f'<th style="padding:3px 4px;text-align:right;font-weight:600;">Impr.</th>'
                       f'<th style="padding:3px 4px;text-align:right;font-weight:600;">Pos.</th></tr>')
            for r in rows:
                k = r["keys"][0]
                label = a(k, urlsplit(k).path or "/") if is_page else e(k)
                out.append(f'<tr style="border-top:1px solid {line};"><td style="padding:3px 4px;'
                           f'word-break:break-all;">{label}</td>'
                           f'<td style="padding:3px 4px;text-align:right;">{r["clicks"]}</td>'
                           f'<td style="padding:3px 4px;text-align:right;">{r["impressions"]:,}</td>'
                           f'<td style="padding:3px 4px;text-align:right;">{r["position"]:.1f}</td></tr>')
            out.append('</table>')
    out.append(f'<div style="margin-top:28px;padding-top:12px;border-top:1px solid {line};font-size:12px;'
               f'color:{ink3};">{e(th["footer"])}</div>')
    out.append('</div></body></html>')
    return "".join(out)
