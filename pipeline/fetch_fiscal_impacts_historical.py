#!/usr/bin/env python3
"""
NYC Council Fiscal Impacts — Historical Scraper (2014–2023)

Phase 1: Paginates through ALL NYC Council legislation, collecting matter IDs
         for bills introduced in the target year range. Stops automatically
         when bills from before the range are reached.

Phase 2: For each matter, fetches the attachments tab, checks for a
         'Fiscal Impact Statement.docx' file, downloads it, extracts
         structured data via Claude, saves to checkpoint.

Phase 3: Merges checkpoint records into the main fiscal_impacts.json.

Usage:
    python pipeline/fetch_fiscal_impacts_historical.py
    python pipeline/fetch_fiscal_impacts_historical.py --years 2020-2023
    python pipeline/fetch_fiscal_impacts_historical.py --phase 2       # skip enumeration
    python pipeline/fetch_fiscal_impacts_historical.py --merge-only    # merge checkpoint only
    python pipeline/fetch_fiscal_impacts_historical.py --reset         # start fresh

Checkpoint: pipeline/cache/historical_checkpoint.json — auto-resumes on restart.
"""
from __future__ import annotations

import os
import re
import json
import time
import logging
import argparse
import sys
from datetime import datetime
from pathlib import Path

import requests
import anthropic

# ── Shared imports from main pipeline ─────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from fetch_fiscal_impacts import (
    create_session,
    download_docx,
    extract_docx_text,
    extract_fiscal_data,
    record_has_fiscal_impact,
    text_is_zero_impact,
    save_output,
    load_existing,
    BASE_URL,
    OUTPUT_PATH,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

CHECKPOINT_PATH = Path(__file__).parent / "cache" / "historical_checkpoint.json"


# ── Checkpoint ────────────────────────────────────────────────────────────────

def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH) as f:
            cp = json.load(f)
        log.info(
            f"Resumed checkpoint: {len(cp['matters'])} matters enumerated, "
            f"{len(cp['processed_ids'])} processed, {len(cp['records'])} records saved"
        )
        return cp
    return {
        "phase1_complete": False,
        "matters": {},        # matter_id -> {"guid": ..., "file_number": ...}
        "processed_ids": [],  # matter_ids already checked in phase 2
        "records": [],        # extracted records with non-zero fiscal impact
        "stats": {"total_enumerated": 0, "with_attachment": 0, "claude_calls": 0, "records_saved": 0},
    }


