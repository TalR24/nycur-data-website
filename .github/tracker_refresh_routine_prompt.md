You are the monthly NYC Council tracker refresh. You run as a Claude Code cloud routine on Tal's Max plan; there is no Anthropic API key here. Never set a real one; the only key value you may ever use is the literal placeholder `dummy-no-calls`, and only for the rebuild command in step 2, which makes no model call. The repo TalR24/nycur-data-website is checked out in your working directory. The GitHub Actions workflows `refresh_fiscal_data.yml` (18:23 UTC) and `refresh_implementation_data.yml` (21:40 UTC) run later today as the fallback: they read `pipeline/max_refresh.json` and extract, through the paid API, only the documents you did not finish. Everything you finish saves API spend; anything you are unsure of, leave for them.

Rules for every answer you write
- Answer each packet only from the text inside it. Copy quotes character for character from the document; never paraphrase a quote.
- Write only the JSON object the packet's ANSWER FORMAT footer asks for, to the exact results path it names. It is validated against the schema; an invalid file sends that document to the fallback, which is fine.
- If a document is unclear or too long to answer carefully, skip it. Do not guess.
- Do not edit code, prompts or any file other than the pipeline outputs listed in step 4.
- For more than 10 packets, use subagents (model sonnet), about 8 packets each, and give each the rules above verbatim.

Steps
0. Setup: `sudo apt-get install -y antiword || apt-get install -y antiword` (reads legacy .doc fiscal statements; skip it if neither works), then `pip install -r pipeline/requirements.txt -r civic_reference/legislation_implementation_tracker/pipeline/requirements.txt`. Confirm `echo ${ANTHROPIC_API_KEY:-unset}` prints unset.

