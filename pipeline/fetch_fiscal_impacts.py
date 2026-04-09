#!/usr/bin/env python3
"""
NYC Council Fiscal Impacts Pipeline
Fetches fiscal impact statement .docx files from NYC Legistar, extracts structured
data using the Claude API, and writes results to fiscal_impacts.json for the
data website.

Usage:
    python fetch_fiscal_impacts.py --years 2024,2025,2026
    python fetch_fiscal_impacts.py --years 2024,2025,2026 --incremental
    python fetch_fiscal_impacts.py --help

Environment variables required:
    ANTHROPIC_API_KEY   Your Anthropic API key

Notes:
    - Uses Legistar's public web interface (no API token required)
    - Caches downloaded .docx files in pipeline/cache/docx/ to avoid re-downloading
    - Run with --incremental in GitHub Actions to only process new matters
"""

from __future__ import annotations

import os
import re
import json
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path
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
OUTPUT_PATH  = REPO_ROOT / "nyc_council_fiscal_impacts_tracker" / "data" / "fiscal_impacts.json"
BASE_URL     = "https://legistar.council.nyc.gov"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# ── Extraction prompt ─────────────────────────────────────────────────────────
EXTRACTION_PROMPT = """You are extracting structured data from a New York City Council fiscal impact statement document. Extract the following fields and return ONLY a valid JSON object — no markdown fences, no explanation, just the JSON.

DOCUMENT TEXT:
---
{text}
---

Return a JSON object with exactly these fields (use null for missing/unknown, 0 for explicit zeros, true/false for booleans):

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

  "total_revenue": 0,
  "total_expenditure": 0,
  "total_capital": null,
  "net_fiscal_impact": 0,

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
- total_revenue / total_expenditure / total_capital: sum across ALL fiscal-year columns. Always positive numbers.
- net_fiscal_impact = total_revenue - total_expenditure - total_capital. Negative = net cost to city.
- If ANY cell says "See below" or indicates the cost cannot be estimated, set cost_estimable to false and set that total to null.
- fiscal_table_columns must preserve the exact column structure from the document (there may be 2–6 columns).
- Extract ALL agencies mentioned anywhere in the document (not just in the table).
- Standard NYC agency abbreviations: DOT, DPR, NYPD, FDNY, DOE, DSS, DFTA, DEP, HPD, HRA, DCAS, DSNY, DOF, DOB, DHS, NYCEM, TLC, SBS, DYCD, DOHMH, DCA, DDC, MTA, DOC, DCLA, ACS, MOCJ, OMB. Create reasonable abbreviations for others.
- program_breakdowns: extract named cost line items from the Impact on Expenditures section. May be empty [].
- For sponsors and prime_sponsor: strip all prefixes ("Council Member", "Council Members", "By Council Members", "(s):"). Return only the name. For "The Speaker (Council Member X)", return "X (Speaker)". Always use last name only as written in the document.
- Return ONLY the JSON object — no markdown, no explanation.
"""


# ── Legistar scraping ─────────────────────────────────────────────────────────

def create_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return s


def search_legistar_year(session: requests.Session, year: int) -> list[tuple[str, str]]:
    """
    Search Legistar for matters with 'Fiscal Impact Statement' in attachments
    for a given year. Returns list of (matter_id, guid) tuples.
    """
    log.info(f"Searching Legistar year={year} ...")

    r = session.get(f"{BASE_URL}/Legislation.aspx", timeout=20)
    r.raise_for_status()

    vs_match  = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', r.text)
    vsg_match = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', r.text)
    if not vs_match:
        log.error("Could not find __VIEWSTATE on Legistar search page")
        return []

    post_data = {
        "__VIEWSTATE":          vs_match.group(1),
        "__VIEWSTATEGENERATOR": vsg_match.group(1) if vsg_match else "",
        "ctl00$ContentPlaceHolder1$txtSearch":   "Fiscal Impact Statement",
        "ctl00$ContentPlaceHolder1$lstYears":    str(year),
        "ctl00$ContentPlaceHolder1$lstTypeBasic": "All Types",
        "ctl00$ContentPlaceHolder1$chkAttachments": "on",
        "ctl00$ContentPlaceHolder1$btnSearch":   "Search Legislation",
    }

    r2 = session.post(f"{BASE_URL}/Legislation.aspx", data=post_data, timeout=30)
    r2.raise_for_status()

    matters = re.findall(
        r"LegislationDetail\.aspx\?ID=(\d+)&(?:amp;)?GUID=([A-F0-9\-]+)",
        r2.text,
    )

    seen, unique = set(), []
    for mid, guid in matters:
        if mid not in seen:
            seen.add(mid)
            unique.append((mid, guid))

    log.info(f"  -> {len(unique)} matters found for {year}")
    return unique


