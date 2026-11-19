# Legislation trackers: extraction audit and prompt audit (Sep 23 2026)

Scope: the Legislation Implementation Tracker (`laws.json`, `obligations.json`) and the Fiscal Impacts Tracker (`fiscal_impacts.json`), plus the three Claude prompts that produce them and the Community Board roster. Nothing in the repo was edited. The proposed code changes are in `prompt_audit_2026-09-23.patch` next to this file (`git apply --check` passes against `625f3b1`).

## Findings, most serious first

1. **Fiscal records disagree with their own source documents.** A blind check of 16 records against the Fiscal Impact Statements on Legistar found 13 wrong: 8 major (wrong total, wrong net, or the wrong document) and 5 minor. Only 3 matched.
2. **The fiscal pipeline reads the oldest statement on an amended bill.** `get_fiscal_attachment()` (`pipeline/fetch_fiscal_impacts.py:474-481`) returns the first attachment whose name contains "fiscal" or "impact". For an amended bill that is the statement for the original version. Three of the 16 sampled records carry a superseded estimate: 7258669 stores $100,000 where Int 1208-A's statement says $413,000; 6639664 stores $3.7M for a program the enacted 807-A replaced with a $1M one-time cost.
3. **`total_expenditure` means three different things across the fiscal table.** The prompt tells the model to "sum across ALL fiscal-year columns" (`fetch_fiscal_impacts.py:129`), which double-counts the Full Fiscal Impact column on a standard three-column statement. Of 332 records with spending: 105 store the full-impact column, 86 store the double-counted sum, 81 match neither, and 60 are multi-year or single-total tables where a sum is right. The agency, sponsor and year charts add these together.
4. **The Sep 1 re-extraction shipped with its restated-text flags pointing at the wrong duties.** The skill requires re-running `sweep_restated_duties.py --no-fetch` after any batch re-extraction; it was not re-run. Of 665 flagged candidates, 48 point at obligation IDs that no longer exist and 97 point at an ID that now holds a different duty (1709673-01 and -02 swapped). The 617 caveats on the site are partly on the wrong records, and 12 reprinted duties in the audit sample carry no caveat.
5. **The Sep 1 batch has a much higher defect rate than the Aug 12 baseline.** A blind check of 10 re-extracted laws found 30 defects in 78 obligations (3.0 per law, against 0.5 per law at the end of the August campaign). The 150 queued laws were the leftovers of the full-corpus pass, not a random draw, so part of the gap may be harder laws. Five laws enacted since Aug 12 had 5 defects in 12 obligations.
6. **Two new defect classes.** NEW-A: a permissive or conditional power ("may", an exception clause) recorded as a duty, 7 records, two with published deadlines (4908135-08, 3486135-20). NEW-B: a schedule of installments stored as one record dated to the last installment (7927500-01 shows 2027-08-01; the first payment is due 2027-01-01).
7. **The monthly quality report cannot see quote verification.** The Sep 3 report says "quote_not_in_law_text: 114 → 0 (improved)" and "law_text_at_or_over_cap: 8 → 0". On the CI runner the text cache is absent, so those checks did not run. The 114 unverified quotes are still there locally, and the Sep 1 batch accounts for 14 of them (1 → 15 on its 665 records).

## Implementation tracker

**Validators** (run locally, no API calls): `validate_obligations.py` over 8,223 obligations in 2,147 laws found 7 hard failures, all `law_text_missing`: laws 128–135 of 2026, extracted in CI, whose text has no local cache yet. Soft counts against the Aug 12 baseline:

| check | Aug 12 | Sep 23 |
|---|---|---|
| quote_not_in_law_text | 100 | 114 |
| quotes_reprinted_text | 663 | 617 (flags misassigned, see finding 4) |
| same_generic_actor_multiple_agencies | ~40 | 42 |
| fewer_reports_than_doris_lists / law_text_at_or_over_cap / legistar_says_sunset_but_none_parsed | 24 / 8 / 24 | 24 / 8 / 24 |

`validate_against_doris.py`: 2,296 DORIS required reports, 1,552 traced to a 2014–2026 local law, 661 laws in both datasets, 0 coverage gaps, 68 classification differences.

**Blind sample.** 15 laws, 90 obligations, seeded sample (`random.Random(20260923)`): 10 of the 128 unprotected laws re-extracted on Sep 1, 5 of the 9 laws added since. An Opus reviewer fetched every law live from Legistar (15 of 15, all inline text) and checked each record's quote, actor, deadline and recurrence, and each law for missed duties. I re-checked two claims against `obligations.json`: 3498451-03 and -08 cite §27-2056 (Housing Maintenance Code, HPD) and are tagged DOHMH; 4908135-08 records the exception "prior to July 1, 2022, the director determines in writing that..." as a duty due 2022-07-01. Both confirmed.

| group | laws | obligations | defects | missed duties |
|---|---|---|---|---|
| re-extracted Sep 1 | 10 | 78 | 30 | 2 |
| new since Aug 12 | 5 | 12 | 5 | 1 |

Defects by class: class 4 unflagged restated text 12, class 1 wrong actor 6, NEW-A 7, class 5 private-party duty 3, class 8/11 actor phrase or citywide tag 4, others 3. Deadline arithmetic and recurrence were correct on all 90. Full table: Appendix A.

**Unconstrained option lists leak into the data.** The prompt describes the allowed values but nothing enforces them. Stored records carry 33 `deadline.kind` values the prompt never offered (`annual` 21, `recurring` 4, `before_effective_date` 3, `before` 2, one each of `ongoing`, `other`, `days_after_fixed_date`); `resolve_deadline()` returns no date for all of them. The prompt's `deadline.kind` list also omits `days_after_other`, which its own rule on line 107 requires (214 records use it anyway).

