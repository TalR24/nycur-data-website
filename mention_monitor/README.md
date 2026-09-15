# Mention Monitor

Monitor for outside citations of Tal Roded, NYCuriosity, and the trackers
(fiscal impacts, legislation implementation / obligations) in news articles
and newsletters, not his own publishing.

It polls Google News RSS for the name/brand/tracker queries, and scans a
fixed list of outlet RSS feeds (full text) for the harder-to-search figure
queries (`2,231`, `8,300`, `$7.5 billion`, `5,000`) and for any link back
to nycuriosity.com. Weekly (on `--digest` and `--backfill` runs) it also
runs a WordPress REST search (`wp_search`) across outlets with no full-text
feed, an OpenAlex lookup (`openalex`) for citations of Tal's academic work,
and, daily, a Ghost sitemap scan (`sitemap_scan`) and any configured Google
Alerts RSS feeds (`alert_feeds`). It dedupes against `seen.db` (SQLite),
queues newly-flagged items as pending, and on Mondays (or `--digest`)
builds `digests/YYYY-MM-DD.md` from everything pending, prints it, marks
those items digested, emails it (as a multipart text/HTML message) if
`--email`, and self-updates: a "Suggested removals" section flags
long-silent sources, and a discovery pass probes new candidate domains
seen via Google News / alerts / OpenAlex and appends any that pass a feed,
`wp_search`, or sitemap probe to `discovered_sources.json`. Real citations
of Tal's academic work get their own "Research citations" section; new
works of his own get "New research listings"; his own bylines that ran in
an outside outlet get "My own pieces". A "Suggested website updates"
section gives a ready-to-run Claude Code prompt for adding each new
outside citation to the personal site / tracker pages.

## How it runs

`.github/workflows/mention_monitor.yml` runs daily at 11:30 UTC. Every day
it collects and queues pending items; on Mondays it also builds and emails
the digest via the existing `GMAIL_USER` / `GMAIL_APP_PASSWORD` secrets, then
commits `seen.db` + the digest back to the repo. Optional secret
`MENTION_DIGEST_TO` overrides the recipient (defaults to `GMAIL_USER`).

**First run:** trigger the workflow manually with `backfill: true` (or run
`python3 monitor.py --backfill` locally and commit `seen.db`). That seeds the
dedup db from roughly the last 90 days so the first real digest isn't a
flood of old links; backfill never queues a pending item.

Local / cron alternative:

```
pip install -r mention_monitor/requirements.txt
python3 mention_monitor/monitor.py --backfill        # once
# crontab: daily, Monday sends the digest
0 7 * * *  cd /path/to/nycur-data-website && python3 mention_monitor/monitor.py $([ "$(date +%u)" = "1" ] && echo "--digest --email")
```

Flags: `--backfill` (seed db, no pending items, no digest, no email),
`--digest` (collect, then build+write the digest from all pending items and
mark them digested), `--email` (send the digest when `--digest` produces
one; silently skips if Gmail env vars are missing), `--referrers-only` (run
only the Cloudflare referrer source and print its rows or error; no other
source, no db writes), `--config`, `--db`, `--outdir`. With no flags, a run
only collects and queues pending items. The workflow's `send_email` dispatch
input implies `--digest` even if `digest` wasn't also checked.

## Config schema (`config.json`)

Edit the config, not the code.

- `outlets`: feeds scanned in full text on every run: `name`, `feed` (RSS
  URL), `tier` (`news` or `newsletter`, drives digest ordering), and
  `fetch_article` (fetch the article page when the feed entry has no usable
  full text, capped by `max_article_fetches`).
- `own_link_domains`: a link to any of these hosts (or a subdomain) in an
  outlet's article HTML flags it as an outside citation on its own, no
  query match needed (this is how the digest catches an article that links
  to nycuriosity.com/nycuriosity.substack.com without quoting a figure).
