# NYCuriosity Data

Last refreshed: Oct 3 2026.

Static site at **[data.nycuriosity.com](https://data.nycuriosity.com)**, the companion to the [NYCuriosity](https://www.nycuriosity.com) Substack (NYC urban policy, transit, infrastructure, street design). Repo `TalR24/nycur-data-website`, served by GitHub Pages from `main` (`CNAME`, `.nojekyll`). No backend: every page is HTML that loads JSON and renders client-side. Brand tokens (palette, fonts, logos) live in `assets/brand.css` and the `nycuriosity-brand` skill, not in this file.

The site holds three kinds of content:
- **Tools**: the NYC Council Legislation Trackers and the Community Board tools.
- **Post data hubs**: charts and tables tied to one Substack article each.
- **Redirect stubs**: old URLs that forward to current ones (77 pages with a meta refresh).

---

## Directory map

| Path | What it holds |
|---|---|
| `index.html` | Homepage: start cards, tool cards, post cards (newest first). |
| `civic_reference/nyc_council_legislation_trackers/` | Trackers umbrella hub, Council Members, Agencies (also the NYC government bodies browser), shared multiselect and tracker-switch JS, `data/*.json`, `pipeline/`, `quality/` (gold sets and scorers), `quality_reports/`. |
| `civic_reference/nyc_council_fiscal_impacts_tracker/` | Fiscal Impacts Tracker: bill table, overview and four chart pages, methodology, `data/`. Pipeline doc: `PIPELINE_REFERENCE.md`. |
| `civic_reference/legislation_implementation_tracker/` | Obligations Tracker, Powers Tracker, Law Explorer (`law/`), deadline timeline, agency workload, member tools page (`alerts/`), methodology, `data/`, `pipeline/`, `quality_reports/`. |
| `civic_reference/cb_member_guide/` | Slide deck and handout: how to be an effective community board member. |
| `civic_reference/block_party_maps/` | Block Party demo maps for Manhattan community boards (`data/` holds per-board JS payloads). |
| `civic_reference/nyc-gov-bodies-explorer/`, `civic_reference/state_capacity_ecosystem/` | Redirect stubs only. |
| `cb-tools/` | Community Board tools hub (`index.html`): `member-tracker/`, `block-party/` (teaser for the members-only dashboard), `board-scorecard/`, `meeting-review/`, `roberts-rules-helper/`, talk pages (`block_party_july2026/`, `harvard-rcn-2026/`, `school-of-data-2026/`, `sogt-2026/`), shared `cb-filter.*` and `cb-switch.js`. |
| `nycuriosity_substack_posts/` | 16 post data hubs, one folder per Substack post, each with `index.html`, chart subpages and `data/`. |
| `assets/` | `chart.css` + `chart.js` (every chart, table and card), `brand.css`, `site.js` (header nav, tool and post menus, related-work block), `whats-new.json`, `related_work.json`, `brand/` (logos, icons). |
| `pipeline/` | Fiscal Impacts pipeline and the agency name crosswalk (`agency_canon.py`). See the fiscal `PIPELINE_REFERENCE.md`. |
| `seo/` | Head-tag check, sitemap, `llms.txt`, JSON-LD, static snapshots, Search Console report and email scripts. Serves all three public sites. |
| `site_health/` | `check_site.py`, the weekly Playwright crawl. |
| `mention_monitor/` | Daily scan for outside citations of Tal and the trackers. Own README. |
| `opportunity_monitor/` | Saturday digest of the private opportunities watch list. Own README. |
| `members/` | Members landing page (links to the premium origin). |
| `new/` | "What's New" page, fed by `assets/whats-new.json`. |
| `privacy/`, `terms/`, `tiktok-callback/` | Legal pages and the TikTok OAuth callback page. |
| `cb-resolutions/`, `nyc_council_fiscal_impacts_tracker/`, `nyc-gov-bodies-explorer/`, `state_capacity_ecosystem/` | Redirect stubs for retired URLs. Keep them so old links work. |
| `.github/workflows/` | 11 workflows (see Automation). `.github/tracker_refresh_routine_prompt.md` is the input to a live cloud routine; do not edit it casually. |
| Root files | `sitemap.xml`, `llms.txt`, `robots.txt` (all generated or SEO-managed), `favicon.svg`, `apple-touch-icon.png`, `site.webmanifest`, `website_logo.png`, `CNAME`. |

Other repos this site touches: `statecapacityecosystem` (the State Capacity Ecosystem site, statecapacityecosystem.com), `nycur-data-premium` (private; members site, downloadable CSVs, alert state, monitor state, SEO reports and the Cloudflare Worker in its `worker/` folder), `personal_website` (talroded.nycuriosity.com).

---

## Tools

### NYC Council Legislation Trackers
Hub: `/civic_reference/nyc_council_legislation_trackers/`. Free, no data downloads for anyone, members included.
- **Fiscal Impacts Tracker** (`/civic_reference/nyc_council_fiscal_impacts_tracker/`): Council bills with a Finance Division fiscal impact statement showing a new non-zero cost or revenue, by agency, sponsor, committee and year.
- **Obligations Tracker** (`/civic_reference/legislation_implementation_tracker/`): the duties each enacted local law since 2014 gives agencies, with deadlines and DORIS report filing status. **Powers Tracker** (`.../powers/`): the powers those laws grant.
- **Council Members** and **Agencies** profiles, and the **Law Explorer** (`.../law/`).
- Member email alerts and "Ask the Trackers" live on the premium origin; this repo builds their inputs (`send_alerts.py`, `build_ask_index.py`).

Concept credit: the Obligations Tracker adapts the implementation-checklist approach Marci Dale prototyped in ["What if every new law came with a checklist?"](https://marcidale.substack.com/p/what-if-every-new-law-came-with-a).

### Community Board tools (`/cb-tools/`)
- **Member Tracker** (`member-tracker/`): leaders, members and term-limit openings for all 59 boards; board profiles, alerts signup, methodology. Pipeline in `member-tracker/pipeline/` (schema: `pipeline/extracted/ROSTER_SCHEMA.md`).
- **Block Party** (`block-party/`): public teaser for the CB Resolutions Dashboard. The working dashboard is members-only on the premium origin.
- **Board Scorecard**, **AI Meeting Review**, **Robert's Rules Helper**, and the **Member Guide** (`/civic_reference/cb_member_guide/`).

### State Capacity Ecosystem
Lives at [statecapacityecosystem.com](https://statecapacityecosystem.com/), repo `TalR24/statecapacityecosystem`. Everything under `state_capacity_ecosystem/` here (and its old `civic_reference/` path) is a redirect stub; the one tracked asset is `state_capacity_ecosystem/assets/sce_logo.png`.

---

## Premium boundary

The CB Resolutions Dashboard, Ask the Trackers, member alerts, district briefs and watchlists run from the private repo `TalR24/nycur-data-premium` on a Cloudflare Worker at `premium.nycuriosity.com`, behind Cloudflare Access. That repo's README holds the architecture, deploy steps and access process.

Rules for this repo:
- **Downloadable CSVs are members-only.** Every CSV or data download button links through `/members/?file=`, and the file lives in the premium repo. Never add a direct `<a href="...csv">` or commit a downloadable CSV here. The `check-html-scripts.sh` hook blocks direct CSV anchors. The Legislation Trackers offer no downloads at all.
- **Never put gated tools' data in this repo.** The teaser stats in `cb-tools/block-party/index.html` and its card in `index.html` are hardcoded; update both when the database grows.
- Teasers stay indexable; the premium origin is `noindex`.

---

## How pages and data are built

All CSS and JS are loaded from shared assets or inline per page; there is no build step for HTML.

- **Charts, tables, cards**: styled by `assets/chart.css` and driven by `assets/chart.js`. Never copy chart styling into a page. Chart actions (PNG, embed) and the `.c-foot` attribution use the shared handlers. Standards are in the `visualization-style-guide` skill.
- **Page chrome**: copy a golden reference page of the same kind (a tool hub, a post hub, a chart subpage) rather than rebuilding it. `assets/site.js` injects the header nav and related-work block; register new tools in its `TOOLS_MENU` and new post hubs in `POSTS_MENU`, and add related links in `assets/related_work.json`.
- **Libraries**: D3 v7, Chart.js, PapaParse, html2canvas (loaded from CDNs), Google Fonts (Playfair Display, JetBrains Mono, Inter).
- **Forms** submit by `mailto:` with a clipboard fallback.

### Data pipelines
| Dataset | Scripts | Output |
|---|---|---|
| Fiscal impacts | `pipeline/fetch_fiscal_impacts.py`, `regenerate_agency_data.py`, `validate_fiscal_impacts.py` | `civic_reference/nyc_council_fiscal_impacts_tracker/data/fiscal_impacts.json`, `agency-fiscal-impact/data.json` |
| Obligations and powers | `civic_reference/legislation_implementation_tracker/pipeline/` (`fetch_enacted_laws.py`, `extract_obligations.py`, `reextract_queued.py`, `build_report_filings.py`, `label_kinds.py`, `validate_obligations.py`) | `legislation_implementation_tracker/data/` (`laws.json`, `obligations.json`, `powers.json`, `report_filings.json`) |
| Council members, agencies | `civic_reference/nyc_council_legislation_trackers/pipeline/` (`rebuild_profiles.sh` runs the roster, stats, agency, votes and context builders) | `nyc_council_legislation_trackers/data/*.json` |
| CB member tracker | `cb-tools/member-tracker/pipeline/` (`fetch_open_data.py`, `fetch_board_pages.py`, `recrawl_gaps.py`, `extract_rosters.py`, `build_tracker_data.py`) | `member-tracker/data/boards.json`, `members.json`, `pipeline/extracted/rosters/` |
| Ask index | `build_ask_index.py` | `worker/ask_index.json` in the premium repo |

Extraction runs on the Claude Max plan first (a monthly cloud routine using `--emit-packets` and `--ingest`), and the workflows call the Anthropic API only for what the routine left. Details: the `legislation-trackers` and `fiscal-impacts-tracker` skills.

### SEO and LLM readiness (`seo/`)
- Every live page needs title, meta description, canonical and og tags. `seo/seo_check.py` checks the contract (`--file` for one page, `--all --live` for production, including fetches as GPTBot, ClaudeBot and PerplexityBot and a check of `/llms.txt`).
- `python3 seo/build_sitemap.py --site data` regenerates `sitemap.xml`, `llms.txt` and the JSON-LD together; add `--check` to report drift. Never hand-edit `sitemap.xml`. Run it after adding, renaming or removing a page.
- `seo/static_snapshot.py` writes pre-rendered copies of JS-built content between `<!-- static:<id>:start -->` and `<!-- static:<id>:end -->` markers inside the element the JS fills, so crawlers without JavaScript read real numbers (10 rows at most). Builders: `pipeline/build_fiscal_static_snapshots.py`, `civic_reference/legislation_implementation_tracker/pipeline/build_static_snapshots.py` (11 obligations and umbrella pages), `cb-tools/member-tracker/pipeline/build_static_boards.py`.
- `robots.txt` explicitly allows the AI crawlers.
- `seo/gsc_pull.py` and `seo/report_email.py` build the monthly SEO report; `seo/sce_monthly.py` builds the State Capacity Ecosystem report.

---

## Automation

Eleven workflows in `.github/workflows/` (times UTC). Workflows need "Read and write permissions" for `GITHUB_TOKEN` (Settings, Actions, General).

| Workflow | Schedule | What it does |
|---|---|---|
| `refresh_fiscal_data.yml` | 1st 18:23; 2nd to 7th 12:00 | Fiscal pipeline in batch mode (skips ids the Max routine finished), agency data, validator, static snapshots, commit. Days 2 to 7 only resume a pending batch. |
| `refresh_implementation_data.yml` | 1st 21:40; 2nd to 7th 13:00 | Fetch enacted laws, re-extract queued laws, DORIS filings, extract obligations, rebuild profiles, static snapshots, commit, send member alerts, rebuild the Ask index. Days 2 to 7 resume pending batches. |
| `refresh_cb_member_data.yml` | 5th 11:23 | Open Data fetch, board site crawl, roster extraction for changed boards, tracker rebuild, static boards, commit, CB alerts. |
| `monthly_quality_report.yml` | 3rd 14:00 | Runs the tracker validators, commits `quality_reports/`, emails the summary. |
| `seo_monthly.yml` | 2nd 12:00 | Search Console pull for `sc-domain:nycuriosity.com`; emails the to-do report and files `YYYY-MM.{md,json,html}` in the premium repo's `seo_reports/`. |
| `sce_monthly.yml` | 1st 15:30 | One State Capacity Ecosystem email (site health, the review routine's output, Search Console data); files the snapshot in the premium repo. |
| `static_snapshots_daily.yml` | Daily 10:15 | Re-renders the tracker snapshots whose content depends on today's date (deadline timeline, overdue marks); commits only on change. No API calls. |
| `site_health.yml` | Mondays 11:00 | Playwright crawl of every page, mention-monitor freshness check, `seo_check.py --all --live`; emails only on errors. |
| `mention_monitor.yml` | Daily 11:30 | Collects outside citations; Sundays also build and email the digest. State is committed to the premium repo. |
| `opportunity_monitor.yml` | Saturdays 12:00 | Emails the opportunities digest; state is committed to the premium repo. |
| `claude_backfill.yml` | Manual | One-off API tasks: `canary`, `label_kinds`, `reextract_obligations`, `pilot_obligations`, `verify_fiscal`, `verify_obligations`. |

The Claude cloud routine "NYC Council trackers monthly refresh" (Max plan, 1st 12:17) writes into this repo ahead of the two refresh workflows, which are its API-billed fallback.

Secrets (names only): `ANTHROPIC_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `MENTION_DIGEST_TO`, `OPPS_DIGEST_TO`, `OPPS_TRACKER_URL`, `PREMIUM_PUSH_TOKEN`, `LEGISTAR_TOKEN`, `GSC_SERVICE_ACCOUNT_JSON`, `CF_ANALYTICS_TOKEN`, `CF_ZONE_ID`, `CF_ACCOUNT_ID`, `GOOGLE_ALERT_FEEDS`.

---

## Common commands

```bash
git fetch && git pull                                    # always first; collaborators push through the web UI
python3 seo/build_sitemap.py --site data                 # after adding, renaming or removing a page
python3 seo/seo_check.py --site data                     # head-tag contract for the repo
python3 pipeline/tests/test_fiscal_rules.py              # fiscal totals rules (25 cases)
python3 pipeline/validate_fiscal_impacts.py              # fiscal data regression suite
python3 -m unittest discover -s mention_monitor -p "test_monitor.py"
python3 -m unittest discover -s opportunity_monitor -p "test_monitor.py"
python3 site_health/check_site.py --dry-run              # needs Playwright; prints, never emails
```

---

## Adding a post data hub or tool

1. Confirm the folder name and bucket (Substack post under `nycuriosity_substack_posts/<folder>/`, tool under `civic_reference/<tool>/` or `cb-tools/<tool>/`).
2. Copy the chrome from a reference page of the same kind. Hub at `<folder>/index.html`, chart subpages in subfolders, source data in `data/`. Full steps are in the `visualization-style-guide` skill (Step 5b covers registration).
3. Register it: homepage card (newest first), `assets/site.js` menu, `assets/whats-new.json`, `assets/related_work.json` if it links to related work.
4. Run `python3 seo/build_sitemap.py --site data`.
5. CSV data for a chart uses raw numbers only (no `$`, commas or units in cells). Any download button goes through `/members/?file=`.

## Conventions for contributors

- **Pull before editing.** Stage explicit paths only; never `git add .` or `git add -A` (the repo carries long-standing untracked files, and a hook blocks both).
- **Hooks** (workspace `.claude/hooks/`): inline-script syntax and restricted-global-name check (a top-level `const top` or `name` blanks a chart's SVG), direct-CSV-link ban, SEO head gate on save, unpushed-commit warning.
- **Buy Me a Coffee**: every page carries a "Support my work" link to `https://buymeacoffee.com/nycuriosity` in the header and footer. Skip it on redirect stubs and on chrome-less pages (`civic_reference/cb_member_guide/` pages).
- **Colour and fonts** come from `assets/brand.css` variables only. Almost nothing in the palette passes contrast as text on cream; check the `nycuriosity-brand` skill first.
- **Voice** in any visible text: no em dashes or double hyphens, headlines that state the takeaway, no weasel words, exact numbers.
- **Redirect stubs** keep query strings and hashes. Do not delete them.
- **Secrets** never appear in code, docs or logs.
