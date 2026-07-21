# Cross-Validation Report: laws.json vs jehiah/nyc_legislation — July 2026

Validated `data/laws.json` (2,128 enacted laws, generated 2026-07-19) against the
jehiah/nyc_legislation archive (API-sourced mirror behind intro.nyc), sparse-cloned
2026-07-21, `introduction/$year/$number.json` (filenames zero-padded to 4 digits).

## Coverage

| Slice | Laws | Matched to archive file | Unmatched |
|---|---|---|---|
| Intro year 2018+ | 1,414 | 1,414 | 0 |
| Intro year pre-2018 (bonus: archive reaches back to 1996) | 714 | 714 | 0 |
| **Total** | **2,128** | **2,128 (100%)** | **0** |

Names normalized on both sides before comparison: NFKD accent-strip, periods and
commas removed, case-folded, whitespace collapsed.

## Discrepancies by field and class (full corpus, pre-fix counts)

| Field | (a) Our scrape wrong | (b) Archive missing/stale | (c) Cosmetic |
|---|---|---|---|
| enactment_date | 1 (Int 1933-2020, blank) | 3 (Dec 2025 laws stuck at `0001-01-01`) | 0 |
| law_number | 0 | 4 (`LocalLaw` null: Int 1075/1049/1004-2024, Int 0799-2015) | 0 |
| committee | 0 | 0 | 0 — all 2,128 exact matches vs `BodyName` |
| sponsor list | 43 laws (", Jr." fragment split) | 206 laws with empty-string sponsor entries + 5 laws with `Sponsors: []` entirely (Int 1075/1049/1004/1123/0984-2024) | 305 laws, name-format only |
| prime_sponsor | 6 ("Rafael Salamanca" missing ", Jr.") | 0 | 21 (middle-initial variants) |
| sponsor order | 0 (identical wherever sets match) | — | — |

### Class (a) — our data was wrong (fixed)

1. **Unmerged ", Jr." suffix fragments — 43 laws.** Legistar renders the sponsor
   line comma-separated, so "Rafael Salamanca, Jr." splits into two entries
   ("Rafael Salamanca" + "Jr."). The parser's re-merge fix exists in
   `parse_detail_page`, but these 43 records were scraped before that fix and
   `--incremental` reused them verbatim ever since. Side effects fixed with them:
   `sponsor_count` inflated by 1 on each, and `prime_sponsor` = "Rafael Salamanca"
   (missing ", Jr.") on the 6 laws where Salamanca was prime sponsor.
   Live-verified against Legistar (Int 0857-2024 sponsor line begins
   "Rafael Salamanca, Jr., Selvena N. Brooks-Powers, …"). Only "Jr." occurred;
   no "Sr."/"II"/"III"/"IV" fragments found.
2. **Int 1933-2020 (LL 55 of 2021) blank `enactment_date`.** Legistar's own
   Enactment date field is empty on the live page (verified 2026-07-21), so the
   scrape was faithful, but the value is knowable: the archive's History shows
   "Signed Into Law by Mayor" on 2021-05-13. Filled as `2021-05-13`.

### Class (b) — archive missing/stale (no action; our data live-verified where it disagreed)

- Int 1075-2024, Int 1049-2024, Int 1004-2024 (LL 197/196/194 of 2025, signed
  2025-12-25): archive files predate enactment — `LocalLaw` null,
  `EnactmentDate` `0001-01-01`, `Sponsors` empty. Live Legistar check of
  Int 1075-2024 confirms our values (Enactment date 12/25/2025, Local Law 2025/197).
- Int 1123-2024 and Int 0984-2024: archive `Sponsors` empty; ours populated.
- Int 0799-2015 (LL 254 of 2017, commercial rent tax): archive `LocalLaw` null
  even though its own `EnactmentDate` (2017-12-22) and Status (Enacted) match ours.
- 206 laws where the archive sponsor array carries 1–3 trailing empty-string
  `FullName` entries (API artifact; our parser correctly drops empties).

### Class (c) — cosmetic (no action)

305 laws differ only in name formatting: our scrape reflects Legistar's current
display names ("Tiffany L. Cabán", "Amanda C. Farías", "Oswald J. Feliz"), the
archive holds older API name strings without middle initials ("Tiffany Cabán",
"Amanda Farías", "Oswald Feliz"). Same on 21 prime_sponsor rows. After stripping
middle initials and accents, every one of these resolves to identical sponsor sets;
zero residual unexplained sponsor diffs across the whole corpus.

## Fixes applied to data/laws.json

- Merged ", Jr." fragments in `sponsors` for 43 laws; recomputed `sponsor_count`
  (−1 each) and `prime_sponsor` (6 laws now "Rafael Salamanca, Jr."):
  Int 0003/0025/0087/0353/0360/0429/0431/0468/0532/0736/0762/0850/0857/0867/0910/0925/0968/0991/0994/0998/1075/1120/1132/1153-2024,
  Int 0946/1057/1058/1059/1101/1118/1131/1161/1278-2023, Int 0198-2022,
  Int 1169/1216/1290/1297/1338/1391/1412/1425/1501-2025.
- Int 1933-2020: `enactment_date` `""` → `"2021-05-13"` (source: archive History
  action "Signed Into Law by Mayor"; Legistar's field is blank).
- Re-applied the pipeline's sort invariant (enactment_date desc, then file_number)
  and rewrote with the pipeline's exact serialization (`json.dumps(..., indent=1)`,
  ensure_ascii, no trailing newline). `count` unchanged at 2,128.

Post-fix re-validation: zero class (a) discrepancies remain on any field.

## Parser changes (pipeline/fetch_enacted_laws.py)

- Extracted the suffix re-merge into `_merge_name_suffixes()` (was inline in
  `parse_detail_page`).
- Added `_normalize_record()` and applied it to records loaded from prior
  `laws.json` and from `cache/laws/*.json` under `--incremental`, so stale
  pre-fix records are repaired on every run instead of persisting forever.
  This was the mechanism that kept the 43 bad records alive.
- `python3 -m py_compile` passes.

## Archive fields we don't capture that could be valuable

- `Sponsors[].ID` and `Slug` — stable member identifiers; would make member-page
  and roster joins robust against name-format drift (the entire class (c) noise).
- `History[]` — full action timeline (introduced, hearings, amended, vetoed,
  overridden, signed) with dates and bodies; also the reliable fallback for blank
  Legistar enactment dates (how Int 1933-2020 was resolved).
- `IntroDate` / `PassedDate` — would let the tracker show time-to-passage.
- `Version` (A, B, …) — how many times a bill was amended before enactment.
- `Attachments[]` — direct links to committee reports, hearing transcripts,
  fiscal impact statements, and plain-language summaries.
- `Name` — short human-readable topic label (vs. our long legal `title`).
- `LastModified` — staleness detection for incremental refreshes.

Caveat for future runs: for laws enacted within the last few weeks, prefer our
live scrape over the archive (its mirror lags, per the class (b) cases above).
