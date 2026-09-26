#!/usr/bin/env python3
"""
Populate reextract_queue.json with EVERY law except the audited exclusions
(pipeline/reextract_exclusions.json) and laws already queued, for a full-corpus
re-extraction with the hardened prompt. Run this, commit the queue, then
dispatch claude_backfill.yml (task reextract_obligations) repeatedly; each run
processes REEXTRACT_LIMIT laws (200/run as of Sep 26 2026) and defers the
rest, until the queue drains. Existing queue entries (e.g. attachment-only
laws) are preserved. One-off: delete this script once the queue is empty.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
laws = json.loads((HERE.parent / "data" / "laws.json").read_text())["laws"]
excl = json.loads((HERE / "reextract_exclusions.json").read_text())["matters"]
qp = HERE / "reextract_queue.json"
queue = json.loads(qp.read_text()) if qp.exists() else {"matters": {}}
existing = queue.get("matters", {})

added = 0
for l in laws:
    mid = l["matter_id"]
    if mid in excl or mid in existing:
        continue
    existing[mid] = "full-corpus re-extraction (hardened prompt, Aug 2026)"
    added += 1

queue["matters"] = existing
queue["reason"] = queue.get("reason", "") + " | Full-corpus pass staged."
qp.write_text(json.dumps(queue, indent=2) + "\n")
print(f"queued {added} laws ({len(excl)} audited exclusions skipped, "
      f"{len(existing)} total pending)")
