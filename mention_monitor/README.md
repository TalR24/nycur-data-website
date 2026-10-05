# Mention Monitor

Last refreshed: Oct 3 2026.

Finds outside citations of Tal Roded, NYCuriosity and the trackers (fiscal impacts, legislation implementation / obligations) in news articles and newsletters. It does not track his own publishing, except to route it into its own digest section.

## Sources

Every run (daily):
- **`google_news`**: Google News RSS for the name, brand and tracker queries.
- **`outlets`**: 12 outlet RSS feeds scanned in full text (The City Reporter, City Limits, Streetsblog NYC, City & State NY, Reinvent Albany, Vital City, Gothamist, amNY, Brooklyn Paper, QNS, The Lo-Down, W42ST). They are scanned for the name, brand and tracker queries and flag any article that links to nycuriosity.com or nycuriosity.substack.com.
- **`sitemap_scan`**: Ghost `sitemap-posts.xml` for Vital City and Hell Gate.
- **`alert_feeds`**: Google Alerts Atom feeds, read from the `GOOGLE_ALERT_FEEDS` secret.
- **`cloudflare_referrers`**: Cloudflare Web Analytics referrer hosts (see below).

Weekly only (`--digest` and `--backfill` runs):
- **`wp_search`**: WordPress REST search (`/wp-json/wp/v2/search?search=nycuriosity`) on the 10 sites in `wp_search_sites`, paged until an empty page or HTTP 400. A hit is fetched and flagged like an outlet article; a hit that does not flag is still recorded as scanned.
- **`openalex`**: Tal's own works and the works citing them, by `openalex_author_ids`. No key needed.

## How a run works

1. Collect from the sources above, dedupe against `seen.db` (SQLite), and queue newly flagged items as pending. Google News links are opaque redirects, so each item is keyed on both its normalized URL and an outlet-domain plus title fingerprint. Everything fetched, including excluded items, is marked seen.
2. On Sundays (or with `--digest`), build `digests/YYYY-MM-DD.md` from all pending items, mark them digested, and with `--email` send it as a multipart text and HTML message.
3. Digest sections: outside citations (ordered news, newsletter, social), Research citations (OpenAlex and `research_domains`), New research listings, My own pieces, Sites sending visitors this week, Suggested website updates, Suggested removals, Candidates needing manual review, Scan progress, Source errors.

A collect-only run never writes a digest. A run skipped for several days is not lost: the next digest covers every pending row.

## How it runs

`.github/workflows/mention_monitor.yml` runs daily at 11:30 UTC. Every day it collects and queues; on Sundays it also builds and emails the digest. It runs the offline tests first (`MENTION_MONITOR_SKIP_LIVE_TESTS=1`). `workflow_dispatch` inputs: `backfill`, `digest`, `send_email` (implies digest), `referrers_only`, `referrers_window_hours`. A failed run emails "Mention monitor run failed", because a failure otherwise looks like a quiet week.

State (`seen.db`, `digests/`, `discovered_sources.json`) lives in the private premium repo under `mention_monitor_state/`, never in this public repo. The workflow clones it with `PREMIUM_PUSH_TOKEN`, passes `--db`, `--outdir` and `--discovered-path`, and commits the state back there. `mention_monitor/check_freshness.py` (run by `site_health.yml`) emails if that folder has had no commit for 3 days.

Secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `MENTION_DIGEST_TO` (recipient, defaults to `GMAIL_USER`), `PREMIUM_PUSH_TOKEN`, `CF_ANALYTICS_TOKEN`, `CF_ACCOUNT_ID`, `CF_ZONE_ID`, `GOOGLE_ALERT_FEEDS`.

Local use:

```
pip install -r mention_monitor/requirements.txt          # requests, feedparser
python3 mention_monitor/monitor.py --backfill            # seed the db from about 90 days back
python3 mention_monitor/monitor.py                       # collect only
python3 mention_monitor/monitor.py --digest --email      # build and send the digest
python3 -m unittest discover -s mention_monitor -p "test_monitor.py" -v
```

Flags: `--backfill` (seed the db; queues nothing, no digest, no email), `--digest`, `--email` (needs the Gmail env vars; silently skipped without them), `--referrers-only` with `--referrers-window-hours N` (runs only the Cloudflare source and prints rows or the error; no db writes), `--config`, `--db`, `--outdir`, `--discovered-path`. Local runs default the db to `mention_monitor/seen.db` and digests to `mention_monitor/digests/`, both gitignored.

## Config (`config.json`)

Edit the config, not the code.

