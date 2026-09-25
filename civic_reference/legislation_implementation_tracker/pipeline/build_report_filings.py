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
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUT = DATA / "report_filings.json"

sys.path.insert(0, str(HERE.parent.parent.parent / "pipeline"))
import agency_canon  # noqa: E402
from agency_canon import canonicalize  # noqa: E402

# DORIS names most agencies inverted, "Name, Department of (ABBR)", and puts
# the short form in a trailing parenthetical that is not always a clean
# 2-6 letter abbreviation ("NYC Aging", "H+H", "OIG-NYPD", "Sustainability").
# Capture whatever is inside the trailing parens verbatim and let
# canonicalize() judge it, rather than pre-filtering by shape.
_DORIS_TAIL = re.compile(r"\(([^()]+)\)\s*$")


def doris_canon(agency: str | None) -> str | None:
    """Resolve a DORIS agency string (e.g. 'Education, Department of (DOE)',
    'Aging, Department for the (NYC Aging)') to the same canonical code
    agency_canon.py uses for our obligations, so NYCPS/DOE and every other
    alias line up on one code."""
    if not agency:
        return None
    base = agency.strip()
    m = _DORIS_TAIL.search(base)
    stripped = _DORIS_TAIL.sub("", base).strip().rstrip(",").strip()
    candidates = []
    if m:
        candidates.append(m.group(1).strip())
    if stripped:
        candidates.append(stripped)
        # "Aging, Department for the" -> "Department for the Aging":
        # DORIS inverts "Head, Department of the Head" for alphabetizing;
        # un-invert on the first comma and try that too.
        if "," in stripped:
            head, _, tail = stripped.partition(",")
            candidates.append(f"{tail.strip()} {head.strip()}".strip())
    candidates.append(base)
    for cand in candidates:
        canon, _ = canonicalize(cand)
        if canon:
            return canon
    return None


# Duty agency vs. DORIS filer are formally distinct entities that are, in
# practice, the same office: a duty on the parent is filed under the
# division that actually runs the program. Naming variants of the *same*
# office (e.g. "Sustainability" for MOCEJ, "Office of Civil Justice" for
# HRA, DOB's building energy office) are fixed in agency_crosswalk.json
# instead, so doris_canon() and canonicalize() already agree on those
# without needing an entry here.
UMBRELLA: dict[str, set[str]] = {
    "DSS": {"HRA", "DHS"},   # HRA and DHS are divisions of DSS; DORIS often
                              # files their mandates under the division.
    "311": {"OTI"},          # NYC311 is run by OTI; DORIS files under OTI.
    # HRA and DHS share DSS's administration, and DORIS files some DHS
    # shelter reports under HRA (5534271-08, housing specialists) and back
    "DHS": {"HRA", "DSS"},
    "HRA": {"DHS", "DSS"},
}
# "Mayor's Office" is a catch-all our extraction uses when a law just says
# "the mayor" without naming a specific office. It may legitimately match
# any DORIS mayoral office, but only when the report name itself is a
# strong match -- unlike a real single-office duty, a generic "the mayor"
# duty gives no agency signal at all.
_MAYORS_OFFICE = "Mayor's Office"
_MAYORAL_MIN_SCORE = 0.5
_MAYORAL_CANONS = {
    a["canonical"] for a in agency_canon._cw["agencies"]
    if a.get("org_type") == "Mayoral Office"
}


def agency_ok(ours_canon: str, doris_c: str | None) -> bool:
    if not doris_c:
        return False
    if doris_c == ours_canon:
        return True
    if doris_c in UMBRELLA.get(ours_canon, ()):
        return True
    if ours_canon == _MAYORS_OFFICE and doris_c in _MAYORAL_CANONS:
        return True
    return False

MANDATES = "https://data.cityofnewyork.us/resource/9azj-tmjp.json"
FILINGS = "https://data.cityofnewyork.us/resource/xip9-pe9k.json"
LATE_NOTICE = "Delinquent Report Notice"

# Josh Greenman's conversion: month = 30.44 days, year = 365.25.
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30.44, "year": 365.25}
_FREQ = re.compile(r"every\s+(\d+)\s+(day|week|month|year)s?", re.I)
_LL = re.compile(r"LL\s*(\d+)\s*/\s*(\d{4})", re.I)
_STOP = {"the", "of", "a", "an", "and", "or", "to", "for", "on", "in", "by",
         "report", "reports", "reporting", "annual", "annually", "each", "such",
         "shall", "submit", "publish", "post", "provide", "city", "new", "york",
         # Procedural/temporal filler that shows up across many unrelated
         # DORIS report names and inflates token overlap without saying
         # anything about the report's actual subject.
         "regarding", "immediately", "immediate", "preceding", "fiscal",
         "calendar", "during", "year", "years"}
# Cue words whose only job is to negate the phrase that follows. A shared
# cue alone is not evidence of a match (it is common boilerplate, "shall
# not include...", unrelated to the report's subject); what matters is
# whether it negates the SAME shared word in both texts. See _polarity().
_NEGATORS = {"not", "except", "excluding", "outside", "unless", "otherthan"}
_NEG_WINDOW = 6


