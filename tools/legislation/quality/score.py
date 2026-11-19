#!/usr/bin/env python3
"""
Score a structured audit results file (Q/criteria.md "Results format") against
its key.json, and optionally append a row to Q/audit_trend.md.

Usage:
    python3 score.py --tracker obligations --key DIR/key.json --results DIR/results.json
    python3 score.py --tracker fiscal --key DIR/key.json --results DIR/results.json \
        --append-trend "audit4 fiscal round"
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREND_PATH = HERE / "audit_trend.md"

SEED_ROWS = """# Audit trend

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
"""


def wilson_ci(correct: int, total: int, z: float = 1.96) -> tuple[float, float, float]:
    if total == 0:
        return (0.0, 0.0, 0.0)
    p = correct / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    lo = (centre - margin) / denom
    hi = (centre + margin) / denom
    return (p, max(0.0, lo), min(1.0, hi))


def fmt_ci(correct: int, total: int) -> str:
    if total == 0:
        return "n/a"
    p, lo, hi = wilson_ci(correct, total)
    return f"{correct}/{total} = {p:.3f} [{lo:.3f}, {hi:.3f}]"


def score_obligations(key: dict, results: dict) -> dict:
    correct = wrong = missed = 0
    by_criterion: Counter = Counter()
    by_stratum: dict[str, Counter] = defaultdict(Counter)
    for mid, entry in results.items():
        strata = (key.get(mid, {}) or {}).get("strata") or ["unknown"]
        for label, r in (entry.get("records") or {}).items():
            v = r.get("verdict")
            if v == "correct":
                correct += 1
                for s in strata:
                    by_stratum[s]["correct"] += 1
            elif v == "wrong":
                wrong += 1
                for s in strata:
                    by_stratum[s]["wrong"] += 1
                for c in r.get("criteria") or []:
                    by_criterion[str(c)] += 1
        m = entry.get("missed") or []
        missed += len(m)
        for s in strata:
            by_stratum[s]["missed"] += len(m)

    precision = correct / (correct + wrong) if (correct + wrong) else None
    recall = correct / (correct + missed) if (correct + missed) else None
    return {
        "correct": correct, "wrong": wrong, "missed": missed,
        "precision": fmt_ci(correct, correct + wrong),
        "recall": fmt_ci(correct, correct + missed),
        "precision_raw": precision, "recall_raw": recall,
        "errors_by_criterion": dict(by_criterion),
        "by_stratum": {s: dict(c) for s, c in by_stratum.items()},
    }


def score_fiscal(key: dict, results: dict) -> dict:
    correct = wrong = 0
    by_field: Counter = Counter()
    by_stratum: dict[str, Counter] = defaultdict(Counter)
    for mid, r in results.items():
        stratum = (key.get(mid, {}) or {}).get("stratum", "unknown")
        v = (r.get("verdict") or "").lower()
        if v == "correct":
            correct += 1
            by_stratum[stratum]["correct"] += 1
        elif v == "wrong":
            wrong += 1
            by_stratum[stratum]["wrong"] += 1
            for e in r.get("errors") or []:
                by_field[e.get("field", "?")] += 1
    total = correct + wrong
    return {
        "correct": correct, "wrong": wrong, "total": total,
        "share_correct": fmt_ci(correct, total),
        "share_correct_raw": correct / total if total else None,
        "errors_by_field": dict(by_field),
        "by_stratum": {s: dict(c) for s, c in by_stratum.items()},
    }


def append_trend(label: str, tracker: str, summary: dict) -> None:
    if not TREND_PATH.exists():
        TREND_PATH.write_text(SEED_ROWS, encoding="utf-8")
    if tracker == "obligations":
        n = summary["correct"] + summary["wrong"] + summary["missed"]
        prec, rec = summary["precision"], summary["recall"]
        stratum = "+".join(sorted(summary["by_stratum"].keys())) or "-"
    else:
        n = summary["total"]
        prec, rec = summary["share_correct"], "-"
        stratum = "+".join(sorted(summary["by_stratum"].keys())) or "-"
    row = f"| {date.today().isoformat()} | {label} | {tracker} | {stratum} | {n} | {prec} | {rec} | scored by score.py |\n"
    with open(TREND_PATH, "a", encoding="utf-8") as f:
        f.write(row)
    print(f"appended trend row: {row.strip()}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", choices=["obligations", "fiscal"], required=True)
    ap.add_argument("--key", default=None, help="required for obligations (gives stratum); optional for fiscal")
    ap.add_argument("--results", required=True)
    ap.add_argument("--append-trend", metavar="LABEL", default=None)
    args = ap.parse_args()

    if args.key:
        key = json.loads(Path(args.key).read_text())
    elif args.tracker == "obligations":
        raise SystemExit("--key is required for --tracker obligations")
    else:
        key = {}
    results = json.loads(Path(args.results).read_text())

    summary = score_obligations(key, results) if args.tracker == "obligations" else score_fiscal(key, results)
    print(json.dumps(summary, indent=1))
    if args.append_trend:
        append_trend(args.append_trend, args.tracker, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
