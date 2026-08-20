# Legislation trackers quality report — quality_report_2026-08-20

Hard failures: **0** (clean)

## validate_obligations.py
```
validating 8,185 obligations across 2,138 laws

HARD FAILURES: 0

SOFT COUNTS (tracked, not failures):
     24  fewer_reports_than_doris_lists
      8  law_text_at_or_over_cap
     24  legistar_says_sunset_but_none_parsed
    100  quote_not_in_law_text
    663  quotes_reprinted_text
     40  same_generic_actor_multiple_agencies

wrote /Users/troded/nycur/data_website/civic_reference/legislation_implementation_tracker/quality_reports/quality_report_2026-08-20.validator.json
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
/Users/troded/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
```
