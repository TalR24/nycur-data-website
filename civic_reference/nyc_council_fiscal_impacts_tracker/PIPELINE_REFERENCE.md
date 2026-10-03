# NYC Council Fiscal Impacts Tracker: Pipeline Reference

Last refreshed: Oct 3 2026.

The tracker at `https://data.nycuriosity.com/civic_reference/nyc_council_fiscal_impacts_tracker/` is free and offers no data downloads. It lists NYC Council bills whose Finance Division fiscal impact statement (a `.docx` attached to the bill on Legistar) shows a new, estimable, non-zero cost or revenue. Scripts, the refresh workflow and the data files all live in this repo (`data_website/`); paths below are relative to it. Run instructions and billing rules are also in the `fiscal-impacts-tracker` skill (`/Users/troded/nycur/.claude/skills/fiscal-impacts-tracker/SKILL.md`).

`data/fiscal_impacts.json` holds the master data. On Oct 3 2026 it had 374 records, last updated 2026-10-01.

---

## Files

```
civic_reference/nyc_council_fiscal_impacts_tracker/
  index.html                  bill table (reads data/fiscal_impacts.json)
  data/fiscal_impacts.json    master data: {metadata, records[]}
  overview/                   stat pills and four charts
  agency-fiscal-impact/       chart page + data.json (enriched copy of the master data)
  cost-revenue-breakdown/     costs vs. revenue chart (reads agency-fiscal-impact/data.json)
  intro-year-impact/          impact by year legislated (reads agency-fiscal-impact/data.json)
  sponsor-fiscal-impact/      impact by prime sponsor (reads agency-fiscal-impact/data.json)
  methodology/                public methodology page
  PIPELINE_REFERENCE.md       this file

pipeline/
  fetch_fiscal_impacts.py             main pipeline (search, download, extract, filter, save)
  fetch_fiscal_impacts_historical.py  REST API enumeration for a year range (needs LEGISTAR_TOKEN)
  backfill_legistar_file.py           adds Legistar File # and a working web link to records
  claude_batch.py                     Message Batches and prompt-caching helpers
  agency_canon.py, agency_crosswalk.json   agency name normalization (NYC Open Data t3jq-9nkf)
  apply_agency_crosswalk.py           re-runs agency normalization over every record
  regenerate_agency_data.py           master data to agency-fiscal-impact/data.json
  validate_fiscal_impacts.py          regression suite for the data
  verify_fiscal.py                    independent LLM check of every record
  build_fiscal_static_snapshots.py    pre-renders overview and hub content for non-JS crawlers
  api_canary.py                       one API call per extraction schema before a paid run
  fiscal_overrides.json               audited corrections, tied to a statement by attachment_id
  no_impact_matters.json              skip list: matter id to reason
  max_refresh.json                    which ids the Max-plan routine finished this month
  tests/test_fiscal_rules.py          25 regression cases for the totals rules (plain asserts)
  cache/docx/                         downloaded statements (gitignored)
```

`pipeline/fiscal_batch_state.json` and `fiscal_batch_pending.json` exist only while a Message Batch is pending, and the workflow commits them so the next run can resume.

---

## Running the pipeline

From `data_website/`, with `pip install -r pipeline/requirements.txt` (requests, python-docx, anthropic):

```bash
python3 pipeline/fetch_fiscal_impacts.py --incremental --seed-laws auto
python3 pipeline/regenerate_agency_data.py
python3 pipeline/validate_fiscal_impacts.py
python3 pipeline/build_fiscal_static_snapshots.py
python3 pipeline/tests/test_fiscal_rules.py
```

`fetch_fiscal_impacts.py` flags:

| Flag | Effect |
|---|---|
| `--incremental` | Skip matters already in the table or on the skip list. |
| `--seed-laws YEARS` | Also check every enacted local law in `laws.json` (`2024-2026`, `2024`, `all`, or `auto` for previous plus current year). |
| `--matters IDS` | Comma-separated matter ids. With `--reextract`, limits it to those records; alone, processes exactly those laws and ignores the skip list. |
| `--reextract superseded\|all` | Replace stored records in place: `superseded` only where the page carries a newer Council statement, `all` every record with a Legistar page. |
| `--historical`, `--historical-years` | Search earlier years through the web form (slow). |
| `--resume-only` | Poll or finish a pending batch and exit; exits at once when none is pending. |
| `--emit-packets DIR`, `--ingest DIR` | Max-plan path: write one prompt per statement, then validate and finish the answers in `DIR/results/<id>.json`. No API call. |
| `--dry-run` | Process without writing output. |

Environment: `ANTHROPIC_API_KEY` for the API path; `CLAUDE_BATCH=1` submits one Message Batch (half price) and `MAX_REFRESH_GATE=1` skips ids listed in `max_refresh.json`.

Billing: the extraction model is `claude-sonnet-5` and API calls are billed per token outside Claude Max. The scheduled path therefore runs on Max first (see Automation) and uses the API only for what the routine left.

---

## How the pipeline works

