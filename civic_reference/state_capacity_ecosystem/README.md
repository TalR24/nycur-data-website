# State Capacity Ecosystem — Project Handoff & Reference

**Last updated:** 2026-06-07
**Maintainer:** Tal Roded (visualization layer) · Henry Grunzweig (curates the underlying database)
**Live:** https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/

This file is the single source of truth for the State Capacity Ecosystem tool. If you are a future Claude session (or future-Tal): **read this file first** before making changes. The companion local-only orientation file at `nycur/state_capacity_ecosystem_claude_ref.md` is a shorter pointer that auto-loads at session start.

---

## What this tool is

A six-page visualization layer over Henry Grunzweig's **State Capacity Ecosystem Database** (an external Airtable curated by Henry, not Tal) plus a separate **Connect** directory (people and orgs) that Tal curates and grows via user self-submission. NYCuriosity does not curate the underlying org data — we only build views on top of Henry's CSV export. The Connect directory has a different source (`connect_submissions.csv` in `data/`) and grows via an in-page 13-field form modal.

The five public pages:

| Page | URL | Purpose |
|---|---|---|
| **Hub** | `/civic_reference/state_capacity_ecosystem/` | Explainer, 4 stat pills, 3 view cards (Directory · Affinity Network · Connect), Methodology card, info panels |
| **Directory** | `…/directory/` | Filterable, searchable table of every org. Semantic search via TF-IDF |
| **Connect** | `…/connect/` | Directory of people and orgs indexed by problem, role, and help-type. 13-field self-submission form modal (mailto + clipboard). Intro request modal for facilitated contacts. Separate dataset from the org pages. |
| **Affinity Network** | `…/network/` | D3 force-directed graph + natural-language semantic search with geographic boosting |
| **Methodology** | `…/methodology/` | Long-form explainer: taxonomy, inclusion criteria, scoring formula |
| **Events** | `…/events/` | Events hub listing state capacity hackathons as cards. Each event links to its own subpage (`…/events/<event-slug>/`) with overview, logistics, tracks, projects produced, Substack writeups, and Luma archive. |

**Pill-nav order across all subpages:** Directory · Connect · Affinity · Events · Methodology · ← Hub

---

## Quick start for a new session

1. **Read this README first.** Don't guess at file structure or weights — they've been deliberately set.
2. **Check the live site** before making changes — `https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/`. The deployed state may differ from your local working copy.
3. **Identify which file you need to edit** from the file map below. The five subpages are independent HTML files; changes to shared concepts (colors, taxonomy, copy) must be made in **all** of them.
4. **For data refreshes:** drop the new CSV in `data/directory.csv` and run `python3 data/build_affinity.py`. Don't hand-edit `affinity.json`, `directory.json`, or `affinity_search.json` — they're regenerated from the CSV.
5. **Push to GitHub** when done. Live in ~1 min via GitHub Pages.

---

## File layout

```
data_website/civic_reference/state_capacity_ecosystem/
├── README.md                        ← THIS FILE
├── index.html                       ← Hub: pills, 4 explore cards, methodology card, info panels
├── data/
│   ├── directory.csv                ← Canonical org source (replace to refresh)
│   ├── build_affinity.py            ← CSV → affinity.json + directory.json + affinity_search.json
│   ├── affinity.json                ← Nodes + scored edges + stats (incl. last_updated)
│   ├── directory.json               ← Flat node bundle for the directory page
│   ├── affinity_search.json         ← Vocab + IDF + per-org sparse TF-IDF for NL search
│   ├── connect_submissions.csv      ← Connect directory seed data (separate dataset)
│   ├── build_people.py              ← CSV → connect.json (simple transform; no scoring)
│   ├── update_stats.py              ← Patches hardcoded stat strings in HTML/MD after org rebuild
│   ├── notify_new_connect.py        ← Emails new Connect entries whose contact field has an @
│   └── connect.json                 ← Flat people bundle for the /connect/ page
├── directory/
│   └── index.html                   ← Filterable table. Reads ../data/directory.json + affinity_search.json
├── network/
│   └── index.html                   ← D3 force-directed graph + NL search bar.
│                                     Reads ../data/affinity.json + affinity_search.json + connect.json.
│                                     Supports ?id=N deep-link from directory.
├── connect/
│   └── index.html                   ← Connect directory + 9-column table + 12-field self-submission
│                                     form modal + intro request modal. Reads ../data/connect.json.
│                                     Submissions post to Airtable via REST API.
├── methodology/
│   └── index.html                   ← Long-form scoring + taxonomy write-up
└── events/
    ├── index.html                   ← Events hub: one card per event
    └── civic-tech-build-night/
        ├── index.html               ← Event detail page. Template for new events
        │                             (copy the folder; HTML comments at top mark
        │                             every section to edit). No JS, no data file.
        │                             Section order: Read about it → Projects produced
        │                             → Overview → Goal → Tracks → Expert judges →
        │                             Event archive. Date shown in the hero.
        └── tideline/                ← Rehosted project (decision #20). TIDELINE flood
            ├── index.html            tracker by D. Lee, D. Berkowitz & L. Kaplan,
            └── *.json                republished WITH PERMISSION + credit. 5 JSON data
                                      files (~6.5 MB). Source repo's build scripts/
                                      notebooks NOT copied. Relative fetch() + CDN libs.
```

---

## CSV schema (10 columns, May 2026)

The CSV columns are read by name (`csv.DictReader`) in `build_affinity.py`. If the schema changes upstream, update the build script.

| Column | Type | Notes |
|---|---|---|
| `Org Name` | string | Canonical name. De-facto primary key. |
| `Primary Segment` | enum | One of 11 categories (see palette below). |
| `Secondary Segments` | comma-list | E.g. `Research,Think Tank` |
| `Focus` | comma-list | `Federal,State,City` (also `Tribal` for a few orgs) |
| `Description` | string | 1–3 sentences. Source of most TF-IDF signal. |
| `Funding Model` | string | `Philanthropy`, `Government`, `VC-backed; Growth stage`, etc. Inconsistencies present. |
| `Funding Detail` | string | Free-text. Funders extracted by regex against `KNOWN_FUNDERS` list. |
| `Website` | string | Often missing protocol; `httpify()` in JS prepends `https://`. |
| `Problem Area` | comma-list | **NEW May 2026.** 7 coarse buckets. See taxonomy below. |
| `Problem Topic` | comma-list | **NEW May 2026** (split from old "Problem Statements"). 36 fine tags as of the 2026-06-01 refresh (was 37). |

**Schema history:**
- April 2026: 8 columns, no problem tagging
- May 10, 2026: Added single `Problem Statements` column (38 tags, 100% coverage)
- May 11, 2026: Split into `Problem Area` (7) + `Problem Topic` (36). `build_affinity.py` reads both; `Problem Topic` maps to `problem_statements` in the JSON output for backward compatibility.
- May 14, 2026: Henry added an 8th Problem Area (`Capacity`) and a 37th Problem Topic. No structural schema change — same 10 columns, just new enum values. Refresh picked up automatically.

---

## Build pipeline

```bash
cd data_website/civic_reference/state_capacity_ecosystem
python3 data/build_affinity.py
```

Pure stdlib + numpy. No env vars, no API keys, no network calls. Outputs three files into `data/`:

- **`affinity.json`** — nodes (with degree) + scored edges + stats block (`org_count`, `edge_count`, `max_weight`, `median_weight`, `last_updated`)
- **`directory.json`** — same node payload, flat array (no edges, no stats)
- **`affinity_search.json`** — `{vocab, idf, vectors}` for client-side TF-IDF semantic search

The build is deterministic — same CSV in, same JSON out.

`last_updated` is stamped automatically from `date.today()` at build time. The hub's "Data last updated" pill reads it and renders `Month D, Year`.

