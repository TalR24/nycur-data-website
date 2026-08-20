# Legislation trackers quality report — quality_report_2026-08-20

Hard failures: **0** (clean)

## validate_obligations.py
```
validating 8,185 obligations across 2,138 laws

HARD FAILURES: 1933
   1933  law_text_missing
           Local Law 126 of 2026: 11 obligations, no cached text
           Local Law 125 of 2026: 1 obligations, no cached text
           Local Law 124 of 2026: 3 obligations, no cached text
           Local Law 122 of 2026: 4 obligations, no cached text
           Local Law 121 of 2026: 17 obligations, no cached text
           Local Law 120 of 2026: 3 obligations, no cached text
           ... and 1927 more

SOFT COUNTS (tracked, not failures):
     24  fewer_reports_than_doris_lists
     24  legistar_says_sunset_but_none_parsed
    663  quotes_reprinted_text
     40  same_generic_actor_multiple_agencies

wrote /home/runner/work/nycur-data-website/nycur-data-website/civic_reference/legislation_implementation_tracker/quality_reports/quality_report_2026-08-20.validator.json
```

## validate_against_doris.py
```
DORIS required reports: 2289
traced to a 2014-2026 local law: 1546
laws present in both corpora: 661

COVERAGE GAPS (DORIS names a reporting law, we extracted nothing): 0

CLASSIFICATION DIFFERENCES (we extracted, but not as a report): 66
  our types on those laws: {'database or data publication': 84, 'rulemaking': 34, 'plan or strategy': 33, 'outreach or education': 24, 'notice or posting': 22, 'enforcement or inspection': 16}

COMPLIANCE, per DORIS, for reports created by in-scope laws:
  DORIS records no filing      589
  current                      375
  overdue                      337
  no schedule in DORIS         239
```
