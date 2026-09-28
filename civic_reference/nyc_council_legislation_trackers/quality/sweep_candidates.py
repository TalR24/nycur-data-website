#!/usr/bin/env python3
"""Whole-corpus class sweep (Tal, Sep 28 2026): find every record in the error
classes audits keep finding, and write them in the reconcile diff shape so the
existing blind-judging path (verify_obligations.py --emit-packets / --ingest,
reconcile_protected.py apply) can judge each one on the Max plan.

Sampling fixes the 40 laws a round draws; this sweeps the whole dataset. The
judge sees each record as a yes/no question (A = right as stored, B = not a
real duty/power, neither = real with corrected fields) and is never told which
class flagged it.

    python3 sweep_candidates.py --out /path/sweep_diff.json [--classes ...]
Then:
    RECONCILE_DIFF=/path/sweep_diff.json RECONCILE_DECISIONS=/path/sweep_decisions.json \\
      python3 ../../legislation_implementation_tracker/pipeline/verify_obligations.py --emit-packets DIR
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIT = HERE.parent.parent / "legislation_implementation_tracker"

MAY = re.compile(r"\bmay\b|\bneed not\b", re.I)
MANDATORY = re.compile(r"\bshall\b|\bmust\b|\bis required\b|\bare required\b", re.I)
STREET = re.compile(r"hereby (co-)?named|following street name|co-nam", re.I)
DEADLINE_WORDS = re.compile(r"\b(no later than|not later than|within \d+|by (january|february|march|april|may|june|"
                            r"july|august|september|october|november|december))", re.I)
MAYOR_DESIGNATED = re.compile(r"designated by the mayor|mayor shall designate", re.I)

CLASSES = {
    "agency_unresolved": lambda o, kind: not o.get("agency_matched"),
    "discretion_as_duty": lambda o, kind: kind == "duty" and MAY.search(o.get("quote", ""))
                                          and not MANDATORY.search(o.get("quote", "")),
    "street_naming": lambda o, kind: kind == "duty" and STREET.search(o.get("quote", "")),
    "dated_kind_without_date": lambda o, kind: o.get("deadline_kind") in ("fixed_date", "on_effective_date")
                                               and not o.get("deadline_date"),
    "deadline_text_kind_none": lambda o, kind: kind == "duty" and o.get("deadline_kind") in (None, "none")
                                               and DEADLINE_WORDS.search(o.get("quote", "")),
    "quote_unverified": lambda o, kind: not o.get("quote_verified"),
    "mayor_designated": lambda o, kind: MAYOR_DESIGNATED.search(o.get("quote", ""))
                                        and o.get("agency") != "Mayor's Office",
}
SHOWN = ("quote", "kind", "agency", "agency_unit", "actor_raw", "deadline_kind", "deadline_date",
         "recurrence", "citation", "action_summary")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--classes", nargs="+", default=list(CLASSES))
    args = ap.parse_args()
    rows = [(o, "duty") for o in json.loads((LIT / "data/obligations.json").read_text())["obligations"]]
    rows += [(o, "power") for o in json.loads((LIT / "data/powers.json").read_text())["powers"]]
    diff: dict[str, dict] = defaultdict(lambda: {"disagreements": [], "snapshot_only": [], "current_only": []})
    by_class: Counter = Counter()
    for o, kind in rows:
        hit = [c for c in args.classes if CLASSES[c](o, kind)]
        if not hit:
            continue
        for c in hit:
            by_class[c] += 1
        rec = {k: o.get(k) for k in SHOWN}
        rec["kind"] = kind
        rec["existing_code"] = bool(o.get("restated"))      # the flag the site shows
        rec["obligation_id"] = o["obligation_id"]
        diff[o["matter_id"]]["current_only"].append(rec)
    Path(args.out).write_text(json.dumps(diff, indent=1, ensure_ascii=False))
    n = sum(len(v["current_only"]) for v in diff.values())
    print(f"wrote {args.out}: {n} records in {len(diff)} laws; by class {dict(by_class)}")


if __name__ == "__main__":
    main()