## Fiscal tracker

**Validator**: `validate_fiscal_impacts.py --links 40` over 359 records: 0 hard failures; all 40 re-fetched links open the right bill; 3 soft title mismatches. Coverage: 0 enacted laws unchecked in any year 2014–2026.

**Blind sample.** 16 records, same seed: 12 added or re-keyed in the Sep 2–3 seed (256 of the 359 current IDs are not in the Aug 21 version, because the Sep 2 fix re-keyed REST IDs to web IDs), 4 older. An Opus reviewer compared each against every Fiscal Impact attachment on its Legistar page.

| group | records | clean | minor | major |
|---|---|---|---|---|
| Sep 2–3 | 12 | 3 | 4 | 5 |
| older | 4 | 0 | 1 | 3 |

Record 69376 could not be identified (no URL or file number; the Legistar API returned 403 without a token). Full table: Appendix B.

**Records that contradict themselves.** 19 records have fiscal-year columns and a headline net with opposite signs. Example: Int 0600-2022's columns show revenue of +$56.25M and +$33.75M and a positive net each year; its headline says a net cost of $90.5M. `reconcile_totals()` moved the headline revenue into expenditure and left the columns alone.

**No source link.** 30 of 359 records (8%) have no `legistar_url`: 17 pre-considered resolutions, 12 Introductions, 1 pre-considered Introduction. Their Bill # shows placeholders such as "Preconsidered Intro. No.". All 30 carry a GUID or attachment ID, so a link can likely be rebuilt.

**Int. No. 146-C** (matter 3331786): expenditure $1,121,805 and net −$1,053,491, a gap no revenue or capital explains. The stored expenditure is the sum of five yearly columns (FY22–FY26).

## Prompt audit

Assumptions, stated rather than asked: the scope is every Claude call site in `data_website` (three prompts; `reextract_queued.py` reuses the obligations prompt; `fetch_fiscal_impacts_historical.py` makes no model call). The target model is `claude-haiku-4-5`, the only model the code calls. No non-Anthropic provider appears anywhere. Structured outputs are documented for Haiku 4.5, and the pinned SDK (`anthropic==0.92.0`) accepts `output_config` on `create` and `stream` (checked by signature).

Counts: Group 1b (API-feature replacements) 5, Group 1c (disagreeing duplicates) 3, Group 4 (request config) 3. No Group 2 or 3 findings: none of these prompts define tools, and skill files were out of scope.

| # | location | evidence | pattern | why it is obsolete here | confidence | action |
|---|---|---|---|---|---|---|
| F1 | `extract_obligations.py:66, 521-536` | `messages.append({"role": "assistant", "content": "{"})` then `messages = [...]` on the next line; fence-stripping regex; "Return ONLY a JSON object ... (no markdown, no explanation)" | 1b prefill / JSON-forcing stack | The prefill line is dead: it is overwritten immediately. Structured outputs on Haiku 4.5 guarantee valid JSON, and schema enums stop off-list values (33 invented deadline kinds, the class-14 placeholder) | High | replace-with-API-feature |
| F6 | `fetch_fiscal_impacts.py:129-130` | "sum across ALL fiscal-year columns ... net_fiscal_impact = total_revenue - total_expenditure - total_capital" | 1b arithmetic the model must compute | Measured: three coexisting total definitions (finding 3) and the 24 sign and duplication errors `reconcile_totals()` patches afterwards. The obligations pipeline already keeps date arithmetic in Python for this reason | High | rewrite: model copies stated figures and columns; code computes totals |
| F8 | `fetch_fiscal_impacts.py:64, 139, 553-561` | "return ONLY a valid JSON object — no markdown fences..." stated twice; fence stripping; `JSONDecodeError` retry | 1b JSON-forcing stack | Same as F1 | High | replace-with-API-feature |
| F3 | `extract_obligations.py:85` vs `:107` | kind list lacks `days_after_other`; rule says "Use kind=days_after_other" | 1c duplicates that disagree | The model resolves the conflict case by case: 214 records use it, 33 invent other kinds | Medium | rewrite: add it to the list (enum in F1) |
| F4 | `extract_obligations.py:89` | `"every N years"` among the recurrence options | 1c single gold example copied literally | Defect class 14 is the model copying this placeholder (15 records fixed by hand). The corpus also needs `weekly`, `daily`, `semiannual`, which the list omits | Medium | rewrite: explicit cadence list (enum in F1) |
| F5 | `extract_obligations.py:111` vs `:78` | "keep actor_resolved as written" vs "return exactly 'unspecified'" | 1c duplicates that disagree | The field description and the rule give opposite instructions for the same case | Medium | rewrite to match line 78 |
| F2 | `extract_obligations.py:86, 112` | "convert months to days as months*30, years to days as years*365" | 1b arithmetic the model must compute | Code already owns the date arithmetic; the model should report the law's own number and unit | Medium | rewrite: `offset {amount, unit}`, converted in code |
| F7 | `fetch_fiscal_impacts.py:135` | inline list of 28 abbreviations including "DCA" (renamed DCWP in 2019); "Create reasonable abbreviations for others" | 1b inline lookup table | `normalize_agency_attribution()` already canonicalizes through the crosswalk; invented abbreviations are what it cannot resolve (7 `agency_not_canonical`) | Medium | rewrite: return names as written |
| F9 | `fetch_fiscal_impacts.py:544` | `text[:18000]` | Group 4 silent truncation | 18,000 characters is about 4.5K tokens of Haiku's 200K window. The cut falls where statements put OMB notes, preparer and date (22 records lack `date_prepared`; the link is plausible, not verified) | Medium | rewrite: 150,000-character cap with a logged warning |
| F10 | `fetch_fiscal_impacts.py:551` | `max_tokens=4096` | Group 4 max_tokens sized too small | The output copies two full narrative paragraphs plus line items; a cut-off response fails as a JSON error and burns a retry | Medium | rewrite: 16,000 and treat `max_tokens` stop as an error |
| F11 | `cb-tools/member-tracker/pipeline/extract_rosters.py:40, 125-132` | "Return ONLY a JSON object ... (no markdown fences, no prose)"; fence stripping | 1b JSON-forcing stack | Same as F1 | Medium | replace-with-API-feature |
| K1 | `extract_obligations.py:78, 100-110` | NEVER / must NOT / only-inside-braces rules | reviewed, kept | Added Aug 6–11 against Haiku 4.5, each tied to a documented defect class that still reproduces (the sample found class 1, 4 and 5 again). Keep list 5 | n/a | keep |
| K2 | `extract_rosters.py:44-45`; `fetch_fiscal_impacts.py:137` | "copied VERBATIM ... Never infer"; street signs to DOT | reviewed, kept | Both enforced again in code (`validate()`, `normalize_agency_attribution()`); working redundancy | n/a | keep |
| L1 | model pin, all three files | `claude-haiku-4-5-20251001` | flag | The sample defect rate is a model-choice question as much as a prompt one; outside a prompt audit. `/claude-api migrate` covers it | Low | flag |

