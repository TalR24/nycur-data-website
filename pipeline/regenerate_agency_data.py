"""Regenerate agency-fiscal-impact/data.json from fiscal_impacts.json.

Enriches each record with intro_year and fy_first_normalized, and rebuilds
the filter_options lists the agency chart page needs. Run after any pipeline
run that adds records (the refresh workflow does this automatically).
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
TRACKER = REPO_ROOT / "civic_reference" / "nyc_council_fiscal_impacts_tracker"
INPUT_PATH = TRACKER / "data" / "fiscal_impacts.json"
OUTPUT_PATH = TRACKER / "agency-fiscal-impact" / "data.json"


def get_intro_year(rec):
    # 1. date_prepared year (most reliable — FIS prep date closely tracks bill introduction)
    dp = rec.get("date_prepared") or ""
    m = re.search(r'\b(20\d{2})\b', str(dp))
    if m:
        yr = int(m.group(1))
        if 2010 <= yr <= 2030:
            return yr
    # 2. T-type prefix in file_number: "Int. No. T2026-0123" → 2026
    fn = str(rec.get("file_number") or "")
    m2 = re.search(r'\bT(20\d{2})\b', fn)
    if m2:
        yr = int(m2.group(1))
        if 2010 <= yr <= 2030:
            return yr
    # 3. Hyphenated year suffix: "Int 0360-2014" → 2014 (validated)
    m3 = re.search(r'-(20\d{2})$', fn)
    if m3:
        yr = int(m3.group(1))
        if 2010 <= yr <= 2030:
            return yr
    # 4. Fall back to processed_at year
    pa = rec.get("processed_at") or ""
    return int(pa[:4]) if pa else None


def normalize_fy(fy):
    if not fy:
        return None
    m = re.search(r'(\d{2,4})', str(fy))
    if not m:
        return None
    yr = m.group(1)
    if len(yr) == 4:
        yr = yr[2:]
    return f"FY{yr}"


def main():
    with open(INPUT_PATH) as f:
        data = json.load(f)
    records = data["records"]

    enriched = []
    for rec in records:
        r = dict(rec)
        r["intro_year"] = get_intro_year(rec)
        r["fy_first_normalized"] = normalize_fy(rec.get("fy_first_effective"))
        enriched.append(r)

    committees   = sorted(set(r["committee"] for r in enriched if r.get("committee")))
    sponsors     = sorted(set(r["prime_sponsor"] for r in enriched if r.get("prime_sponsor")))
    intro_years  = sorted(set(r["intro_year"] for r in enriched if r.get("intro_year")))
    fiscal_years = sorted(set(r["fy_first_normalized"] for r in enriched if r.get("fy_first_normalized")))

    output = {
        "records": enriched,
        "filter_options": {
            "committees": committees,
            "sponsors": sponsors,
            "intro_years": intro_years,
            "fiscal_years": fiscal_years,
        },
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Written {len(enriched)} records")


if __name__ == "__main__":
    main()
