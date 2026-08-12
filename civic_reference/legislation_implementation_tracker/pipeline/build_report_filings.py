#!/usr/bin/env python3
"""Attach real filing status to the tracker's report obligations.

The tracker says what a law requires. It cannot say whether the report ever
arrived. DORIS can: it keeps the official list of required reports and the
catalog of everything agencies have actually filed, and Charter section 1133(d)
(Local Law 29 of 2019) makes it post a Delinquent Report Notice when one is
late. Joining the two turns "agencies owe 864 annual reports" into "here is
which of them are showing up".

The status vocabulary and the rules behind it are Josh Greenman's, from the NYC
Overdue Reports tracker: https://joshgreenman1973.github.io/nyc-overdue-reports/
(code and methodology at https://github.com/joshgreenman1973/nyc-overdue-reports).
This script applies his approach to the subset of mandates created by local
laws enacted since 2014, which is what this tracker covers. For questions about
compliance across all of DORIS, including mandates older than 2014, his
dashboard is the better tool and should be cited alongside any figure here.

Sources, both NYC Open Data:
  9azj-tmjp  Government Publication - Required Reports  (the mandates)
  xip9-pe9k  Government Publications Listing            (79k filings)

Pulled as grouped aggregates rather than 79k rows: the latest filing per
(agency, report), and separately the latest Delinquent Report Notice.

Output: data/report_filings.json, keyed by obligation_id. extract_obligations.py
joins it onto each obligation at flatten time, the same way it joins the sunset
date, so every view gets the status without another fetch.

Usage:
    python3 pipeline/build_report_filings.py

No Anthropic API calls.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUT = DATA / "report_filings.json"

MANDATES = "https://data.cityofnewyork.us/resource/9azj-tmjp.json"
FILINGS = "https://data.cityofnewyork.us/resource/xip9-pe9k.json"
LATE_NOTICE = "Delinquent Report Notice"

# Josh Greenman's conversion: month = 30.44 days, year = 365.25.
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30.44, "year": 365.25}
_FREQ = re.compile(r"every\s+(\d+)\s+(day|week|month|year)s?", re.I)
_LL = re.compile(r"LL\s*(\d+)\s*/\s*(\d{4})", re.I)
_STOP = {"the", "of", "a", "an", "and", "or", "to", "for", "on", "in", "by",
         "report", "reports", "reporting", "annual", "annually", "each", "such",
         "shall", "submit", "publish", "post", "provide", "city", "new", "york"}


def freq_days(freq: str | None) -> float | None:
    m = _FREQ.match((freq or "").strip())
    return int(m.group(1)) * _UNIT_DAYS[m.group(2).lower()] if m else None


def norm(s: str | None) -> str:
    s = re.sub(r"\([^)]*\)", " ", (s or ""))
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def key(agency: str | None, name: str | None) -> str:
    return f"{re.sub(r'  +', ' ', norm(agency))}|{re.sub(r'  +', ' ', norm(name))}"


def tokens(s: str | None) -> set[str]:
    return {w for w in norm(s).split() if w not in _STOP and len(w) > 2}


def law_of(local_law: str | None) -> str | None:
    m = _LL.match((local_law or "").strip())
    return f"Local Law {int(m.group(1))} of {int(m.group(2))}" if m else None


def parse_dt(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "")).date()
    except ValueError:
        return None


def fetch_grouped(where: str) -> dict[str, date]:
    """latest date_published per (agency, required_report_name)."""
    out: dict[str, date] = {}
    offset = 0
    while True:
        r = requests.get(FILINGS, params={
            "$select": "agency,required_report_name,max(date_published) as latest",
            "$group": "agency,required_report_name",
            "$where": where, "$limit": 5000, "$offset": offset}, timeout=180)
        rows = r.json()
        if not rows:
            break
        for row in rows:
            d = parse_dt(row.get("latest"))
            if d:
                out[key(row.get("agency"), row.get("required_report_name"))] = d
        if len(rows) < 5000:
            break
        offset += 5000
    return out


def classify(m: dict, last_filed: date | None, today: date) -> tuple[str, int | None]:
    """Josh Greenman's status rules, in his precedence order."""
    desc = (m.get("description") or "")
    low = desc.lower()
    if "waiv" in low:
        return "waived", None
    if "(completed" in low or ((m.get("frequency") or "").strip().lower() == "once"
                               and last_filed):
        return "completed", None
    if any(w in low for w in ("repealed", "discontinued", "no longer required",
                              "superseded")):
        return "superseded", None
    if not last_filed:
        return "never filed", None
    days = freq_days(m.get("frequency"))
    if not days:
        return "unscheduled", None
    late = (today - last_filed).days - days
    return ("overdue", int(late)) if late > 0 else ("current", None)


