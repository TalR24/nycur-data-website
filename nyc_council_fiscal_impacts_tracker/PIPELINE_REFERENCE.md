# NYC Council Fiscal Impacts Tracker — Pipeline Reference

This document is the complete reference for running, maintaining, and extending the NYC Council Fiscal Impacts Tracker. Read it before touching the pipeline, data, or frontend.

---

## What This Is

An interactive data tool at `data.nycuriosity.com/nyc_council_fiscal_impacts_tracker/` that lets users explore the estimated fiscal impact of NYC City Council legislation. It covers Introductions and Resolutions that have a fiscal impact statement attachment on NYC Legistar, where the Finance Division estimated a **non-zero** fiscal impact.

**Live URL:** `https://data.nycuriosity.com/nyc_council_fiscal_impacts_tracker/`  
**GitHub repo:** `TalR24/nycur-data-website`  
**Current record count:** ~19 bills (2024–2026, as of April 2026)

---

## File Structure

```
data_website/
├── nyc_council_fiscal_impacts_tracker/
│   ├── index.html                     ← Frontend: interactive tracker page
│   ├── data/
│   │   └── fiscal_impacts.json        ← Data file read by the frontend
│   └── PIPELINE_REFERENCE.md          ← This file
│
├── pipeline/
│   ├── fetch_fiscal_impacts.py        ← Main pipeline script
│   ├── requirements.txt               ← Python dependencies
│   ├── .gitignore                     ← Ignores cache/ folder
│   └── cache/
│       └── docx/                      ← Downloaded .docx files (gitignored, local only)
│
└── .github/
    └── workflows/
        └── refresh_fiscal_data.yml    ← Monthly GitHub Actions cron job
```

---

## Running the Pipeline

### Prerequisites

```bash
pip install -r pipeline/requirements.txt
# Packages: requests, python-docx, anthropic
```

### Environment variable required

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Get/manage keys at `console.anthropic.com`. Make sure the account has credits — Claude Haiku is used for extraction and is cheap (~$0.001 per document).

For GitHub Actions, the key is stored as a repository secret: `Settings → Secrets → ANTHROPIC_API_KEY`.

### Run command

```bash
cd /path/to/data_website
python3 pipeline/fetch_fiscal_impacts.py --years 2024,2025,2026
```

Add `--incremental` to skip matter IDs already present in `fiscal_impacts.json` (used by GitHub Actions to avoid reprocessing):

```bash
python3 pipeline/fetch_fiscal_impacts.py --years 2024,2025,2026 --incremental
```

Add `--dry-run` to process without writing output (useful for testing):

```bash
python3 pipeline/fetch_fiscal_impacts.py --years 2024,2025,2026 --dry-run
```

### Adding historical data

To expand to earlier years, add them to the `--years` flag:

```bash
python3 pipeline/fetch_fiscal_impacts.py --years 2018,2019,2020,2021,2022,2023
```

The docx cache prevents re-downloading already-fetched files. The incremental flag prevents re-processing already-extracted matter IDs. Run in batches if doing a full history pull.

---

## How the Pipeline Works

### Step 1 — Legistar search (no API token required)

The NYC Legistar REST API requires a registered token. This pipeline uses the **public web interface** instead, which requires no authentication. It POSTs to the Legistar legislation search form with:
- Search text: `"Fiscal Impact Statement"`
- Search scope: Attachments only
- Year: the target year
- Type: All Types

The response HTML contains matter IDs and GUIDs as links of the form:
`LegislationDetail.aspx?ID={matter_id}&GUID={guid}`

These are extracted with regex. **Note:** Legistar uses Telerik RadGrid with AJAX pagination — only the first page of results is captured per year search. For 2024–2026 this appears sufficient. Pagination handling is a future improvement if needed for years with very high bill counts.

### Step 2 — Find fiscal impact attachment

For each matter, the pipeline fetches the matter detail page (with `Options=Attachments|`) and finds download links of the form `View.ashx?M=F&ID={att_id}&GUID={att_guid}`. It does a HEAD request on each attachment and checks the `Content-Disposition` header for "fiscal" or "impact" in the filename. The naming convention is consistent: `"Fiscal Impact Statement - City Council.docx"` (newer) or `"Fiscal Impact Statement.docx"` (older).

### Step 3 — Download and cache .docx

Files are downloaded to `pipeline/cache/docx/{att_id}.docx`. On subsequent runs, cached files are reused — no re-download.

### Step 4 — Pre-check (skip obvious zero-cost bills)

Before calling Claude, the raw docx text is scanned for non-zero dollar amounts. If every dollar figure in the document is `$0` and there's no "See below" language, the bill is skipped entirely. This avoids ~80% of Claude API calls since most legislation has $0 fiscal impact.

### Step 5 — Claude extraction

