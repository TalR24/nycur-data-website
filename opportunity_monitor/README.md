# Opportunity monitor

Saturday digest of Tal's private opportunities watch list. Sibling of
`data_website/mention_monitor`; reuses its premium-repo state checkout and
Gmail SMTP conventions.

## What it does

Reads `opportunities/watchlist.yaml` from the private `nycur-data-premium`
repo, drops anything skipped, done, won, declined, or requiring full-time
leave, re-checks each remaining item's official page for date or deadline
changes, scores what is left against `opportunities/profile.md`, and builds
an HTML plus plain-text digest: pursuing, closing in 45 days, new this week,
windows opening soon, deadlines announced or changed since the last run, pages that changed, rolling and open (first week of
the month only), and past deadline items to clean up.

## Where state lives

All state is in the private premium repo, never in this public one:

- `opportunities/state/pages.json`: per-item hash and extracted date lines,
  used to detect page changes between runs.
- `opportunities/state/deadlines.json`: per-item deadline, deadline kind and
  expected month from the last real run. The next run lists items whose
  deadline was announced, moved, or went from expected/open/rolling to set
  under "Deadlines announced or changed" (priority items included). The
  first run only records a baseline; new watch list items are not reported
  there. Written only on runs that fetch, never on `--no-fetch`.
- `opportunities/state/digests/YYYY-MM-DD.{html,txt}`: the digest that ran
  that day.
- `opportunities/state/last_run.json`: date, per-section counts, fetch
  failures from the most recent run.

## Run locally

```
python3 opportunity_monitor/monitor.py \
  --watchlist /path/to/nycur-data-premium/opportunities/watchlist.yaml \
  --state-dir /path/to/nycur-data-premium/opportunities/state \
  --today 2026-10-03 --no-fetch
```

Drop `--no-fetch` to re-check pages over the network. Add `--email` to send
the digest (needs the secrets below). `--out PATH` writes `PATH.html` and
`PATH.txt` instead of the default `<state-dir>/digests/<date>.{html,txt}`.

Tests (offline, no network):

```
python3 -m unittest discover -s opportunity_monitor -p "test_monitor.py" -v
```

## Secrets used

- `GMAIL_USER`, `GMAIL_APP_PASSWORD`: Gmail SMTP login (shared with
  mention_monitor).
- `OPPS_DIGEST_TO`: recipient; falls back to `MENTION_DIGEST_TO`, then
  `GMAIL_USER`.
- `OPPS_TRACKER_URL`: optional link to the tracker page, printed at the top
  of the digest when set.
- `PREMIUM_PUSH_TOKEN`: clones and pushes the premium repo's state (workflow
  only, same token mention_monitor uses).
