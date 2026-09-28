#!/usr/bin/env python3
"""Retirement path for the 423 "protected" laws in reextract_exclusions.json.

Those laws were hand-corrected in Aug 2026 and reextract_queued.py skips them
forever, so the corpus can never learn whether today's better model (audit 4:
92%/97% precision/recall vs. 72%/62-69% for the protected set) already beats
the hand fix. This gives that a safe, reviewable path instead of the two bad
options (leave them protected forever, or blindly overwrite hand fixes):

    snapshot   write pipeline/protected_snapshot.json from the current
               committed data (data/obligations.json + powers.json). Run
               once, before any re-extraction of the protected set.
    queue      write the 423 matter ids into reextract_queue.json (does NOT
               run re-extraction; a separate step with
               REEXTRACT_INCLUDE_PROTECTED=1 does that).
    diff       after re-extraction, pair each law's snapshot records against
               its current records and write reconcile_protected.json:
               field disagreements, snapshot-only records, current-only
               records. Needs only protected_snapshot.json + data/*.json, so
               it runs in CI (cache/ is gitignored and empty there).
    apply      turn reconcile_decisions.json (written by verify_obligations.py)
               into record_overrides.json entries. Never run on real data by
               this session (per orders); exercised only in the scratch test.

Usage:
    python3 pipeline/reconcile_protected.py snapshot
    python3 pipeline/reconcile_protected.py queue
    python3 pipeline/reconcile_protected.py diff
    python3 pipeline/reconcile_protected.py apply
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
EXCLUSIONS = HERE / "reextract_exclusions.json"
SNAPSHOT = HERE / "protected_snapshot.json"
QUEUE = HERE / "reextract_queue.json"
DIFF = HERE / "reconcile_protected.json"
DECISIONS = Path(os.environ.get("RECONCILE_DECISIONS") or HERE / "reconcile_decisions.json")
RECORD_OVERRIDES_PATH = HERE / "record_overrides.json"

sys.path.insert(0, str(HERE))
from extract_obligations import normalize_quote, quote_similarity  # noqa: E402

_JOINED_KEYS = {"file_number", "law_number_display", "law_title", "committee",
                "prime_sponsor", "enactment_date", "effective_date",
                "legistar_url", "law_sunset_date", "quotes_restated_text", "filing"}

FIELDS_TO_DIFF = ["kind", "agency", "agency_unit", "deadline_date",
                  "deadline_kind", "recurrence", "existing_code", "restated"]  # records' own name (was deadline_type)


def protected_matters() -> dict:
    if not EXCLUSIONS.exists():
        return {}
    return json.loads(EXCLUSIONS.read_text()).get("matters", {})


def committed_by_matter() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for path, key in ((DATA / "obligations.json", "obligations"),
                      (DATA / "powers.json", "powers")):
        if not path.exists():
            continue
        for o in json.loads(path.read_text()).get(key, []):
            out[o["matter_id"]].append({k: v for k, v in o.items()
                                        if k not in _JOINED_KEYS})
    return out


def cmd_snapshot() -> None:
    protected = protected_matters()
    by_matter = committed_by_matter()
    snap = {mid: by_matter.get(mid, []) for mid in protected}
    n_records = sum(len(v) for v in snap.values())
    SNAPSHOT.write_text(json.dumps(
        {"generated": date.today().isoformat(),
         "reason": "pre-reextraction snapshot of the 423 hand-corrected "
                   "protected laws (reextract_exclusions.json), taken before "
                   "any re-extraction of them, for reconcile_protected.py diff",
         "laws": snap}, indent=1))
    print(f"wrote {SNAPSHOT}: {len(snap)} laws, {n_records} records")


def cmd_queue() -> None:
    protected = protected_matters()
    queue = json.loads(QUEUE.read_text()) if QUEUE.exists() else {"matters": {}}
    queue["generated"] = date.today().isoformat()
    queue["reason"] = ("Sep 27 2026: retirement re-extraction of the 423 "
                       "protected laws (reextract_exclusions.json), to "
                       "measure whether the current model now beats the "
                       "Aug 2026 hand fixes (audit 4: 92%/97% vs 72%/62-69%). "
                       "Run with REEXTRACT_INCLUDE_PROTECTED=1.")
    queue["matters"] = {mid: reason for mid, reason in protected.items()}
    QUEUE.write_text(json.dumps(queue, indent=2) + "\n")
    print(f"wrote {QUEUE}: {len(queue['matters'])} matters queued")


def _pair(snapshot_rows: list[dict], current_rows: list[dict]) -> tuple[list, list, list]:
    """Pair snapshot vs current records for one law: normalize_quote prefix
    first, then quote_similarity >= 0.8. Returns (pairs, snapshot_only,
    current_only)."""
    used_current: set[int] = set()
    pairs = []
    for s in snapshot_rows:
        sq = normalize_quote(s.get("quote", ""))[:160]
        match = None
        for i, c in enumerate(current_rows):
            if i in used_current:
                continue
            if normalize_quote(c.get("quote", ""))[:160] == sq:
                match = i
                break
        if match is None:
            best, best_sim = None, 0.0
            for i, c in enumerate(current_rows):
                if i in used_current:
                    continue
                sim = quote_similarity(s.get("quote"), c.get("quote"))
                if sim > best_sim:
                    best, best_sim = i, sim
            if best is not None and best_sim >= 0.8:
                match = best
        if match is not None:
            used_current.add(match)
            pairs.append((s, current_rows[match]))
    snapshot_only = [s for s in snapshot_rows if s not in [p[0] for p in pairs]]
    current_only = [c for i, c in enumerate(current_rows) if i not in used_current]
    return pairs, snapshot_only, current_only


def cmd_diff() -> None:
    if not SNAPSHOT.exists():
        sys.exit(f"{SNAPSHOT} missing; run `snapshot` first")
    snap = json.loads(SNAPSHOT.read_text())["laws"]
    current = committed_by_matter()
    result = {}
    total_disagreements = total_snap_only = total_cur_only = 0
    for mid, srows in snap.items():
        crows = current.get(mid, [])
        pairs, snapshot_only, current_only = _pair(srows, crows)
        disagreements = []
        for s, c in pairs:
            diffs = {f: {"snapshot": s.get(f), "current": c.get(f)}
                     for f in FIELDS_TO_DIFF if s.get(f) != c.get(f)}
            if diffs:
                disagreements.append({
                    "snapshot_id": s.get("obligation_id"),
                    "current_id": c.get("obligation_id"),
                    "quote": (s.get("quote") or "")[:200],
                    # the CURRENT record's own quote: apply() matches against
                    # committed (current) data, and a similarity-matched pair
                    # can have slightly different quote text (item 5)
                    "current_quote": (c.get("quote") or "")[:200],
                    "agency": c.get("agency"),
                    "fields": diffs,
                })
        if disagreements or snapshot_only or current_only:
            result[mid] = {
                "disagreements": disagreements,
                "snapshot_only": snapshot_only,
                "current_only": current_only,
            }
        total_disagreements += len(disagreements)
        total_snap_only += len(snapshot_only)
        total_cur_only += len(current_only)
    DIFF.write_text(json.dumps(result, indent=1))
    print(f"wrote {DIFF}: {len(result)} laws with differences, "
          f"{total_disagreements} field disagreements, "
          f"{total_snap_only} snapshot-only records, "
          f"{total_cur_only} current-only records")


def _entry_key(entry: dict) -> tuple:
    """Identity for idempotency: same quote_prefix + agency (set/remove) or
    same quote + agency (add) already present means a re-run adds nothing."""
    return (entry.get("quote_prefix") or entry.get("quote") or "",
           entry.get("agency"))


_BOOL_FIELDS = {"existing_code", "restated"}


def _right_values(item: dict) -> dict:
    """right_value whitelisted to FIELDS_TO_DIFF, nulls dropped, and the
    schema's string booleans coerced ("false" is truthy as a string)."""
    rv = item.get("right_value") or {}
    out = {}
    for f in FIELDS_TO_DIFF:
        v = rv.get(f)
        if v is None:
            continue
        if isinstance(v, str) and v.strip().lower() == "null":
            out[f] = None                # the judge asked to clear the field
            continue
        if f in _BOOL_FIELDS and isinstance(v, str):
            v = v.strip().lower() in ("true", "yes", "1")
        out[f] = v
    return out


