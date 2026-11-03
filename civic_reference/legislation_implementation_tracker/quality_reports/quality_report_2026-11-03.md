# Legislation trackers quality report, quality_report_2026-11-03

Hard failures: **0** (clean)

## Change vs quality_report_2026-09-03

- **fiscal_soft:agency_not_canonical**: 7 → 17 (REGRESSION +10)
- **fiscal_soft:breakdown_line_without_amount**: 22 → 14 (improved -8)
- **fiscal_soft:date_prepared_missing**: 22 → 20 (improved -2)
- **fiscal_soft:file_number_missing**: 5 → 10 (REGRESSION +5)
- **fiscal_soft:legistar_file_missing**: 30 → 17 (improved -13)
- **fiscal_soft:legistar_url_missing**: 30 → 17 (improved -13)
- **fiscal_soft:missing_status**: 0 → 17 (REGRESSION +17)
- **fiscal_soft:narrative_multi_year_total**: 0 → 1 (REGRESSION +1)
- **fiscal_soft:net_differs_from_revenue_minus_costs**: 1 → 0 (improved -1)
- **fiscal_soft:no_agency_attributed**: 22 → 47 (REGRESSION +25)
- **fiscal_soft:nonzero_totals_no_agencies**: 0 → 47 (REGRESSION +47)
- **fiscal_soft:status_in_progress**: 0 → 35 (REGRESSION +35)
- **fiscal_soft:time_limited_without_program_end_fy**: 0 → 2 (REGRESSION +2)
- **hard:recurrence_is_a_template_placeholder**: 2 → 0 (improved -2)
- **soft:code_title_agency_mismatch**: 0 → 3 (REGRESSION +3)
- **soft:discretion_typed_as_duty**: 0 → 37 (REGRESSION +37)
- **soft:duplicate_within_law**: 0 → 154 (REGRESSION +154)
- **soft:fewer_reports_than_doris_lists**: 24 → 28 (REGRESSION +4)
- **soft:fixed_date_without_date**: 0 → 56 (REGRESSION +56)
- **soft:kind_not_rederived_no_text**: 0 → 9425 (REGRESSION +9425)
- **soft:model_label_differs_from_rule**: 0 → 513 (REGRESSION +513)
- **soft:override_already_absent**: 0 → 485 (REGRESSION +485)
- **soft:override_ambiguous**: 0 → 28 (REGRESSION +28)
- **soft:quotes_reprinted_text**: 617 → 342 (improved -275)
- **soft:same_generic_actor_multiple_agencies**: 42 → 54 (REGRESSION +12)
- **soft:stale_override**: 0 → 16 (REGRESSION +16)

## validate_obligations.py
```
validating 8,290 obligations across 2,171 laws

HARD FAILURES: 0
      0  power_with_deadline

SOFT COUNTS (tracked, not failures):
      3  code_title_agency_mismatch
     37  discretion_typed_as_duty
    154  duplicate_within_law
     28  fewer_reports_than_doris_lists
     56  fixed_date_without_date
   9425  kind_not_rederived_no_text
      1  law_text_cache_absent
     24  legistar_says_sunset_but_none_parsed
    513  model_label_differs_from_rule
    485  override_already_absent
     28  override_ambiguous
    342  quotes_reprinted_text
     54  same_generic_actor_multiple_agencies
     16  stale_override

wrote /home/runner/work/nycur-data-website/nycur-data-website/civic_reference/legislation_implementation_tracker/quality_reports/quality_report_2026-11-03.validator.json
```

## validate_against_doris.py
```
DORIS required reports: 2307
traced to a 2014-2026 local law: 1563
laws present in both corpora: 670

COVERAGE GAPS (DORIS names a reporting law, we extracted nothing): 1
  Local Law 152 of 2023: Annual Report of the Office of Nightlife

CLASSIFICATION DIFFERENCES (we extracted, but not as a report): 69
  our types on those laws: {'database or data publication': 68, 'notice or posting': 38, 'other': 35, 'outreach or education': 27, 'plan or strategy': 21, 'rulemaking': 19}

COMPLIANCE, per DORIS, for reports created by in-scope laws:
  DORIS records no filing      578
  current                      393
  overdue                      340
  no schedule in DORIS         246
```

## validate_fiscal_impacts.py (fiscal tracker)
```
validating 481 fiscal records (3,610 matters on the skip list)

HARD FAILURES: 0

SOFT COUNTS (tracked, not failures):
     17  agency_not_canonical
     14  breakdown_line_without_amount
     20  date_prepared_missing
     10  file_number_missing
      0  full_impact_column_earlier_than_succeeding
      0  later_column_dwarfs_total
     17  legistar_file_missing
     17  legistar_url_missing
     17  missing_status
      1  narrative_multi_year_total
     47  no_agency_attributed
     47  nonzero_totals_no_agencies
     35  status_in_progress
      2  time_limited_without_program_end_fy

COVERAGE vs enacted local laws (laws.json), by enactment year:
  year   laws  in_table  skipped  unchecked | records dated
  2014     68        15       53          0 |      35
  2015    113        26       87          0 |      36
  2016    194        35      159          0 |      38
  2017    282        44      238          0 |      25
  2018    206        33      173          0 |      63
  2019    227        39      188          0 |      34
  2020    115        13      102          0 |      12
  2021    172        36      136          0 |      15
  2022    125        17      108          0 |      33
  2023    174        26      148          0 |      18
  2024    136        26      110          0 |      62
  2025    199        50      149          0 |      22
  2026    160        46      114          0 |      87

wrote /home/runner/work/nycur-data-website/nycur-data-website/civic_reference/legislation_implementation_tracker/quality_reports/quality_report_2026-11-03.fiscal.json
```
