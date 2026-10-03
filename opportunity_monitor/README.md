# Opportunity monitor

Last refreshed: Oct 3 2026.

Saturday email digest of Tal's private opportunities watch list (conferences, fellowships, grants, awards, civic seats). Sibling of `mention_monitor/`; it shares that monitor's premium-repo state checkout and Gmail SMTP conventions.

## What it does

Reads `opportunities/watchlist.yaml` from the private `nycur-data-premium` repo and:
1. Drops items with status `skip`, `done`, `won` or `declined`, and items that require full-time leave.
2. Re-checks each remaining item's official page for date or deadline changes (skipped with `--no-fetch`).
3. Scores what is left against `opportunities/profile.md`.
4. Builds an HTML and plain-text digest with these sections, in order: Your priorities; Deadlines announced or changed; Pursuing; Closing in the next 45 days; New this week; Windows opening soon; Pages that changed; Rolling and open (first week of the month only); Past deadline, update or retire.

A scheduled run always emails, even when nothing is flagged, so a missing email means a failure. A failed run sends "Opportunities radar run failed".

## How it runs

`.github/workflows/opportunity_monitor.yml` runs Saturdays at 12:00 UTC. It installs `requirements.txt` (requests, PyYAML), runs the offline tests, clones the premium repo with `PREMIUM_PUSH_TOKEN`, runs the monitor, and commits `opportunities/state/` back to the premium repo. Manual dispatch inputs: `send_email` and `no_fetch`.

Secrets (names only):
- `GMAIL_USER`, `GMAIL_APP_PASSWORD`: Gmail SMTP login, shared with the mention monitor.
- `OPPS_DIGEST_TO`: recipient; falls back to `MENTION_DIGEST_TO`, then `GMAIL_USER`.
- `OPPS_TRACKER_URL`: optional link to the tracker page, printed at the top of the digest when set.
- `PREMIUM_PUSH_TOKEN`: clones and pushes the premium repo (workflow only).

The watch list itself is filled by the Claude cloud routine "Opps radar" (Friday discovery), which writes `opportunities/watchlist.yaml` in the premium repo.

## State (private premium repo only, never this repo)

- `opportunities/state/pages.json`: per-item page hash and extracted date lines, used to detect page changes between runs.
- `opportunities/state/deadlines.json`: per-item deadline, deadline kind and expected month from the last real run. The next run lists items whose deadline was announced, moved, or went from expected, open or rolling to set under "Deadlines announced or changed" (priority items included). The first run records a baseline only, and new watch list items are not reported there. Written only on runs that fetch, never on `--no-fetch`.
- `opportunities/state/digests/YYYY-MM-DD.{html,txt}`: the digest of that day.
- `opportunities/state/last_run.json`: date, per-section counts and fetch failures from the latest run.

## Run locally

```
python3 opportunity_monitor/monitor.py \
  --watchlist /path/to/nycur-data-premium/opportunities/watchlist.yaml \
  --state-dir /path/to/nycur-data-premium/opportunities/state \
  --today 2026-10-03 --no-fetch
```

Flags: `--watchlist` and `--state-dir` (required), `--today YYYY-MM-DD`, `--no-fetch` (skip the network re-check), `--email` (send the digest; needs the Gmail secrets as environment variables), `--out PATH` (write `PATH.html` and `PATH.txt` instead of `<state-dir>/digests/<date>.{html,txt}`).

Tests (offline, no network; 54 tests as of Oct 3 2026):

```
python3 -m unittest discover -s opportunity_monitor -p "test_monitor.py" -v
```
