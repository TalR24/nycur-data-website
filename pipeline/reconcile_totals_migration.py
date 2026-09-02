#!/usr/bin/env python3
"""
One-off (Sep 2 2026): apply reconcile_totals() from fetch_fiscal_impacts.py to
every record in fiscal_impacts.json. See that function's docstring for the two
extraction errors it corrects. Idempotent. Run from the repo root, then
`python3 pipeline/regenerate_agency_data.py`.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_fiscal_impacts import OUTPUT_PATH, reconcile_totals, save_output

data = json.loads(OUTPUT_PATH.read_text())
changed = []
for r in data["records"]:
    before = (r.get("total_revenue"), r.get("total_expenditure"))
    reconcile_totals(r)
    if (r.get("total_revenue"), r.get("total_expenditure")) != before:
        changed.append(f"{r.get('legistar_file') or r.get('file_number')}: {r['totals_reconciled']} {before} -> {(r['total_revenue'], r['total_expenditure'])}")
print("\n".join(changed) or "nothing to reconcile")
print(f"{len(changed)} records changed")
if "--dry-run" not in sys.argv:
    save_output(OUTPUT_PATH, data["records"])