`claude-haiku-4-5-20251001` is called with a structured prompt asking for a JSON object. The prompt explicitly instructs:
- Strip "Council Member/Council Members" prefix from all sponsor names
- Return only last names for sponsors (the fiscal impact statements only include last names)
- Handle "The Speaker (Council Member X)" → "X (Speaker)"
- Sum all fiscal year columns for the `total_*` fields
- Use `null` for unestimable values, `0` for explicit zeros
- `net_fiscal_impact = total_revenue - total_expenditure - total_capital` (negative = net cost)

Retry logic: 3 attempts with exponential backoff on API errors.

### Step 6 — Post-extraction filter

After Claude returns data, bills are discarded if:
- `cost_estimable` is `false` (Finance Division said it can't estimate costs)
- All of `total_expenditure`, `total_capital`, `total_revenue`, `net_fiscal_impact` are zero
- `extraction_error` is present (Claude failed to return valid JSON)

### Step 7 — Write output

All passing records are written to `fiscal_impacts.json`. The file structure is:

```json
{
  "metadata": {
    "last_updated": "2026-04-09T...",
    "total_records": 19,
    "years_searched": [2024, 2025, 2026],
    "source": "NYC Legistar (legistar.council.nyc.gov)"
  },
  "records": [...]
}
```

---

## Data Schema

Each record in `records[]`:

| Field | Type | Description |
|---|---|---|
| `matter_id` | string | Legistar internal matter ID (unique key for deduplication) |
| `legistar_guid` | string | Legistar GUID |
| `legistar_url` | string | Direct URL to Legistar matter page |
| `attachment_id` | string | Attachment ID for the fiscal impact docx |
| `processed_at` | string | ISO timestamp of when this record was extracted |
| `file_number` | string | Bill number (e.g. "Int. No. 692", "Res. No. 1234-A") |
| `legislation_type` | string | "Introduction", "Resolution", "Pre-Considered Resolution", "Other" |
| `title` | string | Full title of the legislation |
| `committee` | string | Council committee (e.g. "Transportation", "Finance") |
| `sponsors` | string[] | All sponsor last names, cleaned (e.g. ["Lee", "Louis"]) |
| `prime_sponsor` | string | First listed sponsor's last name (e.g. "Lee") |
| `effective_date` | string | When the law takes effect (e.g. "120 days after becoming law") |
| `fy_first_effective` | string | First fiscal year affected (e.g. "FY26") |
| `fy_full_impact` | string | Fiscal year of full impact (e.g. "FY27") |
| `source_of_funds` | string | "General Fund", "N/A", "Federal Funds", etc. |
| `cost_estimable` | boolean | False if Finance Division said costs can't be estimated |
| `total_revenue` | number\|null | Sum of all revenue columns (positive) |
| `total_expenditure` | number\|null | Sum of all expense/operational cost columns (positive) |
| `total_capital` | number\|null | Sum of all capital cost columns (positive); null if no capital |
| `net_fiscal_impact` | number\|null | `revenue - expenditure - capital`; negative = net cost to city |
| `fiscal_table_columns` | object[] | Per-column breakdown: `{label, revenue, expenditure, capital, net}` |
| `agencies_abbrev` | string[] | Agency abbreviations (e.g. ["DOT", "DPR"]) |
| `agencies_full` | string[] | Full agency names |
| `program_breakdowns` | object[] | Named cost line items: `{agency, program, description, cost_type, amount, fy_range, offset_notes}` |
| `impact_narrative_revenue` | string | Full "Impact on Revenues" paragraph |
| `impact_narrative_expenditure` | string | Full "Impact on Expenditures" paragraph |
| `omb_estimate_provided` | boolean | Whether OMB provided a separate estimate |
| `omb_estimate_notes` | string\|null | What OMB said (or null) |
| `estimate_prepared_by` | string | Finance Division analyst name |
| `estimate_reviewed_by` | string[] | Reviewer names |
| `date_prepared` | string | Date the fiscal impact statement was prepared |
| `hearing_date` | string\|null | Committee hearing date (newer bills only) |

### Key quirks

- **Capital costs**: Only present on infrastructure-heavy bills. Most bills have `total_capital: null`, not `0`.
- **Fiscal table columns**: Vary by bill. Newer template has 3 standard columns (Effective FY, FY Succeeding, Full Fiscal Impact FY). Older bills have custom column structures (e.g., Streets Plan had 5-year plan periods).
- **Budget modifications** (Pre-Considered Resolutions like MN-6): Have large balanced revenue=expenditure, net=$0 — these will be filtered out by the zero-impact check. If you want budget modifications included, the filter logic needs adjustment.
- **Sponsor names**: Last names only, as written in the fiscal impact statement. The Finance Division never includes first names. "Menin (Speaker)" indicates The Speaker.

---

## Known Issues and Fixes Applied

### 1. Duplicate records from overlapping year searches
**Problem:** Searching years 2024, 2025, 2026 separately caused the same bills to appear in multiple year results, storing them multiple times and inflating totals.  
**Fix:** Deduplication by `matter_id` was applied to clean historical data. The `--incremental` flag on future runs prevents re-adding already-stored matter IDs.  
**Prevention:** Always use `--incremental` in GitHub Actions (already configured).

### 2. Sponsor names with "Council Member" prefix
**Problem:** Claude inconsistently stripped the "Council Member / Council Members / By Council Members / (s):" prefix, resulting in "Council Members Lee" and "Lee" as different values for the same person.  
**Fix:** A normalization pass was applied to all existing records. The extraction prompt now explicitly instructs Claude to strip all prefixes and return last name only.  
**If it recurs:** Run this normalization script on the JSON:
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

### 3. Python 3.9 type hint incompatibility
**Problem:** `str | None` union type syntax requires Python 3.10+. The script uses Python 3.9 on the local machine.  
**Fix:** Added `from __future__ import annotations` at the top of `fetch_fiscal_impacts.py`. GitHub Actions uses Python 3.11, so no issue there.

### 4. GitHub push authentication
**Problem:** The local git credential is cached as `troded_LinkedIn` which doesn't have push access to `TalR24/nycur-data-website`.  
**Fix:** Set the remote URL with the PAT embedded:
```bash
git remote set-url origin https://TalR24:{PAT}@github.com/TalR24/nycur-data-website.git
```
The PAT is stored in Claude memory (`reference_github.md`).

---

## Fiscal Impact Statement Document Formats

Two template variants exist across the Council's history:

**New template (~2020–present):**
- Header: "City Council Estimate:"
- 3 standard columns: "Effective FY{N}", "FY Succeeding Effective FY{N+1}", "Full Fiscal Impact FY{N+1}"
- Rows: Revenues (+), Expenditures (−), Net
- Includes "Office of Management and Budget Estimate:" section
- Includes "Hearing/Meeting Date:" field

**Old template (pre-~2020):**
- Header: "Fiscal Impact Statement:"
- Column structure varies — custom labels based on legislation scope
- Rows: Revenues, Expense, Capital (sometimes), Net
- No OMB section
- No hearing date field

The extraction prompt handles both.

---

## Frontend Notes

**File:** `nyc_council_fiscal_impacts_tracker/index.html`  
**Data source:** Fetches `./data/fiscal_impacts.json` on page load.  
**No build step** — pure HTML/CSS/JS, same pattern as all other data website pages.

### Filters available
- Text search (bill number or title keyword)
- Type (Introduction / Resolution / Pre-Considered Resolution)
- Agency (from `agencies_abbrev[]`)
- Committee
- Prime Sponsor
- Full Impact FY (from `fy_full_impact`)
- Net Impact sign (cost / revenue / zero / unknown)

### Running totals
The results bar above the table shows net impact, expense, capital, and revenue summed across the current filtered view — useful for aggregate queries like "total DOT expenditure in FY27 from bills sponsored by council member X."

### Row detail panel
Click any row to expand: shows the full fiscal table (per-column), program breakdowns if available, revenue/expenditure narratives, OMB estimate, and a link to Legistar.

### Adding a new filter column
1. Add the filter `<select>` in the filter-section HTML
2. Populate it in `populateFilters()`
3. Add the filter logic in `applyFilters()`

---

## GitHub Actions Auto-Refresh

**File:** `.github/workflows/refresh_fiscal_data.yml`  
**Schedule:** 1st of each month at 7:00 AM UTC  
**Can also be triggered manually:** Actions tab → "Refresh NYC Council Fiscal Impacts" → Run workflow

The workflow:
1. Checks out repo
2. Installs Python 3.11 + dependencies
3. Runs `fetch_fiscal_impacts.py --years 2024,2025,2026 --incremental`
4. Commits and pushes `fiscal_impacts.json` if changed

**Required secret:** `ANTHROPIC_API_KEY` in repo settings → Secrets → Actions.

To add more years to the scheduled run, edit the `years` default in the workflow file.

---

## Extending the Dataset

### To add historical years
```bash
python3 pipeline/fetch_fiscal_impacts.py --years 2014,2015,2016,2017,2018,2019,2020,2021,2022,2023
```
The existing 19 records will be preserved (pipeline appends, doesn't overwrite). Run in batches by era to avoid very long single runs.

### To add a new field to the schema
1. Add the field to the extraction prompt in `fetch_fiscal_impacts.py` (in the JSON template and in the RULES section if it needs special handling)
2. Add the field to the detail panel HTML in `index.html`
3. If it should be filterable, add it to the filter bar
4. For existing records, you'd need to re-run extraction without `--incremental` (or write a one-off script to backfill)

### To change what's filtered out
Edit `record_has_fiscal_impact()` in `fetch_fiscal_impacts.py`. Currently excludes: `cost_estimable=False`, all-zero values, extraction errors. If you want to include budget modifications (which have large balanced revenue=expenditure, net=$0), you would need a different filter condition.

### To improve extraction accuracy
Edit the `EXTRACTION_PROMPT` constant in `fetch_fiscal_impacts.py`. The prompt is passed the full docx text (up to 18,000 characters). If certain fields are consistently wrong for a bill type, add a targeted rule to the RULES section.
