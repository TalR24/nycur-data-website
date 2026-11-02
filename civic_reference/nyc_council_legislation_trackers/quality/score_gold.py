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
import re
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
FIELD_ALIAS = {
    "existing_code": "restated",      # the field the site shows (Sep 28 2026)
    # auditors' names for fields the data stores under another name; without
    # these the agreement rows for them read 0/N and measure nothing (Nov 2 2026)
    "deadline_type": "deadline_kind",
    "unit": "agency_unit",
    "due_date": "deadline_date",
}
RECORD_OVERRIDES = LIT / "pipeline" / "record_overrides.json"


def get_path(rec: dict, field: str):
    """Read a gold field from a record. Fiscal gold names nested values by path
    ("fiscal_table_columns[0].expenditure", and "a / b" for a pair, returned as
    a list); a literal .get() of such a name is always None (Nov 2 2026: the
    8033442 "regression" was the data already matching gold)."""
    parts = [x.strip() for x in field.split(" / ")]
    if len(parts) > 1:
        head = re.match(r"^(.*\.)[^.]+$", parts[0])
        prefix = head.group(1) if head else ""
        return [get_path(rec, p if ("." in p or "[" in p) else prefix + p) for p in parts]
    cur = rec
    for tok in re.findall(r"[^.\[\]]+|\[\d+\]", field):
        if tok.startswith("["):
            i = int(tok[1:-1])
            cur = cur[i] if isinstance(cur, list) and i < len(cur) else None
        else:
            cur = cur.get(tok) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def override_source(matter_id: str, quote: str, overrides: dict) -> str | None:
    """The record_overrides.json entry (set/remove/add) that touches this quote,
    if any: a gold disagreement caused by a later judge's override is a
    conflict between two verdicts to tiebreak, not pipeline drift."""
    q = normalize_quote(quote or "")
    for action in ("set", "remove", "add"):
        for e in overrides.get(str(matter_id), {}).get(action, []):
            pre = normalize_quote(e.get("quote_prefix") or e.get("quote") or "")[:80]
            if pre and (q.startswith(pre) or pre in q):
                return f"{action}: {e.get('source', '?')}"
    return None


