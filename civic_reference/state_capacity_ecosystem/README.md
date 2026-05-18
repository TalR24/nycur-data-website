# State Capacity Ecosystem — Project Handoff & Reference

**Last updated:** 2026-05-14
**Maintainer:** Tal Roded (visualization layer) · Henry Grunzweig (curates the underlying database)
**Live:** https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/

This file is the single source of truth for the State Capacity Ecosystem tool. If you are a future Claude session (or future-Tal): **read this file first** before making changes. The companion local-only orientation file at `nycur/state_capacity_ecosystem_claude_ref.md` is a shorter pointer that auto-loads at session start.

---

## What this tool is

A five-page visualization layer over Henry Grunzweig's **State Capacity Ecosystem Database** (an external Airtable curated by Henry, not Tal) plus a separate **People & Problem Statements** seed CSV that Tal curates for matchmaking. NYCuriosity does not curate the underlying org data — we only build views on top of Henry's CSV export. The people directory has a different source (`problem_statement_seeds_v5.csv` in `data/`) and is meant to grow via user self-submission.

The five public pages:

| Page | URL | Purpose |
|---|---|---|
| **Hub** | `/civic_reference/state_capacity_ecosystem/` | Explainer, 4 stat pills, 4 view cards (Directory · Affinity Network · Segments · People), Methodology card, 3 info panels |
| **Directory** | `…/directory/` | Filterable, searchable table of every org. Semantic search via TF-IDF |
| **Segments** | `…/segments/` | Bar chart of segment counts; click a bar to expand a table of orgs in that segment |
| **Affinity Network** | `…/network/` | D3 force-directed graph + natural-language semantic search |
| **People** | `…/people/` | Directory of practitioners indexed by problem statement. 7-dimension filtering. Submit-yourself CTA (form placeholder). Separate dataset from the org pages. |
| **Methodology** | `…/methodology/` | Long-form explainer: taxonomy, inclusion criteria, scoring formula |

**Pill-nav order across all subpages:** Directory · Affinity Network · Segments · People · Methodology · ← Hub

---

## Quick start for a new session

1. **Read this README first.** Don't guess at file structure or weights — they've been deliberately set.
2. **Check the live site** before making changes — `https://data.nycuriosity.com/civic_reference/state_capacity_ecosystem/`. The deployed state may differ from your local working copy.
3. **Identify which file you need to edit** from the file map below. The four subpages are independent HTML files; changes to shared concepts (colors, taxonomy, copy) must be made in **all** of them.
4. **For data refreshes:** drop the new CSV in `data/state_capacity_ecosystem.csv` and run `python3 data/build_affinity.py`. Don't hand-edit `graph.json`, `orgs.json`, or `search_index.json` — they're regenerated from the CSV.
5. **Push to GitHub** when done. Live in ~1 min via GitHub Pages.

---

## File layout

