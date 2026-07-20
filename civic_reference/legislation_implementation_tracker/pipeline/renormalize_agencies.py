#!/usr/bin/env python3
"""
Re-resolve agency names in cached extractions against the current
agency_crosswalk.json, without any Claude calls.

Use after the crosswalk gains variants or canonical overrides: it rewrites
cache/extracted/*.json in place, then `extract_obligations.py --incremental`
rebuilds obligations.json (and the members CSV) from the refreshed cache.

    python3 pipeline/renormalize_agencies.py
    python3 pipeline/extract_obligations.py --incremental
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from extract_obligations import (resolve_actor, CROSSWALK_JSON, EXTRACT_CACHE)


def main() -> None:
    cw = json.loads(CROSSWALK_JSON.read_text())
    lookup = cw["lookup"]
    by_canon = {a["canonical"]: a for a in cw["agencies"]}

    files = sorted(EXTRACT_CACHE.glob("*.json"))
    touched = 0
    for f in files:
        res = json.loads(f.read_text())
        changed = False
        for o in res.get("obligations", []):
            # actor_raw is the name as written in the law; the stored agency
            # string is the previous resolution (used as a fallback candidate)
            canon, full, display = resolve_actor(
                res["matter_id"],
                [o.get("actor_raw", ""), o.get("agency", "")],
                lookup, by_canon)
            if canon is None:
                new = {"agency": display,
                       "agency_full": ("Not specified in the law text"
                                       if display == "Unspecified"
                                       else display),
                       "agency_matched": False}
            else:
                new = {"agency": canon, "agency_full": full, "agency_matched": True}
            if (new["agency"] != o.get("agency") or
                    new["agency_full"] != o.get("agency_full") or
                    new["agency_matched"] != o.get("agency_matched")):
                o.update(new)
                changed = True
        if changed:
            f.write_text(json.dumps(res, indent=1))
            touched += 1
    print(f"Re-normalized {touched} of {len(files)} cached extractions")


if __name__ == "__main__":
    main()
