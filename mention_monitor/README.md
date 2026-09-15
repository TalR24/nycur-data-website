# Mention Monitor

Weekly monitor for outside citations of Tal Roded, NYCuriosity, and the
trackers (fiscal impacts, legislation implementation / obligations) in news
articles, newsletters, and social posts — *not* his own publishing.

It polls Google News RSS, Bing News RSS, the Bluesky public search API, and
Reddit search for each query in `config.json`, drops results from his own
properties, dedupes against `seen.db` (SQLite), and writes a markdown digest
to `digests/YYYY-MM-DD.md` (also printed to stdout, optionally emailed).

## How it runs

`.github/workflows/mention_monitor.yml` runs Mondays ~6:30am ET (after Site
Health), emails the digest via the existing `GMAIL_USER` /
`GMAIL_APP_PASSWORD` secrets, and commits `seen.db` + the digest back to the
repo. Optional secret `MENTION_DIGEST_TO` overrides the recipient (defaults
to `GMAIL_USER`).

**First run:** trigger the workflow manually with `backfill: true` (or run
`python3 monitor.py --backfill` locally and commit `seen.db`). That seeds the
dedup db from roughly the last 90 days so the first real digest isn't a
flood of old links.

Local / cron alternative:

```
pip install -r mention_monitor/requirements.txt
python3 mention_monitor/monitor.py --backfill        # once
# crontab: Mondays 7am local
0 7 * * 1  cd /path/to/nycur-data-website && python3 mention_monitor/monitor.py --email
```

Flags: `--backfill` (seed db, no digest/email), `--email` (send when there
are new items; silently skips if Gmail env vars are missing), `--config`,
`--db`, `--outdir`.

## Config schema (`config.json`)

Edit the config, not the code.

- `queries` — run separately, never combined. Each has:
  - `id` — short label shown in the digest
  - `q` — the search string sent to every source (quote exact phrases)
  - `match_terms` — phrases to locate in result text for the context snippet
  - `require_terms` (optional) — post-fetch filter: keep a result only if at
    least one term appears in its title/summary. This is what keeps the
    figure queries (`"$7.5 billion"`, `"2,231"`) usable — search engines
    ignore punctuation, so raw results are noisy.
  - `sources` (optional) — per-query override of the top-level `sources` list
- `exclude_domains` — own properties, matched including subdomains
  (`nycuriosity.com` covers `data.nycuriosity.com`)
- `exclude_url_prefixes` — path-level own properties
  (`substack.com/@nycuriosity`, the LinkedIn/Instagram/Facebook profiles)
- `exclude_bluesky_handles` / `exclude_reddit_authors` — self-exclusion on
  social is by author. **The Bluesky handles are guesses — correct them.**
  Someone *else* sharing an NYCuriosity link is a mention and is kept.
- `own_columns` — Citizens Union Searchlight (matched by domain or the
  keyword "searchlight" in outlet/title) goes to a separate "My own columns"
  digest section instead of being dropped.
- `newsletter_domains`, `tier_overrides` — control the digest's
  news / newsletter / social ordering. Override a domain's tier with e.g.
  `"tier_overrides": {"somesite.org": "news"}`.
- `user_agent`, `request_delay_seconds` — politeness settings. Reddit 429s
  generic user agents; keep a real one.

## Dedup

Google News RSS links are opaque redirects that can't be decoded offline,
and the same article often arrives via both Google and Bing — so each item
is keyed on **both** its normalized URL (tracking params stripped, Bing
redirects unwrapped) and an outlet-domain + title fingerprint. An item is
new only if no key has been seen. Everything fetched — including excluded
and filtered items — is marked seen so nothing resurfaces weekly.

## Known limits

- **Context snippets are best-effort.** RSS summaries are often just the
  headline; the digest shows the text around the matched term when the feed
  provides it, otherwise the summary start. Full-article fetching was left
  out deliberately (paywalls, bot-blocking).
- **Backfill depth varies by source.** Google honors `after:`, Bluesky
  honors `since`, Reddit gets `t=year`; Bing has no date operator and only
  returns recent items.
- **Reddit may fail from GitHub Actions** — it aggressively blocks
  datacenter IPs even with a proper User-Agent. Failures land in the
  digest's "Source errors" section rather than killing the run.
- **Bing News RSS is unofficial** and Microsoft has been retiring Bing
  search surfaces; treat it as best-effort redundancy for Google.
- **Not covered at all:** Substack Notes (no public search API) and
  paywalled newsletters. Worth a manual check monthly.