---

## Affinity score (composite, 0–1)

```
score = 0.40 × description_TFIDF_cosine
      + 0.30 × problem_topic_jaccard
      + 0.15 × named_funder_jaccard
      + 0.15 × segment_overlap_jaccard     (NO primary boost)
```

**Why these weights** (rebalanced May 2026 from the original 0.40/0.35/0.25 with primary-segment boost):

- **Description (40%)** — Strongest signal. TF-IDF cosine over a token bag that includes description + funding detail + Problem Area + Problem Topic + segment names. Distinctive terms ("permitting reform," "procurement") matter more than generic ones ("government," "policy").
- **Problem topics (30%)** — Jaccard over Henry's 36 curated tags. Highest-confidence signal because tags are curator-assigned. Drives cross-segment surprise connections — the whole reason this scoring exists.
- **Funders (15%)** — Jaccard over funders extracted by substring match against `KNOWN_FUNDERS` (~50 entries at top of `build_affinity.py`). Falls back to a 0.15 bonus when funding-model strings match exactly and no named funders are detected. Coverage is partial (~21% of orgs).
- **Segments (15%)** — Plain Jaccard over primary + secondary segment sets. **No primary-segment boost.** Earlier versions had 35% weight plus a +0.5 primary boost, which made the network collapse into same-segment cliques. Reducing weight + dropping the boost was a deliberate decision (May 2026) — do not reintroduce the boost without checking with Tal.

**Problem Areas are folded into TF-IDF (description signal) but NOT used as a Jaccard signal.** Reason: an org sharing an Area with another (1 of 7 buckets) is too common to be a high-confidence signal — Jaccard would inflate. Topics are the right granularity for Jaccard.

**Edge thresholding** (in `build_affinity.py`):
- Composite < 0.05 → dropped entirely (not even in candidate pool)
- Composite < 0.10 → dropped from kept set (`MIN_W = 0.10`)
- Per-node degree cap: walk edges in descending score order; keep an edge only if at least one endpoint has fewer than `MAX_DEG = 8` neighbors. Prevents central hubs from dominating.

**Current dataset stats (May 14, 2026 refresh):**
- 328 orgs, 1,759 kept edges
- 21,932 candidate edges before thresholding
- Max edge: 0.82, median: 0.10
- Funder coverage: 64/328 orgs

---

## Semantic search (client-side, no API)

`build_affinity.py` emits `affinity_search.json` containing:
- `vocab` — sorted list of every term in the corpus (~2,400 terms)
- `idf` — IDF score per term (parallel array)
- `vectors` — array of per-org sparse maps `{term_idx_string: tfidf_weight}` (~35 terms per org avg)

At query time, the directory and network views:
1. Tokenize the query (same regex + stopword list as the Python build)
2. Build an IDF-weighted query vector, L2-normalize
3. Cosine similarity against every org's vector
4. Apply boosts: +0.5 if query is substring of org name, +0.15 if substring of a funder
5. Sort descending, take top N

Total cost is one ~190 KB JSON fetch + O(query_terms × num_orgs) per query. No external API. ~$0/query.

**Trade-off vs real embeddings:** TF-IDF can't infer that "permits" and "licensing" refer to the same concept unless those words co-occur in the corpus. For 328 orgs with rich curator-assigned tags, this is the right cost/quality point. If the dataset grows past ~2000 orgs or the user wants true semantic understanding, consider switching to OpenAI `text-embedding-3-small` (~$0.02/1M tokens — still cheap) or a local sentence-transformer model.

---

## Pages — what each does