- `outlets`: `name`, `feed`, `tier` (`news` or `newsletter`), `fetch_article` (fetch the page when the feed entry has no usable full text, capped by `max_article_fetches`).
- `queries`: run separately, never combined. Fields: `id`, `q` (the Google News string), `match_terms` (must appear in the full text or the Google News title), optional `require_terms` (at least one must also appear) and `exclude_terms` (none may appear), and `sources`. All queries use `google_news` and `outlets`. Current ids: `name`, `brand`, `fiscal-tracker`, `obligations-tracker`, `implementation-tracker`. No figure queries (a bare number such as `2,231`): Tal dropped them on Oct 5 2026 after `2231` matched a Cloudflare ray ID in Gothamist page scripts and flagged two unrelated articles.
- `own_link_domains`: a link to these hosts in an outlet article flags it as a citation with no query match.
- `exclude_domains`, `exclude_url_prefixes`: own properties, matched including subdomains and path prefixes.
- `own_byline_page`: Tal's live Publications page. On digest and backfill runs every entry outside its "In the press" section counts as his own writing. A failed fetch leaves the configured lists in place.
- `own_author_names`, `own_byline_urls`, `own_byline_titles`, `own_columns`: his writing in outside outlets, matched by author metadata, seeded URL, or normalized title (Google News items carry no author). A title match must be a prefix, never a substring, and once the real outlet URL is known it counts only on an outlet that hosts one of his bylines, so coverage of his piece (EV Grieve on the Clinton Street op-ed, Oct 2026) lands in outside mentions. They merge into "My own pieces".
- `research_domains`: citations of his academic work (NBER, Cato, Fed research banks and similar) go to "Research citations". A Google News item matched only by name, with the name absent from the visible title and snippet, is kept and labeled "(name match from Google News, not verified in text)".
- `newsletter_domains`, `tier_overrides`: digest ordering.
- `roundup_title_patterns`: titles of link roundups ("Headlines", "Roundup").
- `referrer_ignore_hosts`: hosts left out of the referrer report. An entry ending in `.` (`google.`) matches that label anywhere in the host; other entries match a full host or parent domain.
- `discovery_ignore_domains`, `prune_exempt`, `auto_add_discovered`, `prune_after_weeks` (8), `prune_error_weeks` (3), `new_probe_cap` (10): self-updating behavior, below.
- `user_agent`, `mailto`, `request_delay_seconds` (2.0).
- Budgets: `max_article_fetches` 150, `outlet_time_budget_seconds` 300, `run_time_budget_seconds` 1500. A normal run takes about 4 minutes against the workflow's 45-minute timeout. `sitemap_scan` splits what is left of `max_article_fetches` into an equal share per sitemap, recomputed from the remainder.

### Sitemap scan window
The window is 90 days on an outlet's first run (or a backfill), otherwise since the outlet's last fully successful scan minus a 2-day overlap. The stored watermark means "this run scanned every in-window entry", so a run that hits the cap or budget never advances it. The per-URL `scanned` table, not the window, stops refetching. A paywalled page with no usable article text (Hell Gate) is recorded as scanned with a note.

### Self-updating
`source_yield` records one row per run per unit (outlet, `wp_search` site, sitemap outlet, Google News query). A unit with zero flagged items across `prune_after_weeks` consecutive weeks that each had a successful run, or with `prune_error_weeks` consecutive weeks of all-error runs, gets a "Suggested removals" line naming the exact spot to edit. It never edits `config.json`. A discovery pass takes candidate domains from Google News, alerts, OpenAlex and referrer hosts, skips covered or ignored ones, probes each remaining candidate at most once per 30 days (feed, then `wp_search`, then sitemap), and appends a passing one to `discovered_sources.json`. It is scanned from the next run, capped at `discovered_max_fetches` (default 10) article fetches per run. Failed probes and candidates held back by `auto_add_discovered: false` appear under "Candidates needing manual review". Discovery results from a backfill are held for the next digest.

### Scan progress
When an outlet, `wp_search` site, sitemap outlet or the shared Google News budget runs out before every candidate is scanned, the carry-over goes to a small "Scan progress" section, not to "Source errors". Backlog alone never triggers an email, and the subject line's error count excludes it. HTTP, TLS, parse and GraphQL failures still count as errors.

### Suggested website updates
Each new news or newsletter citation and each own byline gets a ready-to-run Claude Code prompt in the digest (inside a `<pre>` block in the email), naming the personal site and tracker files to update per `site_update_rules`. URLs in `never_feature_urls` and titles in `never_feature_titles` are skipped. A citation already live on a page listed in `site_pages` is marked "already listed".

### Google Alerts
Alert RSS URLs go in the `GOOGLE_ALERT_FEEDS` secret, one per line, never in `config.json` (they embed a Google account id and this repo is public). `alert_feeds` in the config stays empty. Each entry's `google.com/url?...&url=` link is unwrapped and highlight tags are stripped; no term match is required. The log shows only a feed's `<title>`, never its URL.

## Cloudflare referrer report

`cloudflare_referrers_enabled` is `true`. With `CF_ANALYTICS_TOKEN` (Account Analytics Read) and `CF_ACCOUNT_ID` set, every run queries the Cloudflare GraphQL Analytics API (`rumPageloadEventsAdaptiveGroups`) for the last 24 hours of `refererHost` traffic, drops nycuriosity.com hosts and `referrer_ignore_hosts`, and stores daily rows in `seen.db`. Sunday's digest aggregates 7 days into "Sites sending visitors this week", with each host's top landing paths. Web Analytics must be enabled on the hostnames: data.nycuriosity.com and talroded.nycuriosity.com carry the beacon snippet in every page head, and automatic edge injection covers nycuriosity.com. Counts are RUM-sampled, so they arrive in multiples of the sample rate. `CF_WA_SITE_TAG` optionally scopes the query to one site. Without both secrets the source is skipped with one info line. A GraphQL error is recorded as a source error (message only, hex ids redacted) and does not fail the run.

## Known limits

- `fetch_article` outlets return the whole page's text (navigation and boilerplate included), which can occasionally match on generic context terms. A human reviews the digest before anything is published from it.
- Google honors `after:` on backfill; outlet feeds return only what they currently publish, so the 90-day outlet backfill is best-effort.
- Not covered: Substack Notes (no public search API) and paywalled newsletters. Check those by hand monthly.
