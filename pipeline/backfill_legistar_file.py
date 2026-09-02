#!/usr/bin/env python3
"""
One-off backfill (Sep 2026): give every fiscal_impacts.json record Legistar's own
File # ("Int 1002-2026") and a working Legistar web link.

Why: `file_number` is whatever the fiscal impact statement printed, which is
inconsistent ("Intro. No. 831-A", "Int 1677-2017", "Preconsidered Int. No.")
and blank for bills numbered after the statement was drafted (the table then
showed the raw matter ID, e.g. "8150660"). Separately, the 184 records that
came from the historical REST scraper carry REST MatterIds (52198…72255) that
are NOT web IDs, so their "View on Legistar" links returned "Invalid
parameters!".

Sources, in order:
  1. Web-sourced records (numeric attachment_id): fetch the Legistar detail page
     and read the File # label. Their matter_id is already the web ID.
  2. REST-sourced records (attachment_id is a URL): crosswalk to the
     implementation tracker's laws.json (web matter_id + canonical file_number
     for every enacted local law 2014–2026) by intro number, Council session and
     title similarity. On a match the record's matter_id becomes the web ID
     (the old one is kept in `rest_matter_id`) so the incremental pipeline,
     which dedups on matter_id, will not re-extract the bill.
  3. Anything left (state bills, unnumbered preconsidered intros): search
     Legistar by title and accept a hit only if the detail page title matches.

New fields: legistar_file (str|None), rest_matter_id (str, REST records only).
Idempotent: records that already have legistar_file are skipped.

Usage:
    python3 pipeline/backfill_legistar_file.py [--dry-run]
"""
from __future__ import annotations

import argparse
import difflib
import json
import logging
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_fiscal_impacts import OUTPUT_PATH, BASE_URL, create_session, save_output, fetch_legistar_file  # noqa: E402

LAWS_PATH = (Path(__file__).resolve().parent.parent
             / "civic_reference/legislation_implementation_tracker/data/laws.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("backfill")


def council_session(year: int) -> int:
    """NYC Council sessions run 2014–17, 2018–21, 2022–25, 2026–29."""
    return (year - 2014) // 4


def title_sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower()[:160], (b or "").lower()[:160]).ratio()


def crosswalk_rest_record(rec: dict, laws_by_num: dict) -> dict | None:
    fn = rec.get("file_number") or ""
    m = re.search(r"(\d{2,4})", fn)
    if not m:
        return None
    n = int(m.group(1))
    year = None
    m2 = re.search(r"-(\d{4})$", fn)
    if m2:
        year = int(m2.group(1))
    elif rec.get("date_prepared"):
        year = int(rec["date_prepared"][:4])
    cands = laws_by_num.get(n, [])
    if year:
        same = [c for c in cands if council_session(int(c["file_number"][-4:])) == council_session(year)]
        cands = same or cands
    if not cands:
        return None
    best = max(cands, key=lambda c: title_sim(rec.get("title"), c.get("title")))
    if title_sim(rec.get("title"), best.get("title")) < 0.5:
        return None
    return best