def save_checkpoint(cp: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(cp, f, indent=2)


# ── Phase 1: Enumerate all legislation by paginating the general search ────────

def extract_year(file_number: str) -> int | None:
    """
    Parse the 4-digit year from a Legistar file number.
    Handles two formats:
      T2026-1669       → 2026  (T/Tracking items: year is prefix)
      Int 1102-2023    → 2023  (Introductions, Resolutions, etc.: year is suffix)
    """
    fn = file_number.strip()
    # T-prefix format: one or more uppercase letters followed immediately by 4 digits
    m = re.match(r'[A-Z]+(\d{4})-', fn)
    if m:
        return int(m.group(1))
    # Year-suffix format: ends in -YYYY
    m = re.search(r'-(\d{4})\s*$', fn)
    if m:
        return int(m.group(1))
    return None


def _advanced_search_initial(session: requests.Session) -> tuple[str, requests.Response]:
    """
    Do the two-step switch to Legistar advanced mode and run an empty search
    (all types, all years). Returns (client_state_json, response_with_results).
    """
    r = session.get(f"{BASE_URL}/Legislation.aspx", timeout=20)
    r.raise_for_status()
    vs  = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', r.text).group(1)
    vsg = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', r.text)

    r2 = session.post(f"{BASE_URL}/Legislation.aspx", data={
        "__VIEWSTATE":          vs,
        "__VIEWSTATEGENERATOR": vsg.group(1) if vsg else "",
        "ctl00$ContentPlaceHolder1$btnSwitch":    "Advanced search >>>",
        "ctl00$ContentPlaceHolder1$lstYears":     "This Year",
        "ctl00$ContentPlaceHolder1$lstTypeBasic": "All Types",
    }, timeout=20)
    r2.raise_for_status()

    vs2  = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', r2.text).group(1)
    vsg2 = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', r2.text)

    cs = json.dumps({
        "enabled": True, "emptyMessage": "", "validationText": "All Years",
        "valueAsString": "All Years", "lastSetTextInitiatesRequest": False,
        "blockAnimationTimer": 0, "lastAutoCompleteIndex": -1, "Direction": 0,
    })

    r3 = session.post(f"{BASE_URL}/Legislation.aspx", data={
        "__VIEWSTATE":          vs2,
        "__VIEWSTATEGENERATOR": vsg2.group(1) if vsg2 else "",
        "ctl00$ContentPlaceHolder1$lstYearsAdvanced":             "All Years",
        "ctl00_ContentPlaceHolder1_lstYearsAdvanced_ClientState": cs,
        "ctl00$ContentPlaceHolder1$lstType":                      "All Types",
        "ctl00$ContentPlaceHolder1$lstMax":                       "100",
        "ctl00$ContentPlaceHolder1$btnSearch":                    "Search Legislation",
    }, timeout=60)
    r3.raise_for_status()
    return cs, r3


def enumerate_via_api(token: str, start_year: int, end_year: int, cp: dict) -> None:
    """
    Use the Legistar REST API (webapi.legistar.com) to enumerate all NYC Council
    matters introduced in [start_year, end_year].  Far faster and more complete
    than web-scraping — the API has no result cap.

    Requires a registered Granicus read token (pass via --token or LEGISTAR_TOKEN).
    """
    if cp.get("phase1_complete"):
        log.info("Phase 1 already complete — skipping enumeration")
        return

    BASE_API = "https://webapi.legistar.com/v1/nyc"
    start_date = f"{start_year}-01-01T00:00:00"
    end_date   = f"{end_year}-12-31T23:59:59"
    PAGE       = 1000

    log.info(f"Phase 1 (REST API): fetching {start_year}–{end_year} matters ...")

    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"

    skip = 0
    while True:
        params = {
            "token":    token,
            "$filter":  (
                f"MatterIntroDate ge datetime'{start_date}'"
                f" and MatterIntroDate le datetime'{end_date}'"
            ),
            "$select":  "MatterId,MatterGuid,MatterFile,MatterIntroDate",
            "$orderby": "MatterIntroDate asc",
            "$top":     PAGE,
            "$skip":    skip,
        }
        r = s.get(f"{BASE_API}/Matters", params=params, timeout=30)
        r.raise_for_status()
        batch = r.json()

        if not batch:
            break

        for m in batch:
            mid = str(m["MatterId"])
            if mid not in cp["matters"]:
                cp["matters"][mid] = {
                    "guid":        m["MatterGuid"],
                    "file_number": m.get("MatterFile", ""),
                }

        log.info(
            f"  offset={skip}: {len(batch)} returned | "
            f"total collected: {len(cp['matters'])}"
        )
        save_checkpoint(cp)

        if len(batch) < PAGE:
            break
        skip += PAGE
        time.sleep(0.3)

    cp["phase1_complete"] = True
    cp["stats"]["total_enumerated"] = len(cp["matters"])
    save_checkpoint(cp)
    log.info(f"Phase 1 complete (API): {len(cp['matters'])} matters in {start_year}–{end_year}")


def enumerate_all_legislation(
    session: requests.Session,
    start_year: int,
    end_year: int,
    cp: dict,
) -> None:
    """
    Paginate through ALL Legistar legislation (no filters).
    Collect matters whose file number year falls in [start_year, end_year].
    Stop when an entire page consists of bills from before start_year.
    """
    if cp.get("phase1_complete"):
        log.info("Phase 1 already complete — skipping enumeration")
        return

    log.info(f"Phase 1: paginating all legislation to find {start_year}–{end_year} bills ...")

    cs, r3 = _advanced_search_initial(session)
    current_html = r3.text
    page_num = 0
    last_checkpoint_page = 0

    while True:
        page_num += 1

        # Extract (matter_id, guid, file_number) from this page
        rows = re.findall(
            r'LegislationDetail\.aspx\?ID=(\d+)&(?:amp;)?GUID=([A-F0-9\-]+)[^"]*"[^>]*>([^<]+)<',
            current_html,
        )
        if not rows:
            log.info(f"  Page {page_num}: no rows — enumeration complete")
            break

        page_years = []
        added_this_page = 0
        for matter_id, guid, file_number in rows:
            fn   = file_number.strip()
            year = extract_year(fn)
            if year is not None:
                page_years.append(year)
            if year is not None and start_year <= year <= end_year:
                if matter_id not in cp["matters"]:
                    cp["matters"][matter_id] = {"guid": guid, "file_number": fn}
                    added_this_page += 1

        if page_years:
            min_yr, max_yr = min(page_years), max(page_years)
            in_range = sum(1 for y in page_years if start_year <= y <= end_year)
            log.info(
                f"  Page {page_num}: {len(rows)} bills | years {min_yr}–{max_yr} | "
                f"{in_range} in range | added: {added_this_page} | total: {len(cp['matters'])}"
            )
            # Stop if all bills are older than our target range
            if max_yr < start_year:
                log.info(f"  Reached {max_yr} — all bills before {start_year}. Stopping.")
                break
        else:
            log.info(f"  Page {page_num}: {len(rows)} bills | no parseable years")

        # Checkpoint every 10 pages
        if page_num - last_checkpoint_page >= 10:
            cp["stats"]["total_enumerated"] = len(cp["matters"])
            save_checkpoint(cp)
            last_checkpoint_page = page_num

        # Find next page pager link
        next_page = page_num + 1
        m = re.search(
            r"doPostBack\(&#39;([^&]+)&#39;,&#39;&#39;\)[^<]*<span>" + str(next_page) + r"</span>",
            current_html,
        )
        if not m:
            log.info(f"  No page {next_page} link — enumeration complete at page {page_num}")
            break

        event_target = m.group(1)
        vs_p  = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', current_html).group(1)
        vsg_p = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', current_html)

        rn = session.post(f"{BASE_URL}/Legislation.aspx", data={
            "__VIEWSTATE":          vs_p,
            "__VIEWSTATEGENERATOR": vsg_p.group(1) if vsg_p else "",
            "__EVENTTARGET":        event_target,
            "__EVENTARGUMENT":      "",
            "ctl00$ContentPlaceHolder1$lstYearsAdvanced":             "All Years",
            "ctl00_ContentPlaceHolder1_lstYearsAdvanced_ClientState": cs,
            "ctl00$ContentPlaceHolder1$lstType":                      "All Types",
            "ctl00$ContentPlaceHolder1$lstMax":                       "100",
        }, timeout=60)
        rn.raise_for_status()
        current_html = rn.text
        time.sleep(0.8)

    cp["phase1_complete"] = True
    cp["stats"]["total_enumerated"] = len(cp["matters"])
    save_checkpoint(cp)
    log.info(f"Phase 1 complete: {len(cp['matters'])} matters in {start_year}–{end_year}")


# ── Phase 2: Check each matter for a fiscal impact statement attachment ────────

def find_fiscal_attachment_api(
    matter_id: str, token: str
) -> str | None:
    """
    Use the Legistar REST API to get attachments for a matter.
    Returns the direct download URL (MatterAttachmentHyperlink) for the
    fiscal impact statement, or None if not found.
    """
    BASE_API = "https://webapi.legistar.com/v1/nyc"
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    r = s.get(
        f"{BASE_API}/Matters/{matter_id}/Attachments",
        params={"token": token},
        timeout=15,
    )
    r.raise_for_status()
    for att in r.json():
        name = att.get("MatterAttachmentName", "")
        if "fiscal" in name.lower():
            url = att.get("MatterAttachmentHyperlink", "")
            if url and url.lower().endswith(".docx"):
                return url
    return None


def download_docx_url(session: requests.Session, url: str) -> Path | None:
    """Download a .docx file from a direct URL and return the local path."""
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        if r.content[:4] != b"PK\x03\x04":
            return None  # not a valid docx/zip
        tmp = Path("/tmp") / f"fiscal_{abs(hash(url))}.docx"
        tmp.write_bytes(r.content)
        return tmp
    except Exception as e:
        log.warning(f"    Download failed ({url[:60]}): {e}")
        return None


def find_fiscal_attachment(
    session: requests.Session, matter_id: str, guid: str
) -> tuple[str | None, str | None]:
    """
    Fetch the matter's Attachments tab. If 'Fiscal Impact Statement.docx' is
    present, locate and return (att_id, att_guid). Returns (None, None) if not found.
    Used as fallback when no API token is available.
    """
    url = (
        f"{BASE_URL}/LegislationDetail.aspx"
        f"?ID={matter_id}&GUID={guid}&Options=Attachments|&Search=Fiscal+Impact+Statement"
    )
    r = session.get(url, timeout=20)
    r.raise_for_status()

    # Quick pre-check — if "fiscal impact" doesn't appear at all, skip HEAD requests
    if "fiscal impact" not in r.text.lower():
        return None, None

    # Find all attachment download links and HEAD each one
    views = re.findall(
        r'View\.ashx\?M=F&(?:amp;)?ID=(\d+)&(?:amp;)?GUID=([A-F0-9\-]+)', r.text
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


# ── Phase 3: Merge ─────────────────────────────────────────────────────────────

def merge_into_main(records: list[dict]) -> int:
    """Merge records into fiscal_impacts.json. Returns count actually added."""
    existing = load_existing(OUTPUT_PATH)
    existing_ids = {str(r["matter_id"]) for r in existing.get("records", [])}
    all_records = list(existing.get("records", []))

    added = 0
    for rec in records:
        if str(rec["matter_id"]) not in existing_ids:
            all_records.append(rec)
            existing_ids.add(str(rec["matter_id"]))
            added += 1

    save_output(OUTPUT_PATH, all_records)
    return added


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="NYC Council Historical Fiscal Impacts Scraper")
    parser.add_argument("--years",       default="2014-2023", metavar="START-END",
                        help="Year range to search (default: 2014-2023)")
    parser.add_argument("--phase",       type=int, choices=[1, 2],
                        help="Run only phase 1 (enumerate) or phase 2 (process)")
    parser.add_argument("--merge-only",  action="store_true",
                        help="Skip scraping; merge checkpoint records into fiscal_impacts.json")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Enumerate + check for attachments, but skip downloads and Claude")
    parser.add_argument("--reset",       action="store_true",
                        help="Delete checkpoint and start from scratch")
    parser.add_argument("--token",       default=os.environ.get("LEGISTAR_TOKEN"),
                        help="Legistar REST API token for Phase 1 enumeration "
                             "(or set LEGISTAR_TOKEN env var). Without this, falls back "
                             "to web-scraping, which is capped at ~164 recent bills.")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    needs_claude = not args.dry_run and not args.merge_only and args.phase != 1
    if not api_key and needs_claude:
        log.error("ANTHROPIC_API_KEY is not set")
        return 1

    try:
        start_year, end_year = [int(y) for y in args.years.split("-")]
    except ValueError:
        log.error(f"Invalid --years value: {args.years!r} (expected e.g. 2014-2023)")
        return 1

    if args.reset and CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()
        log.info("Checkpoint deleted")

    cp      = load_checkpoint()
    client  = None if args.dry_run else anthropic.Anthropic(api_key=api_key)
    session = create_session()

    # ── Merge-only mode ───────────────────────────────────────────────────────
    if args.merge_only:
        added = merge_into_main(cp["records"])
        log.info(f"Merged {added} new records into fiscal_impacts.json")
        return 0

    # Existing matter IDs to skip in phase 2 (already in main file)
    existing_ids = {str(r["matter_id"]) for r in load_existing(OUTPUT_PATH).get("records", [])}

    # ── Phase 1: Enumerate ────────────────────────────────────────────────────
    if args.phase is None or args.phase == 1:
        if args.token:
            enumerate_via_api(args.token, start_year, end_year, cp)
        else:
            log.warning(
                "No --token or LEGISTAR_TOKEN set — falling back to web scraping "
                "(capped at ~164 recent bills, will NOT reach 2014–2023 bills)"
            )
            enumerate_all_legislation(session, start_year, end_year, cp)

    # ── Phase 2: Process ──────────────────────────────────────────────────────
    if args.phase is None or args.phase == 2:
        processed_set = set(cp["processed_ids"])
        pending = [
            (mid, info["guid"], info.get("file_number", "?"))
            for mid, info in cp["matters"].items()
            if mid not in processed_set and mid not in existing_ids
        ]
        log.info(
            f"Phase 2: {len(pending)} matters to check "
            f"({len(processed_set)} already done, {len(existing_ids)} already in main file)"
        )

        total_new = 0

        for i, (matter_id, guid, file_num) in enumerate(pending, 1):

            # Progress log + checkpoint save every 100 items
            if i % 100 == 0:
                s = cp["stats"]
                log.info(
                    f"  Progress {i}/{len(pending)} | "
                    f"attachments: {s['with_attachment']} | "
                    f"records: {s['records_saved']} | "
                    f"Claude calls: {s['claude_calls']}"
                )
                save_checkpoint(cp)

            try:
                if args.token:
                    att_url = find_fiscal_attachment_api(matter_id, args.token)
                    has_attachment = att_url is not None
                else:
                    att_id, att_guid = find_fiscal_attachment(session, matter_id, guid)
                    has_attachment = att_id is not None
                time.sleep(0.3)

                if not has_attachment:
                    cp["processed_ids"].append(matter_id)
                    continue

                cp["stats"]["with_attachment"] = cp["stats"].get("with_attachment", 0) + 1
                log.info(f"  [{i}/{len(pending)}] {file_num} ({matter_id}) — fiscal attachment found")

                if args.dry_run:
                    cp["processed_ids"].append(matter_id)
                    continue

                if args.token:
                    docx_path = download_docx_url(session, att_url)
                else:
                    docx_path = download_docx(session, att_id, att_guid)
                time.sleep(0.3)

                if not docx_path:
                    cp["processed_ids"].append(matter_id)
                    continue

                text = extract_docx_text(docx_path)
                if not text.strip():
                    cp["processed_ids"].append(matter_id)
                    continue

                if text_is_zero_impact(text):
                    log.info(f"    Pre-check: all-zero — skipping Claude call")
                    cp["processed_ids"].append(matter_id)
                    continue

                log.info(f"    Calling Claude ...")
                fiscal = extract_fiscal_data(text, client)
                cp["stats"]["claude_calls"] = cp["stats"].get("claude_calls", 0) + 1

                if not record_has_fiscal_impact(fiscal):
                    log.info(f"    Post-check: zero/unestimable — skipping")
                    cp["processed_ids"].append(matter_id)
                    continue

                record = {
                    "matter_id":     matter_id,
                    "legistar_guid": guid,
                    "legistar_url":  (
                        f"https://legistar.council.nyc.gov/LegislationDetail.aspx"
                        f"?ID={matter_id}&GUID={guid}"
                    ),
                    "attachment_id": att_url if args.token else att_id,
                    "processed_at":  datetime.utcnow().isoformat() + "Z",
                    **fiscal,
                }
                cp["records"].append(record)
                cp["processed_ids"].append(matter_id)
                cp["stats"]["records_saved"] = len(cp["records"])
                total_new += 1

                fn    = fiscal.get("file_number", file_num)
                title = (fiscal.get("title") or "")[:60]
                log.info(f"    -> SAVED: {fn}: {title}")

            except requests.exceptions.Timeout:
                log.warning(f"  [{i}] Timeout on {matter_id} — will retry next run")
                # Don't mark as processed — it will be retried
            except Exception as e:
                log.error(f"  [{i}] Error on {matter_id}: {e}")
                cp["processed_ids"].append(matter_id)  # skip on error

            time.sleep(0.8)

        save_checkpoint(cp)
        log.info(f"\nPhase 2 complete. New records this run: {total_new}")
        log.info(f"Stats: {cp['stats']}")

        if not args.dry_run and cp["records"]:
            # Merge everything in checkpoint (deduplication handled in merge_into_main)
            added = merge_into_main(cp["records"])
            log.info(f"Merged {added} records into fiscal_impacts.json")
        elif args.dry_run:
            log.info("Dry run — no output written. Re-run without --dry-run to process.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
