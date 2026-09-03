# Legislation trackers quality report — quality_report_2026-09-03

Hard failures: **2** — RUN A QUALITY LOOP

## Change vs quality_report_2026-09-02

- **fiscal_soft:breakdown_line_without_amount**: 18 → 22 (REGRESSION +4)
- **fiscal_soft:date_prepared_missing**: 16 → 22 (REGRESSION +6)
- **fiscal_soft:enacted_laws_never_checked**: 13 → 0 (improved -13)
- **fiscal_soft:file_number_missing**: 2 → 5 (REGRESSION +3)
- **fiscal_soft:net_differs_from_revenue_minus_costs**: 0 → 1 (REGRESSION +1)
- **fiscal_soft:no_agency_attributed**: 15 → 22 (REGRESSION +7)
- **hard:law_text_missing**: 7 → 0 (improved -7)
- **soft:law_text_at_or_over_cap**: 8 → 0 (improved -8)
- **soft:law_text_cache_absent**: 0 → 1 (REGRESSION +1)
- **soft:quote_not_in_law_text**: 114 → 0 (improved -114)

## validate_obligations.py
```
validating 8,223 obligations across 2,147 laws

HARD FAILURES: 2
      2  recurrence_is_a_template_placeholder
           6558020-07: every n years
           5534259-08: every n years

SOFT COUNTS (tracked, not failures):
     24  fewer_reports_than_doris_lists
      1  law_text_cache_absent
     24  legistar_says_sunset_but_none_parsed
    617  quotes_reprinted_text
     42  same_generic_actor_multiple_agencies

wrote /home/runner/work/nycur-data-website/nycur-data-website/civic_reference/legislation_implementation_tracker/quality_reports/quality_report_2026-09-03.validator.json
```

## validate_against_doris.py
```
DORIS required reports: 2289
traced to a 2014-2026 local law: 1546
laws present in both corpora: 661

COVERAGE GAPS (DORIS names a reporting law, we extracted nothing): 0

CLASSIFICATION DIFFERENCES (we extracted, but not as a report): 68
  our types on those laws: {'database or data publication': 83, 'plan or strategy': 42, 'rulemaking': 35, 'outreach or education': 24, 'notice or posting': 22, 'enforcement or inspection': 16}

COMPLIANCE, per DORIS, for reports created by in-scope laws:
  DORIS records no filing      589
  overdue                      360
  current                      352
  no schedule in DORIS         239
```

## validate_fiscal_impacts.py (fiscal tracker)
```
validating 359 fiscal records (2,000 matters on the skip list)

HARD FAILURES: 0

SOFT COUNTS (tracked, not failures):
      7  agency_not_canonical
     22  breakdown_line_without_amount
     22  date_prepared_missing
      5  file_number_missing
     30  legistar_file_missing
     30  legistar_url_missing
      1  net_differs_from_revenue_minus_costs
     22  no_agency_attributed

COVERAGE vs enacted local laws (laws.json), by enactment year:
  year   laws  in_table  skipped  unchecked | records dated
  2014     68         6       62          0 |      15
  2015    113        14       99          0 |      25
  2016    194        19      175          0 |      20
  2017    282        31      251          0 |      23
  2018    206        24      182          0 |      49
  2019    227        30      197          0 |      31
  2020    115        10      105          0 |       7
  2021    172        27      145          0 |      10
  2022    125        11      114          0 |      21
  2023    174        19      155          0 |      20
  2024    136        17      119          0 |      52
  2025    199        47      152          0 |      22
  2026    135        33      102          0 |      58

wrote /home/runner/work/nycur-data-website/nycur-data-website/civic_reference/legislation_implementation_tracker/quality_reports/quality_report_2026-09-03.fiscal.json
```
