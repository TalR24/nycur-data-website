# NYCuriosity Data

**[data.nycuriosity.com](https://data.nycuriosity.com)**

A companion site to [NYCuriosity](https://nycuriosity.substack.com), a Substack publication covering NYC urban policy, transit, infrastructure, and street design. The site hosts two types of content: **civic reference tools** (standalone interactive explorers) and **post data pages** (charts and tables tied to specific Substack articles).

---

## Civic Reference

Standalone reference tools, listed in homepage order. New tools live under `/civic_reference/`; the CB Resolutions Dashboard predates that convention and is served from `/cb-resolutions/`.

### [State Capacity Ecosystem](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/)
Directory, segment view, affinity network, and matchmaking for 300+ organizations working on state capacity — research, advocacy, GovTech, philanthropy, fellowships, digital services, investors, and ecosystem-builders. Underlying database curated by Henry Grunzweig. Affinity score combines description TF-IDF, shared problem statements, named funders, and segment overlap, with semantic search powered by a precomputed TF-IDF index.

- [`/civic_reference/state_capacity_ecosystem/`](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/) — hub
- [`/civic_reference/state_capacity_ecosystem/directory/`](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/directory/) — searchable, filterable org table
- [`/civic_reference/state_capacity_ecosystem/network/`](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/network/) — D3 force-directed affinity graph + semantic search with geographic boosting
- [`/civic_reference/state_capacity_ecosystem/connect/`](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/connect/) — directory of people and orgs working on specific problems, with self-submission form and intro request flow
- [`/civic_reference/state_capacity_ecosystem/methodology/`](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/methodology/) — scoring formula, taxonomy, inclusion criteria

### [NYC Council Fiscal Impacts Tracker](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/)
Estimated fiscal impact of every NYC Council bill with a Finance Division impact statement. Filterable by agency, committee, sponsor, and fiscal year, with cost/revenue/capital breakdowns and per-bill detail panels.

- [`/civic_reference/nyc_council_fiscal_impacts_tracker/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/) — bill table
- [`/civic_reference/nyc_council_fiscal_impacts_tracker/agency-fiscal-impact/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/agency-fiscal-impact/) — fiscal impact by agency
- [`/civic_reference/nyc_council_fiscal_impacts_tracker/sponsor-fiscal-impact/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/sponsor-fiscal-impact/) — fiscal impact by sponsor
- [`/civic_reference/nyc_council_fiscal_impacts_tracker/intro-year-impact/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/intro-year-impact/) — by year legislated
- [`/civic_reference/nyc_council_fiscal_impacts_tracker/cost-revenue-breakdown/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/cost-revenue-breakdown/) — costs vs. revenue
- [`/civic_reference/nyc_council_fiscal_impacts_tracker/methodology/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/methodology/) — methodology

### [NYC Government Bodies Explorer](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/)
Browse all ~80 NYC government bodies — agencies, elected offices, DA offices, authorities, and boards — with FY2025 Adopted Budget and headcount data. Searchable card grid with inline detail panels and a D3.js treemap sized by budget or headcount, with sector-level filtering.

- [`/civic_reference/nyc-gov-bodies-explorer/`](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/) — main explorer (card grid + treemap)
- [`/civic_reference/nyc-gov-bodies-explorer/methodology/`](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/methodology/) — data sources, definitions, and known limitations

### [NYC CB Resolutions Dashboard](https://data.nycuriosity.com/cb-resolutions/)
Search and visualize 11,000+ resolutions from Manhattan Community Boards 2 and 3 (817 meetings, 2002–2025). Filter by board, search full text, and compare topic and agency mentions side-by-side.

- [`/cb-resolutions/`](https://data.nycuriosity.com/cb-resolutions/) — hub page
- [`/cb-resolutions/explorer/`](https://data.nycuriosity.com/cb-resolutions/explorer/) — full-text search and browse across all resolutions, filterable by board
- [`/cb-resolutions/resolutions-per-year/`](https://data.nycuriosity.com/cb-resolutions/resolutions-per-year/) — annual resolution volume over time
- [`/cb-resolutions/top-agencies/`](https://data.nycuriosity.com/cb-resolutions/top-agencies/) — most frequently addressed city agencies
- [`/cb-resolutions/top-topics/`](https://data.nycuriosity.com/cb-resolutions/top-topics/) — most common resolution topics

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
- [Google Fonts](https://fonts.google.com/) — Roboto Mono, Inter

**Legacy redirects:** the Fiscal Impacts Tracker and Gov Bodies Explorer originally lived at top-level paths. The old folders (`/nyc_council_fiscal_impacts_tracker/`, `/nyc-gov-bodies-explorer/`) now contain only meta-refresh redirect stubs that preserve query strings and hashes — keep them so old links keep working.

---

## Repo Structure

```
/                                                  → Hub homepage (index.html)
├── favicon.svg, website_logo.png, CNAME
├── robots.txt, sitemap.xml                        → SEO (update sitemap when adding pages)
│
├── .github/workflows/                             → Scheduled data refresh workflows (see below)
│
├── pipeline/                                      → Fiscal impacts data pipeline (Python)
│   ├── fetch_fiscal_impacts.py                    → Incremental Legistar fetch + Claude extraction
│   ├── fetch_fiscal_impacts_historical.py         → Historical backfill (2014–2023)
│   └── requirements.txt
│
├── civic_reference/                               → Standalone interactive tools
│   ├── state_capacity_ecosystem/
│   │   ├── index.html                             → Hub (explainer, stat pills, view cards)
│   │   ├── README.md                              → Full project reference doc
│   │   ├── data/
│   │   │   ├── directory.csv                      → Canonical org source (306 rows)
│   │   │   ├── connect_submissions.csv            → Connect directory seed data
│   │   │   ├── build_affinity.py                  → directory.csv → affinity/directory/search JSON
│   │   │   ├── build_people.py                    → connect_submissions.csv → connect.json
│   │   │   ├── update_stats.py                    → Patches hardcoded stat strings after rebuild
│   │   │   ├── notify_new_connect.py              → Emails new Connect entries
│   │   │   └── *.json                             → Generated data bundles
│   │   ├── directory/  network/  connect/  methodology/
│   ├── nyc_council_fiscal_impacts_tracker/
│   │   ├── index.html                             → Bill table
│   │   ├── PIPELINE_REFERENCE.md                  → Pipeline + schema reference
│   │   ├── data/fiscal_impacts.json               → Master data file (written by pipeline/)
│   │   ├── agency-fiscal-impact/  sponsor-fiscal-impact/  intro-year-impact/
│   │   └── cost-revenue-breakdown/  methodology/
│   └── nyc-gov-bodies-explorer/
│       ├── index.html                             → Card grid + D3 treemap
│       └── methodology/
│
├── cb-resolutions/                                → CB Resolutions Dashboard (MCB2 + MCB3)
│   ├── index.html                                 → Hub page
│   ├── cb-filter.css, cb-filter.js                → Shared board-filter UI
│   ├── data/                                      → full_resolutions.csv + chart CSVs
│   ├── explorer/  resolutions-per-year/  top-agencies/  top-topics/
│
├── nycuriosity_substack_posts/                    → Charts and tables tied to Substack posts
│   ├── queensway_vs_queenslink/
│   ├── mamdani_100_days/
│   ├── mcb3_history_analysis/
│   ├── cso_reports_2026/
│   └── streets_plan_2026/
│
├── nyc_council_fiscal_impacts_tracker/            → Redirect stubs (old URL — do not delete)
└── nyc-gov-bodies-explorer/                       → Redirect stubs (old URL — do not delete)
```

New post data projects follow the pattern described in `CLAUDE.md` and `visualization-style-guide/SKILL.md` (in the parent research repo): hub page at `nycuriosity_substack_posts/<folder>/index.html`, individual chart subpages in subdirectories, source CSVs in `data/`. New civic reference tools follow the same pattern under `civic_reference/<tool>/`.

---

## GitHub Actions

Two scheduled workflows run in `.github/workflows/`:

| Workflow | Schedule | What it does |
|---|---|---|
| `refresh_state_capacity.yml` | 6 AM ET daily | Detects changes to `directory.csv` (rebuilds org JSON + patches stat strings) and `connect_submissions.csv` (rebuilds connect.json + emails new entries) independently. Requires `GMAIL_USER` and `GMAIL_APP_PASSWORD` secrets. |
| `refresh_fiscal_data.yml` | 1st of each month, 7 AM UTC | Fetches new fiscal impact statements from NYC Legistar, runs Claude extraction (`pipeline/fetch_fiscal_impacts.py`), and commits the updated `civic_reference/nyc_council_fiscal_impacts_tracker/data/fiscal_impacts.json`. Requires `ANTHROPIC_API_KEY` secret. |

Both workflows require the repo's **Workflow permissions** set to "Read and write permissions" (Settings → Actions → General) so `GITHUB_TOKEN` can push commits.