def search_by_title(session: requests.Session, title: str) -> list[tuple[str, str]]:
    """
    Legistar basic search with the "legislative text" checkbox on; without it
    the box only matches file numbers and returns 0 records for any phrase.
    Returns [(web_id, guid)]. The text index, like the attachment index, only
    reaches back a few years, so pre-2020 bills mostly stay unresolved.
    """
    url = f"{BASE_URL}/Legislation.aspx"
    r = session.get(url, timeout=60)
    r.raise_for_status()
    vs = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', r.text)
    vsg = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]+)"', r.text)
    if not vs:
        return []
    # A distinctive chunk of the title: drop the boilerplate opening.
    snippet = re.sub(r"\s+", " ", title).strip()
    snippet = re.sub(r"^(A |An )?(local law|act)\b.*?(in relation to|to amend|relating to)\s*", "", snippet, flags=re.I)[:70]
    form = {
        "__VIEWSTATE": vs.group(1),
        "__VIEWSTATEGENERATOR": vsg.group(1) if vsg else "",
        "ctl00$ContentPlaceHolder1$txtSearch": snippet,
        "ctl00$ContentPlaceHolder1$lstYears": "All Years",
        "ctl00$ContentPlaceHolder1$lstTypeBasic": "All Types",
        "ctl00$ContentPlaceHolder1$chkText": "on",
        "ctl00$ContentPlaceHolder1$btnSearch": "Search Legislation",
    }
    r = session.post(url, data=form, timeout=90)
    r.raise_for_status()
    return list(dict.fromkeys(re.findall(r"LegislationDetail\.aspx\?ID=(\d+)&(?:amp;)?GUID=([A-F0-9\-]+)", r.text)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = json.load(open(OUTPUT_PATH))
    records = data["records"]
    laws = json.load(open(LAWS_PATH))["laws"]
    laws_by_num: dict[int, list[dict]] = {}
    for l in laws:
        m = re.match(r"Int\s+0*(\d+)-(\d{4})", l.get("file_number") or "")
        if m:
            laws_by_num.setdefault(int(m.group(1)), []).append(l)

    session = create_session()
    stats = {"web": 0, "crosswalk": 0, "title_search": 0, "unresolved": 0, "skipped": 0}
    unresolved = []

    for rec in records:
        if rec.get("legistar_file"):
            stats["skipped"] += 1
            continue
        is_rest = str(rec.get("attachment_id", "")).startswith("http")

        if not is_rest:
            lf, _ = fetch_legistar_file(session, rec["matter_id"], rec["legistar_guid"])
            time.sleep(0.4)
            rec["legistar_file"] = lf
            if lf:
                stats["web"] += 1
                log.info(f"web       {rec['matter_id']}  {rec.get('file_number')!r:34} -> {lf}")
                continue

        law = crosswalk_rest_record(rec, laws_by_num) if is_rest else None
        if law:
            rec["rest_matter_id"] = rec["matter_id"]
            rec["matter_id"] = law["matter_id"]
            rec["legistar_guid"] = law["legistar_guid"]
            rec["legistar_url"] = f"{BASE_URL}/LegislationDetail.aspx?ID={law['matter_id']}&GUID={law['legistar_guid']}"
            rec["legistar_file"] = law["file_number"]
            stats["crosswalk"] += 1
            log.info(f"crosswalk {rec['rest_matter_id']:>8}  {rec.get('file_number')!r:34} -> {law['file_number']} ({law['matter_id']})")
            continue

        # Title search fallback (state bills, unnumbered preconsidered intros).
        title = rec.get("title") or ""
        hit = None
        if len(title) > 25:
            try:
                for web_id, guid in search_by_title(session, title)[:5]:
                    lf, page_title = fetch_legistar_file(session, web_id, guid)
                    time.sleep(0.4)
                    # Bills are re-introduced across sessions under identical
                    # titles, so a title match must also sit in the record's
                    # own Council session (a 2016 statement matched a 2026
                    # bill before this guard).
                    m_year = re.search(r"-(\d{4})$", lf or "")
                    rec_year = int((rec.get("date_prepared") or "0")[:4] or 0)
                    same_session = (not rec_year) or (m_year and council_session(int(m_year.group(1))) == council_session(rec_year))
                    if lf and same_session and title_sim(title, page_title) >= 0.8:
                        hit = (web_id, guid, lf)
                        break
            except Exception as e:  # noqa: BLE001
                log.warning(f"title search failed for {rec['matter_id']}: {e}")
            time.sleep(1)
        if hit:
            web_id, guid, lf = hit
            if is_rest:
                rec["rest_matter_id"] = rec["matter_id"]
                rec["matter_id"] = web_id
                rec["legistar_guid"] = guid
                rec["legistar_url"] = f"{BASE_URL}/LegislationDetail.aspx?ID={web_id}&GUID={guid}"
            rec["legistar_file"] = lf
            stats["title_search"] += 1
            log.info(f"title     {rec.get('rest_matter_id', rec['matter_id']):>8}  {rec.get('file_number')!r:34} -> {lf} ({web_id})")
        else:
            rec["legistar_file"] = None
            if is_rest:
                # The stored URL was built from a REST MatterId and returns
                # "Invalid parameters!"; better no link than a dead one.
                rec["rest_matter_id"] = rec.get("rest_matter_id") or rec["matter_id"]
                rec["legistar_url"] = None
            stats["unresolved"] += 1
            unresolved.append((rec["matter_id"], rec.get("file_number"), title[:70]))
            log.info(f"UNRESOLVED {rec['matter_id']:>8}  {rec.get('file_number')!r:34}  {title[:60]}")

    log.info(f"stats: {stats}")
    for u in unresolved:
        log.info(f"  unresolved: {u}")
    if args.dry_run:
        log.info("--dry-run: not writing")
        return 0
    save_output(OUTPUT_PATH, records)
    log.info(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
