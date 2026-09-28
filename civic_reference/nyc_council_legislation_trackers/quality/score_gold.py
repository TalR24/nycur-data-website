#!/usr/bin/env python3
"""
Score the CURRENT tracker data against the gold set: per-field agreement, and
the REGRESSIONS list (gold says X, data now says Y; data record missing; a
gold "missed" item is still missing; a gold "not a real duty" item is still
present). Matches gold entries to current records by matter_id + normalized
quote prefix, falling back to quote_similarity >= 0.85.

    python3 score_gold.py [--strict]   # exit 1 on any regression with --strict
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
LIT = REPO / "civic_reference" / "legislation_implementation_tracker"
FISCAL_TRACKER = REPO / "civic_reference" / "nyc_council_fiscal_impacts_tracker"

sys.path.insert(0, str(LIT / "pipeline"))
from extract_obligations import normalize_quote, quote_similarity  # noqa: E402

GOLD_OBL = HERE / "gold_obligations.json"
GOLD_FIS = HERE / "gold_fiscal.json"
OUT_JSON = HERE / "gold_score.json"

# gold entries use the packet's human field names (criteria.md / audit_lib.py);
# obligations.json's own field for "reprint of existing code" is quotes_restated_text.
FIELD_ALIAS = {"existing_code": "restated"}  # the field the site shows (Sep 28 2026)


def load(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def find_match(gold_quote: str, records_for_law: list[dict]) -> dict | None:
    """matter_id + normalized quote prefix, falling back to quote_similarity >= 0.85."""
    gq = normalize_quote(gold_quote or "")
    if not gq:
        return None
    best, best_sim = None, 0.0
    for r in records_for_law:
        rq = normalize_quote(r.get("quote") or "")
        if rq.startswith(gq[:200]) or gq.startswith(rq[:200]):
            return r
        sim = quote_similarity(gold_quote, r.get("quote") or "")
        if sim > best_sim:
            best, best_sim = r, sim
    return best if best_sim >= 0.85 else None


def score_obligations() -> dict:
    gold = load(GOLD_OBL, [])
    obl = load(LIT / "data" / "obligations.json", {}).get("obligations", [])
    powers = load(LIT / "data" / "powers.json", {}).get("powers", [])
    by_law: dict[str, list[dict]] = {}
    for r in obl + powers:
        by_law.setdefault(str(r["matter_id"]), []).append(r)

    field_agree: dict[str, int] = {}
    field_total: dict[str, int] = {}
    regressions: list[dict] = []
    unmatched: list[dict] = []

    for g in gold:
        mid = str(g.get("matter_id"))
        records_for_law = by_law.get(mid, [])
        verdict = g.get("verdict")

        if verdict == "missed":
            match = find_match(g.get("quote", ""), records_for_law)
            if match is not None:
                regressions.append({
                    "type": "gold_missed_item_now_present",
                    "matter_id": mid, "quote": g.get("quote", ""), "note": g.get("note", ""),
                })
            continue

        if verdict == "not_a_real_duty":
            match = find_match(g.get("quote", ""), records_for_law)
            if match is not None:
                regressions.append({
                    "type": "gold_not_a_real_duty_still_present",
                    "matter_id": mid, "quote": g.get("quote", ""), "note": g.get("note", ""),
                })
            continue

        match = find_match(g.get("quote", ""), records_for_law)
        if match is None:
            unmatched.append(g)
            if verdict == "correct":
                regressions.append({
                    "type": "gold_correct_record_missing",
                    "matter_id": mid, "quote": g.get("quote", ""),
                })
            continue

        for field, expected in (g.get("fields_expected") or {}).items():
            actual = match.get(FIELD_ALIAS.get(field, field))
            if field == "existing_code":
                actual = bool(actual)          # an absent flag means new matter
            field_total[field] = field_total.get(field, 0) + 1
            if isinstance(expected, dict) and "not" in expected:
                ok = actual != expected["not"]
            else:
                ok = actual == expected
            if ok:
                field_agree[field] = field_agree.get(field, 0) + 1
            else:
                if verdict == "correct" and not ok:
                    regressions.append({
                        "type": "field_regressed",
                        "matter_id": mid, "field": field,
                        "gold_value": expected, "current_value": actual,
                        "obligation_id": match.get("obligation_id"),
                    })
                elif verdict == "wrong" and isinstance(expected, dict) and "not" in expected and actual == expected["not"]:
                    regressions.append({
                        "type": "known_wrong_value_still_present",
                        "matter_id": mid, "field": field, "value": actual,
                        "obligation_id": match.get("obligation_id"),
                    })

    return {
        "gold_entries": len(gold),
        "unmatched": len(unmatched),
        "unmatched_examples": unmatched[:15],
        "field_agreement": {
            f: {"agree": field_agree.get(f, 0), "total": field_total[f],
                "rate": round(field_agree.get(f, 0) / field_total[f], 3)}
            for f in field_total
        },
        "regressions": regressions,
    }


def score_fiscal() -> dict:
    gold = load(GOLD_FIS, [])
    records = load(FISCAL_TRACKER / "data" / "fiscal_impacts.json", {}).get("records", [])
    by_id = {str(r["matter_id"]): r for r in records}

    field_agree: dict[str, int] = {}
    field_total: dict[str, int] = {}
    regressions: list[dict] = []
    unmatched: list[dict] = []

    for g in gold:
        mid = str(g.get("matter_id"))
        current = by_id.get(mid)
        if current is None:
            unmatched.append(g)
            if g.get("verdict") == "correct":
                regressions.append({"type": "gold_bill_missing", "matter_id": mid})
            continue
        for field, expected in (g.get("fields_expected") or {}).items():
            actual = current.get(field)
            field_total[field] = field_total.get(field, 0) + 1
            ok = actual == expected
            if ok:
                field_agree[field] = field_agree.get(field, 0) + 1
            else:
                regressions.append({
                    "type": "fiscal_field_regressed" if g.get("verdict") == "correct" else "fiscal_field_still_wrong",
                    "matter_id": mid, "field": field, "gold_value": expected, "current_value": actual,
                })

    return {
        "gold_entries": len(gold),
        "unmatched": len(unmatched),
        "unmatched_examples": unmatched[:15],
        "field_agreement": {
            f: {"agree": field_agree.get(f, 0), "total": field_total[f],
                "rate": round(field_agree.get(f, 0) / field_total[f], 3)}
            for f in field_total
        },
        "regressions": regressions,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    obl_result = score_obligations()
    fis_result = score_fiscal()
    result = {"obligations_powers": obl_result, "fiscal": fis_result}
    OUT_JSON.write_text(json.dumps(result, indent=1, ensure_ascii=False))

    print(f"OBLIGATIONS/POWERS gold: {obl_result['gold_entries']} entries, {obl_result['unmatched']} unmatched")
    print("field agreement:")
    for f, v in sorted(obl_result["field_agreement"].items()):
        print(f"  {f:20s} {v['agree']}/{v['total']} = {v['rate']}")
    print(f"regressions: {len(obl_result['regressions'])}")
    for r in obl_result["regressions"][:15]:
        print(f"  {r}")

    print(f"\nFISCAL gold: {fis_result['gold_entries']} entries, {fis_result['unmatched']} unmatched")
    print("field agreement:")
    for f, v in sorted(fis_result["field_agreement"].items()):
        print(f"  {f:20s} {v['agree']}/{v['total']} = {v['rate']}")
    print(f"regressions: {len(fis_result['regressions'])}")
    for r in fis_result["regressions"][:15]:
        print(f"  {r}")

    n_regressions = len(obl_result["regressions"]) + len(fis_result["regressions"])
    if args.strict and n_regressions:
        sys.exit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
