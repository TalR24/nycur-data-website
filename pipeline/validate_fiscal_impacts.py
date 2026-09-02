#!/usr/bin/env python3
"""
Regression suite for the NYC Council Fiscal Impacts Tracker data
(civic_reference/nyc_council_fiscal_impacts_tracker/data/fiscal_impacts.json).

Sibling of the implementation tracker's validate_obligations.py, written Sep 2
2026 after two defects sat in the live table for months because every earlier
check verified that the pipeline RAN, never that its output was right:
  - 184 historical records linked to Legistar with REST MatterIds, which the
    website rejects as "Invalid parameters!";
  - the Bill # column showed whatever the fiscal statement printed (or the raw
    matter ID when it printed nothing), and there was not a single bill dated
    2024 because Legistar's attachment search caps at ~317 matters.

HARD failures are objectively wrong records (the pipeline's own filters or
invariants violated). SOFT counts are tracked month over month; a rising count
is the signal to look. The COVERAGE section compares the table against an
independent universe: the implementation tracker's list of enacted local laws.

Offline by default. `--links` re-fetches Legistar pages (source-grounded
check of the fields that sit above the document text: link validity, File #,
title). Usage:

    python3 pipeline/validate_fiscal_impacts.py                 # offline
    python3 pipeline/validate_fiscal_impacts.py --links 40      # + 40 random pages
    python3 pipeline/validate_fiscal_impacts.py --links all --json out.json --strict
"""
from __future__ import annotations

import argparse
import difflib
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TRACKER = REPO / "civic_reference" / "nyc_council_fiscal_impacts_tracker"
DATA = TRACKER / "data" / "fiscal_impacts.json"
AGENCY_DATA = TRACKER / "agency-fiscal-impact" / "data.json"
SKIP = HERE / "no_impact_matters.json"
LAWS = REPO / "civic_reference" / "legislation_implementation_tracker" / "data" / "laws.json"

sys.path.insert(0, str(HERE))
from agency_canon import canonicalize  # noqa: E402

FIRST_YEAR = 2014


def label(r: dict) -> str:
    return f"{r.get('legistar_file') or r.get('file_number') or '?'} [{r.get('matter_id')}]"