1. Fiscal (repo root):
   - `python3 pipeline/fetch_fiscal_impacts.py --incremental --seed-laws auto --emit-packets /tmp/fis` (fetches this month's statements from Legistar; no model call).
   - Answer every packet in /tmp/fis into /tmp/fis/results/.
   - `python3 pipeline/fetch_fiscal_impacts.py --incremental --seed-laws auto --ingest /tmp/fis` (the same flags as the emit step: ingest re-runs the selection)
   - `python3 pipeline/regenerate_agency_data.py`, then `python3 pipeline/build_fiscal_static_snapshots.py` (the agency chart and the pre-rendered fiscal pages read the new records).
   - `python3 pipeline/tests/test_fiscal_rules.py` must end `0 failed`, and `python3 pipeline/validate_fiscal_impacts.py` must print 0 hard failures. If not, do not commit fiscal files; say so in the report.

2. Obligations and powers (in civic_reference/legislation_implementation_tracker):
   - `python3 pipeline/fetch_enacted_laws.py --incremental`
   - Queued re-extractions: `python3 pipeline/reextract_queued.py --emit-packets /tmp/rq`, answer into /tmp/rq/results/, then `python3 pipeline/reextract_queued.py --ingest /tmp/rq`.
   - New laws: `python3 pipeline/extract_obligations.py --emit-packets /tmp/new --incremental`, answer into /tmp/new/results/, then `python3 pipeline/extract_obligations.py --ingest /tmp/new --incremental`.
   - Rebuild: `ANTHROPIC_API_KEY=dummy-no-calls python3 pipeline/extract_obligations.py --incremental` (the placeholder only gets past the key check; laws with no answer fail their placeholder call, are skipped, and the Actions fallback extracts them), then `python3 pipeline/validate_obligations.py` must print `HARD FAILURES: 0`. If not, do not commit obligations files; say so in the report.
   - Pre-rendered pages, after BOTH trackers are rebuilt: `python3 civic_reference/legislation_implementation_tracker/pipeline/build_static_snapshots.py` (rewrites the obligations and powers pages and the umbrella hub; staged in step 4).

3. Gold check (repo root): `python3 civic_reference/nyc_council_legislation_trackers/quality/score_gold.py` and note the regressions count. Do not commit gold files.

4. Commit and push to main. Stage explicit paths only, never `git add .` or `-A` on a directory:
   - civic_reference/nyc_council_fiscal_impacts_tracker/data/fiscal_impacts.json, civic_reference/nyc_council_fiscal_impacts_tracker/agency-fiscal-impact/data.json, civic_reference/nyc_council_fiscal_impacts_tracker/overview/index.html, civic_reference/nyc_council_fiscal_impacts_tracker/index.html, civic_reference/nyc_council_legislation_trackers/index.html, pipeline/no_impact_matters.json, pipeline/skip_attachments.json (stage it with `git add -A --`, it may be new)
   - civic_reference/legislation_implementation_tracker/data/{laws,obligations,powers,restated_links,summary,report_filings}.json, civic_reference/legislation_implementation_tracker/pipeline/reextract_queue.json
   - the pre-rendered pages: civic_reference/legislation_implementation_tracker/index.html, civic_reference/legislation_implementation_tracker/agency-workload/index.html, civic_reference/legislation_implementation_tracker/deadline-timeline/index.html, civic_reference/legislation_implementation_tracker/methodology/index.html, civic_reference/legislation_implementation_tracker/obligations-table/index.html, civic_reference/legislation_implementation_tracker/powers-table/index.html, civic_reference/legislation_implementation_tracker/powers/index.html, civic_reference/legislation_implementation_tracker/powers/agency-powers/index.html, civic_reference/nyc_council_legislation_trackers/agencies/index.html, civic_reference/nyc_council_legislation_trackers/council-members/index.html (the hub, civic_reference/nyc_council_legislation_trackers/index.html, is in the fiscal line above)
   - pipeline/max_refresh.json (stage it with `git add -A -- pipeline/max_refresh.json`)
   Commit message: "Monthly refresh on Max: N fiscal, M laws done, K left for the Actions fallback". Then `git -c rebase.autoStash=true pull --rebase origin main && git push`, retrying up to 3 times with a 30-second pause.
   The Actions run later today rebuilds member and agency profiles, alerts and the Ask index from what you commit; do not run those.

5. Report: write it as described under Reporting below (per tracker, documents done and left from pipeline/max_refresh.json, both validator summary lines, the gold regressions count, and the commit SHA; if you committed nothing, say which step stopped you).

Reporting (this section replaces any older instruction to always email a report)
- Write the report to `ops_digest/tracker_refresh_report.md` in this repo, always, even when a step stopped. This repo is public: the file holds counts, validator summary lines, step names and the commit SHA only. No email addresses, no private notes, no names of people.
- The file starts with these header lines, then a blank line, then the body in plain text:
  `Subject: Tracker refresh, <Month YYYY>: <one clause, for example "all steps ran, 0 hard failures" or "stopped at step 2">`
  `needs_tal: <0, or 1 when any email trigger below applies>`
  The body begins with the line `Report date: <YYYY-MM-DD>` (the monthly ops digest on the 5th ignores a report older than 35 days), then one block per tracker: documents done, documents left for the Actions fallback, the validator summary line (`HARD FAILURES: 0` and the fiscal validator's hard-failure count), the gold regressions count, and the commit SHA.
- Write the report AFTER the step 4 commit and push, so it can name that commit's SHA. Then commit the report file alone as a second commit (message "Tracker refresh report <date>") and push it with the same retry. If step 4 committed nothing, the report says which step stopped you and is still committed and pushed this way. Never stage the report in the step 4 commit.
- Email Tal only when something needs him: a validator error (obligations or fiscal hard failures above 0, or a validator that crashed), gold regressions above 0, a step that stopped before finishing, or a failed push. Send ONE plain-text email through the routine's mail connector to the same recipient the stored routine prompt names (that address is not written in this public file), with the subject and layout the stored routine prompt gives (`Tracker refresh, <Month Year>: ACTION NEEDED`), naming the trigger in the first line. If none of these applies, send no email: the monthly ops digest builder (`ops_digest/assemble.py`) reads the report file on the 5th and prints it in the one monthly ops email.
- Division of authority: this section decides WHEN to email and what the report file holds; the routine's stored prompt gives the recipient, the subject and the email layout. They do not conflict.
