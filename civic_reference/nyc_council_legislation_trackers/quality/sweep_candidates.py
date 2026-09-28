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
ESTABLISH = re.compile(r"\bhereby (established|created)\b|\bthere shall be (established|created)\b", re.I)

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
    # audit 9 (Sep 28 2026)
    "effective_kind_other_date": lambda o, kind: o.get("deadline_kind") == "on_effective_date"
                                                 and o.get("deadline_date") and o.get("effective_date")
                                                 and o["deadline_date"] != o["effective_date"],
    "establishment_clause": lambda o, kind: kind == "duty" and ESTABLISH.search(o.get("quote", ""))
                                            and not re.search(r"\bshall\b(?!\s+be\s+(established|created))",
                                                              o.get("quote", ""), re.I),
}
SHOWN = ("quote", "kind", "agency", "agency_unit", "actor_raw", "deadline_kind", "deadline_date",
         "recurrence", "citation", "action_summary")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--classes", nargs="+", default=list(CLASSES) + ["restated_but_new_matter"])
    ap.add_argument("--exclude-judged", nargs="*", default=[], metavar="DIFF",
                    help="earlier sweep diff files: skip records already judged there (matter + quote)")
    args = ap.parse_args()
    judged = set()
    for f in args.exclude_judged:
        for mid, d in json.loads(Path(f).read_text()).items():
            for r in d.get("current_only", []):
                judged.add((mid, (r.get("quote") or "")[:120]))
    # reprint flag against the law's own new-matter markers (audit 9): a record
    # flagged reprinted whose quote is mostly underlined new matter
    import sys
    sys.path.insert(0, str(LIT / "pipeline"))
    from sweep_restated_duties import split_markers, condense, locate, restated_spans
    parsed: dict = {}

    def new_share(o):
        mid = o["matter_id"]
        if mid not in parsed:
            tp = LIT / "pipeline/cache/text" / f"{mid}.txt"
            if not tp.exists():
                parsed[mid] = None
            else:
                plain, flags = split_markers(tp.read_text(errors="ignore"))
                hay, idx = condense(plain)
                parsed[mid] = (hay, idx, flags, restated_spans(plain)) if "{{" in tp.read_text(errors="ignore") else None
        if not parsed[mid]:
            return None
        hay, idx, flags, spans = parsed[mid]
        return locate(hay, idx, flags, o.get("quote") or "", spans)

    if "restated_but_new_matter" in args.classes:
        CLASSES["restated_but_new_matter"] = lambda o, kind: o.get("restated") and (new_share(o) or 0) >= 0.5
    rows = [(o, "duty") for o in json.loads((LIT / "data/obligations.json").read_text())["obligations"]]
    rows += [(o, "power") for o in json.loads((LIT / "data/powers.json").read_text())["powers"]]
    diff: dict[str, dict] = defaultdict(lambda: {"disagreements": [], "snapshot_only": [], "current_only": []})
    by_class: Counter = Counter()
    for o, kind in rows:
        hit = [c for c in args.classes if CLASSES[c](o, kind)]
        if not hit or (o["matter_id"], (o.get("quote") or "")[:120]) in judged:
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
