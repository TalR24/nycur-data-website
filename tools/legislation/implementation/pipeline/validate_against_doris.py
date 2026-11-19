#!/usr/bin/env python3
"""Cross-check the tracker against DORIS's own list of required reports.

The tracker reads duties out of enacted law text. The Department of Records and
Information Services publishes a separate, independently maintained list of the
reports agencies owe, with the local law that created each one and the date it
was last filed. Where the two overlap they should agree, which makes DORIS the
only external validation this dataset has.

Two NYC Open Data resources:
  9azj-tmjp  Government Publication - Required Reports  (the mandates)
  xip9-pe9k  Government Publications Listing            (the filings)

What this reports:
  1. COVERAGE. For every 2014+ local law DORIS names, did we extract any
     obligation at all? A law DORIS calls a reporting mandate where we found
     nothing is a genuine miss and the strongest signal here.
  2. CLASSIFICATION. Laws where we extracted a duty but not as a "report".
     Usually a taxonomy difference, not an error: DORIS counts plans, data
     publications, and outreach materials as required reports; the tracker
     splits those into their own deliverable types.
  3. COMPLIANCE. DORIS records the last filing date, so a cadence plus that
     date says whether a report is current. The tracker itself has no
     compliance data; this is the only place to get it.

Credit: Josh Greenman's overdue-reports dashboard
(joshgreenman1973.github.io/nyc-overdue-reports) does the compliance analysis
across all of DORIS; this script scopes the same idea to the tracker's corpus.
The framing of Legistar's "Report Required" tag as unreliable comes from
Maximum New York, maximumnewyork.com/p/2023-reporting-requirements.

Usage:
    python3 pipeline/validate_against_doris.py            # fetch live, print report
    python3 pipeline/validate_against_doris.py --json out.json

No Anthropic API calls.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
DORIS_URL = "https://data.cityofnewyork.us/resource/9azj-tmjp.json?$limit=5000"

# DORIS cadence strings → days. Anything absent from this map has no schedule
# and is skipped in the compliance section rather than guessed at.
FREQ_DAYS = {
    "Every 1 Week": 7, "Every 1 Month": 30, "Every 2 Months": 61,
    "Every 3 Months": 91, "Every 6 Weeks": 42, "Every 6 Months": 182,
    "Every 1 Year": 365, "Every 2 Years": 730, "Every 3 Years": 1095,
    "Every 4 Years": 1460, "Every 5 Years": 1825, "Every 10 Years": 3650,
}
LL = re.compile(r"LL\s*(\d+)\s*/\s*(\d{4})", re.I)


def law_key(local_law: str | None) -> tuple[int, str] | tuple[None, None]:
    m = LL.match((local_law or "").strip())
    if not m:
        return None, None
    year, num = int(m.group(2)), int(m.group(1))
    return year, f"Local Law {num} of {year}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write the full result to this path")
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args()
    today = date.fromisoformat(args.today)

    doris = requests.get(DORIS_URL, timeout=120).json()
    ours = json.loads((DATA / "obligations.json").read_text())
    our_laws = {l["law_number_display"] for l in ours["laws"]}
    by_law: dict[str, list] = defaultdict(list)
    for o in ours["obligations"]:
        by_law[o["law_number_display"]].append(o)

    doris_by_law: dict[str, list] = defaultdict(list)
    for r in doris:
        year, key = law_key(r.get("local_law"))
        if year and 2014 <= year <= today.year:
            doris_by_law[key].append(r)

    shared = sorted(set(doris_by_law) & our_laws)
    missing, misclassified = [], []
    for key in shared:
        got = by_law.get(key, [])
        if not got:
            missing.append({"law": key,
                            "doris_reports": [r.get("name") for r in doris_by_law[key]]})
        elif not any(o["deliverable_type"] == "report" for o in got):
            misclassified.append({
                "law": key,
                "doris_reports": [r.get("name") for r in doris_by_law[key]],
                "our_types": dict(Counter(o["deliverable_type"] for o in got)),
            })

    compliance = Counter()
    overdue = []
    for key in shared:
        for r in doris_by_law[key]:
            freq = FREQ_DAYS.get(r.get("frequency") or "")
            if not freq:
                compliance["no schedule in DORIS"] += 1
                continue
            last = r.get("last_published_date")
            if not last:
                compliance["DORIS records no filing"] += 1
                continue
            filed = datetime.fromisoformat(last.replace("Z", "")).date()
            late = (today - filed).days - freq
            if late > 0:
                compliance["overdue"] += 1
                overdue.append({"law": key, "agency": r.get("agency"),
                                "report": r.get("name"), "years_late": round(late / 365, 1)})
            else:
                compliance["current"] += 1

    result = {
        "generated": today.isoformat(),
        "doris_records": len(doris),
        "doris_traced_to_in_scope_law": sum(len(v) for v in doris_by_law.values()),
        "laws_in_both": len(shared),
        "coverage_gaps": missing,
        "classification_differences": misclassified,
        "compliance": dict(compliance),
        "most_overdue": sorted(overdue, key=lambda x: -x["years_late"])[:25],
    }

    print(f"DORIS required reports: {len(doris)}")
    print(f"traced to a {2014}-{today.year} local law: {result['doris_traced_to_in_scope_law']}")
    print(f"laws present in both corpora: {len(shared)}\n")
    print(f"COVERAGE GAPS (DORIS names a reporting law, we extracted nothing): {len(missing)}")
    for m in missing[:20]:
        print(f"  {m['law']}: {m['doris_reports'][0][:70]}")
    print(f"\nCLASSIFICATION DIFFERENCES (we extracted, but not as a report): "
          f"{len(misclassified)}")
    agg = Counter()
    for m in misclassified:
        agg.update(m["our_types"])
    print(f"  our types on those laws: {dict(agg.most_common(6))}")
    print(f"\nCOMPLIANCE, per DORIS, for reports created by in-scope laws:")
    for k, v in compliance.most_common():
        print(f"  {k:26s} {v:5d}")

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