def year_of(r: dict) -> int | None:
    m = re.search(r"-(20\d{2})$", r.get("legistar_file") or "")
    if m:
        return int(m.group(1))
    if r.get("date_prepared"):
        return int(str(r["date_prepared"])[:4])
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write the full result here")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any hard failure")
    ap.add_argument("--links", metavar="N|all", help="re-fetch N random (or all) Legistar pages")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--seed", type=int, default=None, help="random seed for --links sampling")
    args = ap.parse_args()

    records = json.loads(DATA.read_text())["records"]
    skips = json.loads(SKIP.read_text()) if SKIP.exists() else {}
    laws = json.loads(LAWS.read_text())["laws"] if LAWS.exists() else []
    hard: dict[str, list[str]] = defaultdict(list)
    soft: dict[str, list[str]] = defaultdict(list)

    # --- HARD: identity ------------------------------------------------------
    seen: Counter = Counter(str(r.get("matter_id")) for r in records)
    for mid, n in seen.items():
        if n > 1:
            hard["duplicate_matter_id"].append(f"{mid} x{n}")
    for r in records:
        url = r.get("legistar_url") or ""
        m = re.search(r"[?&]ID=(\d+)", url)
        if url and (not m or m.group(1) != str(r.get("matter_id"))):
            hard["legistar_url_id_differs_from_matter_id"].append(label(r))
        # REST MatterIds are 5-digit; every web ID Legistar has issued for NYC
        # is 7 digits. A 5-digit ID in a web URL is the exact Aug 2026 defect.
        if m and len(m.group(1)) < 7:
            hard["legistar_url_uses_rest_id"].append(label(r))

    # --- HARD: the pipeline's own filters -----------------------------------
    for r in records:
        rev, exp, cap, net = (r.get(k) for k in ("total_revenue", "total_expenditure", "total_capital", "net_fiscal_impact"))
        if all(not v for v in (rev, exp, cap, net)) and not r.get("package_note"):
            # package_note: Finance costed several intros as one package and the
            # full cost sits on one of them; the others are deliberately null.
            hard["all_totals_zero"].append(label(r))
        if r.get("cost_estimable") is False:
            hard["cost_not_estimable_included"].append(label(r))
        if re.search(r"\bMN-\d+", (r.get("title") or "") + " " + (r.get("file_number") or "")):
            hard["budget_modification_included"].append(label(r))
        if (r.get("file_number") or "").lower().startswith("proposed"):
            hard["proposed_bill_included"].append(label(r))
        if None not in (rev, exp, net):
            expected = (rev or 0) - (exp or 0) - (cap or 0)
            if abs(expected - net) > 1:
                soft["net_differs_from_revenue_minus_costs"].append(
                    f"{label(r)}: net {net:,.0f} vs {expected:,.0f}")

    # --- SOFT: fields the page depends on -----------------------------------
    for r in records:
        if not r.get("legistar_file"):
            soft["legistar_file_missing"].append(label(r))
        if not r.get("legistar_url"):
            soft["legistar_url_missing"].append(label(r))
        if not r.get("file_number"):
            soft["file_number_missing"].append(label(r))
        if not r.get("date_prepared"):
            soft["date_prepared_missing"].append(label(r))
        if not r.get("prime_sponsor"):
            soft["prime_sponsor_missing"].append(label(r))
        if not r.get("agencies_abbrev"):
            soft["no_agency_attributed"].append(label(r))
        for a in r.get("agencies_abbrev") or []:
            canon, _ = canonicalize(a)
            if canon != a:
                soft["agency_not_canonical"].append(f"{label(r)}: {a!r} -> {canon!r}")
        for pb in r.get("program_breakdowns") or []:
            if pb.get("amount") in (None, 0) and pb.get("cost_type"):
                soft["breakdown_line_without_amount"].append(f"{label(r)}: {pb.get('program')}")

    # --- SOFT: derived chart data in sync -----------------------------------
    if AGENCY_DATA.exists():
        n_chart = len(json.loads(AGENCY_DATA.read_text()).get("records", []))
        if n_chart != len(records):
            soft["agency_chart_data_out_of_sync"].append(
                f"agency-fiscal-impact/data.json has {n_chart} records, table has {len(records)}")
    else:
        soft["agency_chart_data_out_of_sync"].append("agency-fiscal-impact/data.json missing")

    # --- COVERAGE vs the enacted-law universe --------------------------------
    # Every enacted local law should be either in the table or in the skip
    # list (checked, no storable impact). Anything else was never looked at.
    in_table = {str(r.get("matter_id")) for r in records}
    in_skip = set(skips)
    coverage: dict[str, dict] = {}
    this_year = int(args.today[:4])
    for yr in range(FIRST_YEAR, this_year + 1):
        coverage[str(yr)] = {"laws": 0, "in_table": 0, "skipped": 0, "unchecked": 0, "records": 0}
    for law in laws:
        yr = str(law.get("enactment_date") or "")[:4]
        if yr not in coverage:
            continue
        c = coverage[yr]
        c["laws"] += 1
        mid = str(law.get("matter_id"))
        if mid in in_table:
            c["in_table"] += 1
        elif mid in in_skip:
            c["skipped"] += 1
        else:
            c["unchecked"] += 1
    for r in records:
        y = year_of(r)
        if y and str(y) in coverage:
            coverage[str(y)]["records"] += 1
    unchecked_total = sum(c["unchecked"] for c in coverage.values())
    if unchecked_total:
        soft["enacted_laws_never_checked"].extend(
            f"{yr}: {c['unchecked']} of {c['laws']}" for yr, c in coverage.items() if c["unchecked"])
    for yr, c in coverage.items():
        if int(yr) < this_year and c["records"] == 0:
            soft["year_with_zero_records"].append(yr)
    if not laws:
        soft["laws_json_unavailable"].append(str(LAWS))

    # --- LINKS: source-grounded re-check of the above-the-text fields --------
    link_stats = None
    if args.links:
        import requests
        pool = [r for r in records if r.get("legistar_url")]
        if args.links != "all":
            random.seed(args.seed)
            pool = random.sample(pool, min(int(args.links), len(pool)))
        s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0"
        link_stats = {"checked": 0, "dead": 0, "file_mismatch": 0, "title_mismatch": 0, "fetch_error": 0}
        for r in pool:
            link_stats["checked"] += 1
            try:
                html = s.get(r["legistar_url"], timeout=60).text
            except Exception as e:  # noqa: BLE001
                link_stats["fetch_error"] += 1
                soft["legistar_fetch_error"].append(f"{label(r)}: {e}")
                continue
            if "Invalid parameters" in html:
                link_stats["dead"] += 1
                hard["legistar_link_dead"].append(label(r))
                continue

            def lbl(name: str) -> str:
                m = re.search(rf'id="ctl00_ContentPlaceHolder1_{name}"[^>]*>(.*?)</span>', html, re.S)
                return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""

            page_file, page_title = lbl("lblFile2"), lbl("lblTitle2")
            if r.get("legistar_file") and page_file and page_file != r["legistar_file"]:
                link_stats["file_mismatch"] += 1
                hard["legistar_file_differs_from_page"].append(f"{label(r)}: page says {page_file}")
            sim = difflib.SequenceMatcher(None, (r.get("title") or "").lower()[:160], page_title.lower()[:160]).ratio()
            if page_title and sim < 0.5:
                link_stats["title_mismatch"] += 1
                soft["title_differs_from_page"].append(f"{label(r)}: {sim:.2f}")
            time.sleep(0.4)

    # --- report -------------------------------------------------------------
    result = {
        "generated": args.today,
        "records": len(records),
        "skip_list": len(skips),
        "hard_failures": {k: v for k, v in sorted(hard.items())},
        "soft_counts": {k: len(v) for k, v in sorted(soft.items())},
        "soft_detail": {k: v[:50] for k, v in sorted(soft.items())},
        "coverage_by_enactment_year": coverage,
        "links": link_stats,
    }
    n_hard = sum(len(v) for v in hard.values())

    print(f"validating {len(records):,} fiscal records ({len(skips):,} matters on the skip list)\n")
    print(f"HARD FAILURES: {n_hard}")
    for k, v in sorted(hard.items()):
        print(f"  {len(v):5d}  {k}")
        for line in v[:6]:
            print(f"           {line}")
        if len(v) > 6:
            print(f"           ... and {len(v) - 6} more")
    print("\nSOFT COUNTS (tracked, not failures):")
    for k, v in sorted(soft.items()):
        print(f"  {len(v):5d}  {k}")
    print("\nCOVERAGE vs enacted local laws (laws.json), by enactment year:")
    print("  year   laws  in_table  skipped  unchecked | records dated")
    for yr, c in coverage.items():
        print(f"  {yr}  {c['laws']:5d}  {c['in_table']:8d}  {c['skipped']:7d}  {c['unchecked']:9d} | {c['records']:7d}")
    if link_stats:
        print(f"\nLINKS: {link_stats}")

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(f"\nwrote {args.json}")
    if args.strict and n_hard:
        sys.exit(1)


if __name__ == "__main__":
    main()
