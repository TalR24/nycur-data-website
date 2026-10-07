#!/usr/bin/env python3
"""Keep the compact bill index current between full fetches. No model calls, public data only.

Reads the Open Legislation change feed since data/index_state.json, fetches each changed bill (view=no_fulltext),
and upserts its row in data/bills/{session}.json, then rebuilds data/hub_stats.json. Runs daily.
Rows are written one per line so a day's changes are a small git diff, not a new 8 MB blob.
Not covered: signed-law text and the duty extraction (those still come from fetch_bills.py / fetch_signed_texts.py).

Usage: python3 apply_updates.py            resume from data/index_state.json (first run: the last 2 days)
       python3 apply_updates.py --days 3   re-read a window
       python3 apply_updates.py --dry-run  report what would change, write nothing
The cursor advances only after every file was written."""
import argparse, datetime as dt, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import openleg  # noqa: E402
import poll_updates  # noqa: E402
import fetch_bills  # noqa: E402

DATA = poll_updates.DATA
FMT = poll_updates.FMT
STATE = os.path.join(DATA, "index_state.json")


def write_index(path, doc):
    """Compact JSON with one row per line (stable diffs); the explorer reads it with JSON.parse either way."""
    head = {k: v for k, v in doc.items() if k != "rows"}
    head_s = json.dumps(head, separators=(",", ":"), ensure_ascii=False)[:-1]
    rows = ",\n".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in doc["rows"])
    with open(path, "w") as f:
        f.write(head_s + ',"rows":[\n' + rows + "\n]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    now = dt.datetime.now().replace(microsecond=0)
    if a.days:
        start = now - dt.timedelta(days=a.days)
    elif os.path.exists(STATE):
        start = dt.datetime.strptime(json.load(open(STATE))["cursor"], FMT)
    else:
        start = now - dt.timedelta(days=2)
    items, t = [], start
    while t < now:
        e = min(t + dt.timedelta(days=1), now)
        items += poll_updates.fetch_window(t, e)
        t = e
    changed, _ = poll_updates.summarize(items)
    by_session = {}
    for b in changed:
        by_session.setdefault(b["session"], []).append(b["base_print_no"])
    updated = added = 0
    for session, prints in sorted(by_session.items()):
        path = os.path.join(fetch_bills.INDEX_DIR, "%d.json" % session)
        if not os.path.exists(path):
            continue
        doc = json.load(open(path))
        pos = {r[2]: i for i, r in enumerate(doc["rows"])}
        for p in prints:
            d = openleg.get("/api/3/bills/%d/%s" % (session, p), {"view": "no_fulltext"})
            if not d:
                continue
            row = fetch_bills.index_row(fetch_bills.normalize(d["result"]))
            if p in pos:
                if doc["rows"][pos[p]] != row:
                    doc["rows"][pos[p]] = row
                    updated += 1
            else:
                doc["rows"].append(row)
                pos[p] = len(doc["rows"]) - 1
                added += 1
        doc["total_in_api"] = len(doc["rows"])
        doc["generated"] = now.strftime("%Y-%m-%d")
        if not a.dry_run:
            write_index(path, doc)
    print("window %s -> %s: %d changed bills in %d sessions; %d rows updated, %d added" % (start, now, len(changed), len(by_session), updated, added))
    if a.dry_run:
        return
    subprocess.run([sys.executable, os.path.join(HERE, "build_hub_stats.py")], check=True)
    json.dump({"cursor": now.strftime(FMT), "last_run_bills": len(changed), "rows_updated": updated, "rows_added": added}, open(STATE, "w"), indent=1)


if __name__ == "__main__":
    main()