def main() -> None:
    today = date.today()
    mandates = requests.get(MANDATES, params={"$limit": 5000}, timeout=180).json()
    filed = fetch_grouped(f"report_type != '{LATE_NOTICE}'")
    notices = fetch_grouped(f"report_type = '{LATE_NOTICE}'")
    print(f"DORIS: {len(mandates)} mandates, {len(filed)} filed report groups, "
          f"{len(notices)} late-notice groups")

    ours = json.loads((DATA / "obligations.json").read_text())
    our_reports: dict[str, list] = defaultdict(list)
    for o in ours["obligations"]:
        if o.get("deliverable_type") == "report":
            our_reports[o["law_number_display"]].append(o)

    by_law: dict[str, list] = defaultdict(list)
    for m in mandates:
        law = law_of(m.get("local_law"))
        if law:
            by_law[law].append(m)

    out: dict[str, dict] = {}
    matched_mandates = 0
    for law, obs in our_reports.items():
        cands = by_law.get(law) or []
        if not cands:
            continue
        used: set[int] = set()
        for o in obs:
            ours_tok = tokens(o.get("action_summary")) | tokens(o.get("quote"))
            best, best_score = None, 0.0
            for i, m in enumerate(cands):
                if i in used and len(cands) >= len(obs):
                    continue
                mt = tokens(m.get("name"))
                if not mt:
                    continue
                score = len(mt & ours_tok) / len(mt)
                if score > best_score:
                    best, best_score = i, score
            # A single mandate under a single-report law needs no name evidence.
            # Everywhere else demand real overlap: an audit found a record paired
            # with a same-law mandate it did not match, which published a filing
            # status for the wrong duty. A missing status is honest; a wrong one
            # is not.
            solo = len(cands) == 1 and len(obs) == 1
            if best is None or (not solo and best_score < 0.34):
                continue
            # Never reuse a mandate for a second obligation when the law has
            # several: that is how one duty's filing date lands on another's.
            if best in used and len(cands) > 1:
                continue
            used.add(best)
            m = cands[best]
            k = key(m.get("agency"), m.get("name"))
            last = max([d for d in (parse_dt(m.get("last_published_date")), filed.get(k))
                        if d and d <= today] or [None], default=None)
            status, days_late = classify(m, last, today)
            notice = notices.get(k)
            out[o["obligation_id"]] = {
                "status": status,
                "days_late": days_late,
                "last_filed": last.isoformat() if last else None,
                "frequency": m.get("frequency"),
                "doris_agency": m.get("agency"),
                "doris_name": m.get("name"),
                "doris_url": (m.get("see_all_reports") or {}).get("url"),
                "late_notice": notice.isoformat() if notice else None,
                "match_confidence": round(best_score, 2),
            }
            matched_mandates += 1

    counts: dict[str, int] = defaultdict(int)
    for v in out.values():
        counts[v["status"]] += 1
    payload = {
        "generated": today.isoformat(),
        "source": "NYC Open Data 9azj-tmjp (mandates) + xip9-pe9k (filings), DORIS",
        "method_credit": {
            "name": "Josh Greenman, NYC Overdue Reports",
            "dashboard": "https://joshgreenman1973.github.io/nyc-overdue-reports/",
            "code": "https://github.com/joshgreenman1973/nyc-overdue-reports",
        },
        "matched": len(out),
        "status_counts": dict(sorted(counts.items(), key=lambda x: -x[1])),
        "filings": out,
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"matched {len(out)} of {sum(len(v) for v in our_reports.values())} "
          f"report obligations to a DORIS mandate")
    for k2, v in payload["status_counts"].items():
        print(f"  {k2:14s} {v:5d}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