Not verified: no live request was sent with the patched prompts (it spends API credit and needs the key). Offline checks run: both schemas meet the structured-outputs rules (every object closed, every property required); the rendered prompt has no leftover placeholders; "18 months" converts to 540 days; all three patched files compile and import.

**What the F6 change does to the data.** Applied to the stored columns, `totals_from_columns()` changes 167 of 359 records and the summed expenditure falls from $16.98B to $13.97B. The definition it uses is a decision for you (see below), and recomputing from columns inherits the column errors in findings 1 and 2, so the patch belongs with a re-extraction, not a recompute alone.

## Proposed order of work

1. Re-run `python3 pipeline/sweep_restated_duties.py --no-fetch`, rebuild from cache, and confirm the flag count and the 12 unflagged reprinted duties in Appendix A. No API spend.
2. Fix `get_fiscal_attachment()` to take the statement for the enacted version (the latest one, or the one whose name carries the final suffix such as "-A"), then re-extract the amended bills.
3. Decide the definition of a bill's total, then apply the patch and re-extract the fiscal table.
4. Apply the obligations half of the patch and re-extract the Sep 1 batch, then re-sample.
5. Make the monthly quality report say "not measured" when the text cache is absent, instead of reporting an improvement.
6. Hand-fix the Appendix A records through `actor_overrides.json` and the exclusions list, and add "Department of Education of the City of New York" → NYCPS to the crosswalk.
7. Add NEW-A and NEW-B as standing checks: a quote whose operative verb is "may" or that sits in an exception clause; a deadline clause that lists several dates.

## Decisions for you