```
data_website/civic_reference/state_capacity_ecosystem/
├── README.md                        ← THIS FILE
├── index.html                       ← Hub: pills, 4 explore cards, methodology card, info panels
├── data/
│   ├── state_capacity_ecosystem.csv ← Canonical org source (replace to refresh)
│   ├── build_affinity.py            ← CSV → graph.json + orgs.json + search_index.json
│   ├── graph.json                   ← Nodes + scored edges + stats (incl. last_updated)
│   ├── orgs.json                    ← Flat node bundle for the directory + segments pages
│   ├── search_index.json            ← Vocab + IDF + per-org sparse TF-IDF for NL search
│   ├── problem_statement_seeds_v5.csv ← People + problem-statement seeds (separate dataset)
│   ├── build_people.py              ← CSV → people.json (simple transform; no scoring)
│   └── people.json                  ← Flat people bundle for the /people/ page
├── directory/
│   └── index.html                   ← Filterable table. Reads ../data/orgs.json + search_index.json
├── segments/
│   └── index.html                   ← Bar chart + click-to-list. Reads ../data/orgs.json
├── network/
│   └── index.html                   ← D3 force-directed graph + NL search bar.
│                                     Reads ../data/graph.json + search_index.json.
│                                     Supports ?id=N deep-link from directory.
├── people/
│   └── index.html                   ← People directory + 7 filters + submit-yourself CTA.
│                                     Reads ../data/people.json.
└── methodology/
    └── index.html                   ← Long-form scoring + taxonomy write-up
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
| `Problem Topic` | comma-list | **NEW May 2026** (split from old "Problem Statements"). 37 fine tags as of the 2026-05-14 refresh (was 36). |

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

- **`graph.json`** — nodes (with degree) + scored edges + stats block (`org_count`, `edge_count`, `max_weight`, `median_weight`, `last_updated`)
- **`orgs.json`** — same node payload, flat array (no edges, no stats)
- **`search_index.json`** — `{vocab, idf, vectors}` for client-side TF-IDF semantic search

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
- **Problem topics (30%)** — Jaccard over Henry's 37 curated tags. Highest-confidence signal because tags are curator-assigned. Drives cross-segment surprise connections — the whole reason this scoring exists.
- **Funders (15%)** — Jaccard over funders extracted by substring match against `KNOWN_FUNDERS` (~50 entries at top of `build_affinity.py`). Falls back to a 0.15 bonus when funding-model strings match exactly and no named funders are detected. Coverage is partial (~21% of orgs).
- **Segments (15%)** — Plain Jaccard over primary + secondary segment sets. **No primary-segment boost.** Earlier versions had 35% weight plus a +0.5 primary boost, which made the network collapse into same-segment cliques. Reducing weight + dropping the boost was a deliberate decision (May 2026) — do not reintroduce the boost without checking with Tal.

**Problem Areas are folded into TF-IDF (description signal) but NOT used as a Jaccard signal.** Reason: an org sharing an Area with another (1 of 7 buckets) is too common to be a high-confidence signal — Jaccard would inflate. Topics are the right granularity for Jaccard.

**Edge thresholding** (in `build_affinity.py`):
- Composite < 0.05 → dropped entirely (not even in candidate pool)
- Composite < 0.10 → dropped from kept set (`MIN_W = 0.10`)
- Per-node degree cap: walk edges in descending score order; keep an edge only if at least one endpoint has fewer than `MAX_DEG = 8` neighbors. Prevents central hubs from dominating.

**Current dataset stats (May 14, 2026 refresh):**
- 304 orgs, 1,629 kept edges
- 21,932 candidate edges before thresholding
- Max edge: 0.82, median: 0.10
- Funder coverage: 62/304 orgs

---

## Semantic search (client-side, no API)

`build_affinity.py` emits `search_index.json` containing:
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

**Trade-off vs real embeddings:** TF-IDF can't infer that "permits" and "licensing" refer to the same concept unless those words co-occur in the corpus. For 304 orgs with rich curator-assigned tags, this is the right cost/quality point. If the dataset grows past ~2000 orgs or the user wants true semantic understanding, consider switching to OpenAI `text-embedding-3-small` (~$0.02/1M tokens — still cheap) or a local sentence-transformer model.

---

## Pages — what each does

### Hub (`index.html`)
- Hero with explainer paragraph
- **4 stat pills:** Organizations · Primary segments · Problem topics · Data last updated
- **Submit-an-organization panel** sits right after the pills, above "Four ways to explore" — full-width with Henry's Google Form CTA (this is the *org* intake form, not the people-directory submission)
- **4 view cards under "Four ways to explore":** Directory · Affinity Network · Segments · People. Section was relabeled from "Three" to "Four" in May 2026 when the People card was added.
- **1 methodology card under "How this works":** the hub-level entry point to the methodology page. Card preview is a static rendering of the scoring formula and thresholds. (Methodology is also reachable from every subpage's pill nav.)
- **2 info panels at bottom:** What gets included (inclusion criteria) · Problem statements (areas + topics)
- Loads `data/graph.json` to dynamically fill the pills (org count, segment count, problem-topic count, last_updated date)

### Directory (`directory/index.html`)
- **Visible table columns:** Organization · Segment · Secondary Segments · Description (truncated to 180 chars) · Problem Area (orange chips) · Problem Topic (blue chips). Every other field (focus, funding model, funding detail, named funders, website) lives in the row-click detail panel.
- Filters: search box · Primary segment · Focus level · Problem area · Problem topic
- **No Funding Model filter** (removed May 2026 per user request)
- **No Named Funder filter** (removed May 2026; substring search still matches funder text)
- Search behavior:
  - Empty: sorted by current column header (default: name)
  - Non-empty: ranked by TF-IDF cosine, with name-substring (+0.5) and funder-substring (+0.15) boosts
  - Falls back to plain substring filter if no TF-IDF hits (handles short fragments)
- Multi-select dropdowns: opening one closes any other open dropdown. Clicking outside closes all.
- Click any row to expand a detail panel showing: description, Problem areas (orange chips), Problem topics (blue chips), segments, focus, funding model, funding detail, named funders, website, "See in network" deep link
- Loads `data/orgs.json` + `data/search_index.json`

### Segments (`segments/index.html`)
- Bar chart of primary-segment counts (descending)
- Click any bar → orange highlight on that row + table appears below showing every org in that segment with their focus, funding model, and problem-topic chips
- Click the same bar again to deselect
- Loads `data/orgs.json`

### People (`people/index.html`)
- Separate dataset from the org pages — sourced from `data/problem_statement_seeds_v5.csv`, a Tal-curated seed list of 34 practitioners working on specific state-capacity problems. Meant to grow via user self-submission (form is a placeholder for now).
- **Submit-yourself pill** sits in the hero, prominent orange CTA: `Submit yourself to the directory`. Currently `href="#"` with a small italic caption "Submission form coming soon — link will be added here." Swap the href once the form exists.
- **7-dimension filter row:** search (Name / Organization / Problem details) · Role · Jurisdiction · Problem area · Problem topic · Help they're seeking · Time window. All but search are multi-select dropdowns using the same `MS` component as Directory + Network. Jurisdiction is multi-valued per person (semicolon-separated in source), so the filter matches any-of.
- **Table columns:** Person (name + org subtitle) · Role (colored badge) · Jurisdiction (orange chips) · Problem area (orange pill) · Problem topic (blue pill) · Contact (auto-detects email vs URL). Click a row to expand a detail panel with the full Problem Details narrative, what kind of help they're seeking, time window, and a duplicated contact link.
- **Contact rendering:** strings with `@` (and not `http`) become `mailto:` links; everything else gets `https://` prepended and opens in a new tab. The Contact field in the source CSV is free-text so this heuristic handles emails, plain domains, and full URLs uniformly.
- **Sortable columns:** Person (by name), Role, Problem area, Problem topic. Jurisdiction and Contact are not sortable.
- **Hardened fetch:** explicit 15s `AbortController` timeout + `r.ok` check + try/catch around render. Same pattern as the segments page after that one's "Loading…" stall.
- Loads `data/people.json` (regenerated by `python3 data/build_people.py`). Don't hand-edit `people.json` — edit the CSV and rebuild.

