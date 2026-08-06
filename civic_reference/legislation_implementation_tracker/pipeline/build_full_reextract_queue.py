#!/usr/bin/env python3
"""
Populate reextract_queue.json with EVERY law except the audited exclusions
(pipeline/reextract_exclusions.json) and laws already queued, for a full-corpus
re-extraction with the hardened prompt. Run this, commit the queue, then
dispatch the refresh workflow repeatedly; each run processes REEXTRACT_LIMIT
laws (default 200) and defers the rest, so ~10 dispatches cover the corpus.
Existing queue entries (e.g. attachment-only laws) are preserved.
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
