#!/usr/bin/env python3
"""
NYC Council Fiscal Impacts Pipeline
Fetches fiscal impact statement .docx files from NYC Legistar, extracts structured
data using the Claude API, and writes results to fiscal_impacts.json for the
data website.

Usage:
    python fetch_fiscal_impacts.py
    python fetch_fiscal_impacts.py --incremental
    python fetch_fiscal_impacts.py --incremental --historical
    python fetch_fiscal_impacts.py --incremental --historical --historical-years 2010-2023
    python fetch_fiscal_impacts.py --seed-laws auto
    python fetch_fiscal_impacts.py --matters 12345,67890
    python fetch_fiscal_impacts.py --reextract superseded
    python fetch_fiscal_impacts.py --dry-run
    python fetch_fiscal_impacts.py --help

Environment variables required:
    ANTHROPIC_API_KEY   Your Anthropic API key

Notes:
    - Uses Legistar's public web interface (no API token required)
    - Caches downloaded .docx files in pipeline/cache/docx/ to avoid re-downloading
    - Run with --incremental in GitHub Actions to only process new matters
    - --seed-laws checks laws.json directly for fiscal statements Legistar's
      attachment search misses; --matters targets specific matter ids;
      --reextract replaces records already in the table in place
    - fiscal_overrides.json applies blind-audit corrections on every save
"""

from __future__ import annotations

import os
import re
import sys
import json
import subprocess
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import requests
from docx import Document
import anthropic

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
REPO_ROOT    = SCRIPT_DIR.parent   # data_website/ root (this repo)
CACHE_DIR    = SCRIPT_DIR / "cache" / "docx"
OUTPUT_PATH  = REPO_ROOT / "civic_reference" / "nyc_council_fiscal_impacts_tracker" / "data" / "fiscal_impacts.json"
BASE_URL     = "https://legistar.council.nyc.gov"
# Matters already downloaded and found to have no storable fiscal impact
# (all-zero, unestimable, budget modification, proposed). Committed by the
# monthly Action so they are not re-downloaded and re-extracted every run.
SKIP_PATH    = SCRIPT_DIR / "no_impact_matters.json"
SKIP_ATT_PATH = SCRIPT_DIR / "skip_attachments.json"   # matter_id -> attachment the skip was judged on
# Enacted-law universe from the implementation tracker (web matter_id + GUID).
LAWS_PATH    = REPO_ROOT / "civic_reference" / "legislation_implementation_tracker" / "data" / "laws.json"
# Sonnet 5 since Sep 24 2026: Haiku 4.5 misapplied the judgment rules (lowest
# "at least" scenario, whether the costed program itself sunsets) in blind
# audit rounds 3 and 4; Tal approved the switch
CLAUDE_MODEL = "claude-sonnet-5"
# Sonnet 5 (and the Haiku 4.5 it replaced) reads far more than this; 18,000
# chars (~4.5K tokens) cut the end of long statements, where the OMB section,
# preparer and date live, so the cap stays generous rather than tight to the
# model's context window.
FIS_TEXT_CAP = 150_000