### Affinity Network (`network/index.html`)
- D3 force-directed graph; nodes colored by primary segment; edge width scales with composite score
- **No inline methodology blurb** (removed May 2026 per user request). The Methodology pill in the nav (restored May 2026 after a brief removal) is the in-page link to the full methodology page.
- **Controls row 1** (in order): Search by name or question · Show edges at or above (threshold slider) · Segment filter chips · Reset
- **Controls row 2** (added May 2026): Focus level · Problem area · Problem topic — multi-select dropdowns, mirroring the directory's `MS` component. A node passes only if every active filter accepts it. The dropdowns share the same registry as each other (opening one closes any sibling), and clicking outside closes them all.
- **Search behavior:**
  - Empty: graph in normal state
  - Non-empty: computes relevance scores; top-10 matches get `.hi` (highlighted), everything else gets `.dim`; results panel below the controls lists top matches as clickable chips with scores; selecting a chip pans and centers on that org
  - Top-N is restricted to currently visible nodes — toggling a filter while a search is active re-runs the search so the top panel doesn't show orgs that have been filtered out.
- **Threshold slider** (0.10–0.40, default 0.18): changes which edges are visible. "More edges (weaker matches)" ↔ "Fewer edges (stronger matches)"
- **Org labels only:** every visible node has a small label below the circle (9.5px, weight 600, white halo). DOM-ordered by ascending degree so high-degree orgs paint on top. **No segment labels in the map** (removed May 2026 — they cluttered the view; segment identity is conveyed by node color + filter chips).
- Side panel: clicking a node shows full description, Problem statement chips, funding info, closest peers, **and a "People working on these problem topics" section listing practitioners from `/people/` whose `problem_topic` is in this org's `problem_statements` list** (added May 2026). At current coverage ~97% of orgs surface at least one matching person. Up to 8 inline cards + "more →" link to the people directory.
- **People matchmaking sidebar:** when Problem area or Problem topic filters are active, an orange-accented panel appears below the controls listing up to 6 matching practitioners + total count + "Open people directory ↗" deep link. Hidden otherwise. Mirrors the existing `search-results` pattern.
- Supports `?id=N` deep link from directory

