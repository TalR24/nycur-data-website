# Monthly ops digest

`assemble.py` builds the ONE monthly ops email (5th of the month, `.github/workflows/monthly_ops_digest.yml`, 15:00 UTC) from sections waiting in the private premium repo's `ops_digest/pending/`.

## Sections

| Source | Written by | Format |
|---|---|---|
| `seo` | `seo_monthly.yml` (`seo/gsc_pull.py --ops-pending`) | `.html` `.txt` `.json` |
| `trackers_quality` | `monthly_quality_report.yml` (`email_quality_summary.py`) | `.html` `.txt` `.json` |
| `block_party_quality` | resolution_engine `monthly-quality-report.yml` (needs repo secret `PREMIUM_PUSH_TOKEN`; until Tal adds it the section shows under "Did not report", and the repo has no GMAIL secrets either, so the Block Party cloud routine's delta summary is the only Block Party email) | `.html` `.txt` `.json` |
| `fiscal_drafts`, `copy_currency`, `brand_qa` | cloud routines | `.md` |
| `trackers_refresh` | the monthly tracker refresh routine, committed to THIS public repo as `ops_digest/tracker_refresh_report.md` (counts and validator lines only; header `Subject:`, `needs_tal:`, body line `Report date: YYYY-MM-DD`; ignored when older than 35 days). Never moved or filed. The routine emails Tal itself only on a problem | `.md` |

Action sections come with a `.json`: `{source, title, generated_at, needs_tal}`. Routine `.md` files start with `Subject: <subject line>` and `needs_tal: <integer>`, then a blank line and the plain-text body (CAPS headings, numbered TO DO items, prompts between lines of dashes, rendered in `<pre>` blocks).

The email opens with Needs you (sum of `needs_tal`), Did not report (expected sources with no file), and Failed Action runs since the last digest (data-website with `GITHUB_TOKEN`; premium, talroded_personal and resolution_engine with `PREMIUM_PUSH_TOKEN`, or "not checked" when the token cannot read the repo; `pages-build-deployment` excluded). Sections follow in the order above. After a successful send the files move to `ops_digest/sent/YYYY-MM/`, the exact assembled body is saved as `planning/sent/<date>_monthly_ops_digest.md`, one line per ask (numbered TO DO items, SEO action headings, or the section title) is added to `planning/inbox/asks_<YYYY-MM>.md` in TODO_tal.md format for the Sunday routine, and premium is pushed in one commit.

## Delivery switch

Producers read `DIGEST_DELIVERY` (`file` in their workflows, `email` when unset). In `file` mode a failed premium write or push falls back to the old direct email. Set it to `email` in a workflow to restore the old behavior.

## Commands

```
python3 ops_digest/assemble.py --premium /tmp/premium --dry-run          # print, send nothing, move nothing
python3 ops_digest/assemble.py --premium /tmp/premium --dry-run --no-runs --extras-dir /tmp/x   # also write the archive and asks files under /tmp/x
python3 ops_digest/assemble.py --send-files --subject S --txt a.txt --html a.html   # fallback email of existing files
```

Stdlib only. No Anthropic API. The SCE monthly email (`sce_monthly.yml`) is separate.