### Hub (`index.html`)
- Hero with explainer paragraph
- **4 stat pills:** Organizations · Primary segments · Problem topics · Data last updated
- **"Add to Directory" hero CTA** deep-links to `./directory/?add=1`, which auto-opens the directory's in-page **Suggest-an-organization** form modal (`openOF()`). This mirrors the "Add to Connect" CTA's `./connect/?add=1` pattern. The directory's org form POSTs to a Google Form (`OF_ACTION` = a `…/formResponse` endpoint) via `fetch(..., {mode:"no-cors"})`. **It no longer links to the old `forms.gle/GSNh2ZqUfFG4EAzF6` short link** (changed June 2026). The org intake is distinct from the people-directory (Connect) submission.
- **3 view cards under "Explore the ecosystem":** Directory · Affinity Network · Connect.
- **1 methodology card under "How this works":** the hub-level entry point to the methodology page. Card preview is a static rendering of the scoring formula and thresholds. (Methodology is also reachable from every subpage's pill nav.)
- **2 text panels at bottom:** "How we built this" (links to Methodology page) · "Submit feedback" (mailto:statecapacityecosystem@gmail.com)
- Loads `data/affinity.json` to dynamically fill the pills (org count, segment count, problem-topic count, last_updated date)

### Directory (`directory/index.html`)
- **Visible table columns:** Organization · Segment · Secondary Segments · Description (truncated to 180 chars) · Problem Area (orange chips) · Problem Topic (blue chips). Every other field (focus, funding model, funding detail, named funders, website) lives in the row-click detail panel.
- Filters: search box · Primary segment · Geography · Problem area · Problem topic
- **No Funding Model filter** (removed May 2026 per user request)
- **No Named Funder filter** (removed May 2026; substring search still matches funder text)
- **Problem topic filter is case-insensitive** (May 2026): dropdown deduplicates by lowercase key (first-seen canonical form wins), and filter matching is also case-insensitive. Prevents duplicates like "AI in government" / "Ai in government" from appearing as separate options.
- Search behavior:
  - Empty: sorted by current column header (default: name)
  - Non-empty: ranked by TF-IDF cosine, with name-substring (+0.5) and funder-substring (+0.15) boosts
  - Falls back to plain substring filter if no TF-IDF hits (handles short fragments)
- Multi-select dropdowns: opening one closes any other open dropdown. Clicking outside closes all.
- Click any row to expand a detail panel showing: description, Problem areas (orange chips), Problem topics (blue chips), segments, focus, funding model, funding detail, named funders, website, "See in network" deep link
- Loads `data/directory.json` + `data/affinity_search.json`

### Connect (`connect/index.html`)
- Separate dataset from the org pages — sourced from `data/connect_submissions.csv`, a Tal-curated seed list. Entries can be people OR organizations. Grows via a 12-field in-page form modal that POSTs directly to Airtable.
- **Self-submission form modal** (`openSF()` / `closeSF()`): opened by the "Add yourself or a challenge" pill button in the hero. Full-page overlay with fields: Name, Organization (optional), Role (single, 9 options), Offering (multi, 9 options), Problem Area (multi, 9 options), Problem Topic (multi, conditional — shown only after a mappable area is selected), Geography (multi, 4 options), Due By (date, optional), Details (280-char textarea), Contact preference (Direct / Facilitated). Email always shown and required. For Facilitated: a privacy note is shown (email kept private) and a Connection Parameters textarea appears. On submit, POSTs to Airtable REST API. **CSS critical:** `.sf-body` requires `flex:1; min-height:0` — without `min-height:0` the flex child defaults to `min-height:auto` and can't scroll, so lower chip rows clip out of view.
- **Airtable backend:** `AIRTABLE_ENDPOINT` points to base `appFIPqXkeQMQ3n94`, table `tbl2ArzY6c0CdNVsh` ("State Capacity Ecosystem Connect Submissions"). Token is a write-only PAT in client-side JS (intentional — scoped to this table only; readers can submit but cannot read/edit/delete). Table columns: Name, Organization, Role, Offering, Problem Areas, Problem Topics, Geography, Due By, Details, Contact Type, Email, Connection Parameters.
- **Intro request modal** (`openIR(id)` / `closeIR()`): triggered by "Request intro →" links in the Contact column for Facilitated entries. 3-field overlay (name, email, why). Submits via `mailto:statecapacityecosystem@gmail.com` + clipboard copy.
- **9-column table:** Name · Role · Offering · Problem Area · Problem Topic · Geography · Due By · Contact · expand chevron. Click any row to expand a detail panel.
- **Contact column rendering:** Facilitated → "Request intro →" link (opens IR modal); Direct → `mailto:` link on email field. Entries without a contact field show an em-dash.
- **`AREA_TOPICS` constant** maps each of the 7 mappable problem areas to its topic list. "Ecosystem & Capacity" and "Open to Any" have no topics — topic section stays hidden if only those are selected. `sfUpdateTopics()` rebuilds topic chips on area change, preserving prior selections.
- **Backward compatibility:** existing `connect.json` entries use old field names (`help_source`, `jurisdictions`, `problem_area`, `problem_topic`). New Airtable submissions use new names (`offering`, `geography`, `problem_areas`, `problem_topics`). Helper functions `_pGeos()`, `_pAreas()`, `_pTopics()`, `_pOfferings()` handle both schemas throughout the page JS.
- **Neutral language throughout:** "entry" / "entries" / "Name" — the directory contains both people and organizations.
- Loads `data/connect.json` (regenerated by `python3 data/build_people.py`). Don't hand-edit `connect.json` — edit the CSV and rebuild.

### Affinity Network (`network/index.html`)
- D3 force-directed graph; nodes colored by primary segment; edge width scales with composite score
- **No inline methodology blurb** (removed May 2026 per user request). The Methodology pill in the nav (restored May 2026 after a brief removal) is the in-page link to the full methodology page.
- **Controls row 1** (in order): Search by name or question · Show edges at or above (threshold slider) · Segment filter chips · Reset
- **Controls row 2** (added May 2026): Geography · Problem area · Problem topic — multi-select dropdowns, mirroring the directory's `MS` component. A node passes only if every active filter accepts it. The dropdowns share the same registry as each other (opening one closes any sibling), and clicking outside closes them all.
- **Search behavior:**
  - Empty: graph in normal state
  - Non-empty: computes relevance scores; top-10 matches get `.hi` (highlighted), everything else gets `.dim`; results panel below the controls lists top matches as clickable chips with scores; selecting a chip pans and centers on that org
  - Top-N is restricted to currently visible nodes — toggling a filter while a search is active re-runs the search so the top panel doesn't show orgs that have been filtered out.
- **Threshold slider** (0.10–0.40, default 0.18): changes which edges are visible. "More edges (weaker matches)" ↔ "Fewer edges (stronger matches)"
- **Org labels only:** every visible node has a small label below the circle (9.5px, weight 600, white halo). DOM-ordered by ascending degree so high-degree orgs paint on top. **No segment labels in the map** (removed May 2026 — they cluttered the view; segment identity is conveyed by node color + filter chips).
- **Geographic search boost** (added May 2026): `detectGeoFocus()` parses the query for geographic terms (nyc, new york, city, local, state, albany, federal, dc, etc.) and adds a +0.25 score bonus to orgs whose `focus` field matches the implied level. Handles the mismatch between natural-language queries ("procurement in NYC") and the `focus` field's controlled values ("City", "State", "Federal") — none of those city names appear in the TF-IDF corpus.
- Side panel: clicking a node shows full description, Problem statement chips, funding info, closest peers, **and a "People working on these problem topics" section listing entries from `/connect/` whose `problem_topic` is in this org's `problem_statements` list** (added May 2026). At current coverage ~97% of orgs surface at least one matching entry. Up to 8 inline cards + "more →" link to the Connect page.
- **Connect matchmaking sidebar:** when Problem area or Problem topic filters are active, an orange-accented panel appears below the controls listing up to 6 matching entries + total count + "Open Connect ↗" deep link. Hidden otherwise. Mirrors the existing `search-results` pattern.
- Supports `?id=N` deep link from directory
- Loads `data/affinity.json` + `data/affinity_search.json` + `data/connect.json`

### Methodology (`methodology/index.html`)
- Long-form explainer organized as: data source → inclusion criteria → problem statements → directory filters → semantic search → affinity score (formula + per-signal explanation + thresholding) → score range table → what the graph does/doesn't show → color palette → credits
- **No "Refreshing the data" section** (removed May 2026 — was internal-workflow only)
- **No links to Claude conversations** (removed May 2026)

---

## Color palette (11 segments)

These hex codes are duplicated in `SEGMENT_COLORS` constants across `index.html`, `directory/index.html`, `network/index.html`, and as inline `background:` in methodology bullet dots. If you change one, change all four.

```js
{
  "Research":                      "#2563eb",  // blue (primary brand)
  "Government":                    "#0891b2",  // cyan
  "Philanthropy":                  "#dc2626",  // red
  "Fellowships":                   "#d97706",  // amber
  "Community":                     "#7c3aed",  // violet
  "GovTech":                       "#16a34a",  // green
  "Advocacy":                      "#db2777",  // pink
  "Digital Services & Consulting": "#0d9488",  // teal
  "Investor":                      "#9333ea",  // purple
  "Capacity Building":             "#ca8a04",  // yellow (renamed from "Training" May 2026)
  "Ecosystems":                    "#65a30d",  // lime (new May 2026)
}
```

Site-wide design tokens (defined in `:root` of each subpage):
- `--blue: #2563eb` — primary brand
- `--orange: #FF6319` — accent (breadcrumb current page, active states); reserved, do not reuse for segments
- Body bg `#f8faff`, surface `#ffffff`, text `#111827`, text-mid `#374151`, text-muted `#6b7280`, text-faint `#9ca3af`

---

## Problem taxonomy

**7 Problem Areas** (broad buckets) — as of 2026-06-01 refresh (Capacity area removed):
- Service Delivery
- Procurement & Operations
- Technology & Data
- Talent & Hiring
- Test & Learn
- Participatory Democracy
- Domains

**36 Problem Topics** (fine tags, nested under Areas; -1 in the 2026-06-01 refresh). Top by frequency: AI in Government, Service Design, Benefits Access, Talent Pipeline, Operational Excellence, Expert Contribution, Procurement Reform, Transparency & Accountability, Scaling What Works, Outcomes Measurement, Legacy Systems, Data Integration, Civic Engagement, Data Security, Iterative Learning…

100% coverage on both fields. Both feed into TF-IDF for semantic search; only Topics feed into the affinity Jaccard signal.

---

## GitHub push workflow

The repo lives at `https://github.com/TalR24/nycur-data-website`. GitHub Pages serves `data.nycuriosity.com` from the `main` branch.

### Automated refresh (GitHub Actions)

`.github/workflows/refresh_state_capacity.yml` runs at **6 AM ET daily** and handles CSV → JSON rebuilds automatically. It tracks the two CSVs independently:

- **`directory.csv` newer than `affinity.json`** → runs `build_affinity.py` + `update_stats.py`, commits org JSON files and all patched stat strings.
- **`connect_submissions.csv` newer than `connect.json`** → runs `build_people.py`, emails new entries whose `contact` field contains `@`, commits `connect.json`.

Required GitHub secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD`. Requires repo Workflow permissions set to "Read and write permissions" (Settings → Actions → General).

### Manual push (for HTML/code changes)

```bash
cd /Users/troded/Library/CloudStorage/OneDrive-Microsoft/Desktop/nycur/data_website
git add <explicit file paths>
git commit -m "..."
git push
```

**Important — the remote URL has the PAT baked in.** It was set up via `git remote set-url origin https://TalR24:{PAT}@github.com/TalR24/nycur-data-website.git`. The PAT lives in the local-only memory file `~/.claude/projects/.../memory/reference_github.md`. If the remote ever gets reset, re-add the PAT-baked URL.

**Don't stage unrelated files.** Always stage explicit paths — never `git add .` or `git add -A`. The repo has long-standing untracked files (`.DS_Store`s, dated backup CSVs) that must not be committed accidentally.

Dated backup CSVs (`state_capacity_DATE.csv`) are left in the data folder unstaged as working artifacts. The canonical tracked file is `directory.csv`.

---

## Decisions to honor (do not silently reverse)

These were arrived at via user feedback over multiple sessions. Don't reintroduce them without explicit user request.

1. **Affinity weights 0.40 / 0.30 / 0.15 / 0.15.** Indexes toward surprise connections, away from same-segment cliques. **No primary-segment boost** in segment_sim.
2. **No "Funding Model" filter on the directory.** Removed because the source data has inconsistencies (`Government,Philanthropy` vs `Philanthropy,Government` are treated as different categories) and the filter was low-value.
3. **No "Named Funder" filter on the directory.** Removed because it was cluttered with ~50 options. Funder text is still matched by the search box.
4. **Em dashes are banned** in NYCuriosity prose. So is the "not just X / it's Y not X" framing. See `nycur/.claude/projects/.../memory/feedback_writing_style_rules.md`.
5. **"Henry Grunzweig"** is the curator's name (no 'e' between 'z' and 'w'). Earlier sessions used "Henry Tolchard" and "Henry Grunzeweig" — both were wrong. Corrected to "Grunzweig" May 2026. Watch for this when refreshing data or writing prose.
6. **No links to Claude conversations** anywhere on the public site. (Previously the methodology page linked to a Claude convo for weight rationale — removed.)
7. **The methodology page has no "Refreshing the data" section.** That's internal workflow, doesn't belong in public-facing docs.
8. **Pill-nav order:** Directory · Connect · Affinity · Events · Methodology · ← Hub. Applies to every subpage including the affinity network page (the Methodology pill was briefly removed from the network page mid-May 2026 and then restored at user request — keep it). The **Events** pill was added June 2026 when the Events page launched, and moved ahead of Methodology later that month at user request.
9. **Org labels appear below every visible bubble** in the network view (not just top-N by degree). 9.5px / weight 600 / white halo. DOM-sorted by ascending degree so high-degree labels paint on top of overlaps.
10. **No segment labels rendered inside the map.** Earlier versions drew uppercase segment names at the cluster centroid (counter-scaled with zoom). Removed May 2026 — they competed with org names for attention and segment identity is already conveyed by node color + the segment filter chips above the graph.
11. **Multi-select dropdowns close siblings on open.** `MS._registry` static array tracks all instances; `_show()` closes any other open dropdown first. Used on the directory page (Primary segment · Geography · Problem area · Problem topic) and on the network page (Geography · Problem area · Problem topic — added May 2026).
12. **Methodology page stays in sync with the affinity network.** Any change to the scoring formula, weights, token bag, edge thresholding, degree cap, or graph rendering MUST be reflected on `methodology/index.html` in the same commit. Touch points: the formula block, the per-signal `<h3>` paragraphs, the score-range table, the "what gets dropped" thresholds, and the published-dataset stats line. (Note: the network page no longer has its own inline methodology blurb, so the methodology page is the single source of truth for user-facing scoring documentation.)
13. **Directory table is the 6 user-asked columns + expand chevron:** Organization · Segment · Secondary Segments · Description (truncated) · Problem Area · Problem Statement. All other CSV fields are in the row-click detail panel. Do not add columns without explicit user request — the layout was deliberately narrowed May 2026.
14. **Connect (`/connect/`) is a SEPARATE dataset from the org pages.** Source is `data/connect_submissions.csv`, built by `build_people.py` → `connect.json`. Do not merge into `build_affinity.py` — affinity is org-to-org, Connect is a parallel track.
15. **Connect form POSTs to Airtable, not mailto.** The "Add yourself or a challenge" pill opens a 12-field overlay modal. Submission POSTs to `appFIPqXkeQMQ3n94 / tbl2ArzY6c0CdNVsh` via a write-only PAT in client-side JS. This is intentional — the PAT is scoped to that table only (write, no read/edit/delete). Intro requests for Facilitated contacts use a separate 3-field modal that still uses `mailto:statecapacityecosystem@gmail.com` + clipboard.
16. **Network page bridges to /connect/ in two places** (added May 2026): (a) inline "People working on these problem topics" subsection at the bottom of the org-node detail panel; (b) `people-results` sidebar in controls when Problem area or Problem topic filters are active. Both link to `../connect/`. The `connect.json` fetch is wrapped in `.catch(() => [])` so the network page degrades gracefully if the file is missing.
17. **Connect uses neutral language ("Name", "entry", "entries") not "Person" / "practitioners"** — the directory contains both people and organizations. Do not reintroduce people-only language in table headers, filter labels, or JS string templates on this page.
18. **Geographic search boost in network:** `GEO_FOCUS_MAP` + `detectGeoFocus()` in `rankByQuery()` add +0.25 to orgs matching the inferred focus level. Do not remove — the `focus` field values are "City"/"State"/"Federal", not city names, so without the boost "NYC" returns no results. The boost is additive to TF-IDF, not a replacement.
19. **Events use a copy-the-folder template, not a data file.** Each event is a hand-authored static page at `events/<event-slug>/index.html`. To add an event, copy `events/civic-tech-build-night/` and follow the HTML-comment checklist at the top of the file, then add a matching card to `events/index.html`. There is no JSON, no build script, and no `data/` dependency for events — keep it that way unless the event count grows enough to warrant one. Project and Substack links live in clearly-marked `href="#"` slots with `.pending` styling until the real URLs are dropped in. The "Join Our Event" hero CTA on the hub was removed June 2026 once the first event passed; the Events page is now the entry point.
20. **Rehosted hackathon projects live in a subfolder of the event, with credit and permission.** Some event projects are rehosted on our site so we don't send traffic to a builder's personal hosting. The first is **TIDELINE** (`events/civic-tech-build-night/tideline/`), by David A. Lee, Dean Berkowitz & Lyndsey Kaplan, rehosted **with their explicit permission**. It is a self-contained `index.html` + five JSON data files (the build scripts/notebooks from the source repo are NOT copied). The page uses relative `fetch()` and CDN libs only, so it is portable to a subfolder unchanged. A `.credit` line was added to its header (author names + "Republished with permission by NYCuriosity" + a link to the source repo). Rule: only rehost a project with the builder's permission, always credit the builders on both the rehosted page and the event-page card, and link back to the source. Source repo: https://github.com/DALEE9000/nyc_state_capacity_hackathon
21. **Cross-promo loop points at the SCE Substack + the Hub (no Community link yet).** A "Stay connected" strip (Subscribe to our Substack ↗ + Explore the Hub →) sits directly above the `<footer>` on every subpage (directory, connect, network, methodology, events hub, event detail). The Connect form success state has a "While you're here" subscribe/Hub nudge, and the hub's "Stay in touch" section leads with a publication-level "State Capacity Ecosystem Substack · Subscribe" row. **Substack target:** https://statecapacityecosystem.substack.com/ (the tool's own publication — NOT NYCuriosity, NOT an organizer's personal Substack). The strips are intentionally **self-contained inline styles** (they reference `:root` design tokens that exist on every page), so there is no per-page CSS class to keep in sync — edit the inline block if restyling. **There is no "Community" link yet:** when the user provides one (Discord/Slack/Luma/etc.), add a "Join our Community" CTA alongside the Substack button in the strip and the Connect success nudge. Don't invent a Community URL.
22. **No "Buy Me a Coffee" / Support button in the HEADER of the subpages.** Removed July 2026 at user request from the header (`.header-actions`) of every subpage: directory, connect, events, methodology, network. Do NOT re-add it to these subpage headers — even though the shared site-chrome convention (and the `reference_website_chrome.md` memory) puts a Support button in the header elsewhere, this tool's subpages are a deliberate exception. The **footer** support link (`.footer-support`) stays. The hub `index.html` was left untouched.

---

## Things to NOT change without thinking

- **Weights** (0.40 / 0.30 / 0.15 / 0.15). See above.
- **`MAX_DEG` (8).** Lower → cleaner graph but may hide bridge edges. Higher → hairball.
- **`MIN_W` (0.10).** Edges below this never reach the UI. If you raise it, raise the default UI threshold proportionally (currently 0.18).
- **Default UI threshold (0.18).** Calibrated for legibility on first paint.
- **Segment color map.** Used across five files; out-of-sync colors break the visualization's trust.
- **Token bag composition** (description + funding detail + problem topic + problem area + segments). This is what makes semantic search work for short queries — removing any of these inputs degrades search quality.
- **Geographic boost (`GEO_FOCUS_MAP`, `GEO_BOOST = 0.25`).** Necessary because the `focus` field uses "City"/"State"/"Federal", not city names. Removing this means "NYC" / "local" / "city" queries return no geographically targeted results.
- **The `last_updated` stamp** uses `date.today()`. Don't replace with a static string — it'll go stale silently.

---

## Parking lot — ideas surfaced but not built

- **True semantic embeddings** — if the corpus grows or higher search quality is needed, swap TF-IDF for a local sentence-transformer (`all-MiniLM-L6-v2` is ~25 MB, ~$0/query). Would handle synonyms ("permits"/"licensing") that TF-IDF misses.
- **Documented relationships layer** — distinguish "inferred affinity" (current edges) from "documented partnerships" (would require a second Henry data-collection pass). Would overlay solid edges from explicit links.
- **Better funder extraction** — 21% coverage currently. Could move to NER (spaCy) or LLM extraction to cover smaller foundations and family offices. Trade-off: false positives on common nouns.
- **Automated refresh cadence** — currently manual. A monthly cron pulling Henry's Airtable share-view CSV + running `build_affinity.py` is doable. Airtable has a CSV export endpoint per share view; no API token needed.
- **Per-org "claim listing" workflow** — Henry has a Tally form for org reps to claim a listing. Could surface that on individual directory rows to drive traffic into his curation flow.
- **Mobile interaction polish for the network view** — drag/zoom is fine on desktop, cramped on mobile. Could add tap-to-select + slide-up panel.

---

## Cost guidance — working with Claude on this project

Working sessions on this tool tend to involve many file reads and edits across 5+ HTML files. Context accumulates fast. To keep costs reasonable:

**Model choice:**
- **Routine work** (refresh CSV, copy edits, color tweaks, filter additions): use **Sonnet 4.6**. Switch with `/model claude-sonnet-4-6`. ~5× cheaper than Opus, indistinguishable output for this kind of work.
- **Architecture decisions, debugging, novel features** (e.g., the rewrite of the affinity score, designing the semantic search, building the segments page): **Opus 4.7** is worth it. Most of this project's complexity is now built — future work is mostly maintenance.

**When to `/compact`:**
- After finishing a discrete task and before moving to an unrelated one (e.g., "data refresh done, now adding a filter").
- After any session where Claude has read 3+ large HTML files. The reads stick in context for the whole session.
- Before asking Claude to do something that requires re-loading state (Read calls won't be cached the way Bash output is).

**New session per discrete task** is often cheapest. Sessions about "refresh data," "add a filter," and "tweak segment labels" are all self-contained and would each be ~$0.10–0.50 in Sonnet, vs. an accumulated session that re-reads context 10×.

**Batched asks help.** A single turn asking for 5 related changes is cheaper than 5 separate turns. Per-turn token usage is similar; per-session billing is dominated by total turn count × accumulated context.

**Watch out for:**
- Re-reading large files Claude already touched ("can you check the network page again?") — context is still there, save a read by reminding Claude what's in scope.
- Big Bash outputs (CSV inspections with 30+ orgs) — they're useful but bloat context. Pipe through `head` when possible.

---

## Gotchas & lessons (read before making changes)

Things that bit me in past sessions. Read these so you don't reinvent the wheel — or, worse, the bug.

### Always syntax-check inline `<script>` after non-trivial JS edits

The segments page sat broken in production with a silent `SyntaxError`: `selectSegment(seg)` had `const seg = document.getElementById(...)` inside it, redeclaring its own parameter. ES `const` cannot redeclare an existing binding in the same scope, so the entire `<script>` tag failed to parse — and **no JS ran at all**, leaving the page stuck on "Loading…" forever. Hardening code I'd added (timeout, error surfacing) didn't fire because the hardening itself never executed.

I spent a debugging round investigating fetch / CDN / cache before finding the parse error. Don't repeat that. After any non-trivial JS edit, run:

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('PATH/index.html', 'utf8');
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).filter(s => s.trim() && !s.includes('cdn.jsdelivr.net'));
scripts.forEach((s, i) => {
  try { new Function(s); console.log('script', i, 'OK,', s.length, 'chars'); }
  catch(e) { console.log('script', i, 'SYNTAX ERROR:', e.message); }
});
"
```

`new Function()` runs the parser in strict mode and catches param/const shadows, missing braces, arrow-fn quirks, and reserved-word collisions in milliseconds. Visual review missed the `seg` shadow for multiple sessions.

### Data refreshes need a hardcoded-counts sync checklist

`build_affinity.py` regenerates `affinity.json` / `directory.json` / `affinity_search.json` automatically, and `build_people.py` regenerates `connect.json`. But many user-facing strings have stats baked in. When either CSV is updated, run the appropriate build script first, then update **all** of the locations below in lockstep or the UI will lie to readers.

Stat-pills in the hub hero ARE dynamic (read from `affinity.json` at load). **Items 1–5 below are patched automatically by `data/update_stats.py`** (run via GitHub Actions, or manually after `build_affinity.py`). Items 6–7 still require manual edits.

**After updating `directory.csv` (org data) — run `build_affinity.py` first, then update:**

1. **`data_website/index.html`** (data website homepage) — `card-stat` span inside the State Capacity Ecosystem card: `"N orgs · 11 segments · N problem topics"`
2. **`data_website/README.md`** — file tree entry: `directory.csv → Canonical org source (N rows)`
3. **`civic_reference/state_capacity_ecosystem/index.html`** (hub) — any hardcoded counts in card descriptions or bubble stat text (currently "300+" — only update if it crosses a round-number threshold)
4. **`methodology/index.html`** — three locations:
   - Data Fields bullet: `"N specific issues nested under the Problem Areas"`
   - Funder limitation callout: `"Approximately N of N orgs have at least one named funder detected"`
   - Published-dataset stats line: `"N nodes and N edges, with a maximum edge score of X and a median of Y"`
5. **`README.md`** (this file) — six locations:
   - Schema table: `Problem Topic` row — fine tag count
   - Affinity weights: `"Jaccard over Henry's N curated tags"`
   - Current dataset stats block: org count, edge count, funder coverage
   - Problem taxonomy section: `"N Problem Areas"` header, `"N Problem Topics"` header, and area/topic lists if areas or topics were added/removed
   - Hardcoded-counts checklist (this section): update the example stat strings
   - Glossary: `Problem Topic` entry — fine tag count
6. **`data/build_affinity.py`** — comment: `"Problem Area" (N coarse buckets) and "Problem Topic" (N fine tags)`
7. **`state_capacity_ecosystem_claude_ref.md`** — "Current dataset" line: org count + edge count + refresh date; "Schema" line if area/topic counts changed

**After updating `connect_submissions.csv` (Connect data) — run `build_people.py` first, then update:**

1. **`connect/index.html`** — if entry count is surfaced in hero copy or stats (currently shown dynamically via JS count in results bar — no hardcoded number to update unless you add one)
2. **`README.md`** (this file) — "people card stat (practitioner count)" reference in the checklist above if you add a hardcoded count to the hub card

**Stats to read from the build output after each org-data refresh:**

```bash
python3 -c "
import json
aff  = json.load(open('data/affinity.json'))
dirs = json.load(open('data/directory.json'))
s = aff['stats']
topics = set(t for o in dirs for t in o.get('problem_statements', []))
areas  = set(a for o in dirs for a in o.get('problem_areas', []))
funded = sum(1 for o in dirs if o.get('named_funders'))
print(f'Orgs: {s[\"org_count\"]}  Edges: {s[\"edge_count\"]}')
print(f'Max: {s[\"max_weight\"]:.3f}  Median: {s[\"median_weight\"]:.3f}')
print(f'Segments: {len(set(o[\"primary_segment\"] for o in dirs))}')
print(f'Problem areas: {len(areas)}  Problem topics: {len(topics)}')
print(f'Funder coverage: {funded}/{len(dirs)}')
"
```

### The network ↔ people bridge depends on shared topic vocabulary

The matchmaking on the network detail panel (97% coverage at last audit) only works because the org dataset's `problem_statements` field uses the same canonical 36-tag list as the people dataset's `problem_topic` field. If either side ever uses a different vocabulary — free-text topics, a different controlled list, renamed tags — the bridge will degrade silently (no people will appear in the detail panel, no sidebar will fill). Audit after every dataset refresh:

```bash
python3 -c "
import json
orgs = json.load(open('data/directory.json'))
ppl  = json.load(open('data/connect.json'))
org_topics = set()
for o in orgs:
    for t in o.get('problem_statements', []): org_topics.add(t)
covered = sum(1 for p in ppl if p.get('problem_topic') in org_topics)
print(f'people whose topic is in the org vocab: {covered}/{len(ppl)}')
"
```

If this drops materially (below ~80%), investigate before deploying — Henry may have renamed tags on the Airtable side, or the seeds CSV may have drifted.

### Inline `<script>` is at end-of-body, sync — DOM is ready when it runs

MS multi-select instances are constructed at module-load time and immediately call `document.getElementById(...)`. This works because the `<script>` tag sits at the end of `<body>`, after all HTML elements are parsed. If you ever move the script to `<head>` or add `defer`/`async`, you'll need to gate the MS constructors on `DOMContentLoaded` or they'll silently noop.

### Don't trust the prior session's "decisions to honor" verbatim

The decisions list IS the source of truth — but only at the time it was written. Decisions can flip (Methodology pill removed then restored same day; "Three ways to explore" became "Four"; Henry's surname spelled wrong for multiple sessions). Treat decisions as documented *state*, not as inviolable. When the user changes their mind, update the decision text + change log + any prose that references the old position **in the same commit**, or the README itself becomes the bug.

### Ask for direction before building open-ended additions

For changes where placement/labeling/UX is ambiguous (e.g., "add a new section to the hub") the cheapest path is `AskUserQuestion` with 2-3 concrete option previews **before** writing code. Validated twice this session — saved multiple revision cycles vs. guessing.

---

## Open items (as of 2026-06-29 — waiting on user input)

These are concrete, half-done tasks, not parking-lot ideas. Pick them up when the user supplies what's missing.

1. **Claude artifact project not yet added to the build-night page.** The user wants a project hosted at a `claude.ai/public/artifacts/...` link added as a build-night `.proj-card`, but Claude artifacts render client-side, so WebFetch returns only an empty shell (no title/description). **Need from user:** a title + one-line description (or the artifact source to rehost like TIDELINE). It would also be the only `claude.ai` outbound link in the tool — a published artifact is fine (it's a hosted mini-app, not a Claude *conversation*, which decision #6 bans).
2. **Build-night "Read about it" link is a placeholder.** The writeup row is `Post coming ↗` (`<a class="post-link pending" href="#">`). Swap in the SCE Substack recap URL when published and remove the `.pending` class.
3. **No "Community" link in the cross-promo loop** (see decision #21). Add a "Join our Community" CTA to the "Stay connected" strip + Connect success nudge once the user has a URL. Don't invent one.

## Recent change log

| Date | Commit | Summary |
|---|---|---|
| 2026-06-29 | — | Docs: end-of-session sync. Added an "Open items" section (Claude-artifact card pending a title/desc; build-night "Read about it" link still a placeholder; Community link pending a URL), decision #21 (cross-promo loop pattern + SCE Substack target + no-Community-yet rule), and the SCE Substack to external pointers. Refreshed the local ref doc's dataset stat (328 orgs / 1,759 edges) and added the build-night recap facts + open items. |
| 2026-06-29 | — | Cross-promo loop: added a "Stay connected" strip (Subscribe to our Substack ↗ + Explore the Hub →) above the footer on all five subpages plus the events hub and the event detail page; a "While you're here" subscribe/Hub nudge on the Connect form success state; and a publication-level "State Capacity Ecosystem Substack · Subscribe" row at the top of the hub's "Stay in touch" section. Substack target = https://statecapacityecosystem.substack.com/ (the tool's own publication, ~90 subs, confirmed live). **No "Community" link yet** — user has no community URL, so the loop is Substack + Hub only for now; add a Community CTA to the strip/nudge once a URL exists. Strips use self-contained inline styles (design tokens exist on every page) so there's no per-page CSS to maintain. |
| 2026-06-29 | — | Pill-nav: move Events ahead of Methodology on all subpages (new order: Directory · Connect · Affinity · Events · Methodology · ← Hub). Connect: rename problem-area "Domain-Specific" → "Domains" (matches the org/Connect data, which already used "Domains"; the form key was a mismatch). Build-night event page: corrected to the real recap — 80+ builders / 20 teams / 20 tools in under two hours (was "5 projects"); Overview rewritten around inclusive building (practitioners, researchers, advocates building alongside technologists) with a practitioner quote; Goal rewritten to "AI as a tool for inclusive rapid prototyping" + teams built against judge problem statements; removed the false "show-and-tell opening" and "virtual track"; added Bid Finder NYC + FormSpeak project cards (now 8 highlighted of 20); added Civic Roundtable + CUNY PIT Lab partner credit. Hub + events-hub card stats updated to match (no more "NYC + virtual" / "5 projects"). |
| 2026-06-28 | — | Hub: fix "Add to Directory" CTA — was still pointing at the old `forms.gle/GSNh2ZqUfFG4EAzF6` Google Form short link; now deep-links to `./directory/?add=1`, which auto-opens the directory's in-page Suggest-an-organization form (`openOF()`). Added the `?add=1` auto-open handler to `directory/index.html`, mirroring `connect/?add=1`. |
| 2026-06-28 | — | Events hub reframed as a hub for past + upcoming events (not hackathons-only): new hero copy, a "kinds of events we run" section (large hackathons, targeted hackathons, demo nights, speaker/salon nights), broadened host-an-event CTA, and updated meta + hub Events-bubble copy. Methodology: Problems Taxonomy table reordered alphabetically (areas A–Z with Domains last as the catch-all; topics A–Z within each area). Affinity: ran `build_affinity.py` — JSON already current vs the 2026-06-27 directory.csv (no data diff). |
| 2026-06-28 | — | Events: rehost TIDELINE. Add `events/civic-tech-build-night/tideline/` (self-contained index.html + 5 JSON data files, ~6.5 MB) republished with permission from David A. Lee, Dean Berkowitz & Lyndsey Kaplan. Added a `.credit` line to the rehosted page header (authors + permission note + source-repo link) and a 6th project card on the event page linking to `./tideline/#map`. Build scripts/notebooks from the source repo not copied. |
| 2026-06-28 | — | Events: wire all 5 project links, move Projects above Overview, drop the header subtitle, business-health-map collapsed to a single figma.site link. |
| 2026-06-28 | — | Events: restructure build-night page — remove At a glance (date now in hero), move Read about it to top, add Expert judges section, remove Who's in the room. |
| 2026-06-28 | — | Events: add Events page. New `events/index.html` hub (event cards) + `events/civic-tech-build-night/index.html` detail page (template for future events, populated with the June 2026 "A Civic Tech Build Night" hackathon: overview, logistics, 4 tracks, audience, 5 projects produced, Substack writeup slot, Luma archive). Add Events as a 4th explore bubble on the hub and an Events pill to the nav on all four subpages. Remove the now-expired "Join Our Event" hero CTA. Project/Substack links left as `.pending` placeholders pending real URLs. |
| 2026-06-07 | — | Docs: update data_website README (fix stale JSON filenames, add update_stats.py + notify_new_connect.py to file tree, add GitHub Actions section). Update project README (file layout, hardcoded-counts checklist notes automation, GitHub push section documents Actions workflow, last-updated date). Update local ref doc (dataset stats, JSON filenames, automation notes). |
| 2026-06-05 | `3f9711b` | Rename CSVs: `state_capacity_ecosystem.csv` → `directory.csv`, `problem_statement_seeds_v5.csv` → `connect_submissions.csv`. Updated all references across build scripts, workflow, HTML download links, and all READMEs. |
| 2026-06-05 | `dc9c1f0` | Workflow: split change detection into two independent pipelines — `directory.csv` triggers org rebuild + stat patches; `connect_submissions.csv` triggers connect rebuild + email notifications. Each can fire independently or together. |
| 2026-06-04 | `d803750` | Automation: add GitHub Actions workflow (`refresh_state_capacity.yml`) running at 6 AM ET daily. Add `update_stats.py` to auto-patch 7 hardcoded stat strings across 4 files. Add `notify_new_connect.py` to email new Connect entries via Gmail SMTP. |
| 2026-06-04 | `98fee12` | Data: rebuild JSON from June 4 2026 CSV refresh. 313 orgs (+5 vs prior), 1,675 edges (+22). Problem topics and areas unchanged (36/7). Funder coverage 65/313. Updated hardcoded counts in homepage, methodology, data_website README, and this README. |
| 2026-06-03 | `c18257a` | Segments: remove page entirely and scrub all references — deleted `segments/index.html`, removed Segments pill from nav on all four remaining pages, removed Segments bubble card from hub, removed dead `.seg-*` CSS from hub, updated OG meta, methodology hero/credits, CLAUDE.md, both READMEs, and session ref doc. |
| 2026-06-03 | `7f1b501` | Connect: fix broken table caused by orphaned `msGeo` JS variable after `#ms-geo` HTML element was removed — `MS()` constructor called `.classList` on null, throwing TypeError that killed entire script. Removed `msGeo` from constructor, `populateFilters()`, `applyFilters()`, and reset handler. Methodology credits rewritten to single sentence. |
| 2026-06-03 | `21c8f2d` | All pages: align hero heading style — Directory lost "Browse organizations" eyebrow and all-blue h1; both Directory and Connect now use standard dark h1 + blue `<span>` pattern matching Network/Segments/Methodology. |
| 2026-06-03 | `c649448` | Directory: "All Levels" → "All Geographies" in geography multi-select. Methodology: "Verticals" → "Domains" in data fields list and Problems Taxonomy table. |
| 2026-06-03 | `2a7f0a2` | Hub: prepend "We are inspired by the ideas of Jennifer Pahlka:" to hero lede. Connect: Geography removed as table column (now in expanded detail card), Geography filter removed from filter bar, name-cell widened (220→280px), contact-cell constrained (max-width 150px, word-break). Methodology: add privacy/curation note to hero description. |
| 2026-06-03 | `a9fb392` | Hub: add "Stay in Touch" strip between "How we built this" and "Submit feedback" — Henry Grunzweig (Substack + LinkedIn), Tal Roded (Substack + LinkedIn), Jeremie Ponak (LinkedIn). Substack orange (#FF6719), LinkedIn blue (#0A66C2). |
| 2026-06-03 | `aca9394` | Hub Mad Libs: wire offering filter to org segment narrowing via `OFFERING_TO_SEGS` constant. Selecting e.g. "Funding / Investment" now narrows org results to Philanthropy/Investor orgs. Unconstrained offerings (Collaboration Opportunity, Other) impose no segment filter. |
| 2026-06-02 | `ccab8e3` | Connect: rebuild from Henry's updated CSV (23 entries, was 19). Add mandatory pull-first section to `state_capacity_ecosystem_claude_ref.md` and pull-first warning to `CLAUDE.md`. |
| 2026-06-01 | `7a80f9c` | Data: rebuild JSON from June 2026 org CSV. 308 orgs (+4 vs prior), 1,653 edges (+24). Capacity Problem Area removed; topic count dropped from 37 to 36. Funder coverage 64/308. |
| 2026-06-01 | `6a6a215` | Methodology: rewrite with mission/vision/segment taxonomy/problems taxonomy table. Remove stale Search page section. Update Focus → Geography, "challenges" → "opportunities". |
| 2026-06-01 | `f5c2596` | Connect: CSV download button, description/CTA rewrite ("opportunity"), contact-info field (email or URL), City geography canonical. build_people.py updated for Henry's June 2026 CSV schema (Offering, Geography, Due by, Details; 19 entries). |
| 2026-06-01 | `246d78f` | Homepage: move Community Board Tools section to last section. |
| 2026-06-01 | `9bf668b` | Multi-page UX overhaul: standardize "Geography" terminology across all pages (was "Geographic Focus"/"Jurisdiction"); card CTAs capitalized ("Open Directory →"); "Add to Connect" links to connect/?add=1; methodology button shortened to "Read →"; connect bubble desc uses "geography" not "jurisdiction"; segments page adds row-expand detail panel; hub feedback card text updated; affinity graph charge/distance spread out. |
| 2026-06-01 | `9ee743d` | Connect: fix Airtable base ID (missing `app` prefix), improve error logging to surface HTTP body on failure. |
| 2026-06-01 | `e7961bf` | Connect: wire live Airtable credentials (base `appFIPqXkeQMQ3n94`, table `tbl2ArzY6c0CdNVsh`). |
| 2026-06-01 | `6a957cd` | Data: rename all JSON files to match page names — `orgs.json` → `directory.json`, `people.json` → `connect.json`, `graph.json` → `affinity.json`, `search_index.json` → `affinity_search.json`. Updated all fetch() calls across hub, directory, segments, network, and connect pages. |
| 2026-06-01 | `a5c9bad` | Hub: update Mad Libs for new Connect schema — ROLE_TO_SEGS expanded to 9 roles (alpha), `_mlInitToks` handles `p.offering`/`p.help_source` and `p.geography`/`p.jurisdictions`, `_mlSearch` removes time-window filter, Mad Libs sentence removes "within [time window]" token. |
| 2026-06-01 | `97f478a` | Connect: overhaul intake form — Airtable REST API backend; 9 roles/offerings/areas (alpha); 4-geography multi-select; strict topic filtering (hidden until a mappable area selected); email always required; Facilitated shows privacy note + connection-params field; 9-column display table; backward-compat helpers for old people.json field names. |
| 2026-06-01 | `f2c51ab` | Hub: add "Submit Feedback" text panel at bottom (mailto:henrygrunzweig@gmail.com), styled like the "How we built this" panel. |
| 2026-06-01 | `511f923` | Hub: uniform hero button sizing (all four CTA buttons now same size); fix Mad Libs dropdown clipping — removed `overflow:hidden` from `.ml-modal`, added `border-radius:12px 12px 0 0` to `.ml-modal-hdr`, added `min-height:300px` to `.ml-results`. |
| 2026-06-01 | `3eab5b5` | Hub + Segments: rename Connect bubble title to "Find Collaborators And Opportunities"; align Segments table columns to match Directory (Organization · Segment · Description · Problem Area · Problem Statement); update Segments hero description; replace hub bottom panels (Who gets included · Problem statements) with single Methodology CTA block ("How we built this"). |
| 2026-05-24 | `648f55a` | Network: rename "Focus Level" → "Geographic Focus"; fix "Ai in Government" capitalization in orgs.json + graph.json (was a single mis-cased entry for Propel); add `GEO_FOCUS_MAP` + `detectGeoFocus()` geographic boost (+0.25) to `rankByQuery()` so "procurement in NYC" surfaces City-focused orgs. |
| 2026-05-24 | `242c950` | Connect: fix form modal chip clipping — `.sf-body` needed `flex:1; min-height:0`; without `min-height:0` flex child can't be constrained by parent and lower chip rows (Time Window, Geography) are invisible. |
| 2026-05-24 | `15db224` | Connect: fix form modal chip clipping (first attempt — added max-height and flex column structure). |
| 2026-05-24 | `56fe2de` | Connect: rename `/people/` → `/connect/`; table columns now match form fields (Name, Role, Looking For, Seeking, Problem Area, Problem Topic, Geographic Focus, Time Window, Contact); neutral language throughout ("entry"/"entries"/"Name" not "person"/"practitioners"). |
| 2026-05-24 | `aadbe1c` | Connect: Contact column — Direct → email link; Facilitated → "Request intro →" inline intro-request modal (3 fields, mailto + clipboard). |
| 2026-05-24 | `79ccc24` | Connect: align table columns with form fields; Seeking and Geographic Focus moved from detail panel to main row. |
| 2026-05-24 | `41baf6a` | Connect: add 13-field self-submission form modal (`openSF()`/`closeSF()`/`sfSubmit()`); mailto + clipboard copy on success; `AREA_TOPICS` topic filtering by problem area; `sfUpdateTopics()` preserves prior selections. |
| 2026-05-18 | `c8a2acf` | Directory: case-insensitive dedup for problem topic filter. |
| 2026-05-18 | `0d7fe75` | Directory: rename "Focus level" → "Geographic focus". |
| 2026-05-18 | `7e1f96b` | Rename People view to "Asks & Opportunities" across all pages. (Later renamed again to "Connect" on 2026-05-24.) |
| 2026-05-18 | `54a17e6` | Hub: 2×2 card grid layout. |
| 2026-05-14 | `f4f028c` | Network ↔ People bridge: (a) detail panel adds "People working on these problem topics" subsection (~97% org coverage); (b) people-results sidebar appears in controls when Problem area or Problem topic filters are active. Both link out to `/people/`. |
| 2026-05-14 | `4201640` | Add People & Problem Statements page (`/people/`). New 4th explore card on the hub. Sources `data/connect_submissions.csv` via `build_people.py` → `people.json`. 7-dimension filtering. Submit-yourself pill placeholder. People pill added to nav across all subpages. |
| 2026-05-14 | `f1bd3e3` | State Capacity Ecosystem: refresh with 2026-05-14 dataset. 304 orgs (unchanged), 1,629 edges (was 1,623). Henry added an 8th Problem Area ("Capacity") and a 37th Problem Topic. Hardcoded counts in hub cards, methodology page, README, and build script comment all updated. |
| 2026-05-13 | `a3e1957` | Network: restore Methodology pill to the pill nav (briefly removed earlier in the day per user request, then restored). |
| 2026-05-13 | `52bf822` | Hub: move Submit-an-org panel above "Three ways to explore"; add a Methodology card under new "How this works" section. |
| 2026-05-13 | `5c99b8b` | Network: add Focus level + Problem area + Problem topic multi-select filters mirroring the directory; search top-N now restricted to visible nodes. |
| 2026-05-13 | `ac74b65` | Segments: fix SyntaxError (param/const shadow on `seg` in `selectSegment`) that prevented the whole script from parsing. Correct curator's name from "Grunzeweig" to "Grunzweig" everywhere. |
| 2026-05-12 | `14115fa` | Network: drop "How affinity is computed" inline blurb + orphan CSS. |
| 2026-05-12 | `b69af42` | Hub: streamline pills, reorder cards, drop About + Taxonomy panels |
| 2026-05-12 | `d65de53` | Directory: rework columns to org/segment/secondary/description/area/topic (others → row detail). Network: remove in-map segment labels + Methodology pill. Methodology + network blurb: sync TF-IDF token bag wording. Segments: harden fetch (timeout, no-cache, visible errors). README: bump decisions list to include methodology-sync rule. |
| 2026-05-11 | `3323f54` | Directory: add Problem Area filter, surface areas in detail panel |
| 2026-05-11 | `a93b155` | Refresh with 2026-05-11 dataset; schema split into Problem Area + Problem Topic |
| 2026-05-11 | `44149f6` | Drop Refresh section from methodology; reorder pill nav; counter-scale segment labels |
| 2026-05-11 | `b1aadf7` | Network: make org labels consistently visible (sort by degree, bigger font, stronger halo) |
| 2026-05-11 | `de01463` | Rebalance affinity (0.40/0.30/0.15/0.15); add semantic search; add /segments/ page; Henry name correction; remove Claude convo links |
| 2026-05-10 | `3f54a4b` | Add "Data last updated" stat pill on hub |
| 2026-05-10 | `fe38118` | Tweak directory filters; add segment labels at cluster centroids |
| 2026-05-10 | `abf8940` | Refresh with May 2026 dataset (225 → 304 orgs); add Problem Statements column |
| 2026-04 | `9f5294a` | Initial State Capacity Ecosystem tool |

Use `git log --oneline -- civic_reference/state_capacity_ecosystem/` for the full history.

---

## External pointers

- **Source Airtable** (Henry's curation): https://airtable.com/appo3EaOAi7JjI2VZ/shrAswoPpY3sbZIY7/tblcsGZwPK5O5TXjb/viwQZffbnIJ8f4zjT
- **Connect Submissions Airtable** (form backend, Tal-managed): base `appFIPqXkeQMQ3n94`, table `tbl2ArzY6c0CdNVsh` ("State Capacity Ecosystem Connect Submissions")
- **Suggest-an-org form** (Henry's intake): https://forms.gle/GSNh2ZqUfFG4EAzF6
- **Site repo:** https://github.com/TalR24/nycur-data-website
- **State Capacity Ecosystem Substack** (the tool's own publication): https://statecapacityecosystem.substack.com/
- **NYCuriosity Substack:** https://nycuriosity.substack.com/

---

## Glossary

- **Affinity** — Composite score 0–1 indicating how likely two orgs are working on similar things. Not a documented relationship; an inference from public-facing data.
- **TF-IDF** — Term Frequency × Inverse Document Frequency. Vectorizes text such that rare distinctive words ("procurement") matter more than ubiquitous ones ("government").
- **Jaccard** — `|A ∩ B| / |A ∪ B|` for two sets. Used for segment, problem-topic, and funder overlap.
- **Problem Area** — One of 7 broad buckets (Service Delivery, Procurement & Operations, Domains, etc.). Coarse.
- **Problem Topic** — One of 36 fine tags (Procurement Reform, AI in Government, etc.). Maps to the `problem_statements` field in JSON output.
- **Composite score** — The weighted sum of the four affinity signals.
- **Edge threshold** — UI slider hiding edges below a certain composite score. Default 0.18.
