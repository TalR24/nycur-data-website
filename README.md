# NYCuriosity Data

**[data.nycuriosity.com](https://data.nycuriosity.com)**

A companion site to [NYCuriosity](https://nycuriosity.substack.com), a Substack publication covering NYC urban policy, transit, infrastructure, and street design. The site hosts two types of content: **civic reference tools** (standalone interactive explorers) and **post data pages** (charts and tables tied to specific articles).

---

## Civic Reference

### [NYC Government Bodies Explorer](https://data.nycuriosity.com/nyc-gov-bodies-explorer/)
Browse all ~80 NYC government bodies — agencies, elected offices, DA offices, authorities, and boards — with FY2025 Adopted Budget and headcount data. Features a searchable card grid with inline detail panels and a D3.js treemap sized by budget or headcount, with sector-level filtering.

- [`/nyc-gov-bodies-explorer/`](https://data.nycuriosity.com/nyc-gov-bodies-explorer/) — main explorer (card grid + treemap)
- [`/nyc-gov-bodies-explorer/methodology/`](https://data.nycuriosity.com/nyc-gov-bodies-explorer/methodology/) — data sources, definitions, and known limitations

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

### [Streets Plan 2026 — Local Law 195](https://data.nycuriosity.com/nycuriosity_substack_posts/streets_plan_2026/)
Data and charts from NYCuriosity's analysis of NYC's 10-year streets master plan (Local Law 195 / Intro 1557-A), including fiscal impact and mandate compliance tracking.

- [`/fiscal-impact/`](https://data.nycuriosity.com/nycuriosity_substack_posts/streets_plan_2026/fiscal-impact/) — FY2025–FY2030 fiscal impact by year
- [`/program-breakdown/`](https://data.nycuriosity.com/nycuriosity_substack_posts/streets_plan_2026/program-breakdown/) — cost breakdown by program type
- [`/ll195-mandates/`](https://data.nycuriosity.com/nycuriosity_substack_posts/streets_plan_2026/ll195-mandates/) — statutory mandates table
- [`/compliance/`](https://data.nycuriosity.com/nycuriosity_substack_posts/streets_plan_2026/compliance/) — compliance status by mandate

### [CSO Reports 2026](https://data.nycuriosity.com/nycuriosity_substack_posts/cso_reports_2026/)
Data and charts from NYCuriosity's analysis of NYC's Chief Savings Officer agency savings plans for FY2026 and FY2027.

- [`/agency-breakdown/`](https://data.nycuriosity.com/nycuriosity_substack_posts/cso_reports_2026/agency-breakdown/) — savings by agency
- [`/savings-by-category/`](https://data.nycuriosity.com/nycuriosity_substack_posts/cso_reports_2026/savings-by-category/) — savings by type of action
- [`/ibo-comparison/`](https://data.nycuriosity.com/nycuriosity_substack_posts/cso_reports_2026/ibo-comparison/) — CSO savings vs. IBO-identified budget options
- [`/nyc-tax-rates/`](https://data.nycuriosity.com/nycuriosity_substack_posts/cso_reports_2026/nyc-tax-rates/) — NYC tax rate reference table

### [MCB3 History Analysis](https://data.nycuriosity.com/nycuriosity_substack_posts/mcb3_history_analysis/)
Charts comparing MCB3 resolution patterns with 311 complaint data for Community District 3.

- [`/agencies-comparison/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mcb3_history_analysis/agencies-comparison/) — MCB3 resolution targets vs. 311 complaint recipients by agency
- [`/topics-comparison/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mcb3_history_analysis/topics-comparison/) — resolution topics vs. 311 complaint categories
- [`/topics-over-time/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mcb3_history_analysis/topics-over-time/) — MCB3 topic trends over time
- [`/311-vs-resolutions/`](https://data.nycuriosity.com/nycuriosity_substack_posts/mcb3_history_analysis/311-vs-resolutions/) — 311 volume vs. resolution volume over time

---

## Tech

Static site hosted on GitHub Pages at a custom domain (`data.nycuriosity.com`). No backend. Each project is a self-contained directory with an `index.html` that loads and renders data client-side.

**Libraries used:**
- [D3.js v7](https://d3js.org/) — treemap and data-driven SVG (NYC Government Bodies Explorer)
- [Chart.js](https://www.chartjs.org/) — bar and line charts (post data pages)
- [PapaParse](https://www.papaparse.com/) — client-side CSV parsing
- [Google Fonts](https://fonts.google.com/) — Roboto Mono, Inter

---

## Repo Structure

```
/                                          → Hub homepage
/nyc-gov-bodies-explorer/                 → NYC Government Bodies Explorer
/nyc-gov-bodies-explorer/methodology/     → Methodology page
/cb3-resolutions/                         → CB3 hub + chart subpages
/nycuriosity_substack_posts/
  ├── streets_plan_2026/                  → Streets Plan 2026 post data
  ├── cso_reports_2026/                   → CSO Reports 2026 post data
  └── mcb3_history_analysis/              → MCB3 History Analysis post data
```

New post data projects follow the pattern described in `CLAUDE.md`: hub page at `nycuriosity_substack_posts/<folder>/index.html`, individual chart subpages in subdirectories, source CSVs in `data/`.