# ── Output schema (structured outputs: the API guarantees parseable JSON) ────
# The API caps union types per schema (30 nullable fields were rejected, Sep 24
# 2026), so text fields are plain strings ("" = missing, turned back into None
# by _blank_to_none) and only numbers whose "unknown" matters stay nullable.
_NUM_OR_NULL = {"anyOf": [{"type": "number"}, {"type": "null"}]}
_BOOL_OR_NULL = {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
_STR = {"type": "string"}


def _obj(props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_STR_LIST = {"type": "array", "items": _STR}
FISCAL_SCHEMA = _obj({
    "file_number": _STR, "legislation_type": _STR, "title": _STR, "committee": _STR,
    "sponsors": _STR_LIST, "prime_sponsor": _STR, "effective_date": _STR,
    "fy_first_effective": _STR, "fy_full_impact": _STR, "source_of_funds": _STR,
    "cost_estimable": {"type": "boolean"},
    "costs_already_in_financial_plan": {"type": "boolean"},
    "time_limited_program": {"type": "boolean"},
    "sunset_quote": _STR,
    # a genuine reduction in city spending (net positive), not a cost, per the
    # savings rule in totals_from_columns(); null/false for an ordinary cost.
    "expenditure_is_savings": _BOOL_OR_NULL,
    # the recurring annual cost when the statement separates it from one-time
    # start-up costs that sit in the Full Fiscal Impact column (audit 10
    # corpus sweep, Sep 28 2026: 9 of 104 checked bills overstated)
    "recurring_annual_expenditure": _NUM_OR_NULL,
    "total_revenue": _NUM_OR_NULL, "total_expenditure": _NUM_OR_NULL,
    "total_capital": _NUM_OR_NULL, "net_fiscal_impact": _NUM_OR_NULL,
    # which categories' table cells read "(See Below)"/were blank for every
    # column, pointing to the narrative for the real figure — even where the
    # model still wrote that narrative figure into the Full column, so
    # totals_from_columns() can label the basis document_stated, not
    # full_impact_column (Sep 27 2026 adjudication: 5534276, 6702327, 5839389,
    # 2939936 all had this shape).
    "see_below_categories": {"type": "array", "items": {"type": "string", "enum": ["revenue", "expenditure", "capital"]}},
    "fiscal_table_columns": {"type": "array", "items": _obj({
        "label": _STR, "revenue": _NUM_OR_NULL, "expenditure": _NUM_OR_NULL,
        "capital": _NUM_OR_NULL, "net": _NUM_OR_NULL})},
    "agencies_abbrev": _STR_LIST, "agencies_full": _STR_LIST,
    "program_breakdowns": {"type": "array", "items": _obj({
        "agency": _STR, "program": _STR, "description": _STR, "cost_type": _STR,
        "amount": _NUM_OR_NULL, "fy_range": _STR, "offset_notes": _STR})},
    "impact_narrative_revenue": _STR, "impact_narrative_expenditure": _STR,
    "omb_estimate_provided": {"type": "boolean"}, "omb_estimate_notes": _STR,
    "estimate_prepared_by": _STR, "estimate_reviewed_by": _STR_LIST,
    "date_prepared": _STR, "hearing_date": _STR,
})


def _blank_to_none(v):
    """Empty strings from the schema's plain-string fields are stored as None, as before."""
    if isinstance(v, dict):
        return {k: _blank_to_none(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_blank_to_none(x) for x in v]
    return None if v == "" else v


# ── Extraction prompt ─────────────────────────────────────────────────────────
EXTRACTION_PROMPT = """You are extracting structured data from a New York City Council fiscal impact statement document. Extract the fields below.

DOCUMENT TEXT:
---
{text}
---

Return a JSON object with exactly these fields (an empty string for missing text, null for an unknown number, 0 for explicit zeros, true/false for booleans):

{{
  "file_number": "e.g. Int. No. 805  or  T2026-1631  or  Res. No. 1234-A  — as written",
  "legislation_type": "Introduction or Resolution or Pre-Considered Resolution or Other",
  "title": "full title as written",
  "committee": "committee name only (e.g. Transportation, Aging, Finance)",
  "sponsors": ["Last Name 1", "Last Name 2"],
  "prime_sponsor": "Last Name of first listed sponsor",
  "effective_date": "as written (e.g. 120 days after becoming law)",
  "fy_first_effective": "e.g. FY26 or FY27 — just the FY label",
  "fy_full_impact": "e.g. FY27 or FY28 — just the FY label",
  "source_of_funds": "General Fund or N/A or Federal Funds or as written",
  "cost_estimable": true,
  "costs_already_in_financial_plan": false,
  "time_limited_program": false,
  "sunset_quote": "",
  "expenditure_is_savings": false,
  "recurring_annual_expenditure": null,

  "total_revenue": 0,
  "total_expenditure": 0,
  "total_capital": null,
  "net_fiscal_impact": 0,

  "see_below_categories": [],

  "fiscal_table_columns": [
    {{
      "label": "column header exactly as written",
      "revenue": 0,
      "expenditure": 0,
      "capital": null,
      "net": 0
    }}
  ],

  "agencies_abbrev": ["DOT", "DPR"],
  "agencies_full": ["Department of Transportation", "Department of Parks and Recreation"],

  "program_breakdowns": [
    {{
      "agency": "DOT",
      "program": "program or line item name",
      "description": "one-sentence description",
      "cost_type": "expense or capital or revenue",
      "amount": 1000000,
      "fy_range": "FY22-FY26 or similar",
      "offset_notes": "any note about baseline offsets, or null"
    }}
  ],

  "impact_narrative_revenue": "full text of the Impact on Revenues paragraph",
  "impact_narrative_expenditure": "full text of the Impact on Expenditures paragraph",

  "omb_estimate_provided": false,
  "omb_estimate_notes": "what OMB said, or null if section absent",

  "estimate_prepared_by": "Name, Title",
  "estimate_reviewed_by": ["Name, Title"],
  "date_prepared": "YYYY-MM-DD if parseable, otherwise as written",
  "hearing_date": null
}}

RULES:
- total_revenue / total_expenditure / total_capital / net_fiscal_impact: the figures the document itself states as the total or full fiscal impact, copied rather than computed except for the range rule below (0 if it states none). The pipeline recomputes them from fiscal_table_columns whenever the table has figures, so copy every column exactly as printed, with revenue reductions entered as negative revenue.
- A cost the narrative states (for example "a one-time capital cost of $2 million" or "approximately $3.5 million for radios") is part of the estimate even when the table shows $0 or omits it: put it in total_capital or total_expenditure as described.
- Ranges and scenarios, in the table or the narrative: when the statement gives an "at least" figure ("at least $750,000", "a minimum of $2 million"), use that figure; when several scenarios each give an "at least" figure, use the lowest one. Otherwise use the midpoint of the range, or of the lowest and highest scenario figures ("$6.3 million to $11.6 million" is 8950000). Apply this to each table cell that prints a range, and to the stated totals. This is the only arithmetic you do.
- costs_already_in_financial_plan: true when the statement says a cost or a revenue is already reflected, included, assumed or funded in the City's Financial Plan or Adopted Budget, or that existing agency resources cover it. Such an amount is not new: leave it out of every total and table column. When only part is already reflected ("the plan reflects $183 million of the $352.8 million"), enter only the remainder. Amounts the statement describes as beyond the Financial Plan still count.
- time_limited_program: true only when the program or pilot that carries the cost itself ends on a stated date or after a stated number of years, and the statement says so. A sunset of one subsection (for example a reporting requirement) or of a separate authority, a discretionary end ("may discontinue"), or a statement that merely shows several years does NOT count. When true, copy into sunset_quote the exact sentence from the document that states the end; otherwise sunset_quote is "". Copy every year column; the pipeline totals a time-limited program over its life.
- A figure in the table or the narrative is a fiscal impact. "See below" pointing to a figure, a $0 Full Fiscal Impact column beside non-zero year columns, or an unknown revenue next to a known cost is NOT zero impact and NOT unestimable.
- Every amount is in whole dollars: "$435 million" is 435000000 and "$2.3 million" is 2300000, never 435 or 2.3, including when a table is labelled "($000)" or "in millions" (multiply out).
- A table cell that says "See below" points to the narrative: leave that cell null, and take the figure the Impact on Revenues or Impact on Expenditures paragraph gives (for example "a one-time capital cost of $1.8 million") as the document's stated total. Set cost_estimable to false only when the narrative itself says the cost cannot be estimated and gives no figure. In see_below_categories, list "revenue"/"expenditure"/"capital" for each category where the figure came from the narrative rather than the table — every column read "See below", was blank, or printed $0 with no capital/expenditure/revenue row while the narrative states a figure for it (e.g. a one-time capital cost mentioned only in prose) — even if you also wrote that figure into the Full Fiscal Impact column, so the pipeline can label its source correctly.
- recurring_annual_expenditure: only when the statement separates one-time or start-up costs (equipment, IT builds, launch campaigns, first-year purchases) from the ongoing yearly cost AND the Full Fiscal Impact column includes those one-time costs, give the ongoing yearly cost as a positive number (for example "a one-time $250,000 technology upgrade ... $687,000 annually thereafter" gives 687000); otherwise null.
- expenditure_is_savings: true only when the statement itself describes the expenditure figure as savings or a reduction in city spending (a net positive to the city), not a cost — for example "annual expenditure savings of approximately $790,000". Leave the number itself positive (its magnitude); the pipeline applies the sign.
- fiscal_table_columns must preserve the exact column structure from the document (there may be 2–6 columns).
- agencies_abbrev: list only agencies that are directly responsible for implementing the legislation — i.e. agencies that have at least one line item in program_breakdowns. Do NOT list agencies that only appear in passing in narrative text (e.g. OMB as reviewer, IBO as analyst, NYC Council as introducer).
- agencies_full: each agency's name as the document writes it. agencies_abbrev and program_breakdowns[].agency: the abbreviation the document uses, or the full name if it uses none; the pipeline canonicalizes both through the NYC agency crosswalk.
- program_breakdowns: extract named cost line items from the Impact on Expenditures section. May be empty [].
- For program_breakdowns entries involving street sign installation, street sign fabrication, co-naming of thoroughfares, or sign procurement: set agency="DOT" regardless of which agency the document credits. DOT is responsible for all street signage in NYC.
- For sponsors and prime_sponsor: strip all prefixes ("Council Member", "Council Members", "By Council Members", "(s):"). Return only the name. For "The Speaker (Council Member X)", return "X (Speaker)". Always use last name only as written in the document.

NARRATIVE FORMAT (older documents without a structured table):
Some documents — particularly pre-2019 legislation — state fiscal impacts as prose rather than a year-by-year table. If there is no structured numeric table, synthesize the totals from the narrative text using these rules:
- Look for phrases like "estimated to cost $X", "increase expenditures by $X annually", "reduce revenues by $X", "capital cost of $X", "estimated at $X million".
- If a dollar amount is given as an annual figure with no multi-year breakdown, use that figure as the total (do not multiply by years unless the document explicitly states a total cumulative cost).
- When the narrative gives several figures (an annual cost growing over time, a multi-year or lifetime total), use the annual figure for the full-impact year (fy_full_impact); use a multi-year total only for a time_limited_program.
- Savings are negative costs: "$67,000 in savings" lowers total_expenditure; a bill whose only effect is a saving has a positive net_fiscal_impact.
- Revenue REDUCTIONS (e.g. "this legislation would reduce revenues by $204,000") are a cost to the city: set total_revenue = 0 and add the reduction amount to total_expenditure so net_fiscal_impact is negative.
- "No impact on revenues" or "existing resources" means 0 for that category — do NOT set cost_estimable to false.
- Create a single fiscal_table_columns entry with label "Total" and populate revenue/expenditure/capital/net from the narrative figures.
- If the narrative gives a cost figure and also says some further part "cannot be determined" or "cannot be projected", keep the stated figure as the estimate (cost_estimable stays true) and note the caveat in the narrative fields. Set cost_estimable to false only when the statement gives no cost figure at all.
"""

# Prompt caching (Tal, Sep 28 2026): EXTRACTION_PROMPT's own text has the
# per-document DOCUMENT TEXT block sandwiched between the intro and the
# (much longer) field-by-field rules — fine for a single formatted string,
# but prefix caching only caches a stable PREFIX, so the fixed instructions
# have to move after the document text in what's actually sent. Built by
# splitting EXTRACTION_PROMPT itself (not retyped) so the wording is
# identical, just reordered: intro + rules, ending with the same "DOCUMENT
# TEXT:\n---\n" header, then the statement text, then the same "\n---\n"
# closer that used to follow it.
_DOC_HEADER = "\n\nDOCUMENT TEXT:\n---\n"
_DOC_CLOSER = "\n---\n"
_EXTRACTION_PREFIX, _EXTRACTION_SUFFIX = EXTRACTION_PROMPT.split("{text}")
_EXTRACTION_INTRO, _, _EXTRACTION_RULES = _EXTRACTION_PREFIX.partition(_DOC_HEADER)
assert _EXTRACTION_SUFFIX.startswith(_DOC_CLOSER)
_EXTRACTION_RULES += _EXTRACTION_SUFFIX[len(_DOC_CLOSER):]  # everything after the old {text} slot
# the JSON example inside _EXTRACTION_RULES uses doubled braces so the old
# single EXTRACTION_PROMPT.format(text=...) call could substitute {text}
# without choking on the example's own braces; since this fixed block is
# never run through .format(), resolve them here the same way format() would.
EXTRACTION_PROMPT_FIXED = (
    (_EXTRACTION_INTRO + "\n" + _EXTRACTION_RULES + "\n" + _DOC_HEADER.lstrip("\n"))
    .replace("{{", "{").replace("}}", "}")
)
EXTRACTION_PROMPT_SUFFIX = _DOC_CLOSER


# ── Legistar scraping ─────────────────────────────────────────────────────────

def create_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return s


def search_legistar_all(
    session: requests.Session, max_retries: int = 3
) -> list[tuple[str, str]]:
    """
    Search Legistar for ALL matters with 'Fiscal Impact Statement' in attachments,
    across all years, handling pagination.

    Background: Legistar's year filter (lstYears) is non-functional for attachment
    searches — it always returns the same results regardless of the year selected.
    We therefore search with 'All Years' and paginate through all result pages.
    Pagination uses ASP.NET __doPostBack with the RadGrid pager event targets.

    Legistar goes unresponsive for stretches (every scheduled CI run May–Aug 2026
    died on one timeout here), so the whole search retries with long waits; after
    the last attempt the Timeout propagates so the Action fails loudly rather
    than committing an empty result.

    Returns list of (matter_id, guid) tuples, deduplicated.
    """
    log.info("Searching Legistar for all fiscal impact statement attachments ...")

    for attempt in range(max_retries + 1):
        try:
            r = session.get(f"{BASE_URL}/Legislation.aspx", timeout=60)
            r.raise_for_status()

            vs_match  = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', r.text)
            vsg_match = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', r.text)
            if not vs_match:
                log.error("Could not find __VIEWSTATE on Legistar search page")
                return []

            # Initial search POST — "All Years" returns all available bills
            post_data = {
                "__VIEWSTATE":          vs_match.group(1),
                "__VIEWSTATEGENERATOR": vsg_match.group(1) if vsg_match else "",
                "ctl00$ContentPlaceHolder1$txtSearch":    "Fiscal Impact Statement",
                "ctl00$ContentPlaceHolder1$lstYears":     "All Years",
                "ctl00$ContentPlaceHolder1$lstTypeBasic": "All Types",
                "ctl00$ContentPlaceHolder1$chkAttachments": "on",
                "ctl00$ContentPlaceHolder1$btnSearch":    "Search Legislation",
            }

            r2 = session.post(f"{BASE_URL}/Legislation.aspx", data=post_data, timeout=120)
            r2.raise_for_status()

            seen:   set[str]           = set()
            unique: list[tuple[str, str]] = []

            def _extract_matters(html: str) -> None:
                for mid, guid in re.findall(
                    r"LegislationDetail\.aspx\?ID=(\d+)&(?:amp;)?GUID=([A-F0-9\-]+)", html
                ):
                    if mid not in seen:
                        seen.add(mid)
                        unique.append((mid, guid))

            _extract_matters(r2.text)
            log.info(f"  Page 1: {len(unique)} matters")

            # Paginate: find all numeric page links beyond page 1 in the pager.
            # The RadGrid pager renders links as:
            #   __doPostBack('ctl00$...$ctl04','')  → page 2
            #   __doPostBack('ctl00$...$ctl06','')  → page 3  etc.
            # We detect them by finding the pager HTML and extracting event targets
            # for pages 2, 3, … until no new pages are found.
            current_html = r2.text
            page_num = 1

            while True:
                # Find pager link for the next page (page_num + 1).
                # Pager links are <a href="javascript:__doPostBack(...)"><span>N</span></a>
                # The current page has class="rgCurrentPage" with no href navigation.
                next_page = page_num + 1
                # Match: href with doPostBack target followed by <span>{next_page}</span>
                pattern = (
                    r"doPostBack\(&#39;([^&]+)&#39;,&#39;&#39;\)"
                    r"[^<]*<span>" + str(next_page) + r"</span>"
                )
                m = re.search(pattern, current_html)
                if not m:
                    break  # no more pages

                event_target = m.group(1)
                vs2  = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', current_html)
                vsg2 = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', current_html)

                page_data = {
                    "__VIEWSTATE":          vs2.group(1) if vs2 else "",
                    "__VIEWSTATEGENERATOR": vsg2.group(1) if vsg2 else "",
                    "__EVENTTARGET":        event_target,
                    "__EVENTARGUMENT":      "",
                    "ctl00$ContentPlaceHolder1$txtSearch":    "Fiscal Impact Statement",
                    "ctl00$ContentPlaceHolder1$lstYears":     "All Years",
                    "ctl00$ContentPlaceHolder1$lstTypeBasic": "All Types",
                    "ctl00$ContentPlaceHolder1$chkAttachments": "on",
                }
                rn = session.post(f"{BASE_URL}/Legislation.aspx", data=page_data, timeout=120)
                rn.raise_for_status()

                before = len(unique)
                _extract_matters(rn.text)
                added = len(unique) - before
                log.info(f"  Page {next_page}: {added} new matters (running total: {len(unique)})")

                current_html = rn.text
                page_num = next_page
                time.sleep(1)

            log.info(f"  -> {len(unique)} total matters found across all pages")
            return unique

        except requests.exceptions.Timeout:
            if attempt < max_retries:
                wait = 120 * (attempt + 1)
                log.warning(
                    f"  Legistar timed out (attempt {attempt+1}/{max_retries+1}) — retrying in {wait}s"
                )
                time.sleep(wait)
            else:
                log.error(f"  Legistar timed out on all {max_retries+1} attempts — failing run")
                raise

    return []


def search_legistar_advanced_year(
    session: requests.Session, year: str, max_retries: int = 2
) -> list[tuple[str, str]]:
    """
    Use the Legistar advanced search form to find matters with 'Fiscal Impact Statement'
    attachments for a specific year. The advanced lstYearsAdvanced filter appears to
    work for historical data where the basic lstYears filter does not.

    Two-step process:
    1. GET the page, then POST with btnSwitch to enter advanced mode
    2. POST with txtAtt + lstYearsAdvanced to run the search, then paginate
    """
    log.info(f"  Advanced search for year {year} ...")

    for attempt in range(max_retries + 1):
        try:
            # Step 1: GET the page
            r = session.get(f"{BASE_URL}/Legislation.aspx", timeout=20)
            r.raise_for_status()

            vs_match  = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', r.text)
            vsg_match = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', r.text)
            if not vs_match:
                log.error(f"  Could not find __VIEWSTATE for year {year}")
                return []

            # Step 2: Switch to advanced search mode
            switch_data = {
                "__VIEWSTATE":          vs_match.group(1),
                "__VIEWSTATEGENERATOR": vsg_match.group(1) if vsg_match else "",
                "ctl00$ContentPlaceHolder1$btnSwitch":    "Advanced search >>>",
                "ctl00$ContentPlaceHolder1$lstYears":     "This Year",
                "ctl00$ContentPlaceHolder1$lstTypeBasic": "All Types",
            }
            r2 = session.post(f"{BASE_URL}/Legislation.aspx", data=switch_data, timeout=20)
            r2.raise_for_status()

            vs2  = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', r2.text)
            vsg2 = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', r2.text)

            # Step 3: Run the advanced search for this year
            client_state = json.dumps({
                "enabled": True,
                "emptyMessage": "",
                "validationText": year,
                "valueAsString": year,
                "lastSetTextInitiatesRequest": False,
                "blockAnimationTimer": 0,
                "lastAutoCompleteIndex": -1,
                "Direction": 0,
            })
            search_data = {
                "__VIEWSTATE":          vs2.group(1) if vs2 else "",
                "__VIEWSTATEGENERATOR": vsg2.group(1) if vsg2 else "",
                "ctl00$ContentPlaceHolder1$txtAtt":               "Fiscal Impact Statement",
                "ctl00$ContentPlaceHolder1$lstYearsAdvanced":     year,
                "ctl00_ContentPlaceHolder1_lstYearsAdvanced_ClientState": client_state,
                "ctl00$ContentPlaceHolder1$lstType":              "All Types",
                "ctl00$ContentPlaceHolder1$lstMax":               "50",
                "ctl00$ContentPlaceHolder1$btnSearch":            "Search Legislation",
            }
            r3 = session.post(f"{BASE_URL}/Legislation.aspx", data=search_data, timeout=90)
            r3.raise_for_status()

            seen:   set[str]              = set()
            unique: list[tuple[str, str]] = []

            def _extract(html: str) -> None:
                for mid, guid in re.findall(
                    r"LegislationDetail\.aspx\?ID=(\d+)&(?:amp;)?GUID=([A-F0-9\-]+)", html
                ):
                    if mid not in seen:
                        seen.add(mid)
                        unique.append((mid, guid))

            _extract(r3.text)
            log.info(f"    Year {year} page 1: {len(unique)} matters")

            # Paginate using the same RadGrid __doPostBack pattern
            current_html = r3.text
            page_num = 1

            while True:
                next_page = page_num + 1
                pattern = (
                    r"doPostBack\(&#39;([^&]+)&#39;,&#39;&#39;\)"
                    r"[^<]*<span>" + str(next_page) + r"</span>"
                )
                m = re.search(pattern, current_html)
                if not m:
                    break

                event_target = m.group(1)
                vs_p  = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', current_html)
                vsg_p = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', current_html)

                page_data = {
                    "__VIEWSTATE":          vs_p.group(1) if vs_p else "",
                    "__VIEWSTATEGENERATOR": vsg_p.group(1) if vsg_p else "",
                    "__EVENTTARGET":        event_target,
                    "__EVENTARGUMENT":      "",
                    "ctl00$ContentPlaceHolder1$txtAtt":               "Fiscal Impact Statement",
                    "ctl00$ContentPlaceHolder1$lstYearsAdvanced":     year,
                    "ctl00_ContentPlaceHolder1_lstYearsAdvanced_ClientState": client_state,
                    "ctl00$ContentPlaceHolder1$lstType":              "All Types",
                    "ctl00$ContentPlaceHolder1$lstMax":               "50",
                }
                rn = session.post(f"{BASE_URL}/Legislation.aspx", data=page_data, timeout=60)
                rn.raise_for_status()

                before = len(unique)
                _extract(rn.text)
                added = len(unique) - before
                log.info(f"    Year {year} page {next_page}: {added} new matters (total: {len(unique)})")

                current_html = rn.text
                page_num = next_page
                time.sleep(1.5)

            log.info(f"    Year {year}: {len(unique)} total matters")
            return unique

        except requests.exceptions.Timeout:
            if attempt < max_retries:
                wait = 30 * (attempt + 1)
                log.warning(f"    Timeout for year {year} (attempt {attempt+1}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                log.error(f"    Timeout for year {year} after {max_retries+1} attempts — skipping")
                return []
        except Exception as e:
            log.error(f"    Error searching year {year}: {e}")
            return []

    return []


def parse_legistar_page(html: str) -> tuple[str | None, str | None]:
    """
    Read Legistar's own File # ("Int 1002-2026") and title off a
    LegislationDetail page. Returns (file_number, title); None for either if
    the page is an "Invalid parameters!" stub.
    """
    def label(name: str) -> str | None:
        m = re.search(rf'id="ctl00_ContentPlaceHolder1_{name}"[^>]*>(.*?)</span>', html, re.S)
        if not m:
            return None
        return re.sub(r"<[^>]+>", "", m.group(1)).strip() or None
    return label("lblFile2"), label("lblTitle2")


def fetch_legistar_file(
    session: requests.Session, matter_id: str, guid: str
) -> tuple[str | None, str | None]:
    """Fetch a matter's detail page and return (legistar_file, title)."""
    r = session.get(f"{BASE_URL}/LegislationDetail.aspx?ID={matter_id}&GUID={guid}", timeout=60)
    r.raise_for_status()
    return parse_legistar_page(r.text)


# Filled by get_fiscal_attachment as a side effect (it already has the detail
# page in hand); read by main() when building the record.
LEGISTAR_FILE_BY_MATTER: dict[str, str | None] = {}


def get_fiscal_attachment(
    session: requests.Session, matter_id: str, guid: str
) -> tuple[str | None, str | None]:
    """
    Fetch a matter's detail page and find the fiscal impact attachment.
    Returns (attachment_id, attachment_guid) or (None, None).
    Also records Legistar's File # for the matter in LEGISTAR_FILE_BY_MATTER.
    """
    url = (
        f"{BASE_URL}/LegislationDetail.aspx"
        f"?ID={matter_id}&GUID={guid}&Options=Attachments|&Search=Fiscal+Impact+Statement"
    )
    r = session.get(url, timeout=20)
    r.raise_for_status()
    LEGISTAR_FILE_BY_MATTER[matter_id] = parse_legistar_page(r.text)[0]

    # An amended bill carries one statement per version ("Fiscal Impact
    # Statement - City Council", later "Int. No. 1208-A - Fiscal Impact
    # Statement - City Council"), listed oldest first. The enacted version's
    # is the newest Council statement; attachment IDs rise over time. OMB's
    # own statement is a separate PDF the extractor does not read.
    # the Search= parameter wraps matched words in <font> highlight tags, so
    # read the whole link body and strip tags before matching the label
    labeled = [(i, g, re.sub(r"<[^>]+>", "", body)) for i, g, body in re.findall(
        r"View\.ashx\?M=F&(?:amp;)?ID=(\d+)&(?:amp;)?GUID=([A-F0-9\-]+)[^>]*>(.*?)</a>", r.text, re.S)]
    council = [(int(i), i, g) for i, g, label in labeled
               if "fiscal impact" in label.lower() and "omb" not in label.lower()]
    if council:
        _, att_id, att_guid = max(council)
        return att_id, att_guid

    views = re.findall(
        r"View\.ashx\?M=F&ID=(\d+)&(?:amp;)?GUID=([A-F0-9\-]+)", r.text
    )

    for att_id, att_guid in views:
        att_url = f"{BASE_URL}/View.ashx?M=F&ID={att_id}&GUID={att_guid}"
        try:
            head = session.head(att_url, timeout=10, allow_redirects=True)
            cd = head.headers.get("Content-Disposition", "")
            if "fiscal" in cd.lower() or "impact" in cd.lower():
                return att_id, att_guid
        except Exception:
            continue

    return None, None


def download_docx(
    session: requests.Session, att_id: str, att_guid: str
) -> Path | None:
    """
    Download a .docx attachment to the cache directory.
    Returns the local path, or None on failure.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local = CACHE_DIR / f"{att_id}.docx"

    if local.exists():
        log.info(f"  Using cached docx: {att_id}.docx")
        return local

    url = f"{BASE_URL}/View.ashx?M=F&ID={att_id}&GUID={att_guid}"
    r = session.get(url, timeout=120)
    r.raise_for_status()

    if len(r.content) < 100:
        log.warning(f"  Suspiciously small download for att_id={att_id}")
        return None

    local.write_bytes(r.content)
    log.info(f"  Downloaded: {att_id}.docx ({len(r.content):,} bytes)")
    return local


def extract_docx_text(docx_path: Path) -> str:
    """Extract text from a fiscal statement, including table cell content.

    The cache names every attachment .docx, but Legistar serves older
    statements as PDFs and legacy Word .doc files under the same "fiscal"
    filename. They are told apart by their first bytes (Oct 6 2026: 82 PDFs
    and 120 .doc statements had been skipped forever as unreadable, e.g.
    Int 0694-2024, the citywide bathroom strategy)."""
    head = docx_path.read_bytes()[:8]
    if head.startswith(b"%PDF"):
        try:
            from pypdf import PdfReader
            return "\n".join((pg.extract_text() or "").strip() for pg in PdfReader(str(docx_path)).pages).strip()
        except Exception as e:  # noqa: BLE001
            log.warning(f"  Could not read PDF {docx_path}: {e}")
            return ""
    if head.startswith(b"\xd0\xcf\x11\xe0"):          # OLE2: legacy Word .doc
        for cmd in (["antiword", "-w", "0", str(docx_path)],                 # Linux (Actions: apt antiword)
                    ["textutil", "-convert", "txt", "-stdout", str(docx_path)]):  # macOS
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        log.warning(f"  No .doc reader for {docx_path} (install antiword)")
        return ""
    try:
        doc = Document(str(docx_path))
    except Exception as e:
        log.warning(f"  Could not open {docx_path}: {e}")
        return ""

    parts = []

    for para in doc.paragraphs:
        t = para.text.strip()
        if t:
            parts.append(t)

    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            row_text = "\t".join(cells)
            if any(cells):
                parts.append(row_text)

    return "\n".join(parts)


# ── Claude extraction ─────────────────────────────────────────────────────────

sys.path.insert(0, str(SCRIPT_DIR))
from claude_batch import cached_content, run_batch, clear_state, Usage, message_text  # noqa: E402

BATCH_STATE_PATH = SCRIPT_DIR / "fiscal_batch_state.json"
# Not part of claude_batch.py's own state (that file only holds the batch id):
# the matter_id -> {text, guid, att_id} a resumed run needs to finish phase 3
# without repeating the Legistar search or re-downloading statements. Written
# right before the batch is submitted, removed once results are collected.
PENDING_PATH = SCRIPT_DIR / "fiscal_batch_pending.json"
# refresh_fiscal_data.yml's job cap is 360 minutes. Budget for the rest of the
# job: checkout + setup-python + pip install ~5 min; the Legistar search plus
# per-matter fetch/download (phase 1, politeness sleeps included) ~30 min for
# a typical monthly run's few hundred matters; regenerate_agency_data.py +
# validate_fiscal_impacts.py ~5 min; commit/push with its retry-with-backoff
# loop (up to 6 attempts, sleeps up to 5*45s) ~5 min. That is 45 min of
# non-wait overhead, leaving 315 min; round down to 300 min (5 h) for margin.
MAX_WAIT_S = 300 * 60
USAGE = Usage()


def extraction_messages(text: str, ttl: str | None = None) -> list[dict]:
    """The user message content for one statement: EXTRACTION_PROMPT_FIXED
    (identical for every document, cached) then the statement text (variable,
    last). `ttl` "1h" inside a batch, default 5 minutes for a synchronous call."""
    if len(text) > FIS_TEXT_CAP:
        log.warning(f"  Statement text is {len(text):,} chars; truncating to {FIS_TEXT_CAP:,}")
    variable = text[:FIS_TEXT_CAP] + EXTRACTION_PROMPT_SUFFIX
    return cached_content(EXTRACTION_PROMPT_FIXED, variable, ttl=ttl)


def extraction_params(text: str, ttl: str | None = None) -> dict:
    """The messages.create kwargs for one statement — reused verbatim as
    batch Request params, so there is exactly one place that builds them."""
    return {
        "model": CLAUDE_MODEL,
        "max_tokens": 16000,
        "messages": [{"role": "user", "content": extraction_messages(text, ttl=ttl)}],
        "output_config": {"format": {"type": "json_schema", "schema": FISCAL_SCHEMA}},
    }


def _finish_extraction(msg, text: str) -> dict:
    """Parse and post-process one successful response — the same step
    whether it came from a synchronous call or a batch result."""
    if msg.stop_reason == "max_tokens":
        raise json.JSONDecodeError("output truncated at max_tokens", "", 0)
    data = _blank_to_none(json.loads(message_text(msg)))
    # the sunset sentence must appear in the statement itself
    norm = lambda t: re.sub(r"\s+", " ", t or "").strip().lower()
    if data.get("time_limited_program") and norm(data.get("sunset_quote"))[:120] not in norm(text):
        data["time_limited_program"] = False
    return totals_from_columns(data)


def extract_fiscal_data(
    text: str, client: anthropic.Anthropic
) -> dict:
    """Call Claude API to extract structured fiscal data from docx text."""
    for attempt in range(3):
        try:
            msg = client.messages.create(**extraction_params(text))
            USAGE.add(msg)
            return _finish_extraction(msg, text)

        except json.JSONDecodeError as e:
            log.warning(f"  JSON decode error (attempt {attempt+1}): {e}")
            if attempt == 2:
                return {"extraction_error": str(e)}
        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            log.warning(f"  Rate limited — waiting {wait}s")
            time.sleep(wait)
        except Exception as e:
            log.warning(f"  API error (attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)

    return {"extraction_error": "Failed after 3 attempts"}


# ── Max-plan packet mode (Tal, Sep 28 2026) ──────────────────────────────────
# The routine (Claude Code on the Max plan, no API key) does the extraction
# itself: --emit-packets writes one prompt per statement (the same fixed+
# variable text the API path sends) for a subagent to answer; --ingest reads
# each subagent's JSON answer, validates it against FISCAL_SCHEMA, and runs
# it through the SAME _finish_extraction() the sync and batch paths use, so
# there is exactly one place that turns a model answer into a stored record.
MAX_REFRESH_PATH = REPO_ROOT / "pipeline" / "max_refresh.json"


def load_max_refresh() -> dict:
    if MAX_REFRESH_PATH.exists():
        return json.loads(MAX_REFRESH_PATH.read_text())
    return {}


def save_max_refresh(data: dict) -> None:
    MAX_REFRESH_PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def _current_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def gated_done_ids() -> set[str]:
    """Matter ids the Max routine already extracted this month, when the
    calling workflow sets MAX_REFRESH_GATE=1."""
    if os.environ.get("MAX_REFRESH_GATE") != "1":
        return set()
    marker = load_max_refresh()
    if marker.get("month") != _current_month():
        return set()
    return set(marker.get("fiscal", {}).get("done", []))


def merge_max_refresh(month: str, done: list[str], left: list[str]) -> None:
    marker = load_max_refresh()
    if marker.get("month") != month:
        marker = {"month": month}
    fiscal = marker.get("fiscal", {"done": [], "left": []})
    fiscal["done"] = sorted(set(fiscal.get("done", [])) | set(done))
    fiscal["left"] = sorted((set(fiscal.get("left", [])) | set(left)) - set(done))
    marker["fiscal"] = fiscal
    save_max_refresh(marker)


def _validate_schema(data, schema, path: str = "") -> list[str]:
    """Minimal validator for the subset of JSON Schema FISCAL_SCHEMA uses:
    object/array/string/number/boolean, required, enum, additionalProperties,
    and anyOf (for the schema's nullable fields). Used only when the
    `jsonschema` package isn't installed (it isn't, per requirements.txt)."""
    errors: list[str] = []
    if "anyOf" in schema:
        if not any(not _validate_schema(data, s, path) for s in schema["anyOf"]):
            errors.append(f"{path or '<root>'}: matches none of {schema['anyOf']}")
        return errors
    t = schema.get("type")
    pytypes = {"object": dict, "array": list, "string": str, "number": (int, float),
               "boolean": bool, "null": type(None)}
    if t and not isinstance(data, pytypes.get(t, object)):
        return [f"{path or '<root>'}: expected {t}, got {type(data).__name__}"]
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path or '<root>'}: {data!r} not in {schema['enum']}")
    if t == "object":
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}.{key}: missing required field")
        if not schema.get("additionalProperties", True):
            extra = set(data) - set(schema.get("properties", {}))
            if extra:
                errors.append(f"{path or '<root>'}: unexpected fields {sorted(extra)}")
        for key, subschema in schema.get("properties", {}).items():
            if key in data:
                errors.extend(_validate_schema(data[key], subschema, f"{path}.{key}"))
    elif t == "array" and "items" in schema:
        for i, item in enumerate(data):
            errors.extend(_validate_schema(item, schema["items"], f"{path}[{i}]"))
    return errors


def emit_packets(pending: list[tuple[str, str]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results").mkdir(exist_ok=True)
    manifest = {"month": _current_month(), "ids": [mid for mid, _ in pending]}
    for mid, text in pending:
        prompt = EXTRACTION_PROMPT_FIXED + text[:FIS_TEXT_CAP] + EXTRACTION_PROMPT_SUFFIX
        (out_dir / f"{mid}.txt").write_text(
            prompt + f"\n\nANSWER FORMAT: write ONLY a JSON object matching this schema to "
            f"results/{mid}.json:\n" + json.dumps(FISCAL_SCHEMA))
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    log.info(f"wrote {len(pending)} packets to {out_dir}")


def ingest_packets(pending: list[tuple[str, str]], in_dir: Path) -> dict[str, dict]:
    """Validate and finish every subagent result found in in_dir/results/.
    An id with no result file, an unparseable one, or one that fails schema
    validation is left out of the return value (and recorded in "left")."""
    by_id = dict(pending)
    out: dict[str, dict] = {}
    done, left = [], []
    for mid, text in pending:
        f = in_dir / "results" / f"{mid}.json"
        if not f.exists():
            left.append(mid)
            continue
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            log.warning(f"  {mid}: invalid JSON in {f}: {e}")
            left.append(mid)
            continue
        errors = _validate_schema(data, FISCAL_SCHEMA)
        if errors:
            log.warning(f"  {mid}: schema validation failed: {errors[:3]}")
            left.append(mid)
            continue
        fake_msg = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(data))])
        try:
            out[mid] = _finish_extraction(fake_msg, by_id[mid])
            done.append(mid)
        except Exception as e:  # noqa: BLE001
            log.warning(f"  {mid}: post-processing failed: {e}")
            left.append(mid)
    merge_max_refresh(_current_month(), done, left)
    log.info(f"ingested {len(done)} of {len(pending)} packets ({len(left)} left)")
    return out


def extract_many(pending: list[tuple[str, str]], client: anthropic.Anthropic,
                  max_wait_s: int | None = None) -> dict[str, dict] | None:
    """Extract fiscal data for every (matter_id, text) in `pending`. Batch
    mode (CLAUDE_BATCH=1) builds every request first and submits one Message
    Batch (half price, ttl 1h so the cache survives the whole batch window);
    an item that errored or expired in the batch falls back to the
    synchronous path for that item only. Returns None when the batch timed
    out (state left in BATCH_STATE_PATH for the next run's resume) — no
    partial results, the caller must write nothing else and exit 0."""
    if not pending:
        return {}
    if os.environ.get("CLAUDE_BATCH") == "1":
        by_id = dict(pending)
        requests = [(mid, extraction_params(text, ttl="1h")) for mid, text in pending]
        kwargs = {"max_wait_s": max_wait_s} if max_wait_s is not None else {}
        results = run_batch(client, requests, BATCH_STATE_PATH, **kwargs)
        if results is None:
            return None
        out: dict[str, dict] = {}
        for mid, text in pending:
            status, payload = results.get(mid, ("missing", None))
            if status == "succeeded":
                # batch messages count in the run's usage line too (Oct 6
                # 2026: an Oct 1 batch of 10 Sonnet calls printed "0 calls")
                USAGE.add(payload)
                try:
                    out[mid] = _finish_extraction(payload, text)
                except json.JSONDecodeError as e:
                    log.warning(f"  {mid}: batch result JSON error, falling back to sync: {e}")
                    out[mid] = extract_fiscal_data(text, client)
            else:
                log.warning(f"  {mid}: batch item {status}, falling back to sync")
                out[mid] = extract_fiscal_data(by_id[mid], client)
        return out
    return {mid: extract_fiscal_data(text, client) for mid, text in pending}


# ── Data persistence ──────────────────────────────────────────────────────────

def load_existing(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"metadata": {}, "records": []}


def load_skip_list(path: Path) -> dict[str, str]:
    """matter_id -> reason for matters checked and found to have no storable impact."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_skip_list(path: Path, skips: dict[str, str]) -> None:
    # apply_overrides (inside save_output) writes override removals to this
    # file first; keep them rather than overwrite them with the copy loaded at
    # the start of the run (fiscal audit round 2, Oct 6 2026: all 5 round-1
    # removals vanished from both the table and the skip list)
    if path.exists():
        on_disk = json.loads(path.read_text())
        for m, why in on_disk.items():
            if why == "audited_no_new_cost" and m not in skips:
                skips[m] = why
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(skips.items())), f, indent=1)
    log.info(f"Saved {len(skips)} no-impact matter IDs -> {path}")


def load_law_seed(years: str) -> list[tuple[str, str]]:
    """
    Seed matters from the implementation tracker's laws.json (every enacted
    local law 2014–present, with web matter_id + GUID). Legistar's attachment
    search only surfaces a few hundred matters, so this is the only token-free
    way to reach the full set of fiscal impact statements.
    `years`: "2024-2026", "2024", "all", or "auto" (previous + current year).
    """
    if not LAWS_PATH.exists():
        log.warning(f"laws.json not found at {LAWS_PATH} — no law seed")
        return []
    if years == "auto":
        y = datetime.utcnow().year
        wanted = {str(y - 1), str(y)}
    elif years == "all":
        wanted = None
    elif "-" in years:
        a, b = years.split("-")
        wanted = {str(v) for v in range(int(a), int(b) + 1)}
    else:
        wanted = {years}
    with open(LAWS_PATH, encoding="utf-8") as f:
        laws = json.load(f)["laws"]
    out = []
    for law in laws:
        yr = str(law.get("enactment_date") or "")[:4]
        if wanted is None or yr in wanted:
            if law.get("matter_id") and law.get("legistar_guid"):
                out.append((str(law["matter_id"]), law["legistar_guid"]))
    return out


OVERRIDES_PATH = SCRIPT_DIR / "fiscal_overrides.json"


def apply_overrides(records: list) -> list:
    """Blind-audit corrections, applied on every save (fiscal rounds 5-6, Sep 24
    2026). Each entry is tied to the statement it was checked against
    (attachment_id): a newer statement voids it and is read fresh. `remove`
    drops a bill whose statement adds nothing new and skip-lists it; `set` pins
    audited totals so reruns cannot drift. Net is recomputed after a `set`."""
    if not OVERRIDES_PATH.exists():
        return records
    ov = json.loads(OVERRIDES_PATH.read_text())
    out, removed = [], []
    for r in records:
        e = ov.get(str(r.get("matter_id")))
        if not e or str(r.get("attachment_id")) != str(e.get("attachment_id")):
            out.append(r)
            continue
        if e.get("remove"):
            removed.append(r["matter_id"])
            continue
        r.update(e.get("set") or {})
        # a lone "Total" column built from a narrative statement must agree
        # with an audited total (round 2: SLR 0015-2026 showed total $121,000
        # beside a "Total $25,000" column); a statement's own year columns
        # stay as printed, since the audited total is the annual figure
        st = e.get("set") or {}
        cols = r.get("fiscal_table_columns") or []
        if ("fiscal_table_columns" not in st and len(cols) == 1 and (cols[0].get("label") or "").strip().lower() == "total"
                and any(k in st for k in ("total_revenue", "total_expenditure", "total_capital"))):
            c = dict(cols[0])
            c["revenue"] = r.get("total_revenue") or 0
            c["expenditure"] = r.get("total_expenditure") or 0
            c["capital"] = r.get("total_capital")
            c["net"] = (c["revenue"] or 0) - (c["expenditure"] or 0) - (c["capital"] or 0)
            r["fiscal_table_columns"] = [c]
        # a package member (Finance costed several intros as one package):
        # its figures sit on one bill and this one shows "see package"
        # (CityFHEPS Int 229/878/893/894, Oct 6 2026: $3.3B counted four times)
        if r.get("package_note") and all(r.get(k) is None for k in ("total_revenue", "total_expenditure", "total_capital")):
            r["net_fiscal_impact"] = None
            r["totals_basis"] = "package"
            r["audited"] = e.get("audit")
            out.append(r)
            continue
        # An override that pins outlasts_statement true is saying the pilot
        # outlasts its statement's columns, so the figure is the annual
        # full-impact amount, never a program-life sum (matter 3597643, Sep
        # 28 2026: totals_from_columns had already run and, on a single-
        # column narrative statement, picked program_life_sum because the
        # override's own time_limited_program hadn't been applied yet at that
        # point — the two fields must agree). Left alone when the override
        # states its own totals_basis.
        if r.get("outlasts_statement") and "totals_basis" not in (e.get("set") or {}):
            r["totals_basis"] = "full_impact_column"
        r["net_fiscal_impact"] = ((r.get("total_revenue") or 0) - (r.get("total_expenditure") or 0)
                                  - (r.get("total_capital") or 0))
        r["audited"] = e.get("audit")
        out.append(r)
    if removed:
        skip = json.loads(SKIP_PATH.read_text()) if SKIP_PATH.exists() else {}
        for mid in removed:
            skip[str(mid)] = "audited_no_new_cost"
        SKIP_PATH.write_text(json.dumps(skip, indent=1, ensure_ascii=False) + "\n")
        log.info(f"Overrides removed {len(removed)} audited records: {removed}")
    return out


def normalize_fiscal_years(records: list) -> list:
    """fy_first_effective / fy_full_impact as "FYnn" (fiscal audit, Oct 6 2026:
    27 values were "FY2020"-style, splitting the filters), and fy_first_effective
    taken from the statement's own first column when it is labelled
    "Effective FYnn" (11 records disagreed with it, e.g. Int 0991-2024)."""
    for r in records:
        for k in ("fy_first_effective", "fy_full_impact"):
            m = re.fullmatch(r"\s*FY\s?'?(?:20)?(\d{2})\s*", str(r.get(k) or ""), re.I)
            if m:
                r[k] = "FY" + m.group(1)
        cols = r.get("fiscal_table_columns") or []
        lab = (cols[0].get("label") or "") if cols else ""
        m = re.match(r"\s*Effective\s+FY\s?'?(?:20)?(\d{2})\b", lab, re.I)
        if m:
            r["fy_first_effective"] = "FY" + m.group(1)
    return records


def fill_blank_titles(records: list) -> list:
    """A statement parsed without a title shows as a blank row: take the
    enacted law's title from laws.json, else the bill's own file number."""
    titles = {}
    if LAWS_PATH.exists():
        titles = {l["matter_id"]: l.get("title") for l in json.loads(LAWS_PATH.read_text()).get("laws", [])}
    for r in records:
        if not (r.get("title") or "").strip():
            r["title"] = titles.get(str(r.get("matter_id"))) or (r.get("file_number") or "").strip() or None
    return records


def save_output(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = normalize_fiscal_years(fill_blank_titles(apply_overrides(records)))
    data = {
        "metadata": {
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "total_records": len(records),
            "source": "NYC Legistar (legistar.council.nyc.gov)",
        },
        "records": records,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(records)} records -> {path}")


# ── Fiscal impact filters ────────────────────────────────────────────────────

def text_is_zero_impact(text: str) -> bool:
    """
    Fast pre-check on raw docx text. Returns True if the document clearly
    shows all-zero figures and no 'See below' language, so we can skip the
    Claude API call entirely.
    """
    t = text.lower()
    # If the doc says cost cannot be estimated, let Claude decide
    if "see below" in t or "cannot estimate" in t or "unable to estimate" in t:
        return False
    # Find all dollar amounts in the text (e.g. $1,234,567 or $1.2 million or $0)
    amounts = re.findall(
        r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:million|billion)?", t
    )
    non_zero = [a for a in amounts if a.replace(",", "").replace(".", "") not in ("0", "")]
    # If there are no dollar figures at all, or all are literally $0, skip
    return len(non_zero) == 0


def record_has_fiscal_impact(fiscal: dict) -> bool:
    """
    Post-extraction check. Returns True only if the bill has a non-zero,
    estimable fiscal impact worth storing.
    Excludes only bills where ALL of revenue, expenditure, capital, and net
    are zero — i.e. no fiscal impact whatsoever.
    """
    if not fiscal.get("cost_estimable", True):
        return False
    if "extraction_error" in fiscal:
        return False  # don't store failed extractions
    exp = fiscal.get("total_expenditure") or 0
    cap = fiscal.get("total_capital") or 0
    rev = fiscal.get("total_revenue") or 0
    net = fiscal.get("net_fiscal_impact") or 0
    return any(abs(v) > 0 for v in [exp, cap, rev, net])


def is_budget_modification(fiscal: dict) -> bool:
    """
    Returns True if this record is a mayoral budget modification (MN-#),
    not independent legislation. These are Charter §107(e) administrative
    approvals and should not appear in the fiscal tracker.
    """
    title = (fiscal.get("title") or "").lower()
    return bool(re.search(r"\bmn-\d+\b", title) or "modification (mn" in title)


_ENACTED_IDS: set[str] | None = None


def enacted_matter_ids() -> set[str]:
    """Web matter ids of every enacted local law (laws.json)."""
    global _ENACTED_IDS
    if _ENACTED_IDS is None:
        try:
            _ENACTED_IDS = {str(l["matter_id"]) for l in json.loads(LAWS_PATH.read_text())["laws"]}
        except (OSError, ValueError, KeyError):
            _ENACTED_IDS = set()
    return _ENACTED_IDS


def is_proposed_bill(fiscal: dict, matter_id: str | None = None) -> bool:
    """
    Returns True if this record is a proposed (not yet passed) bill.
    A matter in the enacted-law list is never proposed: the statement for an
    amended bill's final version is itself titled "Proposed Int. No. 893-A"
    because it is written before the vote (Sep 24 2026: that title removed 83
    enacted laws in a re-extraction). Outside that list, a file number
    beginning with 'Proposed' marks draft legislation.
    """
    if matter_id and str(matter_id) in enacted_matter_ids():
        return False
    file_number = (fiscal.get("file_number") or "").strip()
    return file_number.lower().startswith("proposed")


_SIGN_KEYWORDS = [
    "street sign", "sign installation", "new street sign", "sign procurement",
    "co-name", "thoroughfare sign", "street co-name", "new signs",
    "sign fabricat", "signs at $", "signs for renamed", "signs for thoroughfare",
]

_DOT_FULL = "Department of Transportation"


def normalize_agency_attribution(fiscal: dict) -> dict:
    """
    Apply three post-extraction agency cleanup rules:

    1. Street sign line items → agency = DOT.
       Any program_breakdowns entry whose program or description mentions
       street sign installation, fabrication, or co-naming is credited to DOT.

    2. Crosswalk canonicalization (agency_canon / NYC Open Data t3jq-9nkf).
       Every agency string — in program_breakdowns and in agencies_abbrev —
       is resolved to its canonical abbreviation, so "DCA", "Department of
       Consumer Affairs", and "DCWP" all group as DCWP. Unknown names are
       kept as-is.

    3. agencies_abbrev pruning.
       If program_breakdowns are present, keep only agencies that actually
       appear in at least one breakdown entry. This removes agencies that
       Claude listed from narrative text only (e.g. OMB as reviewer, IBO as
       analyst, NYC Council as introducer).
    """
    from agency_canon import canonicalize

    pbs = fiscal.get("program_breakdowns") or []

    # Rule 1: assign DOT to sign line items
    for pb in pbs:
        combined = ((pb.get("program") or "") + " " + (pb.get("description") or "")).lower()
        if any(kw in combined for kw in _SIGN_KEYWORDS):
            pb["agency"] = "DOT"

    # Rule 2: canonicalize every agency string via the crosswalk
    old_map = dict(zip(
        fiscal.get("agencies_abbrev") or [],
        fiscal.get("agencies_full") or [],
    ))
    old_map["DOT"] = _DOT_FULL
    full_by_canon: dict[str, str] = {}

    def canon_of(name: str) -> str:
        canon, full = canonicalize(name)
        if canon is None and name in old_map:
            canon, full = canonicalize(old_map[name])
        if canon:
            full_by_canon[canon] = full
            return canon
        return name

    for pb in pbs:
        if pb.get("agency"):
            pb["agency"] = canon_of(pb["agency"])

    if not pbs:
        # No breakdowns: canonicalize the extracted agency lists in place
        abbrevs = fiscal.get("agencies_abbrev") or []
        if abbrevs:
            new_abbrevs: list[str] = []
            for a in abbrevs:
                c = canon_of(a)
                if c not in new_abbrevs:
                    new_abbrevs.append(c)
            fiscal["agencies_abbrev"] = new_abbrevs
            fiscal["agencies_full"] = [
                full_by_canon.get(a) or old_map.get(a, a) for a in new_abbrevs]
        return fiscal

    # Rule 3: rebuild agencies_abbrev from pb agencies only
    seen: list[str] = []
    seen_set: set[str] = set()
    for pb in pbs:
        a = pb.get("agency")
        if a and a not in seen_set:
            seen.append(a)
            seen_set.add(a)

    if seen:
        fiscal["agencies_abbrev"] = seen
        fiscal["agencies_full"]   = [
            full_by_canon.get(a) or old_map.get(a, a) for a in seen]

    return fiscal


def _full_impact_column(cols: list[dict]) -> tuple[dict | None, str]:
    """The column a statement labels as full fiscal impact, else the last
    fiscal-year column, with the totals_basis label that says which: a
    statement without a Full column (Int 76-2022) is "last_year_column", and
    the single "Total" column the prompt builds from a narrative-only
    statement (Int 1259-2016) is "document_stated"."""
    for c in cols:
        if "full" in (c.get("label") or "").lower():
            return c, "full_impact_column"
    if not cols:
        return None, "none"
    if len(cols) == 1 and (cols[0].get("label") or "").strip().lower() == "total":
        return cols[0], "document_stated"
    return cols[-1], "last_year_column"


_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "seven": 7, "eight": 8, "nine": 9, "ten": 10}
# the bill title's standard clause, not a program end (Int 1126-2024)
_BOILERPLATE_SUNSET = re.compile(r"providing for the repeal of such local law upon the expiration thereof", re.I)


def _fy(year: int) -> int:
    return year % 100


def program_end_fy(quote: str, first_fy: int | None) -> int | None:
    """The last fiscal year (2-digit) a time-limited program runs, read from
    the statement's own sunset sentence; None when the sentence gives no end
    that can be placed (then coverage is unconfirmed). City fiscal years end
    June 30, so a date from July 3 on falls in the next year's FY; a law
    that ends July 1 or 2 ran through the June 30 before."""
    q = (quote or "").lower()
    ends = []
    dates_found: list[tuple[int, int, int]] = []
    for m, d, y in re.findall(r"(january|february|march|april|may|june|july|august|september|"
                              r"october|november|december)\s+(\d{1,2}),?\s+(\d{4})", q):
        mo, dd, yy = _MONTHS[m], int(d), int(y)
        dates_found.append((mo, dd, yy))
        # a date in the quote is usually the program's expiry: closes the
        # prior fiscal year on July 1-2 (house rule; matters 4806326, 7984588)
        ends.append(_fy(yy + (1 if (mo > 7 or (mo == 7 and dd > 2)) else 0)))
    for y in re.findall(r"\b(?:fiscal(?:\s+year)?|fy)\s*\(?f?y?\)?\s*'?(\d{4}|\d{2})\b", q):
        ends.append(_fy(int(y)))
    # durations run from the program's start. Two cases (blind audit 5/6, Sep
    # 28 2026):
    #  - the quote itself states an explicit start date ("takes effect July 1,
    #    2014 ... two years thereafter", matter 1709673): the start is known
    #    precisely, so the run covers whole fiscal years from the FY that date
    #    begins (July 1 itself starts the FY after it, the ordinary
    #    fiscal-year-containing rule, NOT the expiry house rule above) through
    #    N years later, i.e. start_fy + years - 1 = FY16 here.
    #  - no explicit date, only a bare duration relative to first_fy (the
    #    table's own first column, e.g. "remain in effect for 36 months" with
    #    no stated start): the effective date essentially never falls exactly
    #    on July 1, so a program running N whole years from a date inside
    #    first_fy is still active N years later, partway into fiscal year
    #    first_fy+N, not first_fy+N-1 (matters 1681072, 3521908; also matches
    #    the "ten years from FY19 -> FY29" case below, no stated start date).
    if dates_found:
        mo0, dd0, yy0 = dates_found[0]
        start_fy = _fy(yy0 + (1 if (mo0, dd0) >= (7, 1) else 0))
    if first_fy is not None or dates_found:
        for num, unit in re.findall(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
                                    r"[\s-]+(year|month|day)s?\b", q):
            n = int(num) if num.isdigit() else _NUM_WORDS[num]
            years = int(max(1, -(-(n if unit == "year" else n / 12 if unit == "month" else n / 365) // 1)))
            if dates_found:
                ends.append(start_fy + years - 1)
            elif first_fy is not None:
                ends.append(first_fy + years)
    # with several dates or durations (effective date + repeal) the latest
    # is the end
    return max(ends) if ends else None


def totals_from_columns(fiscal: dict) -> dict:
    """
    One number per bill (Tal, Sep 24 2026): the annual cost at full
    implementation, i.e. the statement's "Full Fiscal Impact" column, falling
    back to the sum of columns when that column is zero (a one-time
    first-year cost), and to the figure the statement states in its narrative
    when the table has nothing for that category ("See below", or capital
    described only in prose while the expense table shows $0).

    Costs are always positive: statements print costs in parentheses, and a
    cost read as negative flips a cost into a saving (3 of 14 audited records,
    Sep 24 2026). A negative revenue is a revenue reduction, counted as cost.
    `totals_basis` records where each figure came from.
    """
    if fiscal.get("cost_estimable") is False:
        return fiscal
    cols = fiscal.get("fiscal_table_columns") or []
    for c in cols:                       # a cost cell is a cost whatever its printed sign
        for k in ("expenditure", "capital"):
            if isinstance(c.get(k), (int, float)):
                c[k] = abs(c[k])
        # a revenue loss written both as negative revenue and as the same
        # amount of expenditure (older instructions asked for both) counts once
        rv, ex = c.get("revenue") or 0, c.get("expenditure") or 0
        if rv < 0 and ex and abs(ex + rv) <= 1:
            c["expenditure"] = 0
        # the column's net follows its own figures (statements print costs
        # unsigned, and the model copied a positive "Net" for a cost; round 5)
        if any(isinstance(c.get(k), (int, float)) for k in ("revenue", "expenditure", "capital")):
            c["net"] = (c.get("revenue") or 0) - (c.get("expenditure") or 0) - (c.get("capital") or 0)
    stated = {
        "revenue": fiscal.get("total_revenue") or 0,
        "expenditure": abs(fiscal.get("total_expenditure") or 0),
        "capital": abs(fiscal.get("total_capital") or 0),
    }
    full, full_basis = _full_impact_column(cols)
    table_has_figures = any((c.get(k) or 0) for c in cols for k in ("revenue", "expenditure", "capital"))
    bases = set()

    # a pilot counts only with the statement's own sunset sentence (round-4
    # audit, Sep 24 2026: 3 of 8 flags had no sunset for the costed program);
    # extract_fiscal_data checks the quote against the document text
    time_limited = (bool(fiscal.get("time_limited_program"))
                    and bool((fiscal.get("sunset_quote") or "").strip())
                    and not _BOILERPLATE_SUNSET.search(fiscal.get("sunset_quote") or ""))
    # the standard table repeats the succeeding year as "Full Fiscal Impact
    # FY27"; summing it too would count that year twice
    year_of = lambda c: (re.findall(r"FY\s*'?(\d{2,4})", c.get("label") or "", re.I) or [None])[-1]
    other_years = lambda c: {year_of(o) for o in cols if o is not c}
    life_cols = [c for c in cols
                 if not ("full" in (c.get("label") or "").lower() and year_of(c) in other_years(c))]

    # Tal, Sep 26 2026: a program-life total only when the statement's
    # columns cover the whole program. A pilot that outlasts them gets the
    # annual full-impact figure like every other bill, plus its end year;
    # the missing years are never extrapolated.
    fiscal.pop("outlasts_statement", None)
    fiscal.pop("program_end_fy", None)
    if time_limited:
        fys = [int(y) % 100 for y in (year_of(c) for c in cols) if y]
        end = program_end_fy(fiscal.get("sunset_quote"), min(fys) if fys else None)
        if end is not None:
            fiscal["program_end_fy"] = end
        if fys and (end is None or end > max(fys)):
            fiscal["outlasts_statement"] = True
            time_limited = False
        elif fys and end is not None and end < max(fys):
            # a law that starts mid-year runs into the year after its
            # nominal end (ten years from FY19 -> FY29, Int 755-2018)
            fiscal["program_end_fy"] = max(fys)

    def pick(key):
        # a pilot that ends has no steady-state year: its cost is the
        # program's life, the sum of its year columns (Int 1085-2018)
        if time_limited:
            col_sum = sum((c.get(key) or 0) for c in life_cols)
            if col_sum:
                bases.add("program_life_sum")
                return col_sum
        if full is not None and (full.get(key) or 0):
            # the model sometimes writes the narrative's figure into the Full
            # column even though every column read "See below" for this
            # category (Sep 27 2026 adjudication: 5534276, 6702327, 5839389,
            # 2939936); see_below_categories says so, so the basis still
            # reads document_stated even though the number sits in the cell
            basis = "document_stated" if key in (fiscal.get("see_below_categories") or []) else full_basis
            bases.add(basis)
            return full.get(key)
        col_sum = sum((c.get(key) or 0) for c in cols)
        if col_sum:
            bases.add("sum_of_columns")
            return col_sum
        # the statement's stated figure only when its table is empty: a table
        # that already carries the cost (e.g. as negative revenue) must not
        # get the same amount added again from the stated total
        # ...and never when the statement says the money is already in the
        # Financial Plan: the prose figure is then the budgeted amount (Int
        # 253-2014, round 5), and the bill adds nothing new
        if stated[key] and not table_has_figures and not fiscal.get("costs_already_in_financial_plan"):
            bases.add("document_stated")
            return stated[key]
        return 0

    rev, exp, cap = pick("revenue"), pick("expenditure"), pick("capital")
    if rev < 0:
        if fiscal.get("costs_already_in_financial_plan"):
            # the loss is already reflected in the budget (Sep 27 2026
            # adjudication, matter 5745591: tracker had added a $33.75M
            # already-budgeted revenue reduction to expenditure, right
            # answer left it out of both totals): it adds nothing new
            rev = 0
        else:                             # revenue reduction: a cost to the city
            exp, rev = exp - rev, 0
    # a genuine reduction in city spending, not a cost (Sep 27 2026
    # adjudication, matter 2103602): keep it negative so net reflects the
    # saving instead of forcing every expenditure figure positive
    if fiscal.get("expenditure_is_savings") and exp > 0:
        exp = -exp
    # a Full column that carries one-time start-up costs is not the annual
    # cost at full implementation; the statement's recurring figure is
    rec = fiscal.get("recurring_annual_expenditure")
    if isinstance(rec, (int, float)) and 0 < rec < exp and not fiscal.get("expenditure_is_savings"):
        exp = rec
        bases.discard("full_impact_column")
        bases.add("document_stated")
    fiscal["total_revenue"] = rev
    fiscal["total_expenditure"] = exp
    fiscal["total_capital"] = cap or None
    fiscal["net_fiscal_impact"] = rev - exp - (cap or 0)
    fiscal["totals_basis"] = (bases.pop() if len(bases) == 1 else
                              "mixed:" + "+".join(sorted(bases)) if bases else "none")
    return fiscal


def reconcile_totals(fiscal: dict) -> dict:
    """
    Make total_revenue / total_expenditure / total_capital agree with
    net_fiscal_impact (= revenue - expenditure - capital). Two extraction
    errors found by validate_fiscal_impacts.py on Sep 2 2026 (24 records):

    1. Revenue LOSS stored as positive revenue: tax abatements/exemptions
       ("$4,000,000 in abatements") came back as total_revenue=+4,000,000 with
       net=-4,000,000. The net was right; the column was not. The prompt's
       convention (NARRATIVE FORMAT rules) is that a revenue reduction is a
       cost: revenue 0, the amount added to expenditure. Rule: if revenue > 0
       and net == -(revenue + expenditure + capital), move revenue into
       expenditure.
    2. Capital double-counted inside expenditure: total_expenditure ==
       total_capital (or contains it) with net == -expenditure. Rule: if
       capital > 0 and net == -expenditure and expenditure >= capital, the
       operational part is expenditure - capital.

    Anything else that still disagrees is left alone and stays a soft finding.
    """
    rev, exp, cap, net = (fiscal.get(k) for k in
                          ("total_revenue", "total_expenditure", "total_capital", "net_fiscal_impact"))
    if None in (rev, exp, net):
        return fiscal
    cap0 = cap or 0
    if cap0 > 0 and abs(exp - cap0) <= 1 and abs(net + exp + cap0) <= 1:
        # the same capital figure written into both expenditure and capital
        # (Int 353-2024, Sep 24 2026: $605M twice, net -$1.21B)
        fiscal["total_expenditure"] = 0
        fiscal["net_fiscal_impact"] = rev - cap0
        fiscal["totals_reconciled"] = "capital_duplicated_as_expenditure"
        return fiscal
    if abs((rev - exp - cap0) - net) <= 1:
        return fiscal
    if rev > 0 and abs(-(rev + exp + cap0) - net) <= 1:
        fiscal["total_revenue"] = 0
        fiscal["total_expenditure"] = exp + rev
        for col in fiscal.get("fiscal_table_columns") or []:
            cr = col.get("revenue") or 0
            if cr > 0 and (col.get("net") or 0) < 0:
                col["revenue"] = 0
                col["expenditure"] = (col.get("expenditure") or 0) + cr
        fiscal["totals_reconciled"] = "revenue_loss_moved_to_expenditure"
        return fiscal
    if cap0 > 0 and abs(-exp - net) <= 1 and exp >= cap0:
        fiscal["total_expenditure"] = exp - cap0
        fiscal["totals_reconciled"] = "capital_inside_expenditure"
        return fiscal
    return fiscal


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="NYC Council Fiscal Impacts Pipeline")
    parser.add_argument(
        "--incremental", action="store_true",
        help="Skip matters already present in fiscal_impacts.json",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Process data but do not write output file",
    )
    parser.add_argument(
        "--historical", action="store_true",
        help="Also search historical years via the advanced search form (slow)",
    )
    parser.add_argument(
        "--historical-years", default="2014-2023",
        metavar="START-END",
        help="Year range for --historical mode, e.g. '2010-2023' (default: 2014-2023)",
    )
    parser.add_argument(
        "--seed-laws", default=None, metavar="YEARS",
        help="Also check every enacted local law in laws.json for a fiscal impact "
             "statement: '2024-2026', '2024', 'all', or 'auto' (previous + current year). "
             "Legistar's attachment search misses most of them.",
    )
    parser.add_argument(
        "--matters", default=None,
        help="Comma-separated matter ids (or @file.json with a list). With --reextract: limit the re-extraction to these table records. Without: process exactly these matters from laws.json (skip list ignored), e.g. to re-check skip-listed laws.",
    )
    parser.add_argument(
        "--resume-only", action="store_true",
        help="Do only the cheap batch-resume check: exit 0 immediately if no batch is pending "
             "(fiscal_batch_state.json absent); otherwise poll it and, if ended, finish and save. "
             "No Legistar search, no re-download. For the daily resume schedule.",
    )
    parser.add_argument(
        "--reextract", choices=["superseded", "all"], default=None,
        help="Re-process records already in the table and replace them in place: "
             "'superseded' only where the page now carries a newer Council statement "
             "than the one stored, 'all' every record with a Legistar page. Skips "
             "the Legistar search. A record whose enacted statement shows no storable "
             "impact is removed and added to the skip list; an error keeps the old record.",
    )
    parser.add_argument(
        "--emit-packets", metavar="DIR", default=None,
        help="Max-plan routine: write one extraction packet per pending statement to DIR "
             "(no API call), for a subagent to answer into DIR/results/<id>.json.",
    )
    parser.add_argument(
        "--ingest", metavar="DIR", default=None,
        help="Max-plan routine: validate and finish every DIR/results/<id>.json (same "
             "post-processing the API path uses), save, and update pipeline/max_refresh.json.",
    )
    args = parser.parse_args()

    # --emit-packets / --ingest: the Max-plan routine, no API key, no billing.
    client = None
    if not (args.emit_packets or args.ingest):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            log.error("ANTHROPIC_API_KEY environment variable is not set. See README.")
            return 1
        client = anthropic.Anthropic(api_key=api_key)
    session = create_session()

    existing     = load_existing(OUTPUT_PATH)
    existing_ids = {str(r["matter_id"]) for r in existing.get("records", [])}
    records      = list(existing.get("records", []))
    skips        = load_skip_list(SKIP_PATH)
    if args.incremental:
        existing_ids |= set(skips)
        log.info(f"Incremental: {len(records)} records + {len(skips)} known no-impact matters will be skipped")

    # the statement each skip was judged on (pipeline/skip_attachments.json),
    # so a pending bill skipped as zero is re-read only when Legistar shows a
    # newer statement (fiscal audit round 2: amended -A statements added costs
    # to 4 bills skipped as zero on their first statement)
    skip_att = json.loads(SKIP_ATT_PATH.read_text()) if SKIP_ATT_PATH.exists() else {}
    current_att: dict[str, str] = {}

    def mark_skip(matter_id: str, reason: str) -> None:
        if current_att.get(matter_id):
            skip_att[matter_id] = current_att[matter_id]
        existing_ids.add(matter_id)  # so a later duplicate hit in this run is skipped
        skips[matter_id] = reason

    total_new = 0

    # Collect all matters, deduplicating by matter_id.
    all_matter_ids: set[str] = set()
    matters: list[tuple[str, str]] = []

    def _add_matters(new: list[tuple[str, str]]) -> int:
        added = 0
        for mid, guid in new:
            if mid not in all_matter_ids:
                all_matter_ids.add(mid)
                matters.append((mid, guid))
                added += 1
        return added

    index_by_id = {str(r["matter_id"]): i for i, r in enumerate(records)}
    replaced = removed = unchanged = 0
    if args.resume_only:
        log.info("--resume-only: skipping the Legistar search entirely")
    elif args.reextract:
        only = None
        if args.matters:
            only = set(json.loads(Path(args.matters[1:]).read_text()) if args.matters.startswith("@")
                       else args.matters.split(","))
        _add_matters([(str(r["matter_id"]), r["legistar_guid"]) for r in records
                      if r.get("legistar_guid") and r.get("legistar_url")
                      and (only is None or str(r["matter_id"]) in only)])
        log.info(f"Re-extract ({args.reextract}): {len(matters)} records with a Legistar page")
    elif args.matters:
        # a named set of matters outside the table (e.g. skip-listed laws to
        # re-check): take their GUIDs from laws.json and ignore the skip list
        only = set(json.loads(Path(args.matters[1:]).read_text()) if args.matters.startswith("@")
                   else args.matters.split(","))
        # "id:GUID" names a bill that is not an enacted law (a pending bill
        # wrongly skip-listed, fiscal audit Oct 6 2026); a bare id takes its
        # GUID from laws.json
        given = dict(t.split(":", 1) for t in only if ":" in t)
        only = {t.split(":", 1)[0] for t in only}
        laws = json.loads(LAWS_PATH.read_text())["laws"]
        _add_matters([(m, g) for m, g in given.items()])
        _add_matters([(str(l["matter_id"]), l["legistar_guid"]) for l in laws
                      if str(l["matter_id"]) in only and l.get("legistar_guid")])
        for m in only:
            skips.pop(m, None)
            existing_ids.discard(m)
        log.info(f"Matters run: {len(matters)} of {len(only)} requested found in laws.json")
    else:
        # Basic all-years search — covers all available bills in Legistar's
        # attachment index (currently 2024+; the year filter is non-functional here).
        basic = search_legistar_all(session)
        _add_matters(basic)
        log.info(f"Basic search: {len(basic)} results, {len(matters)} unique so far")
        time.sleep(2)

    # Optional historical search using the advanced form, which has a working
    # lstYearsAdvanced filter. Run year-by-year for 2014–2023 (or custom range).
    if args.historical and not args.resume_only:
        try:
            start_str, end_str = args.historical_years.split("-")
            hist_years = [str(y) for y in range(int(start_str), int(end_str) + 1)]
        except ValueError:
            log.error(f"Invalid --historical-years value: {args.historical_years!r} (expected START-END)")
            return 1

        log.info(f"Historical search: years {args.historical_years}")
        for year in hist_years:
            hist = search_legistar_advanced_year(session, year)
            added = _add_matters(hist)
            log.info(f"  Year {year}: {added} new unique matters (running total: {len(matters)})")
            time.sleep(3)  # be polite between year searches

    if args.seed_laws and not args.resume_only:
        seed = load_law_seed(args.seed_laws)
        added = _add_matters(seed)
        log.info(f"Law seed ({args.seed_laws}): {len(seed)} enacted laws, {added} new unique matters (running total: {len(matters)})")

    log.info(f"Total matters to process: {len(matters)}")

    def _drop_if_reextracting(matter_id: str) -> None:
        nonlocal removed
        if args.reextract and matter_id in index_by_id:
            records[index_by_id[matter_id]] = None     # compacted before saving
            removed += 1
            log.info(f"  Re-extract: enacted statement has no storable impact; record removed")

    # Phase 1: fetch and pre-check every matter, deferring the actual
    # extraction call so batch mode can build every request before submitting
    # any of them (CLAUDE_BATCH=1: one Message Batch instead of N synchronous
    # calls). `pending` and `pending_ctx` are parallel to each other.
    #
    # --resume-only (the cheap daily schedule, days 2-7 of the month): skip
    # phase 1 entirely and reload `pending`/`pending_ctx` from PENDING_PATH,
    # written just before the batch was submitted, so resuming never repeats
    # the Legistar search or re-downloads statements.
    pending: list[tuple[str, str]] = []
    pending_ctx: dict[str, dict] = {}

    if args.resume_only:
        if not BATCH_STATE_PATH.exists():
            log.info("--resume-only: no pending batch (fiscal_batch_state.json absent) — nothing to do")
            return 0
        if not PENDING_PATH.exists():
            log.error(f"--resume-only: {BATCH_STATE_PATH.name} exists but {PENDING_PATH.name} is missing — cannot resume")
            return 1
        saved = json.loads(PENDING_PATH.read_text())
        for matter_id, d in saved.items():
            pending.append((matter_id, d["text"]))
            pending_ctx[matter_id] = {"guid": d["guid"], "att_id": d["att_id"]}
        log.info(f"--resume-only: resuming {len(pending)} pending extraction(s)")
    else:
        # skips that can go stale are re-checked whenever the matter is in this
        # run's selection (fiscal audit, Oct 6 2026): a statement is often
        # attached after a first check (7 of 68 sampled "no_attachment" skips
        # had one), and a "proposed" skip on a bill since enacted hid 63
        # enacted laws after the Sep 24 is_proposed_bill fix
        enacted = {str(l["matter_id"]) for l in json.loads(LAWS_PATH.read_text())["laws"]} if LAWS_PATH.exists() else set()
        zero_reasons = ("zero_precheck", "zero_or_unestimable")
        recheck = {m for m, _ in matters
                   if skips.get(m) == "no_attachment" or (skips.get(m) == "proposed" and m in enacted)
                   or (skips.get(m) in zero_reasons and m not in enacted)}
        if recheck and args.incremental and not args.reextract:
            existing_ids -= recheck
            log.info(f"Re-checking {len(recheck)} skips that can go stale (no_attachment, proposed-but-enacted)")
        gate_done = gated_done_ids()
        if gate_done:
            log.info(f"MAX_REFRESH_GATE=1: skipped {len(gate_done & {m for m, _ in matters})} ids "
                     f"done on Max this month")
        for matter_id, guid in matters:
            if args.incremental and matter_id in existing_ids and not args.reextract:
                log.info(f"  Skipping already-processed matter {matter_id}")
                continue
            if matter_id in gate_done:
                continue

            log.info(f"Processing matter {matter_id} ...")

            try:
                att_id, att_guid = get_fiscal_attachment(session, matter_id, guid)
                time.sleep(0.5)
                if att_id:
                    current_att[matter_id] = str(att_id)
                # a pending bill skipped as zero: re-read only a newer statement;
                # a skip recorded before skip_attachments.json existed takes
                # today's statement as its baseline (no model call)
                if args.incremental and not args.reextract and skips.get(matter_id) in ("zero_precheck", "zero_or_unestimable"):
                    if att_id and skip_att.get(matter_id) in (None, str(att_id)):
                        skip_att[matter_id] = str(att_id)
                        existing_ids.add(matter_id)
                        continue
                if (args.reextract == "superseded" and matter_id in index_by_id
                        and str(records[index_by_id[matter_id]].get("attachment_id")) == str(att_id)):
                    unchanged += 1
                    continue

                if not att_id:
                    log.info(f"  No fiscal impact attachment found — skipping")
                    mark_skip(matter_id, "no_attachment")
                    continue

                docx_path = download_docx(session, att_id, att_guid)
                time.sleep(0.5)

                if not docx_path:
                    continue

                text = extract_docx_text(docx_path)
                if not text.strip():
                    # never a permanent skip (Oct 6 2026): a failed download or a
                    # missing .doc reader marked 226 real statements unreadable
                    # forever; an empty read is retried on the next run instead
                    log.warning(f"  Empty text from {docx_path} — retried next run")
                    continue

                # Fast pre-check: skip obvious zero-impact bills before calling Claude.
                # If every dollar figure in the text is $0 and there's no "See below",
                # there's nothing worth storing.
                # the pre-check counts only $-prefixed figures, and statement tables
                # often print bare numbers; on a re-extraction let the model read it
                if not args.reextract and text_is_zero_impact(text):
                    log.info(f"  Pre-check: all-zero fiscal impact — skipping Claude call")
                    mark_skip(matter_id, "zero_precheck")
                    _drop_if_reextracting(matter_id)
                    continue

                pending.append((matter_id, text))
                pending_ctx[matter_id] = {"guid": guid, "att_id": att_id}

            except Exception as e:
                log.error(f"  Error on matter {matter_id}: {e}", exc_info=True)

            time.sleep(1)  # be polite to Legistar

    # Phase 2: extract (Max-plan packets, batch, or synchronous).
    used_batch = False
    if args.emit_packets:
        emit_packets(pending, Path(args.emit_packets))
        return 0
    elif args.ingest:
        extracted = ingest_packets(pending, Path(args.ingest))
    else:
        if os.environ.get("CLAUDE_BATCH") == "1" and pending and not BATCH_STATE_PATH.exists():
            PENDING_PATH.write_text(json.dumps(
                {mid: {"text": text, **pending_ctx[mid]} for mid, text in pending}, indent=1, ensure_ascii=False))
        log.info(f"Extracting {len(pending)} statement(s) "
                 f"({'batch' if os.environ.get('CLAUDE_BATCH') == '1' else 'synchronous'}) ...")
        used_batch = os.environ.get("CLAUDE_BATCH") == "1" and bool(pending)
        extracted = extract_many(pending, client, max_wait_s=MAX_WAIT_S)
        if extracted is None:
            log.info("Batch still running; nothing else written this run.")
            log.info(USAGE.line())
            return 0

    # Phase 3: the same post-extraction handling for every result, batch or not.
    for matter_id, text in pending:
        guid, att_id = pending_ctx[matter_id]["guid"], pending_ctx[matter_id]["att_id"]
        try:
            if matter_id not in extracted:
                # --ingest: no result file, invalid JSON, or schema failure;
                # already recorded in max_refresh.json's "left" — try again
                # next run (the Actions fallback, or the routine next month).
                log.warning(f"  {matter_id}: no valid packet result, leaving for next run")
                continue
            fiscal = extracted[matter_id]
            if "extraction_error" in fiscal:
                # a failed call is not evidence of zero impact: never skip-list
                # it, and in --reextract mode keep the existing record
                log.error(f"  Extraction failed, leaving matter for the next run: {fiscal['extraction_error']}")
                continue

            # Post-extraction filter: skip if no real fiscal impact or unestimable.
            if not record_has_fiscal_impact(fiscal):
                reason = ("already_in_financial_plan" if fiscal.get("costs_already_in_financial_plan")
                          else "zero_or_unestimable")
                # a stored record with figures is never dropped as zero on a
                # re-read (round-4 audit: 4 of 4 such drops were wrong); only
                # the budget-plan rule may remove it
                if args.reextract and matter_id in index_by_id and reason == "zero_or_unestimable":
                    log.warning("  Re-extract read zero/unestimable for a stored record; keeping the stored record")
                    continue
                log.info(f"  Post-check: no new fiscal impact ({reason}), skipping")
                mark_skip(matter_id, reason)
                _drop_if_reextracting(matter_id)
                continue

            # Skip budget modification resolutions (MN-#) — these are Charter
            # §107(e) administrative approvals, not independent legislation.
            if is_budget_modification(fiscal):
                log.info(f"  Budget modification (MN-#) — skipping")
                mark_skip(matter_id, "budget_modification")
                _drop_if_reextracting(matter_id)
                continue

            # Skip proposed (not yet passed) bills — only final/enacted legislation
            # belongs in the tracker.
            if is_proposed_bill(fiscal, matter_id):
                log.info(f"  Proposed bill (not yet passed) — skipping")
                mark_skip(matter_id, "proposed")
                _drop_if_reextracting(matter_id)
                continue

            # Normalize agency attribution: assign DOT to street sign line items
            # and prune agencies not present in program_breakdowns.
            fiscal = normalize_agency_attribution(fiscal)
            fiscal = reconcile_totals(fiscal)

            record = {
                "matter_id":    matter_id,
                "legistar_guid": guid,
                "legistar_url": (
                    f"https://legistar.council.nyc.gov/LegislationDetail.aspx"
                    f"?ID={matter_id}&GUID={guid}"
                ),
                "attachment_id": att_id,
                "processed_at": datetime.utcnow().isoformat() + "Z",
                # Legistar's own File # ("Int 1002-2026"); the frontend shows
                # this over the statement's `file_number`, which is inconsistent
                # and blank for bills numbered after the statement was drafted.
                "legistar_file": LEGISTAR_FILE_BY_MATTER.get(matter_id),
                **fiscal,
            }

            if args.reextract and matter_id in index_by_id:
                records[index_by_id[matter_id]] = record
                replaced += 1
            else:
                records.append(record)
                total_new += 1
            existing_ids.add(matter_id)

            fn    = record.get("legistar_file") or fiscal.get("file_number", "?")
            title = (fiscal.get("title") or "")[:60]
            log.info(f"  -> {fn}: {title}")

        except Exception as e:
            log.error(f"  Error on matter {matter_id}: {e}", exc_info=True)

    records[:] = [r for r in records if r is not None]
    if args.reextract:
        log.info(f"Re-extract: {replaced} replaced, {removed} removed, {unchanged} already current")
    log.info(f"Processed {total_new} new matters (total in file: {len(records)})")
    log.info(USAGE.line())

    if not args.dry_run:
        save_output(OUTPUT_PATH, records)
        save_skip_list(SKIP_PATH, skips)
        SKIP_ATT_PATH.write_text(json.dumps(dict(sorted(skip_att.items())), indent=1) + "\n")
        # Only now, with fiscal_impacts.json safely written, is it safe to
        # forget the batch: a crash between extract_many and here must still
        # find the batch id next run rather than resubmitting it (review, Sep
        # 28 2026). The workflow must stage this deletion at commit time.
        if used_batch:
            clear_state(BATCH_STATE_PATH)
            PENDING_PATH.unlink(missing_ok=True)
    else:
        log.info("--dry-run: not writing output file")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