- **What one number per bill means.** The patch proposes the annual cost at full implementation (the statement's Full Fiscal Impact column), falling back to the sum of columns when that column is zero, so a one-time first-year cost is not erased. The alternative is a cumulative multi-year figure. The methodology page must say which.
- **Whether off-list deadline kinds are errors.** The patch's enum would force `before_effective_date` (3 records) into an existing kind. If that concept matters, add it to the enum and to `resolve_deadline()`.

## Method and counts

- Obligations and laws: `data/obligations.json` and `data/laws.json` at `625f3b1`, read locally in full (8,223 and 2,147 records).
- Fiscal: `data/fiscal_impacts.json` at `625f3b1`, 359 records, read locally in full.
- DORIS: the cached pull used by `validate_against_doris.py`, 2,296 rows.
- Samples: seeded, reproducible. Implementation: 15 of 137 eligible laws (128 re-extracted unprotected + 9 new). Fiscal: 16 of 359 records. Sampled rates are estimates from small samples; they show the direction and size of the problem, not a corpus-wide defect count.
- Prior-state comparisons: `git show 29159fb^:` for the pre-Sep 1 queue, laws and obligations; `git show d0e15ba:` for the 257-record fiscal table.

## Unrelated to this audit: the slowest test

`mention_monitor/test_monitor.py:147` `test_wp_search_finds_both_streetsblog_roundups` is the slowest test (10.5s once, then 1.1s steady), because it passes a 0.5-second politeness delay that sleeps before each of 2 live article fetches. CI skips it. Proposed fix: pass `0` as the delay at line 162.

---

# Appendix A: implementation tracker blind audit (Opus reviewer, raw)

The helper scripts and page caches this appendix mentions lived in a temporary job folder and are not kept; every row cites the law text it rests on.

## Implementation tracker blind audit: 15 laws, 90 obligations (Sep 23 2026)

Method: fetched each law's live Legistar LegislationDetail.aspx page (15 of 15 fetched, all with inline text, no attachment fallback needed). Parsed the text div with an HTML walker that keeps underlined runs as `{{...}}` and keeps `[...]` deletions; operative text = brackets removed. Scripts and outputs in this folder: `audit_fetch.py`, `audit_text.py`, `audit_check.py` (quote locator, reports share of each quote that is underlined new text), `audit_check.out`, `audit_show.py`, raw pages and trimmed law text in `audit_html/` (`<matter>.html`, `<matter>.law`). Sample records match the published `obligations.json` field for field (0 diffs on quote/agency/deadline_date/recurrence across all 90).

Class numbers are the skill's (Aug 2026 audit table). Two NEW classes:
- **NEW-A: discretionary or conditional power recorded as a duty.** "may", "when approved by", an exception clause, or a "such other ... as may be authorized" definition turned into an obligation, sometimes with a published due date.
- **NEW-B: multi-installment schedule collapsed to one date.** A duty with several statutory due dates is stored as one record dated to the LAST installment, so the earliest due date never appears.

## Defects

| obligation_id | class | evidence from the law text | proposed fix |
|---|---|---|---|
| 3498451-03 | 1 | §27-2056.2(7)(b) is Housing Maintenance Code; "the department" = HPD. Same law, §27-2056.14: "the department of health and mental hygiene shall notify the department of each dwelling unit"; §3: "the rule promulgated by the department pursuant to paragraph (b) of subdivision (7) of section 27-2056.2" sits in HPD's exemption section | agency → HPD. Also the text is a trigger ("upon the promulgation of a rule"), not a mandate; consider NEW-A |
| 3498451-04 | NEW-A + 4 | "or such more stringent standards as may be adopted by {{rule of}} the department of health and mental hygiene" (only "rule of" is new; 7% underlined) | delete |
| 3498451-06 | 18 (near-duplicate) | same sentence as -05 ("the board of health shall define in the health code such lower levels"), repeated in (8)(b) | merge into -05 |
| 3498451-08 | 1 | §27-2056.7(a): "When the department of health and mental hygiene issues a commissioner's order ... **the department**, within fifteen days of such order, shall notify the owner" (subject is HPD; record's actor_raw rewrites it as DOHMH) | agency → HPD (record already flagged restated) |
| 3498451-09 | 1 | same section: "the department within ten days shall attempt to inspect such units to determine whether there are any violations of section 27-2056.6" | agency → HPD |
| 3498451-10 | 1 + 4 | §27-2056.11(a)(1) rules govern "a notice of violation or order to correct issued by the department pursuant to this article" (HPD); only "or unsafe lead paint" is new (3% underlined), rst=false | agency → HPD; flag restated |
| 3498451-12 | 4 | §27-2056.14 reprinted; "shall notify the department of each dwelling unit..." has no underline; the only change in the section is the blood-lead threshold | flag restated or delete |
| 3498451-13 | 4 | "shall certify such conditions to the department of housing preservation and development ... within sixteen days" has no underline | flag restated or delete |
| 4908135-05, -06 | 8/11 | agency stored as "a contracting agency" (actor phrase). Per-finding duty ("in making any such finding ... shall submit to the director a report") stored as recurrence one-time | agency → All agencies; recurrence → per case / ongoing |
| 4908135-07 | 11 | "no agency shall purchase or lease any desktop computer ..." stored as Unspecified | agency → All agencies |
| 4908135-08 | NEW-A | "This prohibition shall not apply ... if: ... 2. prior to July 1, 2022, the director determines in writing that products ... are not available" is an exception, not a duty; published deadline 2022-07-01 | delete |
| 4908135-09 | NEW-A | "or another standard selected by the director that is similar in function" is optional | delete |
| 4908135-10 | 1/11 | §6-306(f): "No lamp purchased or leased by any agency shall be an incandescent lamp{{, including but not limited to a halogen lamp}}" is a flat purchasing ban on agencies. No rulemaking by the director | agency → All agencies; type → other; rewrite summary |
| 4908135-12 | 4 | §6-311 "By January 1, 2008 ... the city shall develop a plan" has no underline; only the posting sentence is new (already captured as -13) | delete |
| 4908135-23 | 8 | agency field holds the whole 190-char clause "the director of citywide environmental purchasing, in collaboration with the commissioner of environmental protection and ..." | agency → director's canonical agency; collaborators to a note |
| 4908135 (17 records) | 6 | agency "the director of citywide environmental purchasing" is not canonical; 16 records corpus-wide use it | add crosswalk variant (placement of the director under DCAS comes from §6-304's opening, not reprinted in this law; verify before mapping) |
| 3486135-07 | NEW-A | "{{the Fire Department may approve the installation of}} alternative automatic fire-extinguishing systems" | delete or retype as approval authority |
| 3486135-10 | 4 | BC 907.1.1: "shall be submitted for review and approval to [the department and] the Fire Department". FDNY review existed before; the law only removes DOB (0% underlined) | flag restated |
| 3486135-13 | 5 | BC 908.11 "Acceptance testing and maintenance of emergency alarm systems shall be performed in accordance with the New York City Fire Code": duty on owners/contractors | delete |
| 3486135-14 | 4 | BC 917.1.1: "shall be submitted for [review and] approval to [the department and] the Fire Department"; FDNY approval pre-existing | flag restated |
| 3486135-15 | 4 | FC 105.4.1 submission text is wholly pre-existing; the only new text is the private-contractor exception. (Quote also elides a sentence; already quote_verified=false) | delete |
| 3486135-16 | 5 | FC 105.4.3 "it shall be unlawful to construct or alter any facility ... without first having obtained department approval": prohibition on private parties | delete |
| 3486135-18 | NEW-A | "The department **may** make its approval ... subject to such terms and conditions as the department **may** prescribe by rule" | delete |
| 3486135-20 | NEW-A + 8 | §22 "the commissioner of buildings and the fire commissioner **may** promulgate rules" is permissive but carries a published deadline 2019-05-30; agency stored as the raw two-actor phrase | delete, or keep undated with agency DOB; FDNY |
| 5999933-01 | NEW-A | §20-435(2) definition: "such other specific games as may be authorized by the board" (the state gaming commission, not a city body) | delete |
| 5999933-03 | 4 | §20-438(1) lead sentence "The department shall make an investigation of the qualifications of each applicant" has no underline; the only change in (1) is the raffle exception in (a); rst=false | flag restated |
| 5999933-08 | 1 | agency stored as "the commissioner of the department"; Title 20 = DCWP. Also "may promulgate", a discretionary power (record flagged restated) | agency → DCWP |
| 7653637-05 | 4 | BC 202 SST item 3 "(i) the information necessary to establish that the requirements in Item 1 have been satisfied, as specified by the department": no underline; rst=false | flag restated |
| 1890977-04 | 5 | quote "A retail store may seek review, in the department, of the determination ..." is a retail store's right. The summary's "provide written notification" duty is not stated in the law | rewrite as DCWP duty to review on request, or delete |
| 7927500-01 | NEW-B + 6 | §2(b): four installments due "no later than January 1, 2027 ... March 1, 2027 ... June 1, 2027 ... and no later than August 1, 2027"; record dated 2027-08-01 only. Agency "Department of Education of the City of New York" is not canonical (canonical: NYCPS, 254 records) | split into 4 dated records or date to 2027-01-01; agency → NYCPS |
| 7927500-02 | 6 | same non-canonical agency string | agency → NYCPS; add crosswalk variant |
| 7966352-04 | 2 | §21-219(c) wellness checks run "during a cold weather alert, extreme heat warning, or heat-related emergency" under the protocol due "No later than February 1, 2027"; record dated on_effective_date 2026-08-18, before the protocol exists | deadline_kind → days_after_other (per event), date null |
| 7862722-01 | 4 | §12-110(d)(1)(q): COIB's amount-setting power is pre-existing ("[or such other] amount [as] the conflicts of interest board [shall set]"); the law only reworded it and moved the brackets. The duty itself is in Charter §2603(a) | delete |
| 7862722-02 | 18 + 4 | byte-identical quote to -01 ("the amount set by the conflicts of interest board pursuant to subdivision sixteen ...") | delete |

Known issues, noted and not counted: 4908135-01 quote drops "and implementing" (text: "for the purpose of establishing and implementing environmental purchasing standards"; already quote_verified=false). 3486135-15 elision (quote_verified=false). Restated flags are misassigned in both directions (known renumbering issue): flagged although the quote is wholly underlined new text: 3498451-06, -07; 4908135-09; 1890977-02 (7653637-07 is 74% new). Unflagged although wholly reprinted: every class-4 row above. Re-running `sweep_restated_duties.py --no-fetch` would probably catch most of the class-4 rows.

Should-fix (not counted): 3486135-08 ("When approved by the Fire Department, automatic sprinklers shall not be required"), a conditional exemption close to NEW-A. 3486135-05 (applicant's duty to submit per FDNY rules, recorded as FDNY rulemaking). 7966352-05's "updated reports ... whenever such protocol or criteria are updated" is recurring per event but the record says one-time.

## Missed duties

| matter | missed duty (law text) |
|---|---|
| 4908135 | §8, §6-305(a)(2): agencies "submit an annual report as required by the director detailing such compliance, which report shall include all reports required for exemptions ..." (changed duty on every agency; not captured) |
| 4908135 | §11, §6-307(b): power management of "every computer, printer, facsimile machine, photocopy machine and other piece of office equipment ... shall be calibrated to achieve the highest energy savings practicable" (extended to all office equipment; not captured) |
| 8042529 | Charter §20-w(e): "Where the head of an agency or office designated by the mayor establishes the program ..., such head shall submit such report to the mayor" (duty on the designated secondary body; class 9) |

Borderline, not counted: 3704322 (0 obligations): §2 exempts items at stores with enough scanners "as determined by rule of the commissioner" (DCWP). The rule is implied, not mandated.

## Per-law tallies

| matter | law | group | obligations checked | defective records | missed duties |
|---|---|---|---|---|---|
| 4209300 | LL 32/2020 | sep1 | 1 | 0 | 0 |
| 3498451 | LL 66/2019 | sep1 | 13 | 8 | 0 |
| 3704322 | LL 129/2021 | sep1 | 0 | 0 | 0 (1 borderline) |
| 4908135 | LL 111/2021 | sep1 | 23 | 9 (8 records + 1 systemic crosswalk gap over 17 records) | 2 |
| 3486135 | LL 195/2018 | sep1 | 20 | 8 | 0 |
| 5999933 | LL 60/2023 | sep1 | 8 | 3 | 0 |
| 7653637 | LL 10/2026 | sep1 | 7 | 1 | 0 |
| 3199287 | LL 52/2018 | sep1 | 1 | 0 | 0 |
| 1853962 | LL 83/2017 | sep1 | 1 | 0 | 0 |
| 1890977 | LL 5/2017 | sep1 | 4 | 1 | 0 |
| 8134075 | LL 133/2026 | new | 0 | 0 | 0 (tax-credit formula, no agency duty; 0 is correct) |
| 7927500 | LL 129/2026 | new | 3 | 2 | 0 |
| 7966352 | LL 130/2026 | new | 5 | 1 | 0 |
| 8042529 | LL 132/2026 | new | 2 | 0 | 1 |
| 7862722 | LL 127/2026 | new | 2 | 2 | 0 |

Deadline arithmetic re-computed from enactment, all correct: 2022-04-22 (LL111/2021, +180d), 2023-04-22 (+12 months after effective), 2019-05-30 (LL195/2018, +180d), 2026-05-03 (LL10/2026, +120d), 2017-11-26 (LL83/2017, +180d), 2027-02-14 (LL132/2026, +180d). Recurrence: no biannual/biennial mix-ups and no "every n years" placeholder in the sample.

## Totals by why_sampled

| group | laws | obligations | defects | defects per law | missed duties |
|---|---|---|---|---|---|
| sep1_reextracted | 10 | 78 | 30 | 3.0 | 2 |
| new_since_aug12 | 5 | 12 | 5 | 1.0 | 1 |
| **all** | 15 | 90 | 35 | 2.3 | 3 |

By class: 4 (unflagged restated) 12, NEW-A 7, 1 (wrong or unresolved actor) 6, 5 (private-party) 3, 8/11 (agency tag) 5 records, 6 (crosswalk) 2 laws, 18 (duplicate) 2, 2 (event-anchored) 1, NEW-B 1. Some records carry two classes.

Why the sep1 rate is high: 2 laws (LL66/2019 and LL195/2018, both long amendment laws) hold 16 of the 30. Half of the sep1 defects are class 4 or NEW-A, both of which a stricter prompt or a rerun of the restated sweep would address. The Aug 12 baseline was about 1 defect per 2 laws (0.5 per law). This sample runs at 3.0 per law on the Sep 1 re-extractions and 1.0 per law on new laws. The sample is not random with respect to size: 2 of the 15 laws have 0 obligations and 3 are one-obligation laws.

---

# Appendix B: fiscal tracker blind audit (Opus reviewer, raw)

## Fiscal Impacts Tracker: blind audit of 16 sampled records (Sep 23 2026)

Method: for each record, fetched the Legistar detail page (`legistar_url`, unauthenticated web page), listed every attachment whose title contains "Fiscal Impact", downloaded each one (Council FIS are .docx; converted with `textutil`; OMB PDFs read with pypdf), and compared the fields against the document text. For older records the stored `attachment_id` (a legistar1 .docx URL) was downloaded too; in every case it was byte-for-byte the same size as the web FIS attachment. Raw texts: `/Users/troded/.claude/jobs/bcbcad1f/tmp/audit/fis_<matter_id>_<n>.txt`, pages: `audit/page_<matter_id>.html`.

Yardstick: totals are compared with the FIS "Full Fiscal Impact" column, as the orders specify. Note that the pipeline's own rule differs: `EXTRACTION_PROMPT` line 129 says "sum across ALL fiscal-year columns", and the NARRATIVE rule (line 144) and `reconcile_totals()` (lines 827-835) move a revenue loss into `total_expenditure` rather than storing negative revenue. Both conventions are flagged where they change a number.

Severity: MAJOR = a total, net, or the source document is wrong; MINOR = a date, column, or agency field.

## Defects

| # | matter_id | field | stored | source value | evidence in FIS | likely pipeline cause | sev |
|---|---|---|---|---|---|---|---|
| 1 | 7258669 | source document | att 14300291 (FIS for Int 1208, Jun 17 2025) | enacted bill is 1208-A; its FIS is att 14846735 (Oct 8 2025) | page lists "Int. No. 1208-A - Fiscal Impact Statement - City Council" ID 14846735 | `get_fiscal_attachment()` fetch_fiscal_impacts.py:474-481 returns the FIRST attachment whose filename has "fiscal"/"impact"; Legistar lists attachments oldest first | MAJOR |
| 2 | 7258669 | total_expenditure / net | 100,000 / -100,000 | 1208-A full impact FY27: 413,000 / -413,000 (FY26 206,500). Even the stale Int 1208 FIS shows full-impact $0 (the 100,000 is FY26 one-time) | 1208-A table "Full Fiscal Impact FY27 ... $413,000" | wrong version (row 1) | MAJOR |
| 3 | 7258669 | date_prepared, source_of_funds, agencies, breakdowns | 2025-06-17, N/A, DHS, one $100k OTPS line | Oct 8 2025; General Fund; DSS/HPD; $143k PS project manager + $270k OTPS consultant | 1208-A FIS "Date Prepared: October 8, 2025", Impact on Expenditures | wrong version | MAJOR |
| 4 | 6639664 | source document | att 13701309 (FIS for Int 807, shelter pilot) | enacted 807-A (outreach program); FIS att 14009598, prepared 4/08/2025 | page lists "Int. No. 807-A - Fiscal Impact Statement - City Council" ID 14009598 | first-attachment rule (row 1) | MAJOR |
| 5 | 6639664 | total_expenditure / net | 3,700,000 / -3,700,000 | 807-A: full impact FY27 $0; one-time $1,000,000 in FY26. (Stale 807 FIS full impact is 1,900,000; 3.7M = 0+1.9M+1.9M, i.e. the full-impact column summed in) | 807-A table "Expenditures (-) ($1,000,000) $0 $0" | wrong version + "sum ALL columns" rule | MAJOR |
| 6 | 6639664 | fy_first / fy_full / date_prepared / breakdowns | FY25 / FY26 / 2025-01-28 / PS+OTPS+program dev | FY26 / FY27 / 2025-04-08 / one $1M OTPS outreach line | 807-A FIS | wrong version | MAJOR |
| 7 | 6860235 | source document | att 14260742 (Int 1034, Jun 2 2025) | enacted 1034-A; FIS att 14824788 (Sep 23 2025) | page lists a second "Fiscal Impact Statement - City Council" ID 14824788 | first-attachment rule | MAJOR |
| 8 | 6860235 | fy_first_effective, date_prepared, effective_date, file_number | FY26, 2025-06-02, "Immediately", "Int. No. 1034" | FY27, 2025-09-23, "270 days after becoming law", "Proposed Int. No: 1034-A" | 1034-A FIS header and table. Totals (77,000) happen to be unchanged | wrong version | MAJOR |
| 9 | 4265474 | total_expenditure / net | 23,725 / -23,725 | full impact FY21: 8,897 / -8,897 | table: 5,931 / 8,897 / 8,897; 23,725 = sum of all three columns | prompt line 129 "sum across ALL fiscal-year columns" double-counts the Full Fiscal Impact column | MAJOR |
| 10 | 69376 | total_expenditure / net | 1,167,000 / -1,167,000 | full impact FY23: 389,000 / -389,000 | table 389,000 x3; 1,167,000 = 3 x 389,000 | same as row 9 | MAJOR |
| 11 | 69376 | program_breakdowns[0].amount | 931,000 | City cost 389,000; the other 542,000 is paid by other obligors | Impact on Expenditures: "The City would fund $389,000 ... other obligors funding the remaining $542,000" | extractor took the gross annual cost | MINOR |
| 12 | 3830891 | total_capital / net | 65,526,259 / -65,526,259 | full impact FY21 capital 46,253,830 | table "Capital Expenditures $19,272,429 $46,253,830 $46,253,830"; 65,526,259 = FY20+FY21 | summing columns (rule at line 129, applied to two of three columns) | MAJOR |
| 13 | 3830891 | fiscal_table_columns[*].expenditure | 19,272,429 / 46,253,830 / 46,253,830 | 0 (the table has only a capital row) | same table | `reconcile_totals()` lines 837-840 fix the top-level total only, never the columns | MINOR |
| 14 | 8033477 | total_expenditure / net | 1,500,000 / -1,500,000 | full impact FY27: 1,200,000 / -1,200,000 | table "Full Fiscal Impact FY27 ... $1,200,000"; 1.5M is the narrative FY2027-2051 cumulative | extractor used the NARRATIVE path despite a table being present; replaced columns with one "Total (FY2027-FY2051)" column | MAJOR |
| 15 | 8033477 | fy_first_effective | null | FY26 | table header "Effective FY26" | same | MINOR |
| 16 | 8033457 | total_expenditure / net | 376,300 / -376,300 | full impact FY44: 24,900 / -24,900 | table "Full Fiscal Impact FY44 ... $24,900"; 376,300 is the FY2027-2051 cumulative from narrative | same as row 14 | MAJOR |
| 17 | 8033457 | fy_first_effective | FY27 | FY26 | table header "Effective FY26" | same | MINOR |
| 18 | 2858255 | fiscal_table_columns[*].revenue / net | +33,000,000 / +33,000,000 (FY18), +34,300,000 (FY19) | ($33,000,000) / ($33,000,000), ($34,300,000) | table "Revenues ($33,000,000) ($34,300,000) ($33,000,000)"; columns now contradict top-level net -33M | `reconcile_totals()` line 832 only moves column revenue when column net < 0; these columns had positive net so were left with the sign flipped | MINOR |
| 19 | 2858255 | total_revenue / total_expenditure | 0 / 33,000,000 | revenue -33,000,000, expenditure $0 | table "Expenditures $0 $0 $0"; "reduce revenues by $33 million" | by-design convention (prompt line 144, reconcile lines 827-835): a property-tax exemption is shown as operational spending on the tracker's Expense metric. Net is correct | MINOR (convention) |
| 20 | 6509492 | total_revenue / total_expenditure | 0 / 450,000 | revenue -450,000, expenditure $0 | table "Revenues ($450,000) ... Expenditures $0"; FIS says DOT uses existing resources | same convention as row 19 | MINOR (convention) |
| 21 | 2858255, 6509492 | agencies_abbrev | ["DOF"], ["DOT"] with program_breakdowns = [] | per data rule, agencies only if they have a breakdown line | SKILL.md "Key data rules" | extractor ignores the agency rule when there are no expense lines | MINOR |
| 22 | 2352225 | fy_first_effective | FY17 | FY16 | table header "Effective FY16" (revenue/expense start FY17) | extractor chose first year with dollars, not the effective year | MINOR |
| 23 | 2270953 | fiscal_table_columns[0].expenditure | 170,140 | 170,146 | table "Expenditures $170,146" | transcription error | MINOR |
| 24 | 7861459 | fiscal_table_columns[*] | capital 0, net 0 in every column | "(See Below)" in every cell; $1.8M one-time capital in narrative | table rows "(See Below)" | columns filled with 0 instead of null. Totals (capital 1,800,000, net -1,800,000) and cost_estimable=true are correct in substance, though the prompt (line 131) says "See Below" should set cost_estimable false | MINOR |

## Per-record verdicts

| matter_id | cohort | verdict | notes |
|---|---|---|---|
| 2352225 | new | DEFECT (minor) | totals, date, sponsor, agency, breakdown all match; fy_first FY17 vs FY16 |
| 2858255 | new | DEFECT (minor) | net -33M correct; column signs flipped; rev/exp convention; agency without breakdown |
| 2561110 | new | OK | 12,075 = full impact; no Date Prepared in FIS so null is right; DOT per sign rule |
| 7258669 | new | DEFECT (MAJOR) | stale Int 1208 FIS; enacted 1208-A is 413,000/yr |
| 4265474 | new | DEFECT (MAJOR) | 23,725 vs 8,897 |
| 2270953 | new | DEFECT (minor) | totals right; one column off by $6 |
| 6639664 | new | DEFECT (MAJOR) | stale Int 807 FIS (different program); enacted 807-A is $1M one-time |
| 6695220 | new | OK | all checked fields match the 867-A FIS |
| 1709698 | new | OK | 1,975 matches; no Date Prepared in FIS |
| 3830891 | new | DEFECT (MAJOR) | capital 65.5M vs 46.3M; columns still carry capital in expenditure |
| 6509492 | new | DEFECT (minor, convention) | net -450k correct; revenue loss stored as expense; agency without breakdown |
| 6860235 | new | DEFECT (MAJOR) | stale Int 1034 FIS; totals unaffected but fy_first/date/effective date wrong |
| 8033477 | older | DEFECT (MAJOR) | 1.5M cumulative vs 1.2M full impact; fy_first null |
| 69376 | older | DEFECT (MAJOR); (a) UNVERIFIABLE | 1,167,000 vs 389,000. No legistar_url/legistar_file; REST API returned HTTP 403 without a token, so the bill identity could not be confirmed on Legistar. The stored docx is an FIS for A.7971/S.6981B matching file_number |
| 8033457 | older | DEFECT (MAJOR) | 376,300 cumulative vs 24,900 full impact; fy_first FY27 vs FY26 |
| 7861459 | older | DEFECT (minor) | totals right; columns 0 instead of "See Below" |

Checks that passed on all 16: File # on the Legistar page equals `legistar_file` (15 of 15 with a URL); prime_sponsor equals first listed sponsor; cost_estimable true is supported by a dollar figure in every FIS; no record's FIS belongs to a different bill (the 3 version errors are same-bill, earlier-version).

## Totals

| cohort | records | OK | DEFECT minor | DEFECT MAJOR | unverifiable (a) |
|---|---|---|---|---|---|
| new (first 12) | 12 | 3 | 4 | 5 | 0 |
| older (last 4) | 4 | 0 | 1 | 3 | 1 (69376, also MAJOR) |
| all | 16 | 3 | 5 | 8 | 1 |

Records with a wrong total or net against the full-impact column: 8 of 16 (7258669, 4265474, 6639664, 3830891, 8033477, 69376, 8033457; 6860235 has right totals from the wrong document and is counted as MAJOR for the version error, so 7 wrong totals + 1 wrong document).

## Systematic patterns

1. Wrong bill version (3 of 16, all "new" cohort, all 2024-25 bills with a later "-A" FIS on the page): `get_fiscal_attachment()` (fetch_fiscal_impacts.py:474-481) returns the first FIS in page order, which is the oldest. For any bill amended after its first FIS, the tracker reports the superseded estimate.
2. Totals definition is inconsistent (6 of 16): prompt line 129 says sum ALL columns, which double- or triple-counts the Full Fiscal Impact column (it restates a year). The extractor follows it sometimes (4265474, 69376 = 3 columns; 6639664 = 3 columns; 3830891 = 2 columns), ignores it other times (2352225, 2270953, 6695220 = full impact), and for SLR pension bills uses the narrative multi-decade cumulative (8033477, 8033457). There is no single meaning of `total_expenditure` across records, so sums and rankings on the tracker mix one-year, multi-year, and 25-year figures.
3. `reconcile_totals()` repairs top-level totals but leaves `fiscal_table_columns` inconsistent (2858255 signs; 3830891 duplicated capital).
4. Revenue losses stored as expenditure (2858255, 6509492) are by design but contradict the orders' "revenue loss negative" convention and inflate the Operational Expense metric.

Side observation: the orders say the first 12 were "added or rewritten Sep 2-3"; 6 of the 12 carry processed_at 2026-04-14 (the reconcile/re-key pass did not touch processed_at).

---

# Update, Sep 24 2026: the loop run

**Quick fix done.** CI's Sep 1 results synced into the local cache (135 laws, effective dates kept), text fetched for 10 laws that had none, and `sweep_restated_duties.py --no-fetch` re-run, so reprinted-text flags now point at the right duties. Hard failures went from 7 to 0.

**Round 17 hand fixes.** The 35 sampled defects: 13 records deleted, 12 corrected, 3 missed duties added, 10 laws added to `reextract_exclusions.json`.

**Duties and powers are now separate (Tal's decision).** A fixed rule in `extract_obligations.classify()` sorts each record from its full provision into duty (obligations table), power (new powers table, never dated) or neither (a private party's option or duty, published nowhere). The rule was tuned and tested over four blind reviews of 350 records:

| round | records | agreement | when |
|---|---|---|---|
| 1 | 80 | 67 (84%) | first rule, quote only |
| 2 | 90 | 76 (84%) | fresh records |
| 3 | 90 | 78 (87%) | fresh records |
| 4 | 90 | 78 (87%) | fresh records, current rule; 4 of 12 differences high-confidence |

After tuning, 246 of the 260 records from rounds 1–3 agree. Fresh-sample agreement plateaued at 84–87%. The remaining differences are definitional (a passive "shall" with no named actor, a power that carries a notice requirement, a private party's requirement with an agency rule inside), which a hand-written rule will not retire. Current split: 7,418 duties, 569 powers, 226 neither.

**The fiscal version bug is larger than the sample showed.** With the statement selection fixed (`get_fiscal_attachment()` now takes the newest Council statement; the first version of the fix failed because Legistar's search highlighting broke the label match), a scan of all 359 records found 59 of the 175 comparable records built from a superseded statement, 116 current, 153 older records with a single version on the page, 1 older record with two versions, and 30 with no link. Correcting the 59 needs a model re-extraction.