def get_fiscal_attachment(
    session: requests.Session, matter_id: str, guid: str
) -> tuple[str | None, str | None]:
    """
    Fetch a matter's detail page and find the fiscal impact attachment.
    Returns (attachment_id, attachment_guid) or (None, None).
    """
    url = (
        f"{BASE_URL}/LegislationDetail.aspx"
        f"?ID={matter_id}&GUID={guid}&Options=Attachments|&Search=Fiscal+Impact+Statement"
    )
    r = session.get(url, timeout=20)
    r.raise_for_status()

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
    r = session.get(url, timeout=30)
    r.raise_for_status()

    if len(r.content) < 100:
        log.warning(f"  Suspiciously small download for att_id={att_id}")
        return None

    local.write_bytes(r.content)
    log.info(f"  Downloaded: {att_id}.docx ({len(r.content):,} bytes)")
    return local


def extract_docx_text(docx_path: Path) -> str:
    """Extract text from a .docx, including table cell content."""
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

def extract_fiscal_data(
    text: str, client: anthropic.Anthropic
) -> dict:
    """Call Claude API to extract structured fiscal data from docx text."""
    prompt = EXTRACTION_PROMPT.format(text=text[:18000])

    for attempt in range(3):
        try:
            msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw.rstrip())

            data = json.loads(raw)
            return data

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


# ── Data persistence ──────────────────────────────────────────────────────────

def load_existing(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"metadata": {}, "records": []}


def save_output(path: Path, records: list, years: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "metadata": {
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "total_records": len(records),
            "years_searched": years,
            "source": "NYC Legistar (legistar.council.nyc.gov)",
        },
        "records": records,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(records)} records -> {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="NYC Council Fiscal Impacts Pipeline")
    parser.add_argument(
        "--years", default="2024,2025,2026",
        help="Comma-separated years to search on Legistar (default: 2024,2025,2026)",
    )
    parser.add_argument(
        "--incremental", action="store_true",
        help="Skip matters already present in fiscal_impacts.json",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Process data but do not write output file",
    )
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(",")]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY environment variable is not set. See README.")
        return 1

    client  = anthropic.Anthropic(api_key=api_key)
    session = create_session()

    existing     = load_existing(OUTPUT_PATH)
    existing_ids = {str(r["matter_id"]) for r in existing.get("records", [])}
    records      = list(existing.get("records", []))

    total_new = 0

    for year in years:
        matters = search_legistar_year(session, year)
        time.sleep(1)

        for matter_id, guid in matters:
            if args.incremental and matter_id in existing_ids:
                log.info(f"  Skipping already-processed matter {matter_id}")
                continue

            log.info(f"Processing matter {matter_id} ...")

            try:
                att_id, att_guid = get_fiscal_attachment(session, matter_id, guid)
                time.sleep(0.5)

                if not att_id:
                    log.info(f"  No fiscal impact attachment found — skipping")
                    continue

                docx_path = download_docx(session, att_id, att_guid)
                time.sleep(0.5)

                if not docx_path:
                    continue

                text = extract_docx_text(docx_path)
                if not text.strip():
                    log.warning(f"  Empty text from {docx_path} — skipping")
                    continue

                log.info("  Calling Claude for extraction ...")
                fiscal = extract_fiscal_data(text, client)

                record = {
                    "matter_id":    matter_id,
                    "legistar_guid": guid,
                    "legistar_url": (
                        f"https://legistar.council.nyc.gov/LegislationDetail.aspx"
                        f"?ID={matter_id}&GUID={guid}"
                    ),
                    "attachment_id": att_id,
                    "processed_at": datetime.utcnow().isoformat() + "Z",
                    **fiscal,
                }

                records.append(record)
                existing_ids.add(matter_id)
                total_new += 1

                fn    = fiscal.get("file_number", "?")
                title = (fiscal.get("title") or "")[:60]
                log.info(f"  -> {fn}: {title}")

            except Exception as e:
                log.error(f"  Error on matter {matter_id}: {e}", exc_info=True)

            time.sleep(1)  # be polite to Legistar

    log.info(f"Processed {total_new} new matters (total in file: {len(records)})")

    if not args.dry_run:
        save_output(OUTPUT_PATH, records, years)
    else:
        log.info("--dry-run: not writing output file")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
