#!/usr/bin/env python3
"""One source for the Block Party headline numbers on this site (Nov 10 2026).

The resolution count was hand-written on six pages and had drifted into three different figures. This script
writes cb-tools/block-party/data/stats.json and rewrites every marked number on the pages listed in PAGES:

    <!--bp:resolutions-->39,568<!--/bp:resolutions-->     <!--bp:boards-->27<!--/bp:boards-->

Run locally (it never runs in CI; the engine repo is private):

    python3 cb-tools/block-party/update_stats.py                      # from the engine's committed weekly export
    python3 cb-tools/block-party/update_stats.py --from-json FILE     # from a live database count (bp_count.py output)
    python3 cb-tools/block-party/update_stats.py --check              # exit 1 if a page disagrees with stats.json

Definition (same as the engine's public export, src/storage/exporters.py): rows of full_resolutions that are not
superseded or excluded, on boards marked `active: true` in the engine's config/community_boards. Boards still in
backfill are counted in `backfill_resolutions` and are NOT in the public figure until they go live.
The personal site reads stats.json through profile_facts.json (fact `bp_resolutions`), so copy_check.py keeps its
pages in step. After a run: commit stats.json and the changed pages with explicit paths.
"""
import argparse
import csv
import datetime
import glob
import gzip
import json
import os
import re
import subprocess
import sys

SITE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(os.path.dirname(SITE), "block_party", "resolution_engine")
STATS = os.path.join(SITE, "cb-tools", "block-party", "data", "stats.json")
PAGES = [
    "index.html",
    "members/index.html",
    "cb-tools/index.html",
    "cb-tools/block-party/index.html",
    "civic_reference/legislation_implementation_tracker/alerts/index.html",
    "cb-tools/member-tracker/alerts/index.html",
]
MARK = r"<!--bp:{k}-->(.*?)<!--/bp:{k}-->"


def active_boards():
    out = set()
    for f in glob.glob(os.path.join(ENGINE, "config", "community_boards", "*.yaml")):
        t = open(f).read()
        if re.search(r"^active:\s*true", t, re.M):
            m = re.search(r"^(?:board_id|id|code):\s*['\"]?([A-Za-z0-9]+)", t, re.M)
            out.add(m.group(1) if m else os.path.basename(f)[:-5].upper())
    return out


def from_export():
    """Count from the engine's committed weekly export; the date is the export's commit date."""
    csv.field_size_limit(10 ** 9)
    exp = os.path.join(ENGINE, "storage", "exports")
    board_of = {}
    with open(os.path.join(exp, "meetings.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            board_of[r["meeting_id"]] = r["board_id"]
    by = {}
    with gzip.open(os.path.join(exp, "full_resolutions.csv.gz"), "rt", newline="") as fh:
        for r in csv.DictReader(fh):
            b = board_of.get(r["meeting_id"], "?")
            by[b] = by.get(b, 0) + 1
    # Since Nov 11 2026 the exports live on the engine's "exports-latest" release, not in git
    # (fetch them with `bash scripts/exports_release.sh fetch` in the engine repo). Date = the asset's upload date.
    day = subprocess.run(["gh", "release", "view", "exports-latest", "-R", "block-party-studio/resolution_engine",
                          "--json", "assets", "-q",
                          '.assets[]|select(.name=="full_resolutions.csv.gz")|.updatedAt[:10]'],
                         capture_output=True, text=True).stdout.strip()
    if not day:
        import datetime
        day = datetime.date.fromtimestamp(os.path.getmtime(os.path.join(exp, "full_resolutions.csv.gz"))).isoformat()
    return by, day, "engine weekly export (release exports-latest, full_resolutions.csv.gz)"


def from_json(path):
    d = json.load(open(path))
    by = dict(d.get("backfill_boards", {}))
    by["__active__"] = d["resolutions_on_active_boards"]
    return by, d["as_of_utc"][:10], "live database count", d


def build(args):
    act = active_boards()
    if not act:
        sys.exit(f"no active boards found under {ENGINE}/config/community_boards; is the engine repo present?")
    if args.from_json:
        by, day, how, d = from_json(args.from_json)
        live, n_active = d["resolutions_on_active_boards"], d["active_boards"]
        backfill = sum(v for k, v in by.items() if k != "__active__")
        n_backfill = len(by) - 1
    else:
        by, day, how = from_export()
        live = sum(v for k, v in by.items() if k in act)
        n_active = len(act)
        backfill = sum(v for k, v in by.items() if k not in act)
        n_backfill = sum(1 for k in by if k not in act)
        if any(k == "?" for k in by):
            sys.exit("some resolutions have no board in meetings.csv; refusing to publish a count")
    boro = {"manhattan": sum(1 for b in act if b.startswith("MCB")), "brooklyn": sum(1 for b in act if b.startswith("BCB"))}
    return {"resolutions": live, "boards": n_active, "boards_manhattan": boro["manhattan"], "boards_brooklyn": boro["brooklyn"],
            "backfill_resolutions": backfill, "backfill_boards": n_backfill, "as_of": day, "method": how,
            "definition": "resolutions not superseded or excluded, on boards marked active in the engine config",
            "updated": datetime.date.today().isoformat()}


def render(stats, write):
    vals = {"resolutions": f"{stats['resolutions']:,}", "boards": str(stats["boards"])}
    bad = []
    for rel in PAGES:
        p = os.path.join(SITE, rel)
        html = open(p, encoding="utf-8").read()
        new, found = html, 0
        for k, v in vals.items():
            rx = re.compile(MARK.format(k=k), re.S)
            found += len(rx.findall(new))
            for m in rx.finditer(html):
                if m.group(1) != v:
                    bad.append(f"{rel}: {k} shows {m.group(1)}, stats.json says {v}")
            new = rx.sub(lambda m, k=k, v=v: f"<!--bp:{k}-->{v}<!--/bp:{k}-->", new)
        if not found:
            bad.append(f"{rel}: no bp markers found (a page lost its markers)")
        if write and new != html:
            open(p, "w", encoding="utf-8").write(new)
            print("updated", rel)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        bad = render(json.load(open(STATS)), write=False)
        print("\n".join(bad) or "pages match stats.json")
        return 1 if bad else 0
    stats = build(a)
    os.makedirs(os.path.dirname(STATS), exist_ok=True)
    json.dump(stats, open(STATS, "w"), indent=1)
    open(STATS, "a").write("\n")
    print(json.dumps(stats, indent=1))
    left = [b for b in render(stats, write=True) if "no bp markers" in b]
    print("\n".join(left))
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