1. **Find bills.** The Legistar web search with "Fiscal Impact Statement" attachment text and "All Years" scope returns about 300 matters, so every run also walks the enacted-law list `laws.json` (from the Obligations Tracker) for the previous and current year through `--seed-laws auto`.
2. **Find the statement.** Each matter's detail page lists attachments; the fiscal `.docx` is the one whose filename contains "fiscal" or "impact". Files cache in `pipeline/cache/docx/`.
3. **Pre-check.** If every dollar figure in the text is `$0` and the text has no "See below", the matter goes on the skip list as `zero_precheck` with no model call. Unreadable files are skip-listed as `unreadable_attachment`. The pre-check is bypassed on `--reextract`.
4. **Extract.** Claude returns structured JSON under a schema (fixed instructions first, document text last, so prompt caching applies). Key rules in the prompt: sponsors as last names; costs as positive numbers; a "See below" cell is read from the narrative paragraph; a cost already reflected in the City's Financial Plan is left out of every total; a program counts as time-limited only when the statement states its own end date.
5. **Totals** (`totals_from_columns`). Revenue, expenditure and capital come from the statement's "Full Fiscal Impact" column, fall back to the last fiscal-year column, and fall back to the narrative figure when the table has none. A time-limited program is totaled over its life. `net_fiscal_impact = total_revenue - total_expenditure - total_capital`, so a negative net is a net cost. `reconcile_totals` fixes a few double-counts and records them in `totals_reconciled`.
6. **Filters.** A record is dropped (and the matter skip-listed) when the cost cannot be estimated, all four totals are zero, the costs are already in the Financial Plan, or extraction failed. Mayoral budget modifications (`MN-#` titles, Charter 107(e) approvals) are excluded. A file number starting "Proposed" marks a draft bill and is excluded unless the matter is in the enacted-law list, because the statement for an amended bill's final version carries that prefix.
7. **Agency attribution** (`normalize_agency_attribution`). `agencies_abbrev` and `agencies_full` are rebuilt from the agencies in `program_breakdowns` only, names go through `agency_canon.py`, and street sign line items are credited to DOT.
8. **Overrides.** `apply_overrides` runs on every save. An entry in `fiscal_overrides.json` either removes a bill whose statement adds nothing new or pins audited totals; it applies only while the stored `attachment_id` matches, so a newer statement is read fresh. Overridden records carry `audited`.
9. **Save.** Records append to `fiscal_impacts.json` and the skip list updates.

### Historical enumeration

`fetch_fiscal_impacts_historical.py --years START-END` has two phases. Phase 1 pages `GET /v1/nyc/Matters` (OData `$top=1000`) to list matters in the range and stores them in `pipeline/cache/historical_checkpoint.json`. Phase 2 calls `GET /v1/nyc/Matters/{id}/Attachments` per matter, downloads direct `.docx` links on `nyc.legistar1.com`, extracts with the same functions and filters, and merges. It resumes from the checkpoint; `--reset` starts over, `--phase 2` skips enumeration, `--merge-only` merges only. It needs the `LEGISTAR_TOKEN` secret.

REST `MatterId` is a different id space from the web UI `LegislationDetail.aspx?ID=`. Never build a web URL from a REST id. `backfill_legistar_file.py` resolves each REST record to its web id through `laws.json` (the original is kept in `rest_matter_id`) and sets `legistar_file` and `legistar_url`.

---

## Data schema

Each record in `records[]`:

| Field | Type | Description |
|---|---|---|
| `matter_id` | string | Legistar web matter id (dedup key). |
| `legistar_guid`, `legistar_url` | string | Legistar GUID and matter page. |
| `legistar_file` | string | Legistar's own File # (`Int 0408-2024`); its year is the intro year. |
| `rest_matter_id` | string | Original REST id, on 21 records that came from the REST scraper. |
| `attachment_id` | string | Attachment id (a URL for REST-sourced records). |
| `processed_at` | string | ISO timestamp of extraction. |
| `file_number` | string | Bill number as the statement printed it. |
| `legislation_type` | string | Introduction, Pre-Considered Resolution, Pre-Considered Introduction, Preconsidered Introduction or Other. |
| `title`, `committee` | string | Bill title and Council committee. |
| `sponsors`, `prime_sponsor` | string[], string | Sponsor last names; "X (Speaker)" is the Speaker. |
| `effective_date`, `fy_first_effective`, `fy_full_impact` | string | Effective date, first affected fiscal year, full-impact fiscal year. |
| `source_of_funds` | string | "General Fund", "Federal Funds", "N/A" and similar. |
| `cost_estimable` | boolean | False when the Finance Division says costs cannot be estimated. |
| `total_revenue`, `total_expenditure` | number or null | Totals, costs positive. |
| `total_capital` | number or null | Null (not 0) when there is no capital cost. |
| `net_fiscal_impact` | number or null | Revenue minus expenditure minus capital. |
| `totals_basis` | string | Where the totals came from: `full_impact_column`, `last_year_column`, `sum_of_columns`, `document_stated`, `program_life_sum` or `mixed:...`. |
| `fiscal_table_columns` | object[] | Per column: `{label, revenue, expenditure, capital, net}`. |
| `agencies_abbrev`, `agencies_full` | string[] | Agencies that have a `program_breakdowns` entry. |
| `program_breakdowns` | object[] | Cost line items: `{agency, program, description, cost_type, amount, fy_range, offset_notes}`. |
| `impact_narrative_revenue`, `impact_narrative_expenditure` | string | The statement's two narrative paragraphs. |
| `omb_estimate_provided`, `omb_estimate_notes` | boolean, string or null | Whether OMB gave its own estimate, and what it said. |
| `estimate_prepared_by`, `estimate_reviewed_by` | string, string[] | Finance Division analyst and reviewers. |
| `date_prepared`, `hearing_date` | string or null | Preparation date; hearing date on newer statements. |
| `costs_already_in_financial_plan` | boolean | Set on 355 records; true means a cost was left out of the totals. |
| `time_limited_program`, `sunset_quote`, `program_end_fy` | boolean, string, number | A program with a stated end, the statement's sentence that says so, and the last fiscal year. |
| `outlasts_statement` | boolean | The program runs past the statement's columns, so totals use the annual figure. |
| `expenditure_is_savings` | boolean | The statement describes the expenditure figure as savings. |
| `recurring_annual_expenditure` | number | Ongoing yearly cost when the Full column includes one-time costs. |
| `see_below_categories` | string[] | Categories (revenue, expenditure, capital) whose figure came from the narrative. |
| `totals_reconciled` | string | Reconciliation applied to the totals, if any. |
| `audited` | string | Audit round that pinned this record through `fiscal_overrides.json`. |