- `queries`: run separately, never combined. Each has:
  - `id`: short label shown in the digest
  - `q`: the search string sent to google_news (quote exact phrases)
  - `match_terms`: phrases that must appear in the outlet full text (or the
    google_news title/text) for a match
  - `require_terms` (optional): at least one must also appear, so a figure
    like `2,231` doesn't fire on every unrelated use of the number
  - `exclude_terms` (optional): none of these may appear (keeps the
    `2,231` query off UN Resolution 2231 / Iran coverage)
  - `sources`: per-query source list. Name/brand/tracker-name queries use
    `google_news` and `outlets`; figure queries use only `outlets`, since
    Google News RSS strips punctuation and returns unrelated noise for
    numbers.
- `exclude_domains`: own properties, matched including subdomains
  (`nycuriosity.com` covers `data.nycuriosity.com`)
- `exclude_url_prefixes`: path-level own properties
  (`substack.com/@nycuriosity`, the LinkedIn/Instagram/Facebook profiles)
- `own_columns`: Citizens Union Searchlight (matched by domain or the
  keyword "searchlight" in outlet/title).
- `own_author_names` / `own_byline_urls` / `own_byline_titles`: Tal's own
  writing that runs in an outside outlet (a Streetsblog op-ed, a Vital City
  guest post). Matched by feed/article author metadata, an explicit seeded
  URL, or a normalized title match (needed for Google News items, which
  carry no author and only an opaque `news.google.com` redirect URL).
  Merged with `own_columns` into one "My own pieces" digest section instead
  of being dropped as if it were noise, or mistaken for an outside citation.
- `research_domains`: third-party citations of Tal's academic work (NBER,
  Cato, Fed research banks, etc.) go to a separate "Research citations"
  section rather than being dropped as a name collision or mixed into news
  outside-citations. A Google News item matched only by name with the name
  string absent from the visible title/snippet is kept and labeled
  "(name match from Google News, not verified in text)".
- `newsletter_domains`, `tier_overrides`: control the digest's
  news / newsletter / social ordering. Override a domain's tier with e.g.
  `"tier_overrides": {"somesite.org": "news"}`. Each outlet's own `tier`
  is applied automatically at load time.
- `referrer_ignore_hosts`: hosts excluded from the Cloudflare referrer
  report (search engines, social share links, substack.com itself). An
  entry ending in `.` (e.g. `google.`) matches that label anywhere in the
  host (`www.google.com`, `google.co.uk`); other entries match as a full
  host or parent domain.
- `user_agent`, `request_delay_seconds`, `max_article_fetches`: politeness
  settings.

## New sources (round 3)

- **`wp_search`**: WordPress REST search (`/wp-json/wp/v2/search?search=nycuriosity`)
  against `wp_search_sites`, weekly only (digest/backfill runs), paging
  with `page=` until an empty page or HTTP 400. A hit is fetched and run
  through the same link/term flagging as `outlets`; a hit that doesn't
  flag is still recorded `scanned` so it's never re-fetched.
- **`sitemap_scan`**: Ghost `sitemap-posts.xml` outlets (`sitemap_scan`
  config: `sitemap`, `name`, `tier`). Runs every collect. The window is a
  90-day lookback on an outlet's first run (or a backfill), or since the
  outlet's last fully-successful scan minus a 2-day overlap otherwise; the
  stored watermark is a "this run finished scanning every in-window entry"
  timestamp, not a `lastmod` cutoff, so a run that hits the cap or budget
  never advances it and every entry it didn't reach is still a candidate
  next run (nothing is skipped just because it's older than the newest
  entry). The per-URL `scanned` table, not the window, is what stops an
  already-fetched entry from being refetched. Hitting the cap/budget
  records a source error naming how many entries remain. A paywalled page
  with no usable article-body text (Hell Gate) is recorded scanned with a
  note, not an error.
- **`openalex`**: weekly (digest/backfill), no key. Fetches
  `openalex_author_ids`' own works, then works citing any of them
  (`filter=cites:...`). New citing works go to "Research citations"; new
  works of Tal's own go to "New research listings".
- **`alert_feeds`**: Google Alerts Atom feeds. Config `alert_feeds` stays
  empty (see setup below); real feed URLs come from env
  `GOOGLE_ALERT_FEEDS` only. Each entry's `google.com/url?...&url=` link
  is unwrapped and `<b>` highlight tags stripped; no term match is
  required (Google already matched). Never logs a full feed URL, only its
  own `<title>`.
