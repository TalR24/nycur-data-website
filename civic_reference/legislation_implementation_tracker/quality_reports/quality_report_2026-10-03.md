# Legislation trackers quality report — quality_report_2026-10-03

Hard failures: **0** (clean)

## Change vs quality_report_2026-09-03

- **fiscal_soft:agency_not_canonical**: 7 → 0 (improved -7)
- **fiscal_soft:breakdown_line_without_amount**: 22 → 0 (improved -22)
- **fiscal_soft:date_prepared_missing**: 22 → 0 (improved -22)
- **fiscal_soft:file_number_missing**: 5 → 0 (improved -5)
- **fiscal_soft:legistar_file_missing**: 30 → 0 (improved -30)
- **fiscal_soft:legistar_url_missing**: 30 → 0 (improved -30)
- **fiscal_soft:net_differs_from_revenue_minus_costs**: 1 → 0 (improved -1)
- **fiscal_soft:no_agency_attributed**: 22 → 0 (improved -22)
- **hard:recurrence_is_a_template_placeholder**: 2 → 0 (improved -2)
- **soft:fewer_reports_than_doris_lists**: 24 → 0 (improved -24)
- **soft:law_text_cache_absent**: 1 → 0 (improved -1)
- **soft:legistar_says_sunset_but_none_parsed**: 24 → 0 (improved -24)
- **soft:quotes_reprinted_text**: 617 → 0 (improved -617)
- **soft:same_generic_actor_multiple_agencies**: 42 → 0 (improved -42)

## validate_obligations.py
```
Traceback (most recent call last):
  File "/home/runner/work/nycur-data-website/nycur-data-website/civic_reference/legislation_implementation_tracker/pipeline/validate_obligations.py", line 620, in <module>
    main()
  File "/home/runner/work/nycur-data-website/nycur-data-website/civic_reference/legislation_implementation_tracker/pipeline/validate_obligations.py", line 335, in main
    from extract_obligations import classify, final_kind
  File "/home/runner/work/nycur-data-website/nycur-data-website/civic_reference/legislation_implementation_tracker/pipeline/extract_obligations.py", line 47, in <module>
    from claude_batch import cached_content, run_batch, clear_state, Usage, message_text  # noqa: E402
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/nycur-data-website/nycur-data-website/pipeline/claude_batch.py", line 26, in <module>
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
ModuleNotFoundError: No module named 'anthropic'
```

## validate_against_doris.py
```
DORIS required reports: 2296
traced to a 2014-2026 local law: 1552
laws present in both corpora: 661

COVERAGE GAPS (DORIS names a reporting law, we extracted nothing): 1
  Local Law 152 of 2023: Report on Multi-Agency Response to Community Hotspots (MARCH)

CLASSIFICATION DIFFERENCES (we extracted, but not as a report): 71
  our types on those laws: {'database or data publication': 75, 'notice or posting': 47, 'other': 40, 'outreach or education': 27, 'rulemaking': 21, 'plan or strategy': 21}

COMPLIANCE, per DORIS, for reports created by in-scope laws:
  DORIS records no filing      581
  overdue                      372
  current                      354
  no schedule in DORIS         239
```

## validate_fiscal_impacts.py (fiscal tracker)
```
Traceback (most recent call last):
  File "/home/runner/work/nycur-data-website/nycur-data-website/pipeline/validate_fiscal_impacts.py", line 40, in <module>
    from fetch_fiscal_impacts import is_proposed_bill  # noqa: E402  (one rule, shared with the pipeline)
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/nycur-data-website/nycur-data-website/pipeline/fetch_fiscal_impacts.py", line 47, in <module>
    from docx import Document
ModuleNotFoundError: No module named 'docx'
```
