# Audit trend

Comparable, cumulative scoring of every audit round. Columns: date, round, tracker, stratum, n,
precision [95% CI], recall [95% CI], note. "n" is records checked (obligations/powers) or bills
checked (fiscal). Precision/recall use the Wilson interval (score.py). Seed rows below predate the
structured-results harness and are not re-scored; everything after is produced by
`score.py --append-trend`.

| date | round | tracker | stratum | n | precision [CI] | recall [CI] | note |
|---|---|---|---|---|---|---|---|
| 2026-09-23 | haiku data (round 1) | obligations | sonnet+protected | 52 | 28/52 = 0.538 | - | prose results, not re-scored |
| 2026-09-26 | pilot-2 blind A/B, Sonnet side | obligations | pilot | 262 | 224/242 = 0.926 | 224/244 = 0.918 | prose results, not re-scored; correct+wrong=242, correct+missed=244 |
| 2026-09-26 | pilot-2 blind A/B, committed (Haiku) side | obligations | committed | 249 | 146/183 = 0.798 | 146/212 = 0.689 | prose results, not re-scored; Haiku records replaced Sep 26, skip for gold |
| 2026-09-27 | spot audit (15 laws) | obligations | sonnet | 75 | 67/73 = 0.918 | 67/69 = 0.971 | prose results, not re-scored; raw sums from spot_audit_results.json (67 correct, 6 wrong, 2 missed) |
| 2026-09-27 | audit4 Sonnet sample | obligations | sonnet | 72 | 50/67 = 0.746 | 50/55 = 0.909 | prose results, not re-scored; raw sums from audit4/results_sonnet.json (50 correct, 17 wrong, 5 missed) |
| 2026-09-27 | audit4 protected sample | obligations | protected | 104 | 52/72 = 0.722 | 52/84 = 0.619 | prose results, not re-scored; raw sums from audit4/results_protected.json (52 correct, 20 wrong, 32 missed) |
| 2026-09-23 | round 1 | fiscal | - | 16 | 3/16 = 0.188 | - | prose results, not re-scored |
| 2026-09-24 | round 4 | fiscal | - | 20 | 12/20 = 0.600 | - | prose results, not re-scored |
| 2026-09-24 | round 5 | fiscal | - | 20 | 16/20 = 0.800 | - | prose results, not re-scored |
| 2026-09-24 | round 6 | fiscal | - | 24 | 18/24 = 0.750 | - | prose results, not re-scored |
| 2026-09-27 | audit4 fiscal | fiscal | - | 14 | 8/14 = 0.571 | - | prose results, not re-scored |
| 2026-09-23/26/27 | duty/power label agreement rounds 1-4 | obligations | kind label | 80-90 | 67/80, 76/90, 78/90, 78/90 | - | prose results, not re-scored; model label 86/90 |

Note: `seed_gold_from_past.py`'s re-score of the audit4 Sonnet sample (`_seeded/audit4_sonnet/`,
run through `score.py`) counts 30 correct, not 50. Its per-matter "correct" count in
results_sonnet.json has no R-labels, so the script infers the correct set as "every record minus
the ones named in wrong_detail"; for 20 of the 50 stated-correct records that inference could not
be made to match the stated count (7 of the round's ~54 matters), and those records were written
to gold_unparsed.json instead of the gold set. wrong (17) and missed (5) matched exactly. The row
above is the raw, unscored total from the source file, per this rework's instruction.
| 2026-09-27 | audit 5 Sonnet laws (Sep 28) | obligations | recent+sonnet | 118 | 86/111 = 0.775 [0.689, 0.843] | 86/93 = 0.925 [0.853, 0.963] | scored by score.py |
| 2026-09-27 | audit 5 fiscal, verifier-passed bills (Sep 28) | fiscal | plain+tricky | 20 | 16/20 = 0.800 [0.584, 0.919] | - | scored by score.py |
| 2026-09-27 | audit 6 Sonnet laws (Sep 28, after audit-5 rules) | obligations | recent+sonnet | 198 | 176/192 = 0.917 [0.869, 0.948] | 176/182 = 0.967 [0.930, 0.985] | scored by score.py |
| 2026-09-27 | audit 6 protected laws (20 reconciled + 16 hand-fixed) | obligations | protected+recent | 219 | 145/191 = 0.759 [0.694, 0.814] | 145/173 = 0.838 [0.776, 0.886] | scored by score.py |
| 2026-09-27 | audit 6 fiscal (Sep 28) | fiscal | plain+tricky | 18 | 15/18 = 0.833 [0.608, 0.942] | - | scored by score.py |
| 2026-09-28 | audit 7 Sonnet laws (Sep 28) | obligations | recent+sonnet | 137 | 111/132 = 0.841 [0.769, 0.894] | 111/116 = 0.957 [0.903, 0.981] | scored by score.py |
| 2026-09-28 | audit 7 fiscal (Sep 28) | fiscal | plain+tricky | 19 | 17/19 = 0.895 [0.686, 0.971] | - | scored by score.py |
| 2026-09-28 | audit 7 protected laws, all reconciled (Sep 28) | obligations | protected | 286 | 222/264 = 0.841 [0.792, 0.880] | 222/244 = 0.910 [0.867, 0.940] | scored by score.py |