- **Self-updating (items 6-7)**: `source_yield` records one row per run
  per unit (outlet, wp_search site, sitemap outlet, google_news query).
  Multiple rows in the same ISO week count as one week, not one row: a unit
  with zero flagged items across `prune_after_weeks` (default 8) consecutive
  weeks that each had a successful run, or a week streak of `prune_error_weeks`
  (default 3) where every run in the week errored, gets a "Suggested
  removals" line naming the exact spot to edit (`config.json → outlets[name="..."]`,
  a `queries[id="..."].sources` entry, or a `discovered_sources.json` domain);
  suggestions only, config.json is never edited by code. A discovery pass
  extracts candidate domains from google_news/alert_feeds/openalex items and
  Cloudflare referrer hosts, skips anything already covered (by a full-host
  parent/child match) or listed in `research_domains` /
  `discovery_ignore_domains`, probes each remaining candidate (feed, then
  `wp_search`, then sitemap, rejecting a sitemap index unless it can follow
  one level to a posts `<urlset>`) at most once per 30 days, and appends a
  passing probe (with the URL that triggered discovery as `first_item_url`)
  to `discovered_sources.json` when `auto_add_discovered` (default true);
  it's scanned like a hand-configured source from the next run, capped at
  `discovered_max_fetches` (default 10) article fetches per run so one
  high-volume discovered outlet can't consume the whole run's budget.
  Failed probes and `auto_add_discovered: false` candidates land in
  "Candidates needing manual review" instead; results from a backfill run
  are held and shown in the next digest that runs, not lost.

## Google Alerts setup

Alert RSS URLs go in the `GOOGLE_ALERT_FEEDS` repo secret, one per line,
never in config.json (they embed a Google account id and this repo is
public).

## Suggested website updates

Each new outside citation (news/newsletter tier) or own byline gets a
ready-to-run Claude Code prompt in the digest (and the HTML email, inside
a `<pre>` block) naming the personal site and tracker files to update,
per `site_update_rules` in config.json. URLs in `never_feature_urls` are
always skipped; a citation already live on the relevant page (checked via
`site_pages`) is marked "already listed" instead of getting a prompt.

## Cloudflare referrer report (dormant)

If both `CF_ANALYTICS_TOKEN` and `CF_ZONE_ID` secrets are set, every run
queries the Cloudflare GraphQL Analytics API for the last 24 hours of
`clientRefererHost` traffic to the site, filters out nycuriosity.com hosts
and `referrer_ignore_hosts`, and stores daily rows in `seen.db`. The Monday
digest aggregates the last 7 days into a "Sites sending visitors this week"
section: hosts by request count, with their top landing paths. Without
both secrets this source is silently skipped (one info line, not an error).
The exact field names and what's available on Cloudflare's free plan are
**unverified**, since no token exists yet to test against; any GraphQL
error is recorded as a source error rather than failing the run.

## Dedup

Google News RSS links are opaque redirects that can't be decoded offline,
so each item is keyed on **both** its normalized URL (tracking params
stripped) and an outlet-domain + title fingerprint. An item is new only if
no key has been seen. Everything fetched, including excluded and filtered
items, is marked seen so nothing resurfaces on a later run.

## Pending / digest flow

Newly-flagged items go into a `pending` table (not yet shown to anyone).
`--digest` loads every pending row, builds the digest from all of them
(which may span several days' collect runs if a run was skipped), writes
it, and marks those rows digested. A collect-only run never touches the
digest file.

## Known limits

- **Article full-text scraping is unstructured.** `fetch_article` outlets
  get the whole page's text (nav, ads, boilerplate included), which can
  occasionally produce a false match on generic context terms. Reviewed by
  a human before publishing anything from the digest.
- **Backfill depth varies by source.** Google honors `after:`; outlet
  feeds only return what they currently publish, so a 90-day outlet
  backfill is best-effort.
- **Not covered at all:** Substack Notes (no public search API) and
  paywalled newsletters aren't covered; worth a manual check monthly.
