# NYCuriosity Data

**[data.nycuriosity.com](https://data.nycuriosity.com)**

A companion site to [NYCuriosity](https://nycuriosity.substack.com), a Substack publication covering NYC urban policy, transit, infrastructure, and street design. The site hosts three types of content: **civic reference tools** (standalone interactive explorers), **Community Board 3 resolutions data** (a separate corpus with its own toolkit), and **post data pages** (charts and tables tied to specific Substack articles).

---

## Civic Reference

All standalone reference tools live under `/civic_reference/`.

### [NYC Government Bodies Explorer](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/)
Browse all ~80 NYC government bodies — agencies, elected offices, DA offices, authorities, and boards — with FY2025 Adopted Budget and headcount data. Searchable card grid with inline detail panels and a D3.js treemap sized by budget or headcount, with sector-level filtering.

- [`/civic_reference/nyc-gov-bodies-explorer/`](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/) — main explorer (card grid + treemap)
- [`/civic_reference/nyc-gov-bodies-explorer/methodology/`](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/methodology/) — data sources, definitions, and known limitations

### [NYC Council Fiscal Impacts Tracker](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/)
Estimated fiscal impact of every NYC Council bill with a Finance Division impact statement. Filterable by agency, committee, sponsor, and fiscal year, with cost/revenue/capital breakdowns and per-bill detail panels. Data is refreshed monthly via the pipeline scripts in `/pipeline/`.

- [`/civic_reference/nyc_council_fiscal_impacts_tracker/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/) — bill table
- [`/civic_reference/nyc_council_fiscal_impacts_tracker/agency-fiscal-impact/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/agency-fiscal-impact/) — fiscal impact by agency
- [`/civic_reference/nyc_council_fiscal_impacts_tracker/sponsor-fiscal-impact/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/sponsor-fiscal-impact/) — fiscal impact by sponsor
- [`/civic_reference/nyc_council_fiscal_impacts_tracker/intro-year-impact/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/intro-year-impact/) — by year legislated
- [`/civic_reference/nyc_council_fiscal_impacts_tracker/cost-revenue-breakdown/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/cost-revenue-breakdown/) — costs vs. revenue
- [`/civic_reference/nyc_council_fiscal_impacts_tracker/methodology/`](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/methodology/) — methodology

### [State Capacity Ecosystem](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/)
Directory and affinity network of 225 organizations working on state capacity — research, advocacy, GovTech, philanthropy, fellowships, digital services, and investors. Underlying database curated by Henry Tolchard. Affinity score is a composite of description TF-IDF, segment overlap, and named-funder overlap.

- [`/civic_reference/state_capacity_ecosystem/`](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/) — hub (explainer, stat pills, segment-distribution chart)
- [`/civic_reference/state_capacity_ecosystem/directory/`](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/directory/) — searchable, filterable org table
- [`/civic_reference/state_capacity_ecosystem/network/`](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/network/) — D3 force-directed affinity graph
- [`/civic_reference/state_capacity_ecosystem/methodology/`](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/methodology/) — scoring formula, weight rationale, and data notes

---

## CB3 Resolutions

### [CB3 Resolutions Explorer](https://data.nycuriosity.com/cb3-resolutions/)
Hub page for Manhattan Community Board 3 resolution data, covering 7,100+ resolutions from 2002–2025.

- [`/cb3-resolutions/explorer/`](https://data.nycuriosity.com/cb3-resolutions/explorer/) — full-text search and browse across all resolutions
- [`/cb3-resolutions/resolutions-per-year/`](https://data.nycuriosity.com/cb3-resolutions/resolutions-per-year/) — annual resolution volume over time
- [`/cb3-resolutions/top-agencies/`](https://data.nycuriosity.com/cb3-resolutions/top-agencies/) — most frequently addressed city agencies
- [`/cb3-resolutions/top-topics/`](https://data.nycuriosity.com/cb3-resolutions/top-topics/) — most common resolution topics

---

## Substack Post Data

Each post folder lives under `/nycuriosity_substack_posts/` and contains a hub page linking to individual chart subpages.

### [Mamdani's First 100 Days](https://data.nycuriosity.com/nycuriosity_substack_posts/mamdani_100_days/)
Data and charts from NYCuriosity's coverage of the April 7, 2026 Mamdani transition team panel: Rikers capacity, transit corridors, school funding, and DOT progress.

- [`/rikers-population/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mamdani_100_days/rikers-population/) — Rikers ADP trend vs. capacity
- [`/better-billion-corridors/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mamdani_100_days/better-billion-corridors/) — Better Buses billion-dollar corridor investments
- [`/dot-lane-progress/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mamdani_100_days/dot-lane-progress/) — DOT bike and bus lane installation progress
- [`/school-funding/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mamdani_100_days/school-funding/) — DOE school funding shifts

### [QueensWay vs QueensLink](https://data.nycuriosity.com/nycuriosity_substack_posts/queensway_vs_queenslink/)
Side-by-side comparison of the QueensLink M-train extension proposal and the MTA's 2018 Rockaway Beach Branch sketch assessment. Ridership, costs, timeline, and methodology.

- [`/comparison-table/`](https://data.nycuriosity.com/nycuriosity_substack_posts/queensway_vs_queenslink/comparison-table/) — 22-metric comparison across capital cost, ridership, environmental impact, and timeline
- [`/further-facts/`](https://data.nycuriosity.com/nycuriosity_substack_posts/queensway_vs_queenslink/further-facts/) — supporting facts and source citations

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

## Pipelines

Reusable Python scripts that refresh data feeding the live tools.

- `pipeline/fetch_fiscal_impacts.py` — pulls newly-posted Council bill fiscal impact statements from NYC Legistar and writes them to `civic_reference/nyc_council_fiscal_impacts_tracker/data/fiscal_impacts.json`.
- `pipeline/fetch_fiscal_impacts_historical.py` — one-shot historical backfill for the same dataset.
- `civic_reference/state_capacity_ecosystem/data/build_affinity.py` — recomputes the affinity graph and directory bundle from a refreshed CSV.

Detailed notes for the fiscal impacts pipeline live in `civic_reference/nyc_council_fiscal_impacts_tracker/PIPELINE_REFERENCE.md`.

---

## Tech

Static site hosted on GitHub Pages at a custom domain (`data.nycuriosity.com`). No backend. Each project is a self-contained directory with an `index.html` that loads and renders data client-side.

**Libraries used:**
- [D3.js v7](https://d3js.org/) — treemap (Gov Bodies) and force-directed graph (State Capacity)
- [Chart.js](https://www.chartjs.org/) — bar and line charts (post data pages)
- [PapaParse](https://www.papaparse.com/) — client-side CSV parsing
- [Google Fonts](https://fonts.google.com/) — Roboto Mono, Inter

---

## Repo Structure

```
/                                                  → Hub homepage (index.html)
├── favicon.svg, website_logo.png, CNAME
├── full_resolutions.csv                           → CB3 source corpus (used by /cb3-resolutions/)
│
├── civic_reference/                               → Standalone interactive tools
│   ├── nyc-gov-bodies-explorer/
│   │   ├── index.html                             → Card grid + D3 treemap
│   │   └── methodology/
│   ├── nyc_council_fiscal_impacts_tracker/
│   │   ├── index.html                             → Bill table
│   │   ├── data/fiscal_impacts.json               → Output of pipeline/fetch_fiscal_impacts.py
│   │   ├── PIPELINE_REFERENCE.md
│   │   ├── agency-fiscal-impact/
│   │   ├── sponsor-fiscal-impact/
│   │   ├── intro-year-impact/
│   │   ├── cost-revenue-breakdown/
│   │   └── methodology/
│   └── state_capacity_ecosystem/
│       ├── index.html                             → Hub (explainer, stat pills, segment chart)
│       ├── data/
│       │   ├── build_affinity.py                  → CSV → graph.json + orgs.json
│       │   ├── state_capacity_ecosystem.csv       → Source data (225 rows)
│       │   ├── graph.json                         → Nodes + affinity edges
│       │   └── orgs.json                          → Flat directory bundle
│       ├── directory/                             → Searchable / filterable table
│       ├── network/                               → D3 force-directed graph
│       └── methodology/                           → Scoring formula and notes
│
├── cb3-resolutions/                               → Manhattan CB3 resolutions corpus + tools
│   ├── index.html                                 → Hub page
│   ├── data/
│   ├── explorer/                                  → Full-text search + browse
│   ├── resolutions-per-year/
│   ├── top-agencies/
│   └── top-topics/
│
├── nycuriosity_substack_posts/                    → Charts and tables tied to Substack posts
│   ├── mamdani_100_days/
│   │   ├── rikers-population/
│   │   ├── better-billion-corridors/
│   │   ├── dot-lane-progress/
│   │   └── school-funding/
│   ├── queensway_vs_queenslink/
│   │   ├── comparison-table/
│   │   └── further-facts/
│   ├── mcb3_history_analysis/
│   │   ├── agencies-comparison/
│   │   ├── topics-comparison/
│   │   ├── topics-over-time/
│   │   └── 311-vs-resolutions/
│   ├── cso_reports_2026/
│   │   ├── agency-breakdown/
│   │   ├── savings-by-category/
│   │   ├── ibo-comparison/
│   │   └── nyc-tax-rates/
│   └── streets_plan_2026/
│       ├── fiscal-impact/
│       ├── program-breakdown/
│       ├── ll195-mandates/
│       └── compliance/
│
├── pipeline/                                      → Data refresh scripts
│   ├── fetch_fiscal_impacts.py                    → Monthly Legistar pull
│   ├── fetch_fiscal_impacts_historical.py         → One-shot backfill
│   └── cache/                                     → Local cache for fetched docs
│
└── nyc_council_fiscal_impacts_tracker/, nyc-gov-bodies-explorer/
    → Redirect stubs at the pre-move URLs (meta-refresh + JS replace),
      kept so existing external links and bookmarks don't 404.
```

New post data projects follow the pattern described in `CLAUDE.md`: hub page at `nycuriosity_substack_posts/<folder>/index.html`, individual chart subpages in subdirectories, source CSVs in `data/`. New civic reference tools follow the same pattern under `civic_reference/<tool>/`.