def freq_days(freq: str | None) -> float | None:
    m = _FREQ.match((freq or "").strip())
    return int(m.group(1)) * _UNIT_DAYS[m.group(2).lower()] if m else None


def norm(s: str | None) -> str:
    s = re.sub(r"\([^)]*\)", " ", (s or ""))
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def key(agency: str | None, name: str | None) -> str:
    return f"{re.sub(r'  +', ' ', norm(agency))}|{re.sub(r'  +', ' ', norm(name))}"


def _destem(w: str) -> str:
    """Fold cadence adverbs onto their adjective ("triennially" ->
    "triennial", "quarterly" -> "quarter") so a duty phrased as a cadence
    ("every three years") can still line up with a DORIS name that uses
    the adjective form. Narrow on purpose: -ly only, and only for words
    long enough that the strip can't collide with something short."""
    if w.endswith("ly") and len(w) > 5:
        return w[:-2]
    return w


def tokens(s: str | None) -> set[str]:
    out = set()
    for w in norm(s).split():
        if len(w) <= 2:
            continue
        w = _destem(w)
        if w in _STOP:
            continue
        out.add(w)
    return out


def _polarity(raw: str | None, anchor: str) -> bool:
    """True if `anchor` appears in `raw` with a negator within a few words
    before it ("...jail other than a jail located on Rikers Island" negates
    "rikers"; "...jail on Rikers Island" does not). Used to keep a shared
    word from counting as a match when the two texts disagree on whether
    it is negated, e.g. "Jails on Rikers Island" vs "Jails Not on Rikers
    Island" sharing every other word."""
    words = norm(re.sub(r"other\s+than", "otherthan", raw or "", flags=re.I)).split()
    for idx, w in enumerate(words):
        if w == anchor:
            start = max(0, idx - _NEG_WINDOW)
            if any(x in _NEGATORS for x in words[start:idx]):
                return True
    return False


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
        # How many of this law's own report obligations belong to each
        # agency, so the "don't recheck a used mandate" rule below can be
        # scoped to that agency instead of every obligation on the law
        # (that mismatch let 5839385-15, LL 12/2023, escape it and steal a
        # mandate a same-agency sibling was also competing for).
        obs_by_agency: dict[str, int] = defaultdict(int)
        for o2 in obs:
            c2, _ = canonicalize(o2.get("agency"))
            if c2:
                obs_by_agency[c2] += 1
        for o in obs:
            ours_canon, _ = canonicalize(o.get("agency"))
            if not ours_canon:
                # An obligation whose actor never resolved to a real agency
                # ("not specified in the law text", "each covered agency", ...)
                # gets no DORIS link and an explicit "unknown" status, never a
                # name-token guess.
                out[o["obligation_id"]] = {
                    "status": "unknown",
                    "days_late": None,
                    "last_filed": None,
                    "frequency": None,
                    "doris_agency": None,
                    "doris_name": None,
                    "doris_url": None,
                    "late_notice": None,
                    "match_confidence": None,
                }
                continue
            agency_cands = [i for i, m in enumerate(cands)
                            if agency_ok(ours_canon, doris_canon(m.get("agency")))]
            if not agency_cands:
                continue
            our_raw = f"{o.get('action_summary') or ''} {o.get('quote') or ''}"
            ours_tok = tokens(our_raw)
            own_obs = obs_by_agency.get(ours_canon, 0)
            best, best_score = None, 0.0
            for i in agency_cands:
                m = cands[i]
                if i in used and len(agency_cands) >= own_obs:
                    continue
                mt = tokens(m.get("name"))
                if not mt:
                    continue
                overlap = mt & ours_tok
                if not overlap:
                    continue
                name_raw = m.get("name") or ""
                if any(_polarity(name_raw, a) != _polarity(our_raw, a) for a in overlap):
                    continue
                score = len(overlap) / len(mt)
                if score > best_score:
                    best, best_score = i, score
            # A single agency-matched mandate under a single-report law needs
            # no name evidence. Everywhere else demand real overlap: an audit
            # found a record paired with a same-law mandate it did not match,
            # which published a filing status for the wrong duty. A missing
            # status is honest; a wrong one is not. The "Mayor's Office"
            # catch-all carries no agency signal of its own, so it needs a
            # stronger name match before it borrows a mayoral office's record.
            solo = len(agency_cands) == 1 and len(obs) == 1
            min_score = _MAYORAL_MIN_SCORE if ours_canon == _MAYORS_OFFICE else 0.34
            if best is None or (not solo and best_score < min_score):
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
        "matched": sum(v for k, v in counts.items() if k != "unknown"),
        "status_counts": dict(sorted(counts.items(), key=lambda x: -x[1])),
        "filings": out,
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"matched {payload['matched']} of "
          f"{sum(len(v) for v in our_reports.values())} "
          f"report obligations to a DORIS mandate ({counts.get('unknown', 0)} unknown)")
    for k2, v in payload["status_counts"].items():
        print(f"  {k2:14s} {v:5d}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
