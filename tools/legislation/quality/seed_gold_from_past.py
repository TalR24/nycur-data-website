#!/usr/bin/env python3
"""
One-off backfill: parse the pre-harness audit material (audit4, spot_audit,
ab2_audit) into the gold set (Q/gold_obligations.json, Q/gold_fiscal.json),
with anything unparseable written to Q/gold_unparsed.json for a count.

Also writes, per past round, a structured key.json + results.json under
Q/_seeded/<round>/ so score.py can be run against them to check the harness
reproduces the trend-seed numbers (verify step b).

Read-only against the past-audit source material; only writes inside Q/.

Usage: python3 seed_gold_from_past.py [--audit4-dir DIR] [--report]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from audit_lib import parse_packet_records, parse_wrong_detail, field_for_criterion, gold_key_obl  # noqa: E402

DEFAULT_TMP = Path("/Users/troded/.claude/jobs/bcbcad1f/tmp")
GOLD_OBL = HERE / "gold_obligations.json"
GOLD_FIS = HERE / "gold_fiscal.json"
GOLD_UNPARSED = HERE / "gold_unparsed.json"
SEEDED_DIR = HERE / "_seeded"

TODAY = "2026-09-27"


def load(p: Path, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def load_existing_gold() -> tuple[list, list, list]:
    return load(GOLD_OBL, []), load(GOLD_FIS, []), load(GOLD_UNPARSED, [])


def add_gold_obl(gold: list, seen: set, entry: dict) -> None:
    k = gold_key_obl(entry)
    if k in seen:
        return
    seen.add(k)
    gold.append(entry)


def gold_key_fis(g: dict) -> tuple:
    return (g["matter_id"], tuple(sorted(g.get("fields_expected", {}).keys())))


def add_gold_fis(gold: list, seen: set, entry: dict) -> None:
    k = gold_key_fis(entry)
    if k in seen:
        return
    seen.add(k)
    gold.append(entry)


def snapshot_fields(rec: dict, fields: list[str]) -> dict:
    return {f: rec.get(f) for f in fields if f in rec}


def process_obl_round(name: str, packet_dir: Path, results_path: Path, source: str,
                       gold: list, seen: set, unparsed: list, counts: dict,
                       structured_key: dict, structured_results: dict) -> None:
    results = load(results_path, {})
    if isinstance(results, dict) and "protected" in results:
        results = results["protected"]
    for mid, entry in results.items():
        packet_path = packet_dir / f"{mid}.txt"
        if not packet_path.exists():
            unparsed.append({"source": source, "matter_id": mid, "reason": "no packet", "raw": entry})
            counts["unparsed"] += 1
            continue
        records = parse_packet_records(packet_path.read_text(errors="ignore"))
        structured_key[mid] = {"records": {lbl: {"matter_id": mid, "snapshot": rec} for lbl, rec in records.items()}}

        s_records: dict[str, dict] = {}
        s_missed: list[dict] = []

        if isinstance(entry.get("correct"), list):
            # results_protected.json style: correct=[R1,...], wrong=[{record,criterion,note}]
            for lbl in entry.get("correct", []):
                s_records[lbl] = {"verdict": "correct"}
                if lbl in records:
                    add_gold_obl(gold, seen, {
                        "matter_id": mid, "quote": (records[lbl].get("quote") or "")[:200],
                        "kind_expected": records[lbl].get("kind"),
                        "fields_expected": snapshot_fields(records[lbl], ["agency", "deadline_kind", "deadline_date", "recurrence", "existing_code"]),
                        "verdict": "correct", "source": source, "date": TODAY,
                    })
                    counts["gold_correct"] += 1
            for w in entry.get("wrong", []):
                lbl, crit = w.get("record"), [str(w.get("criterion"))] if w.get("criterion") else []
                note = w.get("note", "")
                s_records[lbl] = {"verdict": "wrong", "criteria": crit, "note": note}
                field = field_for_criterion(crit)
                rec = records.get(lbl, {})
                fields_expected = {field: {"not": rec.get(field)}} if field and field in rec else {}
                add_gold_obl(gold, seen, {
                    "matter_id": mid, "quote": (rec.get("quote") or "")[:200],
                    "kind_expected": rec.get("kind"),
                    "fields_expected": fields_expected, "criteria": crit, "note": note,
                    "verdict": "wrong", "source": source, "date": TODAY,
                })
                counts["gold_wrong"] += 1
            for m in entry.get("missed", []):
                if isinstance(m, str):
                    s_missed.append({"note": m})
                    add_gold_obl(gold, seen, {
                        "matter_id": mid, "quote": m[:200], "kind_expected": None,
                        "fields_expected": {}, "verdict": "missed", "note": m,
                        "source": source, "date": TODAY,
                    })
                    counts["gold_missed"] += 1
        else:
            # results_sonnet.json / spot_audit_results.json style: counts + wrong_detail/missed_detail
            n_correct, n_wrong, n_missed = entry.get("correct", 0), entry.get("wrong", 0), entry.get("missed", 0)
            wrong_labels = set()
            for wd in entry.get("wrong_detail", []):
                lbl, crit, note = parse_wrong_detail(wd)
                if lbl is None:
                    unparsed.append({"source": source, "matter_id": mid, "reason": "no R-label in wrong_detail", "raw": wd})
                    counts["unparsed"] += 1
                    continue
                wrong_labels.add(lbl)
                s_records[lbl] = {"verdict": "wrong", "criteria": crit, "note": note}
                field = field_for_criterion(crit)
                rec = records.get(lbl, {})
                fields_expected = {field: {"not": rec.get(field)}} if field and field in rec else {}
                add_gold_obl(gold, seen, {
                    "matter_id": mid, "quote": (rec.get("quote") or "")[:200],
                    "kind_expected": rec.get("kind"), "fields_expected": fields_expected,
                    "criteria": crit, "note": note, "verdict": "wrong",
                    "source": source, "date": TODAY,
                })
                counts["gold_wrong"] += 1
            if n_correct == len(records) - len(wrong_labels):
                for lbl, rec in records.items():
                    if lbl not in wrong_labels:
                        s_records[lbl] = {"verdict": "correct"}
                        add_gold_obl(gold, seen, {
                            "matter_id": mid, "quote": (rec.get("quote") or "")[:200],
                            "kind_expected": rec.get("kind"),
                            "fields_expected": snapshot_fields(rec, ["agency", "deadline_kind", "deadline_date", "recurrence", "existing_code"]),
                            "verdict": "correct", "source": source, "date": TODAY,
                        })
                        counts["gold_correct"] += 1
            else:
                unparsed.append({"source": source, "matter_id": mid,
                                  "reason": f"correct count {n_correct} != records-wrong ({len(records)}-{len(wrong_labels)})",
                                  "raw": entry})
                counts["unparsed"] += 1
            for md in entry.get("missed_detail", []):
                s_missed.append({"note": md})
                add_gold_obl(gold, seen, {
                    "matter_id": mid, "quote": md[:200], "kind_expected": None,
                    "fields_expected": {}, "verdict": "missed", "note": md,
                    "source": source, "date": TODAY,
                })
                counts["gold_missed"] += 1
            if len(s_records) != n_correct + n_wrong or len(s_missed) != n_missed:
                counts["count_mismatch"] = counts.get("count_mismatch", 0) + 1

        structured_results[mid] = {"records": s_records, "missed": s_missed}


def process_ab2(ab2_dir: Path, results_paths: list[Path], key_path: Path,
                 gold: list, seen: set, unparsed: list, counts: dict,
                 structured_key: dict, structured_results: dict) -> None:
    ab2_key = load(key_path, {}).get("key", {})
    for results_path in results_paths:
        results = load(results_path, {})
        for mid, sides in results.items():
            packet_path = ab2_dir / f"{mid}.txt"
            if not packet_path.exists():
                unparsed.append({"source": "ab2_audit", "matter_id": mid, "reason": "no packet", "raw": sides})
                counts["unparsed"] += 1
                continue
            records = parse_packet_records(packet_path.read_text(errors="ignore"))
            side_map = ab2_key.get(mid, {})
            for side_label, entry in sides.items():
                if side_label not in ("A", "B") or not isinstance(entry, dict):
                    continue
                if side_map.get(side_label) != "pilot":
                    continue  # skip the committed (Haiku) side: those records were replaced
                n_correct, n_wrong = entry.get("correct", 0), entry.get("wrong", 0)
                wrong_labels = set()
                for wd in entry.get("wrong_detail", []):
                    lbl, crit, note = parse_wrong_detail(wd)
                    if lbl is None:
                        unparsed.append({"source": "ab2_audit", "matter_id": mid, "reason": "no label", "raw": wd})
                        counts["unparsed"] += 1
                        continue
                    wrong_labels.add(lbl)
                    field = field_for_criterion(crit)
                    rec = records.get(lbl, {})
                    fields_expected = {field: {"not": rec.get(field)}} if field and field in rec else {}
                    add_gold_obl(gold, seen, {
                        "matter_id": mid, "quote": (rec.get("quote") or "")[:200],
                        "kind_expected": rec.get("kind"), "fields_expected": fields_expected,
                        "criteria": crit, "note": note, "verdict": "wrong",
                        "source": "ab2_audit_pilot", "date": TODAY,
                    })
                    counts["gold_wrong"] += 1
                side_records = [lbl for lbl in records if lbl.startswith(side_label)]
                if n_correct == len(side_records) - len(wrong_labels):
                    for lbl in side_records:
                        if lbl not in wrong_labels:
                            rec = records[lbl]
                            add_gold_obl(gold, seen, {
                                "matter_id": mid, "quote": (rec.get("quote") or "")[:200],
                                "kind_expected": rec.get("kind"),
                                "fields_expected": snapshot_fields(rec, ["agency", "deadline_kind", "deadline_date", "recurrence", "existing_code"]),
                                "verdict": "correct", "source": "ab2_audit_pilot", "date": TODAY,
                            })
                            counts["gold_correct"] += 1
                else:
                    unparsed.append({"source": "ab2_audit", "matter_id": mid, "side": side_label,
                                      "reason": "correct count mismatch", "raw": entry})
                    counts["unparsed"] += 1
                for md in entry.get("missed_detail", []):
                    add_gold_obl(gold, seen, {
                        "matter_id": mid, "quote": md[:200], "kind_expected": None,
                        "fields_expected": {}, "verdict": "missed", "note": md,
                        "source": "ab2_audit_pilot", "date": TODAY,
                    })
                    counts["gold_missed"] += 1


def process_units_round(results_path: Path, gold: list, seen: set, unparsed: list, counts: dict) -> None:
    """results_protected.json also carries a separate agency/unit audit
    (obligation_id -> RIGHT/WRONG/UNCLEAR with right_agency), a distinct
    round from the R-label duty/power judgments in the same file."""
    results = load(results_path, {})
    units = results.get("units", {}) if isinstance(results, dict) else {}
    for obl_id, entry in units.items():
        mid = obl_id.split("-")[0]
        verdict = (entry.get("verdict") or "").upper()
        if verdict == "RIGHT":
            add_gold_obl(gold, seen, {
                "matter_id": mid, "quote": obl_id, "kind_expected": None,
                "fields_expected": {"agency": entry.get("right_agency")},
                "verdict": "correct", "note": entry.get("note", ""),
                "source": "audit4_protected_units", "date": TODAY,
            })
            counts["gold_correct"] += 1
        elif verdict == "WRONG":
            add_gold_obl(gold, seen, {
                "matter_id": mid, "quote": obl_id, "kind_expected": None,
                "fields_expected": {"agency": entry.get("right_agency")},
                "verdict": "wrong", "note": entry.get("note", ""),
                "source": "audit4_protected_units", "date": TODAY,
            })
            counts["gold_wrong"] += 1
        else:
            unparsed.append({"source": "audit4_protected_units", "matter_id": obl_id,
                              "reason": "verdict UNCLEAR, no positive claim", "raw": entry})
            counts["unparsed"] += 1


def process_fiscal_round(name: str, results_path: Path, gold: list, seen: set,
                          counts: dict, structured_results: dict) -> None:
    results = load(results_path, {})
    for mid, entry in results.items():
        verdict = (entry.get("verdict") or "").lower()
        errors = entry.get("errors") or []
        structured_results[mid] = {"verdict": verdict, "errors": errors}
        if verdict == "correct":
            counts["gold_correct"] += 1
            add_gold_fis(gold, seen, {"matter_id": mid, "fields_expected": {}, "verdict": "correct",
                                       "source": name, "date": TODAY})
        elif verdict == "wrong":
            counts["gold_wrong"] += 1
            fields_expected = {e["field"]: e.get("right_value") for e in errors if "field" in e}
            add_gold_fis(gold, seen, {"matter_id": mid, "fields_expected": fields_expected,
                                       "errors": errors, "verdict": "wrong", "source": name, "date": TODAY})
        else:
            counts["unparsed"] += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit4-dir", default=str(DEFAULT_TMP / "audit4"))
    ap.add_argument("--spot-audit-dir", default=str(DEFAULT_TMP / "spot_audit"))
    ap.add_argument("--spot-audit-results", default=str(DEFAULT_TMP / "spot_audit_results.json"))
    ap.add_argument("--ab2-dir", default=str(DEFAULT_TMP / "ab2_audit"))
    ap.add_argument("--ab2-key", default=str(DEFAULT_TMP / "ab2_key.json"))
    ap.add_argument("--ab2-p1", default=str(DEFAULT_TMP / "ab2_results_p1.json"))
    ap.add_argument("--ab2-p2", default=str(DEFAULT_TMP / "ab2_results_p2.json"))
    args = ap.parse_args()

    gold_obl, gold_fis, unparsed = load_existing_gold()
    seen_obl = {gold_key_obl(g) for g in gold_obl}
    seen_fis = {gold_key_fis(g) for g in gold_fis}
    counts: dict = {"gold_correct": 0, "gold_wrong": 0, "gold_missed": 0, "unparsed": 0}

    audit4 = Path(args.audit4_dir)
    SEEDED_DIR.mkdir(exist_ok=True)

    for name, packet_sub, results_file, source in [
        ("audit4_sonnet", "sonnet", "results_sonnet.json", "audit4_sonnet"),
        ("audit4_protected", "protected", "results_protected.json", "audit4_protected"),
    ]:
        skey, sres = {}, {}
        process_obl_round(name, audit4 / packet_sub, audit4 / results_file, source,
                           gold_obl, seen_obl, unparsed, counts, skey, sres)
        d = SEEDED_DIR / name
        d.mkdir(exist_ok=True)
        (d / "key.json").write_text(json.dumps(skey, indent=1, ensure_ascii=False))
        (d / "results.json").write_text(json.dumps(sres, indent=1, ensure_ascii=False))

    skey, sres = {}, {}
    process_obl_round("spot_audit", Path(args.spot_audit_dir), Path(args.spot_audit_results), "spot_audit",
                       gold_obl, seen_obl, unparsed, counts, skey, sres)
    d = SEEDED_DIR / "spot_audit"
    d.mkdir(exist_ok=True)
    (d / "key.json").write_text(json.dumps(skey, indent=1, ensure_ascii=False))
    (d / "results.json").write_text(json.dumps(sres, indent=1, ensure_ascii=False))

    process_units_round(audit4 / "results_protected.json", gold_obl, seen_obl, unparsed, counts)

    skey, sres = {}, {}
    process_ab2(Path(args.ab2_dir), [Path(args.ab2_p1), Path(args.ab2_p2)], Path(args.ab2_key),
                gold_obl, seen_obl, unparsed, counts, skey, sres)

    skey, sres = {}, {}
    process_fiscal_round("audit4_fiscal", audit4 / "results_fiscal.json", gold_fis, seen_fis, counts, sres)
    d = SEEDED_DIR / "audit4_fiscal"
    d.mkdir(exist_ok=True)
    (d / "results.json").write_text(json.dumps(sres, indent=1, ensure_ascii=False))

    GOLD_OBL.write_text(json.dumps(gold_obl, indent=1, ensure_ascii=False))
    GOLD_FIS.write_text(json.dumps(gold_fis, indent=1, ensure_ascii=False))
    GOLD_UNPARSED.write_text(json.dumps(unparsed, indent=1, ensure_ascii=False))

    print(json.dumps(counts, indent=1))
    print(f"gold_obligations.json: {len(gold_obl)} entries")
    print(f"gold_fiscal.json: {len(gold_fis)} entries")
    print(f"gold_unparsed.json: {len(unparsed)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