def load(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def override_gold_conflicts(overrides: dict | None = None, gold: list | None = None) -> list[dict]:
    """Every record_overrides.json `set`/`remove` entry that contradicts a gold
    entry the audits marked `correct`: a `remove` of a gold-correct record, or a
    `set` of a field to a value other than the gold one. Two blind verdicts that
    disagree need the gold tiebreak; nothing caught these before Nov 2 2026,
    when 98 of the 155 gold regressions traced to such entries."""
    overrides = overrides if overrides is not None else load(RECORD_OVERRIDES, {})
    gold = gold if gold is not None else load(GOLD_OBL, [])
    out = []
    for g in gold:
        if g.get("verdict") != "correct":
            continue
        mid = str(g.get("matter_id"))
        gq = normalize_quote(g.get("quote") or "")
        exp = g.get("fields_expected") or {}
        ov = overrides.get(mid) or {}
        for action in ("set", "remove"):
            for e in ov.get(action, []):
                pre = normalize_quote(e.get("quote_prefix") or "")[:80]
                if not pre or not (gq.startswith(pre) or pre.startswith(gq[:80])):
                    continue
                if exp.get("agency") and e.get("agency") and e["agency"] != exp["agency"]:
                    continue          # the entry targets another agency's copy
                if action == "remove":
                    out.append({"matter_id": mid, "action": "remove", "quote": g.get("quote"),
                                "gold_source": g.get("source"), "override_source": e.get("source")})
                    continue
                for f, v in (e.get("fields") or {}).items():
                    if f in exp and not isinstance(exp[f], dict) and exp[f] != v:
                        out.append({"matter_id": mid, "action": "set", "field": f,
                                    "gold_value": exp[f], "override_value": v,
                                    "quote": g.get("quote"), "gold_source": g.get("source"),
                                    "override_source": e.get("source")})
    return out


def find_match(gold_quote: str, records_for_law: list[dict],
               agency: str | None = None) -> dict | None:
    """matter_id + normalized quote prefix, falling back to quote_similarity >= 0.85.
    A joint duty is stored once per agency with the same quote, so when several
    records share the prefix, take the one with the gold entry's agency."""
    gq = normalize_quote(gold_quote or "")
    if not gq:
        return None
    best, best_sim = None, 0.0
    prefix_hits = []
    for r in records_for_law:
        rq = normalize_quote(r.get("quote") or "")
        if rq.startswith(gq[:200]) or gq.startswith(rq[:200]):
            prefix_hits.append(r)
    if prefix_hits:
        return next((r for r in prefix_hits if agency and r.get("agency") == agency),
                    prefix_hits[0])
    for r in records_for_law:
        sim = quote_similarity(gold_quote, r.get("quote") or "")
        if sim > best_sim:
            best, best_sim = r, sim
    return best if best_sim >= 0.85 else None


def score_obligations() -> dict:
    gold = load(GOLD_OBL, [])
    obl = load(LIT / "data" / "obligations.json", {}).get("obligations", [])
    powers = load(LIT / "data" / "powers.json", {}).get("powers", [])
    overrides = load(RECORD_OVERRIDES, {})
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
            # an audited miss is fixed once the data holds it (the Sep 27 2026
            # version counted the fix as a regression and ignored real misses)
            match = find_match(g.get("quote", ""), records_for_law)
            if match is None:
                regressions.append({
                    "type": "gold_missed_item_still_missing",
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

        exp_agency = (g.get("fields_expected") or {}).get("agency")
        match = find_match(g.get("quote", ""), records_for_law,
                           exp_agency if isinstance(exp_agency, str) else None)
        if match is None:
            unmatched.append(g)
            if verdict == "correct":
                regressions.append({
                    "type": "gold_correct_record_missing",
                    "matter_id": mid, "quote": g.get("quote", ""),
                    "override": override_source(mid, g.get("quote", ""), overrides),
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
                        "override": override_source(mid, match.get("quote", ""), overrides),
                        "restated_source": match.get("restated_source") if field == "existing_code" else None,
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
            actual = get_path(current, field)
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
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any open disagreement with gold")
    ap.add_argument("--strict-new", action="store_true",
                    help="exit 1 only on regressions absent from the previous gold_score.json "
                         "(the check for a refresh: the open backlog is not news)")
    args = ap.parse_args()

    def rkey(r):
        return json.dumps({k: r.get(k) for k in ("type", "matter_id", "field", "quote",
                                                 "gold_value", "obligation_id")},
                          sort_keys=True, ensure_ascii=False)
    prev = load(OUT_JSON, {})
    prev_keys = {rkey(r) for part in ("obligations_powers", "fiscal")
                 for r in prev.get(part, {}).get("regressions", [])}

    obl_result = score_obligations()
    fis_result = score_fiscal()
    result = {"obligations_powers": obl_result, "fiscal": fis_result}
    all_regs = obl_result["regressions"] + fis_result["regressions"]
    new_regs = [r for r in all_regs if rkey(r) not in prev_keys]
    cur_keys = {rkey(r) for r in all_regs}
    result["vs_previous_score"] = {"new": new_regs,
                                   "resolved": len(prev_keys - cur_keys)}
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

    by_cause: dict[str, int] = {}
    for r in obl_result["regressions"]:
        cause = ("later judge override" if r.get("override") or r.get("restated_source") == "verdict"
                 else "pipeline/rule value")
        by_cause[cause] = by_cause.get(cause, 0) + 1
    conflicts = override_gold_conflicts()
    result["override_gold_conflicts"] = conflicts
    OUT_JSON.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(f"\nobligation disagreements by cause: {by_cause}")
    print(f"record_overrides entries contradicting a gold-correct entry: {len(conflicts)} "
          f"(judge each blind, then keep one side: override or gold)")
    print(f"vs previous gold_score.json: {len(new_regs)} new, "
          f"{result['vs_previous_score']['resolved']} resolved")
    for r in new_regs[:15]:
        print(f"  NEW {r}")

    if args.strict and all_regs:
        sys.exit(1)
    if args.strict_new and new_regs:
        sys.exit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
