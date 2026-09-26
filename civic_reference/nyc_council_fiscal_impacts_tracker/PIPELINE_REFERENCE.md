# NYC Council Fiscal Impacts Tracker — Pipeline Reference

The tracker is free (no paywall, no data downloads, since Sep 24 2026). Pipeline scripts, the monthly refresh GitHub Action, and the data files all live in this repo (`data_website/`); paths below are relative to it.

For running the pipeline, environment variables, and current ops details, see the `fiscal-impacts-tracker` skill (`/Users/troded/nycur/.claude/skills/fiscal-impacts-tracker/SKILL.md`). This document keeps the schema and frontend reference below, which is still accurate.

---

## What This Is

An interactive data tool at `data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/` that lets users explore the estimated fiscal impact of NYC City Council legislation. It covers Introductions and Resolutions that have a fiscal impact statement attachment on NYC Legistar, where the Finance Division estimated a **non-zero** fiscal impact.

**Live URL:** `https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/`
**GitHub repo:** `TalR24/nycur-data-website`
**Current record count:** see `data/fiscal_impacts.json` (dated counts live in the `fiscal-impacts-tracker` skill, not here)

---

## File Structure

```
data_website/
├── civic_reference/nyc_council_fiscal_impacts_tracker/
│   ├── index.html                          ← Frontend: interactive bill table page
│   ├── PIPELINE_REFERENCE.md               ← This file
│   ├── data/
│   │   └── fiscal_impacts.json             ← Master data file (record count in the fiscal-impacts-tracker skill)
│   └── agency-fiscal-impact/
│       ├── index.html                      ← Bar chart: fiscal impact by agency
│       └── data.json                       ← Enriched data for the agency chart
│
├── pipeline/
│   ├── fetch_fiscal_impacts.py             ← Incremental pipeline (2024+)
│   ├── fetch_fiscal_impacts_historical.py  ← Historical scraper (2014–2023, needs Legistar token)
│   ├── requirements.txt                    ← Python dependencies
│   ├── .gitignore                          ← Ignores cache/ folder
│   └── cache/
│       ├── docx/                           ← Downloaded .docx files (gitignored)
│       └── historical_checkpoint.json      ← Historical run resume state (gitignored)
│
└── .github/
    └── workflows/
        └── refresh_fiscal_data.yml         ← Monthly GitHub Actions cron job
```

---

## Running the Pipeline

Full run instructions (prerequisites, environment variables, incremental and historical runs, current flags including `--seed-laws`, `--matters`, `--reextract`, and `fiscal_overrides.json`) live in the `fiscal-impacts-tracker` skill. The model is `claude-sonnet-5` (`pipeline/fetch_fiscal_impacts.py`), not Haiku.

**After any pipeline run that adds new records**, regenerate `agency-fiscal-impact/data.json`:

```bash
cd data_website
python3 pipeline/regenerate_agency_data.py
```