### Methodology (`methodology/index.html`)
- Long-form explainer organized as: data source → inclusion criteria → problem statements → directory filters → semantic search → affinity score (formula + per-signal explanation + thresholding) → score range table → what the graph does/doesn't show → color palette → credits
- **No "Refreshing the data" section** (removed May 2026 — was internal-workflow only)
- **No links to Claude conversations** (removed May 2026)

---

## Color palette (11 segments)

These hex codes are duplicated in `SEGMENT_COLORS` constants across `index.html`, `directory/index.html`, `segments/index.html`, `network/index.html`, and as inline `background:` in methodology bullet dots. If you change one, change all five.

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

**8 Problem Areas** (broad buckets) — Capacity added in the 2026-05-14 refresh:
- Service Delivery
- Procurement & Operations
- Technology & Data
- Talent & Hiring
- Test & Learn
- Participatory Democracy
- Capacity
- Verticals

**37 Problem Topics** (fine tags, nested under Areas; +1 in the 2026-05-14 refresh). Top by frequency: AI in Government (84), Service Design (79), Benefits Access (66), Talent Pipeline (65), Operational Excellence (59), Expert Contribution (50), Procurement Reform (50), Transparency & Accountability (49), Scaling What Works (49), Outcomes Measurement (45), Legacy Systems (44), Data Integration (42), Civic Engagement (39), Data Security (34), Iterative Learning (27)…

100% coverage on both fields. Both feed into TF-IDF for semantic search; only Topics feed into the affinity Jaccard signal.

---

## GitHub push workflow

The repo lives at `https://github.com/TalR24/nycur-data-website`. GitHub Pages serves `data.nycuriosity.com` from the `main` branch.

```bash
cd /Users/troded/Library/CloudStorage/OneDrive-Microsoft/Desktop/nycur/data_website
git add <files>
git commit -m "..."
git push
```

**Important — the remote URL has the PAT baked in.** It was set up via `git remote set-url origin https://TalR24:{PAT}@github.com/TalR24/nycur-data-website.git`. The PAT lives in the local-only memory file `~/.claude/projects/.../memory/reference_github.md`. If the remote ever gets reset, re-add the PAT-baked URL.

**Don't stage unrelated files.** This repo has long-standing in-progress changes (deleted fiscal-impacts files, untracked `.DS_Store`s, the dated CSV `state_capacity_20260511.csv`). Always stage explicit paths, never `git add .` or `git add -A`.