def cmd_apply() -> None:
    if not DECISIONS.exists():
        sys.exit(f"{DECISIONS} missing; run verify_obligations.py first")
    decisions = json.loads(DECISIONS.read_text())
    overrides = (json.loads(RECORD_OVERRIDES_PATH.read_text())
                if RECORD_OVERRIDES_PATH.exists() else {})
    today = date.today().isoformat()
    n_set = n_add = n_remove = n_skipped = 0
    for mid, law_decisions in decisions.items():
        entry = overrides.setdefault(mid, {})
        for k in ("set", "remove", "add"):
            entry.setdefault(k, [])          # tolerant of missing keys (item 5)
        existing_keys = {k: {_entry_key(e) for e in entry[k]} for k in ("set", "remove", "add")}
        for item in law_decisions.get("items", []):
            winner = item.get("winner")
            if winner not in ("A", "B", "neither"):
                continue
            kind = item.get("record_kind")  # "disagreement" | "snapshot_only" | "current_only"
            # one-sided items are a yes/no question (A = real with these
            # fields, B = not real, neither = real with right_value fixes);
            # only paired disagreements use the A/B-is-a-side contract
            if kind == "current_only":
                if winner == "A":
                    continue                 # the re-extraction's record stands
            elif kind == "snapshot_only":
                if winner == "B":
                    continue                 # the hand-kept record was not real
            elif not (item.get("snapshot_label") == winner or winner == "neither"):
                continue
            why = f"reconcile {today}: {item.get('evidence', '')[:150]}"
            agency = item.get("agency")
            rv = _right_values(item)
            if kind == "current_only" and winner == "B":
                new = {"quote_prefix": normalize_quote(item.get("quote", ""))[:100],
                      "agency": agency, "why": why, "source": f"reconcile {today}"}
                bucket = "remove"
            elif kind == "current_only":        # neither: real, fields corrected
                new = {"quote_prefix": normalize_quote(item.get("quote", ""))[:100],
                      "agency": agency, "fields": rv, "why": why,
                      "source": f"reconcile {today}"}
                bucket = "set"
            elif kind == "snapshot_only":       # A, or neither with corrections
                fields = dict(item.get("snapshot_fields", {}))
                fields.pop("obligation_id", None)
                fields.update(rv if winner == "neither" else {})
                fields.setdefault("agency", agency)
                new = {**fields, "why": why, "source": f"reconcile {today}"}
                bucket = "add"
            else:
                if winner == "neither":
                    fields = dict(rv)
                else:
                    disagree_fields = item.get("fields") or {}
                    fields = {f: v.get("snapshot") for f, v in disagree_fields.items()}
                fields.setdefault("agency", agency)
                # apply() matches against CURRENT (committed) data: use the
                # current record's own quote for the prefix (item 5)
                new = {"quote_prefix": normalize_quote(item.get("quote", ""))[:100],
                      "agency": agency, "fields": fields, "why": why,
                      "source": f"reconcile {today}"}
                bucket = "set"
            key = _entry_key(new)
            if key in existing_keys[bucket]:
                # a later verdict on the same record merges into its entry
                # (Sep 28 2026: sweep corrections to records with an earlier
                # override were dropped as "already present")
                if bucket == "set":
                    prev = next(e for e in entry["set"] if _entry_key(e) == key)
                    merged = {**prev.get("fields", {}), **new.get("fields", {})}
                    if merged != prev.get("fields", {}):
                        prev["fields"] = merged
                        prev["why"], prev["source"] = new.get("why"), new.get("source")
                        n_set += 1
                        continue
                n_skipped += 1
                continue
            entry[bucket].append(new)
            existing_keys[bucket].add(key)
            if bucket == "set":
                n_set += 1
            elif bucket == "add":
                n_add += 1
            else:
                n_remove += 1
    RECORD_OVERRIDES_PATH.write_text(json.dumps(overrides, indent=1))
    print(f"wrote {RECORD_OVERRIDES_PATH}: {n_set} set, {n_add} add, {n_remove} remove, "
          f"{n_skipped} already present (idempotent)")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("snapshot", "queue", "diff", "apply"):
        sys.exit(__doc__)
    {"snapshot": cmd_snapshot, "queue": cmd_queue,
     "diff": cmd_diff, "apply": cmd_apply}[sys.argv[1]]()


if __name__ == "__main__":
    main()
