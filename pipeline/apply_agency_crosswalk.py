#!/usr/bin/env python3
"""
One-off migration (Jul 2026): re-run agency normalization over every record in
fiscal_impacts.json so all agency names group through the NYC Open Data
t3jq-9nkf crosswalk (see agency_canon.py). Prints a per-agency diff summary.

Run from the repo root:
    python3 pipeline/apply_agency_crosswalk.py

Afterwards regenerate the agency chart data:
    python3 pipeline/regenerate_agency_data.py
"""
from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_fiscal_impacts import normalize_agency_attribution

DATA = (Path(__file__).resolve().parent.parent /
        "civic_reference" / "nyc_council_fiscal_impacts_tracker" / "data" /
        "fiscal_impacts.json")


def agency_counts(records: list[dict]) -> Counter:
    c: Counter = Counter()
    for r in records:
        for a in r.get("agencies_abbrev") or []:
            c[a] += 1
    return c


def main() -> None:
    doc = json.loads(DATA.read_text())
    records = doc["records"]
    before = agency_counts(records)

    changed_records = 0
    for i, rec in enumerate(records):
        prev = copy.deepcopy(rec)
        records[i] = normalize_agency_attribution(rec)
        if (prev.get("agencies_abbrev") != records[i].get("agencies_abbrev") or
                prev.get("program_breakdowns") != records[i].get("program_breakdowns")):
            changed_records += 1

    after = agency_counts(records)
    DATA.write_text(json.dumps(doc, indent=2, ensure_ascii=False))

    print(f"Records touched: {changed_records} of {len(records)}")
    print("\nAgency label changes (records per label):")
    labels = sorted(set(before) | set(after))
    for lb in labels:
        b, a = before.get(lb, 0), after.get(lb, 0)
        if b != a:
            print(f"  {lb:45} {b:3} -> {a:3}")


if __name__ == "__main__":
    main()