The dated CSV (`state_capacity_DATE.csv`) is left in the data folder unstaged as a working artifact. The canonical `state_capacity_ecosystem.csv` is the one tracked.

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
8. **Pill-nav order:** Directory · Affinity Network · Segments · Methodology · ← Hub. Affinity Network sits before Segments. Applies to every subpage including the affinity network page (the Methodology pill was briefly removed from the network page mid-May 2026 and then restored at user request — keep it).
9. **Org labels appear below every visible bubble** in the network view (not just top-N by degree). 9.5px / weight 600 / white halo. DOM-sorted by ascending degree so high-degree labels paint on top of overlaps.
10. **No segment labels rendered inside the map.** Earlier versions drew uppercase segment names at the cluster centroid (counter-scaled with zoom). Removed May 2026 — they competed with org names for attention and segment identity is already conveyed by node color + the segment filter chips above the graph.
11. **Multi-select dropdowns close siblings on open.** `MS._registry` static array tracks all instances; `_show()` closes any other open dropdown first. Used on the directory page (Primary segment · Focus level · Problem area · Problem topic) and on the network page (Focus level · Problem area · Problem topic — added May 2026).
12. **Methodology page stays in sync with the affinity network.** Any change to the scoring formula, weights, token bag, edge thresholding, degree cap, or graph rendering MUST be reflected on `methodology/index.html` in the same commit. Touch points: the formula block, the per-signal `<h3>` paragraphs, the score-range table, the "what gets dropped" thresholds, and the published-dataset stats line. (Note: the network page no longer has its own inline methodology blurb, so the methodology page is the single source of truth for user-facing scoring documentation.)
13. **Directory table is the 6 user-asked columns + expand chevron:** Organization · Segment · Secondary Segments · Description (truncated) · Problem Area · Problem Statement. All other CSV fields are in the row-click detail panel. Do not add columns without explicit user request — the layout was deliberately narrowed May 2026.
14. **People directory is a SEPARATE dataset from the org pages.** Source is `data/problem_statement_seeds_v5.csv`, built by `build_people.py`. Do not merge into `build_affinity.py` — affinity is org-to-org, people are a parallel track. Hub treats the People card as a 4th "way to explore" alongside Directory / Affinity Network / Segments.
15. **People submission form link is a placeholder.** The hero CTA on the people page currently has `href="#"` with a "form coming soon" caption. When the form exists, swap the href to the real URL and remove the caption. Don't replace with a mailto: — Tal explicitly chose the inert anchor + caption pattern over alert or mailto.
16. **Network page bridges to /people/ in two places** (added May 2026): (a) inline "People working on these problem topics" subsection at the bottom of the org-node detail panel — matches by `problem_topic ∈ org.problem_statements`; (b) `people-results` panel inside the controls block that appears when Problem area or Problem topic filters are active. Both reuse the `.people-card` styling (orange-accented to distinguish from the blue semantic-search panel) and link out to `/people/` for the full list. The `people.json` fetch is wrapped in `.catch(() => [])` so the network page degrades gracefully if the file is missing.

---

## Things to NOT change without thinking

- **Weights** (0.40 / 0.30 / 0.15 / 0.15). See above.
- **`MAX_DEG` (8).** Lower → cleaner graph but may hide bridge edges. Higher → hairball.
- **`MIN_W` (0.10).** Edges below this never reach the UI. If you raise it, raise the default UI threshold proportionally (currently 0.18).
- **Default UI threshold (0.18).** Calibrated for legibility on first paint.
- **Segment color map.** Used across five files; out-of-sync colors break the visualization's trust.
- **Token bag composition** (description + funding detail + problem topic + problem area + segments). This is what makes semantic search work for queries like "procurement in NYC" — removing any of these inputs degrades search quality.
- **The `last_updated` stamp** uses `date.today()`. Don't replace with a static string — it'll go stale silently.