`regenerate_agency_data.py` is the current generator (it also applies the Legistar File # intro-year rule); it replaces the inline script this doc used to carry, which had drifted out of sync with it.

---

## How the Pipeline Works

### Incremental pipeline (`fetch_fiscal_impacts.py`)

**Step 1 — Legistar web search**
POSTs to the Legistar legislation search form with `"Fiscal Impact Statement"` as attachment search text, `"All Years"` scope, and paginates through all result pages using ASP.NET RadGrid `__doPostBack` events. Returns `(matter_id, guid)` tuples.

**Step 2 — Find fiscal attachment**
For each matter, fetches the detail page and HEAD-checks each attachment. Identifies the fiscal impact .docx by `"fiscal"` or `"impact"` in the `Content-Disposition` filename.

**Step 3 — Download and cache**
Downloads to `pipeline/cache/docx/{att_id}.docx`. Cached files are reused on subsequent runs.

**Step 4 — Pre-check (skip zero-impact bills)**
Scans raw docx text for non-zero dollar amounts before calling Claude. Skips the API call if every dollar figure is `$0` and there's no "See below" language. Saves ~80% of Claude calls.

**Step 5 — Claude extraction**
`claude-haiku-4-5-20251001` returns structured JSON. Key extraction rules:
- Strip all sponsor name prefixes ("Council Member", "Council Members", "By Council Members")
- Last names only for sponsors
- Sum all fiscal year columns for `total_*` fields
- `net_fiscal_impact = total_revenue - total_expenditure - total_capital` (negative = net cost)
- Only list agencies in `agencies_abbrev` that have a line item in `program_breakdowns`
- Assign `agency="DOT"` to any street sign installation/fabrication line item

**Step 6 — Post-extraction filters**
After extraction, records are discarded if:
- `cost_estimable` is `false` (Finance Division said costs can't be estimated)
- All of `total_expenditure`, `total_capital`, `total_revenue`, `net_fiscal_impact` are zero
- `extraction_error` is present (Claude failed to return valid JSON)
- Title matches `MN-\d+` pattern (budget modification resolutions — Charter §107(e) administrative approvals, not independent legislation)
- `file_number` starts with "Proposed" (e.g. "Proposed Int. No. 893-A" — draft legislation not yet enacted as a local law)

**Step 7 — Agency normalization** (`normalize_agency_attribution`)
Applied after passing the filters:
1. Any `program_breakdowns` entry whose program/description mentions street sign installation → `agency = "DOT"`
2. Rebuild `agencies_abbrev`/`agencies_full` from only the agencies appearing in `program_breakdowns`

**Step 8 — Write output**
Passing records appended to `fiscal_impacts.json`.

### Historical scraper (`fetch_fiscal_impacts_historical.py`)

Imports all shared functions from `fetch_fiscal_impacts.py` (including filters and normalization). Applies identical post-extraction logic.

**Phase 1 (REST API enumeration):** `GET /v1/nyc/Matters` with OData pagination ($top=1000) to enumerate all 16,339 NYC Council matters. Stores `matter_id → {guid, file_number}` in checkpoint. Requires Legistar token.

**Phase 2 (attachment check + extraction):** For each matter, calls `GET /v1/nyc/Matters/{id}/Attachments` to find fiscal attachment URLs (direct `.docx` links on `nyc.legistar1.com`). Downloads, extracts, filters, and merges.

**Critical ID note:** Legistar REST API `MatterId` ≠ web UI `LegislationDetail.aspx?ID=`. The REST API uses its own ID system. Never try to construct a web UI URL from a REST API matter ID — it will return "Invalid parameters!".

---

## Data Schema

Each record in `records[]`:

| Field | Type | Description |
|---|---|---|
| `matter_id` | string | Legistar internal matter ID (unique dedup key) |
| `legistar_guid` | string | Legistar GUID |
| `legistar_url` | string | Direct URL to Legistar matter page |
| `attachment_id` | string | Attachment ID (numeric for web scraper; URL for REST API) |
| `processed_at` | string | ISO timestamp when this record was extracted |
| `file_number` | string | Bill number (e.g. "Int. No. 692", "Int 0360-2014") |
| `legislation_type` | string | "Introduction", "Resolution", "Pre-Considered Resolution", "Other" |
| `title` | string | Full title of the legislation |
| `committee` | string | Council committee (e.g. "Transportation", "Finance") |
| `sponsors` | string[] | All sponsor last names, cleaned |
| `prime_sponsor` | string | First listed sponsor's last name |
| `effective_date` | string | When the law takes effect |
| `fy_first_effective` | string | First fiscal year affected (e.g. "FY26") |
| `fy_full_impact` | string | Fiscal year of full impact (e.g. "FY27") |
| `source_of_funds` | string | "General Fund", "N/A", "Federal Funds", etc. |
| `cost_estimable` | boolean | False if Finance Division said costs can't be estimated |
| `total_revenue` | number\|null | Sum of all revenue columns (positive) |
| `total_expenditure` | number\|null | Sum of all expense/operational cost columns (positive) |
| `total_capital` | number\|null | Sum of all capital cost columns (positive); null if no capital |
| `net_fiscal_impact` | number\|null | `revenue - expenditure - capital`; negative = net cost |
| `fiscal_table_columns` | object[] | Per-column breakdown: `{label, revenue, expenditure, capital, net}` |
| `agencies_abbrev` | string[] | Agency abbreviations (only agencies with program_breakdowns entries) |
| `agencies_full` | string[] | Full agency names (parallel to agencies_abbrev) |
| `program_breakdowns` | object[] | Named cost line items: `{agency, program, description, cost_type, amount, fy_range, offset_notes}` |
| `impact_narrative_revenue` | string | Full "Impact on Revenues" paragraph |
| `impact_narrative_expenditure` | string | Full "Impact on Expenditures" paragraph |
| `omb_estimate_provided` | boolean | Whether OMB provided a separate estimate |
| `omb_estimate_notes` | string\|null | What OMB said (or null) |
| `estimate_prepared_by` | string | Finance Division analyst name |
| `estimate_reviewed_by` | string[] | Reviewer names |
| `date_prepared` | string | Date the fiscal impact statement was prepared (may be null for older bills) |
| `hearing_date` | string\|null | Committee hearing date (newer bills only) |

### Key data rules (enforced by pipeline)

- **`total_capital`**: `null` (not `0`) when no capital costs exist.
- **`net_fiscal_impact`**: `revenue - expenditure - capital`. Negative = net cost to city.
- **`agencies_abbrev`**: Only agencies with at least one `program_breakdowns` entry. Agencies that appear only in narrative text (OMB as reviewer, IBO as analyst, NYC Council as introducer) are excluded.
- **Street signs**: Any program_breakdown line item about street sign installation/fabrication is credited to DOT, regardless of what the document says.
- **Budget modifications** (MN-# resolutions): Excluded at pipeline level. These are Charter §107(e) administrative budget approvals, not independent legislation.
- **Balanced budgets** (revenue = expenditure, net = 0): Included. The filter only excludes bills where ALL values are zero.
- **Sponsor names**: Last names only. "X (Speaker)" indicates The Speaker.

---

## Frontend Pages

### Bill table (`index.html`)
Fetches `./data/fiscal_impacts.json`. Default sort: `date_prepared` descending (most recent first), with fallback to the year in the file_number for bills without `date_prepared`.

**Filters:** Text search, type, agency, committee, prime sponsor, full impact FY, net impact sign.
**Sort columns:** Date prepared, net fiscal impact, expenditure, capital, revenue.
**Row detail panel:** Click any row — shows per-column fiscal table, program breakdowns, narratives, OMB estimate, Legistar link.

### Agency bar chart (`agency-fiscal-impact/index.html`)
Fetches `./data.json` (the enriched file). Shows top-25 agencies by absolute value of selected metric.

**Metric toggles:** Net Fiscal Impact | Operational Expense | Capital Expense | Revenue
**Filters:** Committee, Prime Sponsor, Bill Intro Year, First Fiscal Year, Expense Type
**Stat pills:** Bills, net, operational, capital, revenue totals for current filter set.
**Chart nav strip:** "Charts in this tracker" pill nav links between the bill table and the agency chart. Active page = solid blue pill.

---

## Known Issues Fixed

| Issue | Fix |
|---|---|
| Legistar year filter non-functional | Pipeline uses "All Years" + pagination |
| Budget modifications (MN-#) appearing in table | Excluded via `is_budget_modification()` filter in both pipeline scripts |
| Agencies from narrative text only (OMB, IBO, NYC Council) in agencies_abbrev | `normalize_agency_attribution()` prunes to program_breakdown agencies only |
| Street signs credited to DPR, NYPD, DCAS, or None | `normalize_agency_attribution()` reassigns to DOT |
| Historical bills without date_prepared sorting wrong | Table sort falls back to year extracted from file_number |
| Sponsor name prefix ("Council Members Lee") | Prompt instructs Claude to strip all prefixes; normalization script available below |
| Narrative-format fiscal statements (pre-2019 prose) | EXTRACTION_PROMPT has a "NARRATIVE FORMAT" rules section |
| Legistar REST API ID ≠ web UI ID | Historical scraper uses `/Matters/{id}/Attachments` endpoint, never constructs web URLs from REST IDs |
| Python 3.9 type hint incompatibility | `from __future__ import annotations` at top of both scripts |

### Sponsor name normalization (if needed)
```python
import re
def normalize_name(name):
    name = (name or '').strip()
    m = re.match(r'^The\s+Speaker\s+\(Council\s+Member\s+([^)]+)\)', name, re.I)
    if m: return m.group(1).strip() + ' (Speaker)'
    name = re.sub(r'^\(s\):\s*(By\s+)?', '', name, flags=re.I)
    name = re.sub(r'^By\s+Council\s+Members?\s+', '', name, flags=re.I)
    name = re.sub(r'^Council\s+Members?\s+', '', name, flags=re.I)
    return name.strip()
```

---

## Fiscal Impact Statement Document Formats

**New template (~2020–present):**
- Header: "City Council Estimate:"
- 3 standard columns: "Effective FY{N}", "FY Succeeding Effective FY{N+1}", "Full Fiscal Impact FY{N+1}"
- Rows: Revenues (+), Expenditures (−), Net
- Includes OMB estimate section and hearing date field

**Old template (pre-~2020):**
- Header: "Fiscal Impact Statement:"
- Column structure varies — custom labels based on legislation scope
- Rows: Revenues, Expense, Capital (sometimes), Net
- No OMB section, no hearing date

**Narrative format (pre-2019, common):**
- No structured table at all — fiscal impact stated as prose paragraphs
- Example: "This legislation is estimated to increase expenditures by $1.6 million annually"
- The EXTRACTION_PROMPT "NARRATIVE FORMAT" rules section handles this, instructing Claude to synthesize totals from narrative text

---

## GitHub Actions Auto-Refresh

**File:** `.github/workflows/refresh_fiscal_data.yml`
**Schedule:** 1st of each month at 11:23 UTC (can be triggered manually); current cron and env vars are in the workflow file and the `fiscal-impacts-tracker` skill, not repeated here.

The workflow runs `fetch_fiscal_impacts.py --incremental` and commits `fiscal_impacts.json` if changed. The historical scraper only runs on manual dispatch with a `rest_years` input, using the `LEGISTAR_TOKEN` repository secret (not skipped for lack of a secret, as this doc previously said).

---

## Legistar REST API Notes

- **Base URL:** `https://webapi.legistar.com/v1/nyc`
- **Token:** A public 2017 read-only token is stored in Claude memory (`reference_github.md`). Pass via `--token` arg or `LEGISTAR_TOKEN` env var.
- **Pagination:** `$top=1000&$skip=N` (OData). 16,339 total matters as of April 2026.
- **Matters endpoint:** `GET /v1/nyc/Matters?$filter=MatterIntroDate ge datetime'...'`
- **Attachments endpoint:** `GET /v1/nyc/Matters/{MatterId}/Attachments` — returns `MatterAttachmentHyperlink` as a direct `.docx` URL on `nyc.legistar1.com`
- **ID warning:** `MatterId` from the REST API ≠ `ID` parameter in the web UI. Do not mix them.
