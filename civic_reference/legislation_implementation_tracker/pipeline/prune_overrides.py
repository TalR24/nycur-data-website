#!/usr/bin/env python3
"""Prune record_overrides.json entries that no longer do anything (Nov 10 2026).

Classification reuses extract_obligations.apply_record_overrides, the same call
validate_obligations.py makes (its soft counts stale_override,
override_ambiguous, override_already_absent), so the two cannot disagree:

  applies        the entry matched a record in the data (not in the report)
  already_absent a `remove` that matched no record (extract_obligations.py
                 apply_record_overrides, status "already_absent")
  stale          a `set` that matched no record (status "stale")
  ambiguous      several candidates and no agency to pick one (status
                 "ambiguous"); never pruned
  add            `add` entries are never reported as unmatched; kept

Pruned on --apply:
  already_absent `remove` entries that are already_absent in the CURRENT data
  and in the two previous committed versions of obligations.json/powers.json,
  AND whose target the producer no longer emits: the law's cached extraction
  (pipeline/cache/extracted, local only) has no record matching the quote.
  The cache test is deliberately lenient (it also matches on letters and
  digits alone), because a cache miss means a rebuild brings the record back
  (7926817 did on the first try, Nov 10 2026, a curly apostrophe stored as a
  literal escape). Without the second test, a remove that works (its target is absent because
  the override removed it) would look the same as one that is dead, and
  pruning it would bring the record back on the next full re-extraction.

Never pruned: ambiguous, applying, add, and `set` entries reported stale. A
stale `set` matched nothing in today's published data, but a re-extraction
could emit that record again and the set would then protect a hand fix, so it
cannot be shown to never match. Ambiguous and stale entries are written to
quality/override_review_queue.json for a later adjudication round.

Pruned entries go, complete and unmodified, to
record_overrides_pruned_2026-11-10.json with their class and evidence.

    python3 pipeline/prune_overrides.py             # dry run (default)
    python3 pipeline/prune_overrides.py --apply
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-no-calls")   # import only; no call is made

from extract_obligations import (  # noqa: E402
    EXTRACT_CACHE, _find_candidates, apply_record_overrides)

LIT = HERE.parent
DATA = LIT / "data"
OVERRIDES_PATH = HERE / "record_overrides.json"
PRUNED_PATH = HERE / "record_overrides_pruned_2026-11-10.json"
QUEUE_PATH = LIT.parent / "nyc_council_legislation_trackers" / "quality" / "override_review_queue.json"
DATE = "2026-11-10"


# --- classification ---------------------------------------------------------

def classify(overrides: dict, rows_by_matter: dict) -> dict:
    """{(matter_id, action, index): status} for every set/remove entry.
    Status is one of applies, already_absent, stale, ambiguous."""
    out = {}
    for mid, ov in overrides.items():
        rows = [dict(r) for r in rows_by_matter.get(mid, [])]
        _, report = apply_record_overrides(rows, mid, {mid: ov})
        for action in ("set", "remove"):
            for i, entry in enumerate(ov.get(action, [])):
                st = "applies"
                for rep in report:
                    if rep["action"] == action and all(rep.get(k) == v for k, v in entry.items()):
                        st = rep["status"]
                        break
                out[(mid, action, i)] = st
    return out


def rows_by_matter(obligations: list, powers: list) -> dict:
    by = defaultdict(list)
    for r in list(obligations) + list(powers):
        by[r["matter_id"]].append(r)
    return by


def producer_emits(mid: str, entry: dict, cache_rows: dict | None) -> bool | None:
    """True when the cached extraction still has a record matching the entry's
    quote (agency ignored, so a retagged copy counts), None when no cache."""
    if cache_rows is None or mid not in cache_rows:
        return None
    prefix = entry.get("quote_prefix", "")
    if _find_candidates(cache_rows[mid], prefix, None):
        return True
    # the cache stores raw quotes (curly apostrophes as a literal \\u2019, no
    # quote cleaning), which the build normalizes before it matches; compare on
    # letters and digits only so that difference cannot hide a live record
    want = _alnum(prefix)[:50]
    return any(want and _alnum(r.get("quote") or "").startswith(want)
               for r in cache_rows[mid])


def _alnum(s: str) -> str:
    s = re.sub(r"\\u[0-9a-fA-F]{4}", "", s)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def plan(overrides: dict, versions: list[tuple[str, dict]], cache_rows: dict | None) -> dict:
    """versions[0] is the current data; the rest are earlier committed ones.
    Each is (label, rows_by_matter). Returns pruned/queue/kept lists."""
    statuses = [(label, classify(overrides, rows)) for label, rows in versions]
    cur = statuses[0][1]
    counts = defaultdict(int)
    pruned, queue = [], []
    kept_absent = defaultdict(int)
    for key, st in cur.items():
        mid, action, i = key
        counts[st] += 1
        entry = overrides[mid][action][i]
        if st == "ambiguous":
            queue.append({"matter_id": mid, "action": action, "class": st, "entry": entry,
                          "reason": "several records match and the entry names no agency that "
                                    "picks one; most say 'duplicate of X' and mean keep one copy, "
                                    "so removing on ambiguity is wrong (SKILL.md legislation-trackers)"})
        elif st == "stale":
            queue.append({"matter_id": mid, "action": action, "class": st, "entry": entry,
                          "reason": "a set that matched no record in the current data; a "
                                    "re-extraction could emit the record again and the set would "
                                    "protect a hand fix, so it is not provably dead"})
        elif st == "already_absent" and action == "remove":
            absent_all = all(s[1].get(key) == "already_absent" for s in statuses)
            emits = producer_emits(mid, entry, cache_rows)
            if absent_all and emits is False:
                pruned.append({"matter_id": mid, "action": action, "class": st, "entry": entry,
                               "evidence": {
                                   "already_absent_in": [s[0] for s in statuses],
                                   "producer_cache_match": False}})
            else:
                kept_absent["not absent in all versions" if not absent_all else
                            "producer cache still emits the record" if emits else
                            "no cached extraction to check"] += 1
    return {"counts": dict(counts), "pruned": pruned, "queue": queue,
            "kept_already_absent": dict(kept_absent)}


def apply_prune(overrides: dict, pruned: list) -> dict:
    """Return a copy of overrides without the pruned entries (matter keys stay)."""
    out = copy.deepcopy(overrides)
    drop = defaultdict(list)
    for p in pruned:
        drop[p["matter_id"]].append(p["entry"])
    for mid, entries in drop.items():
        for e in entries:
            out[mid]["remove"].remove(e)
    return out


# --- data versions ----------------------------------------------------------

def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=LIT, check=True, capture_output=True, text=True).stdout


def load_versions(n_prev: int = 2) -> list[tuple[str, dict]]:
    ob = json.loads((DATA / "obligations.json").read_text())["obligations"]
    pw = json.loads((DATA / "powers.json").read_text())["powers"]
    versions = [("current", rows_by_matter(ob, pw))]
    commits = _git("log", f"-n{n_prev + 1}", "--format=%h", "--",
                   "data/obligations.json", "data/powers.json").split()
    for c in commits[1:]:
        o = json.loads(_git("show", f"{c}:civic_reference/legislation_implementation_tracker/data/obligations.json"))["obligations"]
        p = json.loads(_git("show", f"{c}:civic_reference/legislation_implementation_tracker/data/powers.json"))["powers"]
        versions.append((c, rows_by_matter(o, p)))
    return versions


def load_cache_rows(matters) -> dict | None:
    if not EXTRACT_CACHE.exists():
        return None
    rows = {}
    for m in matters:
        f = EXTRACT_CACHE / f"{m}.json"
        if f.exists():
            rows[m] = json.loads(f.read_text()).get("obligations") or []
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="default")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--exclude", default="", help="comma list of matter ids to leave unpruned")
    args = ap.parse_args()

    overrides = json.loads(OVERRIDES_PATH.read_text())
    versions = load_versions()
    p = plan(overrides, versions, load_cache_rows(overrides))
    excl = {m for m in args.exclude.split(",") if m}
    p["pruned"] = [x for x in p["pruned"] if x["matter_id"] not in excl]
    print("versions:", [v[0] for v in versions])
    print("entries by class (set+remove):", p["counts"])
    print("pruned:", len(p["pruned"]), "queued:", len(p["queue"]),
          "kept already_absent:", p["kept_already_absent"])
    if not args.apply:
        print("dry run: nothing written")
        return 0
    PRUNED_PATH.write_text(json.dumps({
        "pruned_on": DATE, "count": len(p["pruned"]),
        "restore": "append each entry back to record_overrides.json[matter_id][action]",
        "entries": p["pruned"]}, indent=1) + "\n")
    QUEUE_PATH.write_text(json.dumps({
        "generated": DATE, "count": len(p["queue"]),
        "note": "adjudicate in a gold tiebreak round; none of these were pruned",
        "entries": p["queue"]}, indent=1) + "\n")
    OVERRIDES_PATH.write_text(json.dumps(apply_prune(overrides, p["pruned"]), indent=1))
    print("wrote", PRUNED_PATH.name, QUEUE_PATH.name, OVERRIDES_PATH.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
