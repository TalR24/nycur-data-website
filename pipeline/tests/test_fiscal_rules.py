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

Rule gap found, not implemented (Sep 27 2026 adjudication REJECTED matter
8034432; the task orders this reported, not fixed): a one-time cost split
across two fiscal years by the statement itself ("$50,000 ... one-year
feasibility study", no sunset sentence) prints two nonzero year columns
(29,726 then 20,274) with the Full column equal to the second, smaller one.
totals_from_columns() has no time_limited_program (no sunset sentence, so the
program_life_sum path never runs) and picks the Full column (20,274), losing
the first year's 29,726. Proposed rule: when the statement's own narrative
states a single total one-time cost (here $50,000) and the columns split it
across exactly the years the narrative names, sum those columns instead of
taking the Full column alone — a "one_time_cost_split" totals_basis, keyed off
a narrative-stated one-time total the way expenditure_is_savings and
see_below_categories are keyed off their own flags. Needs a new schema
signal (e.g. a nullable narrative_stated_one_time_total) since the columns
alone don't say "these two years are one split cost, not a Full-column read."
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


# ── totals_basis: a "See below" table that still got the narrative figure
# written into the Full column reads document_stated, not full_impact_column
# ─────────────────────────────────────────────────────────────────────────────
# Source: Sep 27 2026 fiscal verification + adjudication (fiscal_adjudication.json),
# matters 5534276, 6702327, 5839389, 2939936 (all CONFIRMED). Columns are the
# pre-override values (git show HEAD~1 at rework time); see_below_categories is
# the new field this rework adds to FISCAL_SCHEMA, set as a fresh extraction
# of these statements would set it (the field did not exist when these were
# first extracted).
_SEE_BELOW_CASES = [
    ("5534276", 100000, [
        {"label": "Effective FY23", "revenue": 0, "expenditure": None, "capital": None, "net": 0},
        {"label": "FY Succeeding Effective FY24", "revenue": 0, "expenditure": None, "capital": None, "net": 0},
        {"label": "Full Fiscal Impact FY28", "revenue": 0, "expenditure": 100000, "capital": None, "net": -100000},
    ]),
    ("6702327", 170000, [
        {"label": "Effective FY27", "revenue": 0, "expenditure": 170000, "capital": None, "net": -170000},
        {"label": "FY Succeeding Effective FY28", "revenue": 0, "expenditure": 170000, "capital": None, "net": -170000},
        {"label": "Full Fiscal Impact FY28", "revenue": 0, "expenditure": 170000, "capital": None, "net": -170000},
    ]),
    ("5839389", 200000, [
        {"label": "Effective FY24", "revenue": 0, "expenditure": 200000, "capital": None, "net": -200000},
        {"label": "FY Succeeding Effective FY25", "revenue": 0, "expenditure": 200000, "capital": None, "net": -200000},
        {"label": "Full Fiscal Impact FY25", "revenue": 0, "expenditure": 200000, "capital": None, "net": -200000},
    ]),
    ("2939936", 4500000, [
        {"label": "Effective FY18", "revenue": None, "expenditure": None, "capital": None, "net": None},
        {"label": "FY Succeeding Effective FY19", "revenue": None, "expenditure": None, "capital": None, "net": None},
        {"label": "Full Fiscal Impact FY19", "revenue": None, "expenditure": 4500000, "capital": None, "net": -4500000},
    ]),
]
for matter_id, expected_exp, cols in _SEE_BELOW_CASES:
    fiscal_sb = {
        "cost_estimable": True, "time_limited_program": False, "sunset_quote": "",
        "costs_already_in_financial_plan": False, "total_revenue": 0,
        "total_expenditure": expected_exp, "total_capital": 0,
        "see_below_categories": ["expenditure"], "fiscal_table_columns": cols,
    }
    out_sb = totals_from_columns(dict(fiscal_sb))
    check(
        f"totals_basis: See-below table -> document_stated, not full_impact_column (matter {matter_id}, "
        f"Sep 27 2026 adjudication)",
        out_sb["total_expenditure"] == expected_exp and out_sb["totals_basis"] == "document_stated",
        f"got expenditure={out_sb['total_expenditure']} basis={out_sb['totals_basis']}",
    )

# ── costs_already_in_financial_plan: an already-budgeted revenue loss is not
# added to expenditure ───────────────────────────────────────────────────────
# Source: matter 5745591 (Sep 27 2026 adjudication, CONFIRMED): tracker had
# 34,250,000 (the $33.75M already-in-plan revenue reduction moved into
# expenditure on top of the real $500,000 cost); right expenditure is 500,000.
fiscal_plan = {
    "cost_estimable": True, "time_limited_program": False, "sunset_quote": "",
    "costs_already_in_financial_plan": True, "total_revenue": 0, "total_expenditure": 0, "total_capital": 0,
    "fiscal_table_columns": [
        {"label": "Effective FY22", "revenue": -56250000, "expenditure": 0, "capital": None, "net": -56250000},
        {"label": "FY Succeeding Effective FY23", "revenue": -33750000, "expenditure": 500000, "capital": None, "net": -34250000},
        {"label": "Full Fiscal Impact FY23", "revenue": -33750000, "expenditure": 500000, "capital": None, "net": -34250000},
    ],
}
out_plan = totals_from_columns(dict(fiscal_plan))
check(
    "costs_already_in_financial_plan: an already-budgeted revenue loss stays out of expenditure (matter 5745591, Sep 27 2026 adjudication)",
    out_plan["total_expenditure"] == 500000 and out_plan["total_revenue"] == 0
    and out_plan["net_fiscal_impact"] == -500000,
    f"got {out_plan}",
)

# ── expenditure_is_savings: a savings row is a negative expenditure ─────────
# Source: matter 2103602 (Sep 27 2026 adjudication, CONFIRMED): right
# expenditure -790,400 ("annual expenditure savings of approximately
# $790,000 ... reach $790,400 by Fiscal 2021"), net +790,400.
fiscal_savings = {
    "cost_estimable": True, "time_limited_program": False, "sunset_quote": "",
    "costs_already_in_financial_plan": False, "expenditure_is_savings": True,
    "total_revenue": 0, "total_expenditure": 0, "total_capital": 0,
    "fiscal_table_columns": [
        {"label": "Effective FY15", "revenue": 0, "expenditure": 0, "capital": None, "net": 0},
        {"label": "FY Succeeding Effective FY16", "revenue": 0, "expenditure": 182000, "capital": None, "net": -182000},
        {"label": "Full Fiscal Impact FY21", "revenue": 0, "expenditure": 790400, "capital": None, "net": -790400},
    ],
}
out_savings = totals_from_columns(dict(fiscal_savings))
check(
    "expenditure_is_savings: a savings row is a negative expenditure (matter 2103602, Sep 27 2026 adjudication)",
    out_savings["total_expenditure"] == -790400 and out_savings["net_fiscal_impact"] == 790400,
    f"got {out_savings}",
)


print(f"\n{PASSED} passed, {FAILED} failed")
if FAILED:
    sys.exit(1)
