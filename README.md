# NYCuriosity Data

> **Brand values (palette, fonts, logos) are defined in the `nycuriosity-brand` skill and `data_website/assets/brand.css`, not here.** This README describes structure and workflow.

**[data.nycuriosity.com](https://data.nycuriosity.com)**

A companion site to [NYCuriosity](https://www.nycuriosity.com), a Substack publication covering NYC urban policy, transit, infrastructure, and street design. The site hosts two types of content: **civic reference tools** (standalone interactive explorers) and **post data pages** (charts and tables tied to specific Substack articles).

---

## ⚠️ Premium data paywall (members-only tools)

The **NYC CB Resolutions Dashboard** is **paywalled** (launched Jul 2026); its public URL here serves a **teaser page** and the working tool lives on a separate **private** origin, alongside the member tools (Ask the Trackers, alerts, district briefs, watchlist). The NYC Council Fiscal Impacts Tracker was paywalled from Jul 5 to Jul 18 2026 and has been free since. On Sep 24 2026 the Legislation Trackers dropped all data downloads, members included (see the Legislation Trackers section).

- **Real tools live in the PRIVATE repo** `TalR24/nycur-data-premium` → Cloudflare Worker (static assets) → **`premium.nycuriosity.com`**, gated by **Cloudflare Access** (email one-time-PIN + allowlist). **Never put these tools' data back in this public repo** — that bypasses the paywall.
- **Public side (this repo):** `cb-tools/block-party/index.html` is the **teaser page** for the resolutions dashboard (premium gate). `cb-resolutions/index.html` is now a redirect stub to `/cb-tools/`, the free Community Board tools hub (member tracker, meeting review, Robert's Rules helper, board scorecard). All the dashboard's subpages + CSV/JSON were removed from this repo.
- **Access is manual:** when someone subscribes on Buy Me a Coffee, add their email in Cloudflare Zero Trust → Access → the app → policy **"NYCuriosity Premium"** → Emails; remove on cancellation.
- **cb-tools/block-party teaser stats are HARDCODED.** When boards/resolutions are added to the database (done in other sessions), bump the `.stat-pills` + hero copy in `cb-tools/block-party/index.html` **and** the CB card in `index.html`.
- **SEO:** teasers stay indexable (marketing); the premium origin is `noindex`/robots-disallowed. Keep `sitemap.xml` free of the removed gated subpages — it should list only the two teaser hubs, not their old subpages.

Full architecture, deploy steps, and the approved Buy Me a Coffee copy are in the **private repo's README** (`nycur-data-premium/README.md`).

---

## Civic Reference

Standalone reference tools, listed in homepage order. New tools live under `/civic_reference/`; the CB Resolutions Dashboard predates that convention and is served from `/cb-tools/block-party/` (renamed from `/cb-resolutions/`, which is now a redirect stub).

### [State Capacity Ecosystem](https://statecapacityecosystem.com/)
Directory, segment view, affinity network, and matchmaking for 300+ organizations working on state capacity — research, advocacy, GovTech, philanthropy, fellowships, digital services, investors, and ecosystem-builders. Underlying database curated by Henry Grunzweig. Affinity score combines description TF-IDF, shared problem statements, named funders, and segment overlap, with semantic search powered by a precomputed TF-IDF index.

- [`/state_capacity_ecosystem/`](https://statecapacityecosystem.com/) — hub
- [`/state_capacity_ecosystem/ecosystem/directory/`](https://statecapacityecosystem.com/ecosystem/organizations/) — searchable, filterable org table
- [`/state_capacity_ecosystem/ecosystem/network/`](https://statecapacityecosystem.com/ecosystem/affinity-map/) — D3 force-directed affinity graph + semantic search with geographic boosting
- [`/state_capacity_ecosystem/ecosystem/connect/`](https://statecapacityecosystem.com/ecosystem/connect/) — directory of people and orgs working on specific problems, with self-submission form and intro request flow
- [`/state_capacity_ecosystem/ecosystem/methodology/`](https://statecapacityecosystem.com/ecosystem/methodology/) — scoring formula, taxonomy, inclusion criteria
- [`/state_capacity_ecosystem/policy-programs/events/`](https://statecapacityecosystem.com/events/) — state capacity hackathons, with per-event pages covering overview, tracks, judges, and the projects produced (e.g. `events/civic-tech-build-night/`)

### [NYC Council Legislation Trackers](https://data.nycuriosity.com/civic_reference/nyc_council_legislation_trackers/)
Three free trackers of what NYC local laws since 2014 cost, require and allow, plus council member and agency profiles and a Law Explorer. No data downloads.
- **[Fiscal Impacts Tracker](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/)**: every Council bill with a Finance Division fiscal impact statement, by agency, sponsor, committee and year. Pipeline: `pipeline/fetch_fiscal_impacts.py`; refreshed by `refresh_fiscal_data.yml`.
- **[Obligations Tracker](https://data.nycuriosity.com/civic_reference/legislation_implementation_tracker/)**: the duties each enacted local law gives city agencies, with deadlines and each required report's filing status from DORIS.
- **[Powers Tracker](https://data.nycuriosity.com/civic_reference/legislation_implementation_tracker/powers/)**: the powers those laws grant agencies (rulemaking, permits, enforcement).
- Pipelines: `civic_reference/legislation_implementation_tracker/pipeline/` and `civic_reference/nyc_council_legislation_trackers/pipeline/`; refreshed by `refresh_implementation_data.yml`. One-off model runs go through `claude_backfill.yml`.

Concept credit: the Obligations Tracker adapts the implementation-checklist approach Marci Dale prototyped for federal legislation in ["What if every new law came with a checklist?"](https://marcidale.substack.com/p/what-if-every-new-law-came-with-a).

### [NYC Government Bodies Explorer](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/)
Browse all ~80 NYC government bodies — agencies, elected offices, DA offices, authorities, and boards — with FY2025 Adopted Budget and headcount data. Searchable card grid with inline detail panels and a D3.js treemap sized by budget or headcount, with sector-level filtering.

- [`/civic_reference/nyc-gov-bodies-explorer/`](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/) — main explorer (card grid + treemap)
- [`/civic_reference/nyc-gov-bodies-explorer/methodology/`](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/methodology/) — data sources, definitions, and known limitations

### [NYC CB Resolutions Dashboard](https://data.nycuriosity.com/cb-tools/block-party/)
Full-text search and visualization of resolutions across seven of Manhattan's Community Boards (2002–2026). Filter by board, search full text, and compare topic and agency mentions side-by-side.

**🔒 Members-only** (see the Premium data paywall section above). `cb-resolutions/` is now a redirect stub to `/cb-tools/`; the dashboard teaser is `/cb-tools/block-party/`, and the working dashboard and its subpages (explorer, resolutions-per-year, top-agencies, top-topics) live in the private `nycur-data-premium` repo at `premium.nycuriosity.com`. *Board and resolution counts grow over time and the teaser stats are hardcoded — update them when the database expands.*

---

## Substack Post Data

Each post folder lives under `/nycuriosity_substack_posts/` and contains a hub page linking to individual chart subpages, with source CSVs in `data/`. Listed newest first.

### [QueensWay vs QueensLink](https://data.nycuriosity.com/nycuriosity_substack_posts/queensway_vs_queenslink/)
Side-by-side comparison of the QueensLink M-train extension proposal and the MTA's 2018 Rockaway Beach Branch sketch assessment. Ridership, costs, timeline, and methodology.

- [`/comparison-table/`](https://data.nycuriosity.com/nycuriosity_substack_posts/queensway_vs_queenslink/comparison-table/) — 22-metric comparison across capital cost, ridership, environmental impact, and timeline
- [`/further-facts/`](https://data.nycuriosity.com/nycuriosity_substack_posts/queensway_vs_queenslink/further-facts/) — supporting facts and source citations

### [Mamdani's First 100 Days](https://data.nycuriosity.com/nycuriosity_substack_posts/mamdani_100_days/)
Data and charts from NYCuriosity's coverage of the April 7, 2026 Mamdani transition team panel: Rikers capacity, transit corridors, school funding, and DOT progress.

- [`/rikers-population/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mamdani_100_days/rikers-population/) — Rikers ADP trend vs. capacity
- [`/better-billion-corridors/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mamdani_100_days/better-billion-corridors/) — Better Buses billion-dollar corridor investments
- [`/dot-lane-progress/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mamdani_100_days/dot-lane-progress/) — DOT bike and bus lane installation progress
- [`/school-funding/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mamdani_100_days/school-funding/) — DOE school funding shifts

### [MCB3 History Analysis](https://data.nycuriosity.com/nycuriosity_substack_posts/mcb3_history_analysis/)
Charts comparing MCB3 resolution patterns with 311 complaint data for Community District 3.

- [`/agencies-comparison/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mcb3_history_analysis/agencies-comparison/) — MCB3 resolution targets vs. 311 complaint recipients by agency
- [`/topics-comparison/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mcb3_history_analysis/topics-comparison/) — resolution topics vs. 311 complaint categories
- [`/topics-over-time/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mcb3_history_analysis/topics-over-time/) — MCB3 topic trends over time
- [`/311-vs-resolutions/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mcb3_history_analysis/311-vs-resolutions/) — 311 volume vs. resolution volume over time

### [CSO Reports 2026](https://data.nycuriosity.com/nycuriosity_substack_posts/cso_reports_2026/)
Data and charts from NYCuriosity's analysis of NYC's Chief Savings Officer agency savings plans for FY2026 and FY2027.

- [`/agency-breakdown/`](https://data.nycuriosity.com/nycuriosity_substack_posts/cso_reports_2026/agency-breakdown/) — savings by agency
- [`/savings-by-category/`](https://data.nycuriosity.com/nycuriosity_substack_posts/cso_reports_2026/savings-by-category/) — savings by type of action
- [`/ibo-comparison/`](https://data.nycuriosity.com/nycuriosity_substack_posts/cso_reports_2026/ibo-comparison/) — CSO savings vs. IBO-identified budget options
- [`/nyc-tax-rates/`](https://data.nycuriosity.com/nycuriosity_substack_posts/cso_reports_2026/nyc-tax-rates/) — NYC tax rate reference table

### [Streets Plan 2026 — Local Law 195](https://data.nycuriosity.com/nycuriosity_substack_posts/streets_plan_2026/)
Data and charts from NYCuriosity's analysis of NYC's 10-year streets master plan (Local Law 195 / Intro 1557-A), including fiscal impact and mandate compliance tracking.

- [`/fiscal-impact/`](https://data.nycuriosity.com/nycuriosity_substack_posts/streets_plan_2026/fiscal-impact/) — FY2025–FY2030 fiscal impact by year
- [`/program-breakdown/`](https://data.nycuriosity.com/nycuriosity_substack_posts/streets_plan_2026/program-breakdown/) — cost breakdown by program type
- [`/ll195-mandates/`](https://data.nycuriosity.com/nycuriosity_substack_posts/streets_plan_2026/ll195-mandates/) — statutory mandates table
- [`/compliance/`](https://data.nycuriosity.com/nycuriosity_substack_posts/streets_plan_2026/compliance/) — compliance status by mandate

---

## Tech

Static site hosted on GitHub Pages at a custom domain (`data.nycuriosity.com`). No backend. Each project is a self-contained directory with an `index.html` that loads and renders data client-side. All forms (self-submission, intro requests) submit via `mailto:` with pre-filled subject/body + clipboard copy fallback — no server required.

**Libraries used:**
- [D3.js v7](https://d3js.org/) — treemap (Gov Bodies) and force-directed graph (State Capacity)
- [Chart.js](https://www.chartjs.org/) — bar and line charts (post data pages)
- [PapaParse](https://www.papaparse.com/) — client-side CSV parsing
- [html2canvas](https://html2canvas.hertzen.com/) — Download PNG buttons on chart pages
- [Google Fonts](https://fonts.google.com/) — Playfair Display, JetBrains Mono, Inter (Helvetica fallback)

**Legacy redirects:** the Fiscal Impacts Tracker and Gov Bodies Explorer originally lived at top-level paths, and the State Capacity Ecosystem originally lived under `/civic_reference/`. The old folders (`/nyc_council_fiscal_impacts_tracker/`, `/nyc-gov-bodies-explorer/`, `/civic_reference/state_capacity_ecosystem/` and its subpages) now contain only meta-refresh redirect stubs that preserve query strings and hashes — keep them so old links keep working.

### Site chrome & shared components

CSS is **inline per-page** (no shared stylesheet), so shared components are duplicated into each page. When adding a new page or tool, replicate the header and footer below.

- **Header** — dark (`--b-surface-dark` (#170C03)). Brand (`nycuriosity / data`) on the left; a `.header-actions` flex row on the right holds outlined `.header-link` pills (**About** → `https://talroded.nycuriosity.com`, **Substack**) and the `.support-link` pill.
- **Footer** — white (`var(--surface)`, `#ffffff`). A `.footer-links` row of text links with a `.footer-support` pill.
- **Buy Me a Coffee** — every page links to `https://buymeacoffee.com/nycuriosity`, label **"Support my work"**, coffee-cup icon, `target="_blank"`. Present in both header and footer.
- **Palette per surface** — the pill color depends on its background: on the dark header use `.support-link` (light-blue text ``--b-on-dark` (Marigold)`); on the white footer use `.footer-support` (blue text ``--b-tangerine-deep` (#C84609)`). Both fill solid blue (``--b-tangerine-deep` (#C84609)`) with white text on hover. Do not put the light-blue `.support-link` on a white surface — it fails contrast.
- **Footer alignment** — `.footer-links` must include `align-items: center`, otherwise the padded pill sits misaligned with the plain text links.
- **Reusable button CSS** on subpages is injected in a single `<style id="support-btn-css">` block before `</head>`.

Page types and how the button attaches:
- **Hub pages** (brand + `.header-link`) → header pills **and** footer pill.
- **Post/hub pages** with a `.footer-links` container → footer pill.
- **Inline `·`-separated footers** (cb-resolutions, mcb3 topics charts) → a plain inline "Support my work" link matching the sibling text links (no pill).
- **Skip:** the 32 meta-refresh redirect stubs; and chrome-less pages that have no header/footer — `civic_reference/cb_member_guide/{index,handout}.html` and `state_capacity_ecosystem/policy-programs/events/civic-tech-build-night/tideline/` (add a footer first if these ever need the button).

---

## Repo Structure

```
/                                                  → Hub homepage (index.html)
├── favicon.svg, website_logo.png, CNAME
├── robots.txt, sitemap.xml                        → SEO (update sitemap when adding pages)
│
├── .github/workflows/                             → Scheduled data refresh workflows (see below)
│
├── state_capacity_ecosystem/                      → SCE tool (top-level since Jul 2026;
│   │                                                old /civic_reference/ URLs redirect)
│   ├── index.html                                 → Hub (explainer, stat pills, view cards)
│   ├── README.md                                  → Full project reference doc
│   ├── data/
│   │   ├── directory.csv                          → moved to TalR24/statecapacityecosystem
│   │   ├── connect_submissions.csv                → Connect directory seed data
│   │   ├── build_affinity.py                      → directory.csv → affinity/directory/search JSON
│   │   ├── build_people.py                        → connect_submissions.csv → connect.json
│   │   ├── update_stats.py                        → Patches hardcoded stat strings after rebuild
│   │   ├── notify_new_connect.py                  → Emails new Connect entries
│   │   └── *.json                                 → Generated data bundles
│   ├── directory/  network/  connect/  methodology/
│   ├── substack/                                  → Posts hub + companion prototypes
│   └── events/                                    → Hackathons hub + per-event pages
│       ├── index.html                             → Events hub (event cards)
│       └── civic-tech-build-night/                → Event page + projects (incl. rehosted
│                                                    TIDELINE dashboard under tideline/)
│
├── pipeline/                                       → Fiscal Impacts Tracker pipeline (fetch, agency
│                                                    canon, regenerate_agency_data.py; see PIPELINE_REFERENCE.md)
│
├── civic_reference/                               → Standalone interactive tools
│   ├── cb_member_guide/                           → CB member field guide (slide deck + handout)
│   ├── nyc_council_fiscal_impacts_tracker/        → Free tool: overview/, data/, methodology/
│   │   ├── index.html                             → Fiscal Impacts Tracker (free since Jul 18 2026)
│   │   └── PIPELINE_REFERENCE.md                  → Pipeline + schema reference
│   ├── legislation_implementation_tracker/        → Obligations + Powers trackers, methodology, pipeline/
│   ├── nyc_council_legislation_trackers/          → Shared Law Explorer, member/agency profiles, pipeline/
│   └── nyc-gov-bodies-explorer/
│       ├── index.html                             → Card grid + D3 treemap
│       └── methodology/
│
├── cb-tools/                                      → CB Resolutions Dashboard + explorer, member-tracker,
│                                                    Block Party maps, and related CB tools
├── cb-resolutions/                                → Redirect stub → /cb-tools/ (old URL — do not delete)
│
├── nycuriosity_substack_posts/                    → Charts and tables tied to Substack posts
│   ├── state_capacity_ai/
│   ├── nyc_building_strategies/
│   ├── cso_reports_2026/
│   ├── mamdani_100_days/
│   ├── queensway_vs_queenslink/
│   ├── mcb3_history_analysis/
│   └── streets_plan_2026/
│
├── nyc_council_fiscal_impacts_tracker/            → Redirect stubs (old URL — do not delete)
└── nyc-gov-bodies-explorer/                       → Redirect stubs (old URL — do not delete)
```

New post data projects follow the pattern described in `CLAUDE.md` and `visualization-style-guide/SKILL.md` (in the parent research repo): hub page at `nycuriosity_substack_posts/<folder>/index.html`, individual chart subpages in subdirectories, source CSVs in `data/`. New civic reference tools follow the same pattern under `civic_reference/<tool>/`.

---

## GitHub Actions

Nine workflows live in `.github/workflows/`:

| Workflow | Schedule | What it does |
|---|---|---|
| `refresh_fiscal_data.yml` | 1st of each month, 11:23 UTC | Fetches new Council fiscal impact statements and rebuilds the Fiscal Impacts Tracker data. |
| `refresh_implementation_data.yml` | 1st of each month, 14:40 UTC (3h+ after the fiscal refresh, so alerts, the Ask index and member/agency profiles read that month's fiscal data) | Fetches newly enacted laws, re-extracts queued laws, rebuilds obligations/powers/member/agency data, sends member alerts, and rebuilds the Ask index. |
| `claude_backfill.yml` | Manual only | One-off Anthropic API tasks: schema canary, duty/power labeling, the full re-extraction backfill, and model pilots. |
| `monthly_quality_report.yml` | 3rd of each month, 14:00 UTC | Runs the tracker validators and emails a quality report. |
| `opportunity_monitor.yml` | Saturdays, 12:00 UTC | Scans for outreach or coverage opportunities. |
| `mention_monitor.yml` | Daily, 11:30 UTC | Watches for new mentions of NYCuriosity; sends a Sunday digest. |
| `refresh_cb_member_data.yml` | 5th of each month, 11:23 UTC | Refreshes Community Board member tracker data. |
| `seo_monthly.yml` | 2nd of each month, 12:00 UTC | Builds the monthly SEO report. |
| `site_health.yml` | Mondays, 11:00 UTC | Checks site health. |

Workflows require the repo's **Workflow permissions** set to "Read and write permissions" (Settings → Actions → General) so `GITHUB_TOKEN` can push commits.
