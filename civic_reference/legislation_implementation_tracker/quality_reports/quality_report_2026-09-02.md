# Legislation trackers quality report — quality_report_2026-09-02

Hard failures: **9** — RUN A QUALITY LOOP

## Change vs quality_report_2026-08-20

- **fiscal_soft:agency_not_canonical**: 0 → 7 (REGRESSION +7)
- **fiscal_soft:breakdown_line_without_amount**: 0 → 18 (REGRESSION +18)
- **fiscal_soft:date_prepared_missing**: 0 → 16 (REGRESSION +16)
- **fiscal_soft:enacted_laws_never_checked**: 0 → 13 (REGRESSION +13)
- **fiscal_soft:file_number_missing**: 0 → 2 (REGRESSION +2)
- **fiscal_soft:legistar_file_missing**: 0 → 30 (REGRESSION +30)
- **fiscal_soft:legistar_url_missing**: 0 → 30 (REGRESSION +30)
- **fiscal_soft:no_agency_attributed**: 0 → 15 (REGRESSION +15)
- **hard:law_text_missing**: 0 → 7 (REGRESSION +7)
- **hard:recurrence_is_a_template_placeholder**: 0 → 2 (REGRESSION +2)
- **soft:fewer_reports_than_doris_lists**: 0 → 24 (REGRESSION +24)
- **soft:law_text_at_or_over_cap**: 0 → 8 (REGRESSION +8)
- **soft:legistar_says_sunset_but_none_parsed**: 0 → 24 (REGRESSION +24)
- **soft:quote_not_in_law_text**: 0 → 114 (REGRESSION +114)
- **soft:quotes_reprinted_text**: 0 → 617 (REGRESSION +617)
- **soft:same_generic_actor_multiple_agencies**: 0 → 42 (REGRESSION +42)

## validate_obligations.py
```
validating 8,223 obligations across 2,147 laws

HARD FAILURES: 9
      7  law_text_missing
           Local Law 135 of 2026: 13 obligations, no cached text
           Local Law 134 of 2026: 3 obligations, no cached text
           Local Law 132 of 2026: 2 obligations, no cached text
           Local Law 130 of 2026: 5 obligations, no cached text
           Local Law 129 of 2026: 3 obligations, no cached text
           Local Law 128 of 2026: 4 obligations, no cached text
           ... and 1 more
      2  recurrence_is_a_template_placeholder
           6558020-07: every n years
           5534259-08: every n years

SOFT COUNTS (tracked, not failures):
     24  fewer_reports_than_doris_lists
      8  law_text_at_or_over_cap
     24  legistar_says_sunset_but_none_parsed
    114  quote_not_in_law_text
    617  quotes_reprinted_text
     42  same_generic_actor_multiple_agencies

wrote /Users/troded/nycur/data_website/civic_reference/legislation_implementation_tracker/quality_reports/quality_report_2026-09-02.validator.json
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
  current                      356
  overdue                      356
  no schedule in DORIS         239
/Users/troded/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
```

## validate_fiscal_impacts.py (fiscal tracker)
```
validating 257 fiscal records (0 matters on the skip list)

HARD FAILURES: 0

SOFT COUNTS (tracked, not failures):
      7  agency_not_canonical
     18  breakdown_line_without_amount
     16  date_prepared_missing
     13  enacted_laws_never_checked
      2  file_number_missing
     30  legistar_file_missing
     30  legistar_url_missing
     15  no_agency_attributed

COVERAGE vs enacted local laws (laws.json), by enactment year:
  year   laws  in_table  skipped  unchecked | records dated
  2014     68         4        0         64 |      11
  2015    113        10        0        103 |      20
  2016    194        15        0        179 |      16
  2017    282        23        0        259 |      18
  2018    206        22        0        184 |      39
  2019    227        22        0        205 |      26
  2020    115        10        0        105 |       6
  2021    172        22        0        150 |       9
  2022    125         6        0        119 |      15
  2023    174        15        0        159 |      17
  2024    136         3        0        133 |      10
  2025    199         1        0        198 |       6
  2026    135        33        0        102 |      58

wrote /Users/troded/nycur/data_website/civic_reference/legislation_implementation_tracker/quality_reports/quality_report_2026-09-02.fiscal.json
```