---

## Parking lot — ideas surfaced but not built

- **Problem Area surfacing on segments page** — could add a "group by Problem Area" view alongside the segment chart.
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

`build_affinity.py` regenerates `graph.json` / `orgs.json` / `search_index.json` automatically. But many user-facing strings have stats baked in. When the dataset refreshes (org count, edge count, segment count, problem area / topic count, funder coverage), update **all** of these in lockstep or the UI will lie to readers:

1. **Hub `index.html`** — directory card stat ("304 orgs · 11 segments · X areas · Y topics"), network card stat ("1,629 edges · …"), problem-statements info panel ("Y fine-grained issues, X broader buckets"), people card stat (practitioner count)
2. **Methodology `index.html`** — schema bullets, problem-statements paragraph, directory-filter bullet, "Limitation worth flagging" funder count, dataset stats line
3. **README** — Current dataset stats, schema history, Problem taxonomy section, Glossary entries
4. **`build_affinity.py`** — the docstring/comment around the schema bit referencing area + topic counts

Stat-pills in the hero ARE dynamic (read from `graph.json` at load). Card-stat strings inside `.card` elements and inline taxonomy descriptions are NOT — they're hand-written. A future improvement would be to make the card stats dynamic too, but until then, hand-update them.

### The network ↔ people bridge depends on shared topic vocabulary

The matchmaking on the network detail panel (97% coverage at last audit) only works because the org dataset's `problem_statements` field uses the same canonical 37-tag list as the people dataset's `problem_topic` field. If either side ever uses a different vocabulary — free-text topics, a different controlled list, renamed tags — the bridge will degrade silently (no people will appear in the detail panel, no sidebar will fill). Audit after every dataset refresh:

```bash
python3 -c "
import json
orgs = json.load(open('data/orgs.json'))
ppl  = json.load(open('data/people.json'))
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

## Recent change log

| Date | Commit | Summary |
|---|---|---|
| 2026-05-17 | _pending_ | README: add "Gotchas & lessons" section capturing the segments parse-error story, the hardcoded-counts sync checklist for data refreshes, the shared-vocabulary requirement for the network ↔ people bridge, and other lessons from the May 2026 sessions. |
| 2026-05-14 | `f4f028c` | Network ↔ People bridge: (a) detail panel adds "People working on these problem topics" subsection (~97% org coverage); (b) people-results sidebar appears in controls when Problem area or Problem topic filters are active. Both link out to `/people/`. |
| 2026-05-14 | `4201640` | Add People & Problem Statements page (`/people/`). New 4th explore card on the hub. Sources `data/problem_statement_seeds_v5.csv` via `build_people.py` → `people.json`. 7-dimension filtering. Submit-yourself pill placeholder. People pill added to nav across all subpages. |
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
- **Suggest-an-org form** (Henry's intake): https://forms.gle/GSNh2ZqUfFG4EAzF6
- **Site repo:** https://github.com/TalR24/nycur-data-website
- **NYCuriosity Substack:** https://nycuriosity.substack.com/

---

## Glossary

- **Affinity** — Composite score 0–1 indicating how likely two orgs are working on similar things. Not a documented relationship; an inference from public-facing data.
- **TF-IDF** — Term Frequency × Inverse Document Frequency. Vectorizes text such that rare distinctive words ("procurement") matter more than ubiquitous ones ("government").
- **Jaccard** — `|A ∩ B| / |A ∪ B|` for two sets. Used for segment, problem-topic, and funder overlap.
- **Problem Area** — One of 8 broad buckets (Service Delivery, Procurement & Operations, Capacity, etc.). Coarse.
- **Problem Topic** — One of 37 fine tags (Procurement Reform, AI in Government, etc.). Maps to the `problem_statements` field in JSON output.
- **Composite score** — The weighted sum of the four affinity signals.
- **Edge threshold** — UI slider hiding edges below a certain composite score. Default 0.18.
