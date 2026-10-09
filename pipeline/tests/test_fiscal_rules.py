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

Correction (Sep 28 2026 rework): an earlier version of this file claimed
matter 4806326's right program_end_fy was 23, not the code's 22. That was
wrong — 22 is right under the house rule (a July 1-2 end date closes the
prior fiscal year: 4806326's own test below asserts 22, alongside 7984588's
Nov 1 -> FY27, which uses the ordinary FY-containing-date rule instead since
Nov 1 isn't a July 1-2 boundary case).

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


# ── totals_basis: an all-$0/blank table category whose figure is narrative-only
# capital reads document_stated, not full_impact_column ────────────────────
# Source: blind audit 5 (Sep 28 2026 rework), matters 5755073 and 7731697:
# revenue/expenditure print $0 in every column, capital is blank except the
# model wrote the narrative's one-time capital figure into the Full cell.
# Pre-fix values (git HEAD at rework time; these two were never overridden).
_CAPITAL_NARRATIVE_CASES = [
    ("5755073", 2000000, [
        {"label": "Effective FY23", "revenue": 0, "expenditure": 0, "capital": None, "net": 0},
        {"label": "FY Succeeding Effective FY24", "revenue": 0, "expenditure": 0, "capital": None, "net": 0},
        {"label": "Full Fiscal Impact FY24", "revenue": 0, "expenditure": 0, "capital": 2000000, "net": -2000000},
    ]),
    ("7731697", 3500000, [
        {"label": "Effective FY26", "revenue": 0, "expenditure": 0, "capital": None, "net": 0},
        {"label": "FY Succeeding Effective FY27", "revenue": 0, "expenditure": 0, "capital": None, "net": 0},
        {"label": "Full Fiscal Impact FY27", "revenue": 0, "expenditure": 0, "capital": 3500000, "net": -3500000},
    ]),
]
for matter_id, expected_cap, cols in _CAPITAL_NARRATIVE_CASES:
    fiscal_cap = {
        "cost_estimable": True, "time_limited_program": False, "sunset_quote": "",
        "costs_already_in_financial_plan": False, "total_revenue": 0, "total_expenditure": 0,
        "total_capital": expected_cap, "see_below_categories": ["capital"], "fiscal_table_columns": cols,
    }
    out_cap = totals_from_columns(dict(fiscal_cap))
    check(
        f"totals_basis: all-$0/blank table, narrative-only capital -> document_stated (matter {matter_id}, blind audit 5)",
        out_cap["total_capital"] == expected_cap and out_cap["totals_basis"] == "document_stated",
        f"got capital={out_cap['total_capital']} basis={out_cap['totals_basis']}",
    )


# ── program_end_fy: a mid-fiscal-year effective date, whole-year duration ───
# Source: blind audit 5 (Sep 28 2026), matters 1681072 and 3521908 (tracker
# rule was wrong, not the record): the old "-1" formula assumed the program
# effectively starts July 1 of first_fy; enactment_date (LIT/data/laws.json)
# + the statement's own effective-date offset shows both start mid-year, so a
# 36-month duration lands a fiscal year later than the old formula gave.
check(
    "program_end_fy: 36 months from a Sep 2018 effective date -> FY22, not FY21 (matter 1681072, blind audit 5)",
    program_end_fy("This local law would remain in effect for 36 months, after which it is deemed repealed.", 19) == 22,
)
check(
    "program_end_fy: 36 months from an Oct 2020 effective date -> FY24, not FY23 (matter 3521908, blind audit 5)",
    program_end_fy("This local law would take effect eight months after it becomes law and would remain in "
                    "effect for 36 months, after which it would be deemed repealed.", 21) == 24,
)

# ── program_end_fy: an EXPLICIT start date + duration is not the mid-year
# case above — a program that starts exactly July 1 ends at the close of its
# Nth fiscal year (the old "-1"), because July 1 truly is the FY boundary.
# Source: matter 1709673 (Int 243-2014, Sep 28 2026 refiscal.py regression):
# the committed program_life_sum (288,702, end FY16) is right; the bare
# mid-year formula above would wrongly give FY17 and flip it to
# outlasts_statement/annual (144,351).
check(
    "program_end_fy: explicit July 1 start + duration ends at the close of the Nth FY (matter 1709673)",
    program_end_fy("The State law takes effect July 1, 2014 and will expire two years thereafter", 15) == 16,
)

# ── program_end_fy: a bare duration with no explicit date, checked against
# the statement's own 180-day effective offset ──────────────────────────────
# Source: matter 6695263 (Int 890-2024, Sep 28 2026 refiscal.py regression):
# enacted 2024-10-26, effective_date "180 days after becoming law" ->
# 2025-04-24 (well inside FY25, not July 1); +3 years = 2028-04-24 = FY28,
# not the old formula's FY27.
check(
    "program_end_fy: three-year pilot, no explicit start date -> FY28 not FY27 (matter 6695263)",
    program_end_fy("This bill would require the Commissioner of Health and Mental Hygiene to implement a "
                    "three-year pilot program to establish postpartum support groups focused on the mental "
                    "health of postpartum individuals.", 25) == 28,
)

# ── program_end_fy: the two house-rule date cases still hold ────────────────
check("program_end_fy: July 2 2022 closes the prior FY -> FY22 (matter 4806326)",
      program_end_fy("it is deemed repealed on July 2, 2022", 21) == 22)
check("program_end_fy: Nov 1 2026 -> FY27, ordinary FY-containing rule (matter 7984588)",
      program_end_fy("the local law shall expire and be repealed on November 1, 2026", 26) == 27)

# ── program_end_fy: the docstring's own worked example ───────────────────────
check("program_end_fy: ten years from FY19, no explicit date -> FY29 (docstring example, Int 755-2018)",
      program_end_fy("in effect for ten years", 19) == 29)

# ── apply_overrides: outlasts_statement true must pair with full_impact_column,
# never program_life_sum ─────────────────────────────────────────────────────
# Source: matter 3597643 (Int 1085-2018, Sep 28 2026 refiscal.py regression):
# a single-column narrative statement (totals_basis document_stated) whose
# override pins outlasts_statement=true; totals_from_columns runs BEFORE the
# override applies time_limited_program, so it never saw the pilot and left
# document_stated, which then contradicted the pinned outlasts_statement.
from fetch_fiscal_impacts import apply_overrides, OVERRIDES_PATH  # noqa: E402
if OVERRIDES_PATH.exists():
    import json as _json
    _ov = _json.loads(OVERRIDES_PATH.read_text())
    _entry = _ov.get("3597643")
    if _entry and not _entry.get("remove"):
        _rec = {
            "matter_id": "3597643", "attachment_id": _entry["attachment_id"],
            "totals_basis": "document_stated", "total_revenue": 0,
            "total_expenditure": 750240, "total_capital": None,
            "fiscal_table_columns": [{"label": "Total", "revenue": 0, "expenditure": 750240,
                                       "capital": None, "net": -750240}],
        }
        _out = apply_overrides([dict(_rec)])[0]
        check(
            "apply_overrides: outlasts_statement true forces totals_basis full_impact_column (matter 3597643)",
            _out.get("outlasts_statement") is True and _out.get("totals_basis") == "full_impact_column"
            and _out.get("total_expenditure") == 750240,
            f"got {_out}",
        )
    else:
        print("  SKIP  apply_overrides consistency test: fiscal_overrides.json has no active 3597643 entry")
else:
    print("  SKIP  apply_overrides consistency test: fiscal_overrides.json not found")

# ── recurring cost below a Full column that carries one-time costs ──────────
# Source: matter 5534240 (audit 10 corpus sweep, Sep 28 2026): "a one-time
# $250,000 technology upgrade" in the first year, 687,000 per year from FY24.
_r = totals_from_columns({
    "cost_estimable": True, "total_revenue": 0, "total_expenditure": 937000, "total_capital": None,
    "fiscal_table_columns": [
        {"label": "Effective FY23", "revenue": 0, "expenditure": 937000, "capital": None},
        {"label": "FY Succeeding Effective FY24", "revenue": 0, "expenditure": 687000, "capital": None},
        {"label": "Full Fiscal Impact FY23", "revenue": 0, "expenditure": 937000, "capital": None}],
    "recurring_annual_expenditure": 687000})
check("recurring_annual_expenditure replaces a first-year Full column (matter 5534240, audit 10 sweep)",
      _r["total_expenditure"] == 687000 and _r["net_fiscal_impact"] == -687000 and _r["totals_basis"] == "document_stated",
      f"got {_r.get('total_expenditure')} {_r.get('totals_basis')}")
_r = totals_from_columns({
    "cost_estimable": True, "total_revenue": 0, "total_expenditure": 500000, "total_capital": None,
    "fiscal_table_columns": [{"label": "Full Fiscal Impact FY27", "revenue": 0, "expenditure": 500000, "capital": None}],
    "recurring_annual_expenditure": None})
check("no recurring figure leaves the Full column in place", _r["total_expenditure"] == 500000, f"got {_r}")

# fiscal audit, Oct 6 2026
from fetch_fiscal_impacts import normalize_fiscal_years  # noqa: E402
_n = normalize_fiscal_years([{"fy_first_effective": "FY26", "fy_full_impact": "FY2028",
                              "fiscal_table_columns": [{"label": "Effective FY25"}]}])[0]
check("fiscal years read the Effective column and normalise to FYnn (Int 0991-2024)",
      _n["fy_first_effective"] == "FY25" and _n["fy_full_impact"] == "FY28", f"got {_n}")
_n = normalize_fiscal_years([{"fy_first_effective": "FY26",
                              "fiscal_table_columns": [{"label": "FY Succeeding Effective FY27"}]}])[0]
check("a 'FY Succeeding Effective' first column does not move fy_first_effective",
      _n["fy_first_effective"] == "FY26", f"got {_n}")

# bill status and summary of legislation, Oct 8 2026
from fetch_fiscal_impacts import status_group, status_bucket, extract_summary_of_legislation, parse_legistar_status  # noqa: E402
check("Enacted -> passed", status_group("Enacted") == "passed")
check("Enacted (Mayor's Desk variant) -> passed", status_group("Enacted (Mayor's Desk for Signature)") == "passed")
check("Adopted resolution -> passed", status_group("Adopted") == "passed")
check("Approved resolution -> passed", status_group("Approved") == "passed")
check("Laid Over in Committee -> in_progress", status_group("Laid Over in Committee") == "in_progress")
check("Approved by Committee stays in_progress", status_group("Approved by Committee") == "in_progress")
for _s in ("Filed (End of Session)", "filed (end of session)", "Withdrawn", "Vetoed", "Disapproved by Mayor",
           "Failed", "Defeated", "Filed"):
    check(f"{_s} -> lapsed", status_group(_s) == "lapsed")
check("None -> unknown", status_group(None) == "unknown")
check("empty -> unknown", status_group("  ") == "unknown")
check("laws.json membership overrides a stale status", status_group("Laid Over in Committee", True) == "passed")
check("laws.json membership overrides a missing status", status_group(None, True) == "passed")
check("bucket: Enacted -> enacted", status_bucket("Enacted", "passed") == "enacted")
check("bucket: Adopted -> enacted", status_bucket("Adopted", "passed") == "enacted")
check("bucket: Mayor's Desk -> awaiting_mayor", status_bucket("Enacted (Mayor's Desk for Signature)", "passed") == "awaiting_mayor")
check("bucket: mayor's desk is case-insensitive", status_bucket("ENACTED (MAYOR'S DESK)", "passed") == "awaiting_mayor")
check("bucket: in_progress", status_bucket("Laid Over in Committee", "in_progress") == "in_progress")
check("bucket: lapsed", status_bucket("Filed", "lapsed") == "lapsed")
check("bucket: unknown", status_bucket(None, "unknown") == "unknown")
check("bucket: a mayor's-desk status outside passed stays in its group", status_bucket("Enacted (Mayor's Desk)", "in_progress") == "in_progress")
check("status parsed off the detail page",
      parse_legistar_status('<span id="ctl00_ContentPlaceHolder1_lblStatus2" class="x">Laid Over in Committee</span>')
      == "Laid Over in Committee")
check("status absent on a stub page", parse_legistar_status("<html>Invalid parameters!</html>") is None)

_t = ("FISCAL IMPACT STATEMENT\nPROPONENT: X\nSummary of Legislation: This bill would require the Department "
      "of Parks   to inspect\nplaygrounds.\nIt would also set penalties.\nEffective Date: July 1, 2027\n"
      "Fiscal Year In Which Full Fiscal Impact Anticipated: FY27\n")
_got = extract_summary_of_legislation(_t)
check("summary stops at Effective Date, collapses spaces, joins a hard-wrapped line, breaks after a sentence",
      _got == "This bill would require the Department of Parks to inspect playgrounds.\n\nIt would also set penalties.",
      f"got {_got!r}")
_t2 = ("Summary of Legislation: The bill would set rules.\nProposed Intro. No. 1017-C Page 2\n"
       "It would also\nrequire a report.\n\n..Body\nEffective Date: immediately\n")
_got2 = extract_summary_of_legislation(_t2)
check("summary drops page headers and the Body artefact, keeps a blank-line break",
      _got2 == "The bill would set rules.\n\nIt would also require a report.", f"got {_got2!r}")
check("heading on its own line, body on the next",
      extract_summary_of_legislation("Summary of Legislation:\nThis bill would ban idling near schools.\nEffective Date: now")
      == "This bill would ban idling near schools.")
check("no heading -> None", extract_summary_of_legislation("Effective Date: July 1\nImpact on Revenues: none") is None)
check("Effective Date right after the heading -> None",
      extract_summary_of_legislation("Summary of Legislation:\nEffective Date: July 1, 2027\nmore text here that is long") is None)
check("stops at Impact on Revenues when it comes first",
      extract_summary_of_legislation("Summary of Legislation: This bill would fund twelve new inspectors.\n"
                                     "Impact on Revenues: none\nEffective Date: later") == "This bill would fund twelve new inspectors.")

# ── REST packet mode (historical script, Oct 2026) ──────────────────────────
from fetch_fiscal_impacts_historical import parse_attachment_log, status_fields  # noqa: E402

_log = ("12:41:02 INFO   [3/6588] Int 1025-2023 (6105123) \u2014 fiscal attachment found\n"
        "12:41:09 INFO   [4/6588] Res 1196-2025 (7213456) \u2014 fiscal attachment found\n"
        "12:41:10 INFO   [9/6588] T2024-0123 (6999999) \u2014 fiscal attachment found\n"
        "12:41:11 INFO     Calling Claude ...\n")
check("attachment log parser: ids and file numbers",
      parse_attachment_log(_log) == {"6105123": "Int 1025-2023", "7213456": "Res 1196-2025", "6999999": "T2024-0123"},
      str(parse_attachment_log(_log)))
_sf = status_fields("Filed (End of Session)")
check("Filed (End of Session) -> lapsed group and bucket",
      _sf["status_group"] == "lapsed" and _sf["status_bucket"] == "lapsed", str(_sf))
_sf = status_fields("Adopted")
check("Adopted -> enacted bucket", _sf["status_group"] == "passed" and _sf["status_bucket"] == "enacted", str(_sf))

print(f"\n{PASSED} passed, {FAILED} failed")
if FAILED:
    sys.exit(1)
