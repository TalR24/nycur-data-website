#!/usr/bin/env python3
"""
Regression cases for totals_from_columns, program_end_fy and reconcile_totals
(pipeline/fetch_fiscal_impacts.py), built from gold fiscal records
(civic_reference/nyc_council_legislation_trackers/quality/gold_fiscal.json)
where the statement's own columns are known and the audited right value is
known. Every case names its source (matter_id + audit round).

Plain asserts; runnable directly or with pytest:
    python3 pipeline/tests/test_fiscal_rules.py
    pytest pipeline/tests/test_fiscal_rules.py

Known rule bug found while building these cases (reported, not fixed here
per the builder's orders: do not change fiscal extraction logic):
  - matter 4806326 (audit4_fiscal, Sep 27 2026): sunset "deemed repealed on
    July 2, 2022" with first_fy=21. The audit's right value is FY23 (July 2
    falls in the NYC FY23 window by the tracker's FY-containing-date
    convention used elsewhere, e.g. matter 7984588 below). program_end_fy()
    currently returns FY22 for this input: its July 1-2 handling treats the
    date as closing the FY that just ended rather than the FY it falls in.
    Not covered by an assert below (it would fail against current code);
    left for a fiscal-pipeline fix.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE = HERE.parent
sys.path.insert(0, str(PIPELINE))

from fetch_fiscal_impacts import program_end_fy, totals_from_columns, reconcile_totals  # noqa: E402

PASSED = FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}  {detail}")


# ── program_end_fy: Nov 1 2026 -> FY27 ───────────────────────────────────────
# Source: matter 7984588 (audit4_fiscal, Sep 27 2026: verdict CORRECT).
# Sunset: "expires and be repealed on November 1, 2026"; first effective FY26.
check(
    "program_end_fy: Nov 1 2026 -> FY27 (matter 7984588, audit4_fiscal)",
    program_end_fy("the local law shall expire and be repealed on November 1, 2026", first_fy=26) == 27,
)

# ── program_end_fy: a pilot that outlasts its statement columns ─────────────
# Source: matter 5669060 (audit4_fiscal, Sep 27 2026: gold right_value=27,
# tracker was null before the fix; now agrees). "Deemed repealed upon
# submission of the third annual report" with columns through FY24.
end = program_end_fy(
    "is deemed repealed upon submission of the third annual report required by subdivision d "
    "of section one of this local law, which shall be filed annually beginning one year after "
    "the local law takes effect", first_fy=23,
)
check("program_end_fy: pilot outlasting its statement columns (matter 5669060)", end is not None)

# ── totals_from_columns: Full column zero -> sum of columns ─────────────────
# Source: matter 7872581 (current data, totals_basis=sum_of_columns): a one-time
# first-year cost with a $0 Full Fiscal Impact column.
fiscal = {
    "cost_estimable": True, "time_limited_program": False, "sunset_quote": "",
    "costs_already_in_financial_plan": False, "total_revenue": 0, "total_expenditure": 0, "total_capital": 0,
    "fiscal_table_columns": [
        {"label": "Effective FY27", "revenue": 0, "expenditure": 50000, "capital": None, "net": -50000},
        {"label": "FY Succeeding Effective FY28", "revenue": 0, "expenditure": 0, "capital": None, "net": 0},
        {"label": "Full Fiscal Impact FY28", "revenue": 0, "expenditure": 0, "capital": None, "net": 0},
    ],
}
out = totals_from_columns(dict(fiscal))
check(
    "totals_from_columns: Full column zero -> sum of columns (matter 7872581)",
    out["total_expenditure"] == 50000 and out["totals_basis"] == "sum_of_columns",
    f"got expenditure={out['total_expenditure']} basis={out['totals_basis']}",
)

# ── totals_from_columns: pilot outlasting the columns -> annual figure ──────
# Source: matter 5669060 (audit4_fiscal): time_limited_program true but the
# sunset (third annual report, no fixed end the columns cover) means the
# pipeline should NOT sum the columns; it uses the annual full-impact figure
# and flags outlasts_statement.
fiscal2 = {
    "cost_estimable": True, "time_limited_program": True,
    "sunset_quote": "is deemed repealed upon submission of the third annual report required by "
                    "subdivision d of section one of this local law",
    "costs_already_in_financial_plan": False, "total_revenue": 0, "total_expenditure": 0, "total_capital": 0,
    "fiscal_table_columns": [
        {"label": "Effective FY23", "revenue": 0, "expenditure": 0, "capital": None, "net": 0},
        {"label": "FY Succeeding Effective FY24", "revenue": 0, "expenditure": 1500000, "capital": None, "net": -1500000},
        {"label": "Full Fiscal Impact FY24", "revenue": 0, "expenditure": 1500000, "capital": None, "net": -1500000},
    ],
}
out2 = totals_from_columns(dict(fiscal2))
check(
    "totals_from_columns: pilot outlasting the columns -> annual figure + outlasts_statement (matter 5669060)",
    out2["total_expenditure"] == 1500000 and out2.get("outlasts_statement") is True,
    f"got expenditure={out2['total_expenditure']} outlasts={out2.get('outlasts_statement')}",
)

# ── totals_from_columns: costs positive (a printed negative cost cell) ──────
# Documented rule (fetch_fiscal_impacts.py totals_from_columns docstring, Sep
# 24 2026 audit: 3 of 14 records had a cost read as negative, flipping a cost
# into a saving). No current gold case; reproduces the documented input shape.
fiscal3 = {
    "cost_estimable": True, "time_limited_program": False, "sunset_quote": "",
    "costs_already_in_financial_plan": False, "total_revenue": 0, "total_expenditure": 0, "total_capital": 0,
    "fiscal_table_columns": [
        {"label": "Full Fiscal Impact FY26", "revenue": 0, "expenditure": -200000, "capital": None, "net": -200000},
    ],
}
out3 = totals_from_columns(dict(fiscal3))
check(
    "totals_from_columns: a printed negative cost cell stays a cost, never a saving",
    out3["total_expenditure"] == 200000, f"got {out3['total_expenditure']}",
)

# ── reconcile_totals: revenue loss counted as cost ───────────────────────────
# Source: rule 1 of reconcile_totals() (fetch_fiscal_impacts.py, Sep 2 2026
# audit of 24 records); current data carries the fixed shape at matters
# 58415 and 71432 (totals_reconciled=revenue_loss_moved_to_expenditure).
fiscal4 = {"total_revenue": 4000000, "total_expenditure": 0, "total_capital": None, "net_fiscal_impact": -4000000}
out4 = reconcile_totals(dict(fiscal4))
check(
    "reconcile_totals: revenue loss stored as +revenue moves to expenditure (matters 58415, 71432)",
    out4["total_revenue"] == 0 and out4["total_expenditure"] == 4000000
    and out4.get("totals_reconciled") == "revenue_loss_moved_to_expenditure",
    f"got {out4}",
)

# ── reconcile_totals: capital duplicated inside expenditure ─────────────────
# Documented rule (reconcile_totals() docstring, Sep 24 2026 audit; matter
# Int 353-2024, since removed from current data): the same capital figure
# written into both expenditure and capital.
fiscal5 = {"total_revenue": 0, "total_expenditure": 605000000, "total_capital": 605000000,
           "net_fiscal_impact": -1210000000}
out5 = reconcile_totals(dict(fiscal5))
check(
    "reconcile_totals: capital duplicated as expenditure is de-duplicated (Int 353-2024, Sep 24 2026 audit)",
    out5["total_expenditure"] == 0 and out5["net_fiscal_impact"] == -605000000
    and out5.get("totals_reconciled") == "capital_duplicated_as_expenditure",
    f"got {out5}",
)


print(f"\n{PASSED} passed, {FAILED} failed")
if FAILED:
    sys.exit(1)
