#!/usr/bin/env python3
"""
Merge a structured audit RESULTS KEY (criteria.md "Results format") into the
gold set (gold_obligations.json / gold_fiscal.json). Idempotent: re-ingesting
the same round does not duplicate entries.

Usage:
    python3 ingest.py --tracker obligations --key DIR/key.json --results DIR/results.json --source "round 5"
    python3 ingest.py --tracker fiscal --key DIR/key.json --results DIR/results.json --source "round 5"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from audit_lib import gold_key_obl  # noqa: E402  (shared with seed_gold_from_past.py)

GOLD_OBL = HERE / "gold_obligations.json"
GOLD_FIS = HERE / "gold_fiscal.json"

OBL_SNAPSHOT_FIELDS = ["agency", "deadline_kind", "deadline_date", "recurrence", "kind"]
# gold key name -> the tracker's own field name (score_gold.py FIELD_ALIAS mirrors this)
OBL_FIELD_RENAME = {"quotes_restated_text": "existing_code"}


def load(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def gold_key_fis(g: dict) -> tuple:
    return (g["matter_id"], tuple(sorted((g.get("fields_expected") or {}).keys())), g.get("verdict"))


def snapshot_fields(snapshot: dict, fields: list[str]) -> dict:
    return {f: snapshot.get(f) for f in fields if f in snapshot}


def ingest_obligations(key: dict, results: dict, source: str, today: str) -> list[dict]:
    gold = load(GOLD_OBL, [])
    seen = {gold_key_obl(g) for g in gold}
    added = 0
    for mid, entry in results.items():
        key_entry = key.get(mid, {})
        key_records = key_entry.get("records", {})
        for label, r in (entry.get("records") or {}).items():
            snapshot = (key_records.get(label) or {}).get("snapshot", {})
            verdict = r.get("verdict")
            fields_stated = r.get("fields") or {}
            if verdict == "correct":
                fields_expected = snapshot_fields(snapshot, OBL_SNAPSHOT_FIELDS)
                if "quotes_restated_text" in snapshot:
                    fields_expected["existing_code"] = snapshot["quotes_restated_text"]
            else:
                fields_expected = dict(fields_stated)
            g = {
                "matter_id": mid, "quote": (snapshot.get("quote") or "")[:200],
                "kind_expected": snapshot.get("kind") or fields_stated.get("kind"),
                "fields_expected": fields_expected,
                "criteria": r.get("criteria") or [], "note": r.get("note", ""),
                "verdict": verdict, "source": source, "date": today,
            }
            k = gold_key_obl(g)
            if k not in seen:
                seen.add(k)
                gold.append(g)
                added += 1
        for m in entry.get("missed") or []:
            g = {
                "matter_id": mid, "quote": (m.get("quote") or "")[:200],
                "kind_expected": m.get("kind"),
                "fields_expected": {"agency": m.get("agency")} if m.get("agency") else {},
                "verdict": "missed", "note": m.get("note", ""),
                "source": source, "date": today,
            }
            k = gold_key_obl(g)
            if k not in seen:
                seen.add(k)
                gold.append(g)
                added += 1
    GOLD_OBL.write_text(json.dumps(gold, indent=1, ensure_ascii=False))
    print(f"gold_obligations.json: {added} new entries, {len(gold)} total")
    return gold


def ingest_fiscal(results: dict, source: str, today: str) -> list[dict]:
    gold = load(GOLD_FIS, [])
    seen = {gold_key_fis(g) for g in gold}
    added = 0
    for mid, entry in results.items():
        verdict = (entry.get("verdict") or "").lower()
        errors = entry.get("errors") or []
        fields_expected = {e["field"]: e.get("right_value") for e in errors if "field" in e}
        g = {
            "matter_id": mid, "fields_expected": fields_expected,
            "errors": errors, "verdict": verdict, "source": source, "date": today,
        }
        k = gold_key_fis(g)
        if k not in seen:
            seen.add(k)
            gold.append(g)
            added += 1
    GOLD_FIS.write_text(json.dumps(gold, indent=1, ensure_ascii=False))
    print(f"gold_fiscal.json: {added} new entries, {len(gold)} total")
    return gold


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", choices=["obligations", "fiscal"], required=True)
    ap.add_argument("--key", default=None)
    ap.add_argument("--results", required=True)
    ap.add_argument("--source", required=True)
    args = ap.parse_args()
    results = json.loads(Path(args.results).read_text())
    today = date.today().isoformat()
    if args.tracker == "obligations":
        key = json.loads(Path(args.key).read_text()) if args.key else {}
        ingest_obligations(key, results, args.source, today)
    else:
        ingest_fiscal(results, args.source, today)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