Rules enforced in code: costs are always positive; a negative revenue is a revenue reduction counted as cost; balanced budgets (revenue equals expenditure) stay in the table; only all-zero records are excluded.

---

## Frontend pages

- **Bill table** (`index.html`). Fetches `./data/fiscal_impacts.json`. Default sort is `date_prepared` descending, falling back to the year in the file number. Search matches bill number or title; multiselect filters cover type, agency, committee, sponsor, full-impact fiscal year and net impact sign. Clicking a row opens the per-column table, program breakdowns, narratives, OMB estimate, pilot notes and the Legistar link.
- **Overview** (`overview/`), **agency** (`agency-fiscal-impact/`), **costs vs. revenue** (`cost-revenue-breakdown/`), **year legislated** (`intro-year-impact/`) and **prime sponsor** (`sponsor-fiscal-impact/`) are chart pages on the shared chart system (`assets/chart.css`, `assets/chart.js`) with the pill nav linking the set. The four chart pages read `agency-fiscal-impact/data.json`; the overview reads that file and the master data.
- `regenerate_agency_data.py` builds that file. It adds `intro_year` (from the File # year, then `date_prepared`, then the file number) and `fy_first_normalized`, and rebuilds the filter option lists.
- Inside the overview and the hub, `<!-- static:<id>:start/end -->` blocks hold pre-rendered copies of the JS-built content (top 10 rows at most) so crawlers that do not run JavaScript read real numbers. `build_fiscal_static_snapshots.py` writes them.

---

## Automation

`.github/workflows/refresh_fiscal_data.yml`:

| Trigger | When (UTC) | What runs |
|---|---|---|
| Cron | 1st of the month, 18:23 | Full pipeline in batch mode with `MAX_REFRESH_GATE=1`, then `regenerate_agency_data.py`, `validate_fiscal_impacts.py` (never blocks the commit), both static-snapshot builders, commit and push. |
| Cron | 2nd to 7th, 12:00 | `--resume-only`: finishes a pending batch, otherwise exits with no API call. |
| Manual | any | Inputs: `sync`, `incremental`, `seed_laws`, `reextract`, `matters`, `rest_years` (runs the REST enumeration and `backfill_legistar_file.py`). |

The Claude cloud routine "NYC Council trackers monthly refresh" (1st, 12:17 UTC, Max plan) runs first: it fetches with these scripts, extracts through `--emit-packets` and `--ingest`, and commits `pipeline/max_refresh.json`. The workflow's gate then skips every id the routine finished, so the API is billed only for the remainder. The workflow runs one at a time (`concurrency: fiscal-data`), uploads the data files as the `fiscal-data` artifact for 30 days, and retries the push with backoff.

Secrets by name: `ANTHROPIC_API_KEY`, `LEGISTAR_TOKEN` (REST enumeration only).

---

## Fiscal impact statement formats

- **Current template (about 2020 onward):** header "City Council Estimate:", three columns (Effective FY, FY Succeeding, Full Fiscal Impact), rows for revenues, expenditures and net, plus an OMB estimate section and a hearing date.
- **Older template:** header "Fiscal Impact Statement:", column labels vary with the bill, rows for revenues, expense and sometimes capital, no OMB section or hearing date.
- **Narrative statements (common before 2019):** no table; the cost is prose such as "estimated to increase expenditures by $1.6 million annually". The prompt builds a single "Total" column from the narrative (`totals_basis` `document_stated`).
