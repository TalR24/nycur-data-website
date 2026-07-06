# NYCuriosity Data

**[data.nycuriosity.com](https://data.nycuriosity.com)**

A companion site to [NYCuriosity](https://nycuriosity.substack.com), a Substack publication covering NYC urban policy, transit, infrastructure, and street design. The site hosts two types of content: **civic reference tools** (standalone interactive explorers) and **post data pages** (charts and tables tied to specific Substack articles).

---

## ⚠️ Premium data paywall (members-only tools)

Two tools are **paywalled** (launched Jul 2026): the **NYC Council Fiscal Impacts Tracker** and the **NYC CB Resolutions Dashboard**. Their public URLs here now serve **teaser pages**; the working tools live on a separate **private** origin.

- **Real tools live in the PRIVATE repo** `TalR24/nycur-data-premium` → Cloudflare Worker (static assets) → **`premium.nycuriosity.com`**, gated by **Cloudflare Access** (email one-time-PIN + allowlist). **Never put these tools' data back in this public repo** — that bypasses the paywall.
- **Public side (this repo):** `civic_reference/nyc_council_fiscal_impacts_tracker/index.html` and `cb-resolutions/index.html` are **teaser pages** ("Become a member" → `buymeacoffee.com/nycuriosity`; "Sign in" → `premium.nycuriosity.com`). All their subpages + CSV/JSON were removed.
- **Access is manual:** when someone subscribes on Buy Me a Coffee, add their email in Cloudflare Zero Trust → Access → the app → policy **"NYCuriosity Premium"** → Emails; remove on cancellation.
- **cb-resolutions teaser stats are HARDCODED.** When boards/resolutions are added to the database (done in other sessions), bump the `.stat-pills` + hero copy in `cb-resolutions/index.html` **and** the CB card in `index.html`.
- **SEO:** teasers stay indexable (marketing); the premium origin is `noindex`/robots-disallowed. Keep `sitemap.xml` free of the removed gated subpages — it should list only the two teaser hubs, not their old subpages.

Full architecture, deploy steps, and the approved Buy Me a Coffee copy are in the **private repo's README** (`nycur-data-premium/README.md`).

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
- [`/civic_reference/state_capacity_ecosystem/events/`](https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/events/) — state capacity hackathons, with per-event pages covering overview, tracks, judges, and the projects produced (e.g. `events/civic-tech-build-night/`)

### [NYC Council Fiscal Impacts Tracker](https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/)
Estimated fiscal impact of every NYC Council bill with a Finance Division impact statement. Filterable by agency, committee, sponsor, and fiscal year, with cost/revenue/capital breakdowns and per-bill detail panels.

**🔒 Members-only** (see the Premium data paywall section above). The public URL is now a teaser; the full tracker and its subpages (bill table, by agency, by sponsor, by year, costs vs. revenue, methodology) live in the private `nycur-data-premium` repo, served at `premium.nycuriosity.com`.

### [NYC Government Bodies Explorer](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/)
Browse all ~80 NYC government bodies — agencies, elected offices, DA offices, authorities, and boards — with FY2025 Adopted Budget and headcount data. Searchable card grid with inline detail panels and a D3.js treemap sized by budget or headcount, with sector-level filtering.

- [`/civic_reference/nyc-gov-bodies-explorer/`](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/) — main explorer (card grid + treemap)
- [`/civic_reference/nyc-gov-bodies-explorer/methodology/`](https://data.nycuriosity.com/civic_reference/nyc-gov-bodies-explorer/methodology/) — data sources, definitions, and known limitations

### [NYC CB Resolutions Dashboard](https://data.nycuriosity.com/cb-resolutions/)
Full-text search and visualization of resolutions across seven of Manhattan's Community Boards (2002–2026). Filter by board, search full text, and compare topic and agency mentions side-by-side.

**🔒 Members-only** (see the Premium data paywall section above). The public URL is now a teaser; the working dashboard and its subpages (explorer, resolutions-per-year, top-agencies, top-topics) live in the private `nycur-data-premium` repo at `premium.nycuriosity.com`. *Board and resolution counts grow over time and the teaser stats are hardcoded — update them when the database expands.*

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

### Site chrome & shared components

CSS is **inline per-page** (no shared stylesheet), so shared components are duplicated into each page. When adding a new page or tool, replicate the header and footer below.

- **Header** — dark (`#111827`). Brand (`nycuriosity / data`) on the left; a `.header-actions` flex row on the right holds outlined `.header-link` pills (**About** → `https://talroded.nycuriosity.com`, **Substack**) and the `.support-link` pill.
- **Footer** — white (`var(--surface)`, `#ffffff`). A `.footer-links` row of text links with a `.footer-support` pill.
- **Buy Me a Coffee** — every page links to `https://buymeacoffee.com/nycuriosity`, label **"Support my work"**, coffee-cup icon, `target="_blank"`. Present in both header and footer.
- **Palette per surface** — the pill color depends on its background: on the dark header use `.support-link` (light-blue text `#93c5fd`); on the white footer use `.footer-support` (blue text `#2563eb`). Both fill solid blue (`#2563eb`) with white text on hover. Do not put the light-blue `.support-link` on a white surface — it fails contrast.
- **Footer alignment** — `.footer-links` must include `align-items: center`, otherwise the padded pill sits misaligned with the plain text links.
- **Reusable button CSS** on subpages is injected in a single `<style id="support-btn-css">` block before `</head>`.

Page types and how the button attaches:
- **Hub pages** (brand + `.header-link`) → header pills **and** footer pill.
- **Post/hub pages** with a `.footer-links` container → footer pill.
- **Inline `·`-separated footers** (cb-resolutions, mcb3 topics charts) → a plain inline "Support my work" link matching the sibling text links (no pill).
- **Skip:** the 8 meta-refresh redirect stubs; and chrome-less pages that have no header/footer — `civic_reference/cb_member_guide/{index,handout}.html` and `civic_reference/state_capacity_ecosystem/events/civic-tech-build-night/tideline/` (add a footer first if these ever need the button).

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
│   │   │   ├── directory.csv                      → Canonical org source (328 rows)
│   │   │   ├── connect_submissions.csv            → Connect directory seed data
│   │   │   ├── build_affinity.py                  → directory.csv → affinity/directory/search JSON
│   │   │   ├── build_people.py                    → connect_submissions.csv → connect.json
│   │   │   ├── update_stats.py                    → Patches hardcoded stat strings after rebuild
│   │   │   ├── notify_new_connect.py              → Emails new Connect entries
│   │   │   └── *.json                             → Generated data bundles
│   │   ├── directory/  network/  connect/  methodology/
│   │   └── events/                                → Hackathons hub + per-event pages
│   │       ├── index.html                         → Events hub (event cards)
│   │       └── civic-tech-build-night/            → Event page + projects (incl. rehosted
│   │                                                TIDELINE dashboard under tideline/)
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
