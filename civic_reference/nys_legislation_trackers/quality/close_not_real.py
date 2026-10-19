#!/usr/bin/env python3
"""List every gold not_real item whose record is still stored (matched by id then quote, the scorer's rule), grouped by audit night and class.
Each one must be dropped by a pipeline rule or kept with a reason: `close_not_real.py --keep ID --why TEXT` records it under "kept_not_real"
in gold_overrides.json (build_gold then treats the item as real). Prints the count still open.
Usage: close_not_real.py [--gold PATH] [--data-dir DIR] [--overrides PATH] [--json] [--keep ID --why TEXT]"""
import argparse
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from score_gold import best_match, quote_only_law, stored_records

T = os.path.dirname(HERE)


def load(p):
    with open(p) as f:
        return json.load(f)


def open_items(gold, data_dir, kept=()):
    """[(gold item, stored record)] for live not_real gold items still stored, minus kept ids."""
    out = []
    recs = collections.defaultdict(list)
    for r in stored_records(data_dir):
        if r["matter_id"] in gold["laws"]:
            recs[r["matter_id"]].append(r)
    for law, g in gold["laws"].items():
        items = g["items"]
        qonly = quote_only_law(recs.get(law, []), items)
        for r in recs.get(law, []):
            it = best_match(r, items, qonly)
            if it and it["status"] == "not_real" and not it.get("excluded") and not it["disputed"] and it["gold_id"] not in kept \
                    and r["obligation_id"] not in kept:
                out.append((it, r))
    return out


def keep(overrides_path, oid, why, gold):
    ids = {i["gold_id"] for g in gold["laws"].values() for i in g["items"]}
    if oid not in ids:
        raise SystemExit(f"{oid} is not a gold item")
    ov = load(overrides_path)
    ov.setdefault("kept_not_real", {})[oid] = {"why": why, "kept_at": datetime.date.today().isoformat()}
    with open(overrides_path, "w") as f:
        json.dump(ov, f, indent=1)
        f.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=os.path.join(HERE, "gold.json"))
    ap.add_argument("--data-dir", default=os.path.join(T, "data"))
    ap.add_argument("--overrides", default=os.path.join(HERE, "gold_overrides.json"))
    ap.add_argument("--keep")
    ap.add_argument("--why")
    ap.add_argument("--json", action="store_true", help="print only the grouped counts as JSON")
    a = ap.parse_args(argv)
    gold = load(a.gold)
    if a.keep:
        if not a.why:
            ap.error("--keep needs --why")
        keep(a.overrides, a.keep, a.why, gold)
        print(f"kept {a.keep}: {a.why}")
    kept = set(load(a.overrides).get("kept_not_real", {}))
    items = open_items(gold, a.data_dir, kept)
    groups = collections.defaultdict(list)
    for it, r in items:
        groups[(it["source"].get("night"), ", ".join(it.get("classes") or ["unclassified"]))].append((it, r))
    if a.json:
        print(json.dumps({f"{n} | {c}": len(v) for (n, c), v in sorted(groups.items())}, indent=1))
    else:
        for (n, c), v in sorted(groups.items()):
            print(f"\n== night {n} | class: {c} ({len(v)})")
            for it, r in v:
                print(f"  {r['obligation_id']} (gold {it['gold_id']}) kind={r.get('kind')} agency={r.get('agency')} unit={r.get('agency_unit')} "
                      f"actor_raw={r.get('actor_raw')!r} deadline={r.get('deadline_kind')}")
                print(f"    quote: {(r.get('quote') or '')[:240]}")
    print(f"\nopen: {len(items)}")
    return items


if __name__ == "__main__":
    main()
