#!/usr/bin/env python3
"""Build per-member context for Council Member profiles: committees and
caucus assignments, meeting attendance, the agencies their enacted laws put
to work, and (for current members only) their district's 311 picture.

Sources:
  - jehiah/nyc_legislation archive (https://github.com/jehiah/nyc_legislation):
    people/<slug>.json for OfficeRecords (committees, subcommittees, caucuses,
    delegations, chair roles); events/<year>/*.json for roll call attendance.
    Slug == roster intro_nyc_slug; roll call entries carry the same Slug.
  - data/members.json for the roster and each member's sponsored legislation.
  - data/agencies.json for the enacted-law duties/powers each agency carries.
  - NYC Open Data 311 Service Requests (erm2-nwe9) for the last 12 full
    months, grouped by council district, complaint type, and agency.

Usage:
    python3 pipeline/build_member_context.py --archive /path/to/nyc_legislation

Output: data/member_context.json (compact JSON).
No Anthropic API calls. Live network calls go to data.cityofnewyork.us only;
set SOCRATA_APP_TOKEN to use an app token, otherwise runs anonymous.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
DATA = BASE / "data"
MEMBERS_PATH = DATA / "members.json"
AGENCIES_PATH = DATA / "agencies.json"
OUT_PATH = DATA / "member_context.json"

TODAY = date.today()
FIRST_YEAR = 2014  # trackers and attendance coverage start here

SOCRATA_BASE = "https://data.cityofnewyork.us/resource/{}.json"
SOCRATA_DATASET = "erm2-nwe9"
SOCRATA_TOKEN = os.environ.get("SOCRATA_APP_TOKEN")

# 311 "agency" code (uppercase) -> agencies.json id, exact matches plus a
# small explicit dict for codes whose id isn't the lowercased code.
AGENCY_311_OVERRIDES = {
    "EDC": "nycedc",
    "DOE": "nycps",
}

CHAIR_RE = re.compile(r"chair", re.I)
COCHAIR_RE = re.compile(r"co-?\s*chair", re.I)
VICECHAIR_RE = re.compile(r"vice\s*chair", re.I)
PARTY_CONFERENCE_RE = re.compile(r"(democratic|republican).*conference", re.I)
# roll-call values that are neither attendance nor absence (recusal, suspension)
NOT_COUNTED_RE = re.compile(r"conflict|suspended|non-voting", re.I)
# "committee roll calls" = committees and subcommittees only, not conference,
# caucus or borough delegation meetings
COMMITTEE_BODY_RE = re.compile(r"^(sub)?committee\b", re.I)
EXCUSED_RE = re.compile(
    r"excused|medical|maternity|paternity|parental|bereavement|jury|leave", re.I
)


# ── Socrata helpers (mirrors build_agency_profiles.py) ──────────────────


def _headers():
    h = {"User-Agent": "nycuriosity-member-context"}
    if SOCRATA_TOKEN:
        h["X-App-Token"] = SOCRATA_TOKEN
    return h


def socrata_get(params: dict, timeout: int = 180) -> list[dict]:
    url = SOCRATA_BASE.format(SOCRATA_DATASET)
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=_headers(), timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
    return []


def socrata_page(params: dict, page_limit: int = 20000) -> list[dict]:
    """Page a Socrata query with $limit/$offset until an empty page."""
    rows: list[dict] = []
    offset = 0
    while True:
        p = dict(params)
        p["$limit"] = page_limit
        p["$offset"] = offset
        batch = socrata_get(p)
        rows.extend(batch)
        if len(batch) < page_limit:
            break
        offset += page_limit
        time.sleep(0.1)
    return rows


# ── committees / caucuses ────────────────────────────────────────────────


def body_excluded(body: str) -> bool:
    b = body.strip()
    if b == "City Council":
        return True
    if b == "Committee of the Whole":
        return True
    if PARTY_CONFERENCE_RE.search(b):
        return True
    return False


def is_caucus(body: str) -> bool:
    b = body.strip()
    return b.startswith("Caucus") or "Delegation" in b


def chair_title(title: str) -> str | None:
    t = title or ""
    if COCHAIR_RE.search(t):
        return "Co-Chair"
    if VICECHAIR_RE.search(t):
        return "Vice Chair"
    if CHAIR_RE.search(t):
        return "Chair"
    return None


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def council_terms(office_records: list[dict]) -> list[tuple[date, date]]:
    terms = set()
    for r in office_records:
        if (r.get("BodyName") or "").strip() != "City Council":
            continue
        s, e = parse_date(r.get("Start")), parse_date(r.get("End"))
        if s and e:
            terms.add((s, e))
    return sorted(terms)


def find_term(terms: list[tuple[date, date]], d: date) -> tuple[date, date] | None:
    for t in terms:
        if t[0] <= d <= t[1]:
            return t
    return None


def build_committees(office_records: list[dict]) -> dict | None:
    terms = council_terms(office_records)
    if not terms:
        return None

    target = find_term(terms, TODAY)
    if not target:
        past = [t for t in terms if t[0] <= TODAY]
        target = max(past, key=lambda t: t[0]) if past else min(terms, key=lambda t: t[0])

    def term_of(d: date) -> tuple[date, date]:
        t = find_term(terms, d)
        if t:
            return t
        # fall back to the nearest term by Start
        return min(terms, key=lambda t: abs((t[0] - d).days))

    filtered = [
        r for r in office_records
        if not body_excluded(r.get("BodyName") or "") and parse_date(r.get("Start"))
    ]

    chairs_map: dict[str, str] = {}
    members_set: set[str] = set()
    caucus_map: dict[str, tuple[date, str]] = {}  # body -> (start, title)
    past_map: dict[str, dict] = {}

    for r in filtered:
        body = (r.get("BodyName") or "").strip()
        start = parse_date(r.get("Start"))
        end = parse_date(r.get("End"))
        title = r.get("Title") or ""
        ct = chair_title(title)
        rec_term = term_of(start)

        if rec_term == target:
            if is_caucus(body):
                prev = caucus_map.get(body)
                if not prev or start >= prev[0]:
                    caucus_map[body] = (start, ct or "Member")
            elif ct:
                chairs_map[body] = ct
            else:
                members_set.add(body)
        else:
            if ct:
                sy = start.year
                ey = end.year if end else None
                prev = past_map.get(body)
                if prev:
                    prev["start_year"] = min(prev["start_year"], sy)
                    if ey is not None:
                        prev["end_year"] = max(prev["end_year"] or ey, ey)
                    prev["title"] = ct
                else:
                    past_map[body] = {"body": body, "title": ct, "start_year": sy, "end_year": ey}

    members_list = sorted(b for b in members_set if b not in chairs_map)
    chairs = [{"body": b, "title": t} for b, t in sorted(chairs_map.items())]
    caucuses = [{"body": b, "title": t} for b, (_s, t) in sorted(caucus_map.items())]
    past_chairs = sorted(past_map.values(), key=lambda x: (x["start_year"], x["body"]))

    sy, ey = target[0].year, target[1].year
    term_label = f"{sy}–{ey} term"

    return {
        "term_label": term_label,
        "chairs": chairs,
        "members": members_list,
        "caucuses": caucuses,
        "past_chairs": past_chairs,
    }


# ── attendance ────────────────────────────────────────────────────────────


def session_for_year(sessions: list[str], year: int) -> str | None:
    for s in sessions:
        m = re.match(r"^(\d{4})-(\d{4})$", s)
        if not m:
            continue
        if int(m.group(1)) <= year <= int(m.group(2)):
            return s
    return None


def classify_value(value: str) -> str:
    v = (value or "").strip()
    if v == "Present":
        return "present"
    if v == "Absent":
        return "absent"
    if EXCUSED_RE.search(v):
        return "excused"
    return "other"


def build_attendance(archive: Path, slug_to_member: dict[str, str],
                      sessions_by_member: dict[str, list[str]]) -> tuple[dict, dict]:
    events_dir = archive / "events"
    per_member: dict[str, dict] = {}
    vocab: dict[str, int] = defaultdict(int)
    events_parsed = 0
    events_with_rollcall = 0

    def bucket(mid: str):
        if mid not in per_member:
            per_member[mid] = {
                "stated": {"present": 0, "total": 0, "excused": 0, "absent": 0},
                "committee": {"present": 0, "total": 0, "excused": 0, "absent": 0},
                "by_session": defaultdict(lambda: {
                    "stated_present": 0, "stated_total": 0,
                    "committee_present": 0, "committee_total": 0,
                }),
            }
        return per_member[mid]

    for ydir in sorted(events_dir.iterdir()):
        if not ydir.is_dir() or not ydir.name.isdigit() or int(ydir.name) < FIRST_YEAR:
            continue
        for path in ydir.glob("*.json"):
            try:
                ev = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            events_parsed += 1
            body = (ev.get("BodyName") or "").strip()
            d = parse_date(ev.get("Date"))
            if not d or d.year < FIRST_YEAR:
                continue
            roll = None
            for item in ev.get("Items") or []:
                rc = item.get("RollCall")
                if rc:
                    roll = rc
                    break
            if not roll:
                continue
            events_with_rollcall += 1
            if body == "City Council":
                key = "stated"
            elif COMMITTEE_BODY_RE.match(body):
                key = "committee"
            else:
                continue
            seen_in_event: set[str] = set()   # the archive repeats some entries
            for entry in roll:
                mid = slug_to_member.get(entry.get("Slug"))
                if not mid or mid in seen_in_event:
                    continue
                seen_in_event.add(mid)
                value = (entry.get("Value") or "").strip()
                vocab[value] += 1
                if NOT_COUNTED_RE.search(value):
                    continue
                cls = classify_value(value)
                rec = bucket(mid)
                rec[key]["total"] += 1
                if cls == "present":
                    rec[key]["present"] += 1
                elif cls == "absent":
                    rec[key]["absent"] += 1
                elif cls == "excused":
                    rec[key]["excused"] += 1
                sess = session_for_year(sessions_by_member.get(mid, []), d.year)
                if sess:
                    sb = rec["by_session"][sess]
                    sb[key + "_total"] += 1
                    if cls == "present":
                        sb[key + "_present"] += 1

    out: dict[str, dict] = {}
    for mid, rec in per_member.items():
        by_session = [
            {"session": s, **vals}
            for s, vals in sorted(rec["by_session"].items())
        ]
        out[mid] = {
            "stated": rec["stated"],
            "committee": rec["committee"],
            "by_session": by_session,
        }
    stats = {
        "events_parsed": events_parsed,
        "events_with_rollcall": events_with_rollcall,
        "vocabulary": dict(sorted(vocab.items(), key=lambda kv: -kv[1])),
    }
    return out, stats


# ── agencies ──────────────────────────────────────────────────────────────


def build_agencies_for_members(members: list[dict], agencies: list[dict]) -> dict[str, list]:
    member_impl: dict[str, dict[str, bool]] = {}
    for m in members:
        impl = {}
        for leg in m.get("legislation", []):
            if leg["k"].startswith("impl:"):
                impl[leg["k"].split(":", 1)[1]] = bool(leg.get("prime"))
        member_impl[m["id"]] = impl

    out: dict[str, list] = {}
    for m in members:
        mid = m["id"]
        impl = member_impl[mid]
        if not impl:
            out[mid] = []
            continue
        rows = []
        for a in agencies:
            laws = a.get("trackers", {}).get("laws") or []
            hit = [law for law in laws if law["matter_id"] in impl]
            if not hit:
                continue
            duties = sum(law.get("duties", 0) for law in hit)
            powers = sum(law.get("powers", 0) for law in hit)
            prime_count = sum(1 for law in hit if impl.get(law["matter_id"]))
            rows.append({
                "id": a["id"],
                "name": a["name"],
                "laws": len(hit),
                "laws_prime": prime_count,
                "duties": duties,
                "powers": powers,
            })
        rows.sort(key=lambda r: -(r["duties"] + r["powers"]))
        out[mid] = rows[:12]
    return out


# ── 311 ───────────────────────────────────────────────────────────────────


def month_windows(window_start: str, window_end: str):
    """(first-of-month, first-of-next-month) pairs covering the window."""
    cur, end = date.fromisoformat(window_start), date.fromisoformat(window_end)
    while cur < end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield cur, nxt
        cur = nxt


def socrata_page_retry(params: dict, tries: int = 2) -> list[dict]:
    """311 is ~3.8M rows a year and the API's speed varies by the hour: retry
    a timed-out month once before failing the build."""
    for i in range(tries):
        try:
            return socrata_page(params)
        except requests.exceptions.RequestException:
            if i == tries - 1:
                raise
            time.sleep(30)


def fetch_311(window_start: str, window_end: str) -> tuple[list[dict], int]:
    # one call per month: a single 12-month grouped call timed out (180 s) on
    # Sep 24 2026; build_districts_311 sums rows that repeat across months
    rows: list[dict] = []
    for cur, nxt in month_windows(window_start, window_end):
        rows.extend(socrata_page_retry({
            "$select": "council_district, complaint_type, agency, count(*) as n",
            "$group": "council_district, complaint_type, agency",
            "$where": (f"created_date >= '{cur.isoformat()}' and created_date < '{nxt.isoformat()}' "
                       "and council_district IS NOT NULL"),
            "$order": "council_district, complaint_type, agency",
        }))
    return rows, len(rows)


def fetch_311_monthly(window_start: str, window_end: str) -> tuple[list[dict], int]:
    """One grouped query per calendar month (each covers ~1/12 of the
    window), since a single 12-month grouped query times out server-side."""
    rows: list[dict] = []
    start = date.fromisoformat(window_start)
    end = date.fromisoformat(window_end)
    cur = start
    while cur < end:
        ny, nm = cur.year, cur.month + 1
        if nm > 12:
            nm -= 12
            ny += 1
        nxt = date(ny, nm, 1)
        where = (
            f"created_date >= '{cur.isoformat()}' and created_date < '{nxt.isoformat()}' "
            "and council_district IS NOT NULL"
        )
        # the month is fixed by the where clause; grouping on date_trunc_ym
        # made Socrata time out (180 s), district-only grouping takes ~5 s
        batch = socrata_page_retry({
            "$select": "council_district, count(*) as n",
            "$group": "council_district",
            "$where": where,
            "$order": "council_district",
        })
        for r in batch:
            r["month"] = cur.isoformat()
        rows.extend(batch)
        cur = nxt
    return rows, len(rows)


def build_districts_311_monthly(rows: list[dict]) -> dict[str, list[dict]]:
    per_district: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        d = r.get("council_district")
        month = r.get("month")
        if not d or not month:
            continue
        ym = month[:7]
        per_district[str(int(d))][ym] = per_district[str(int(d))].get(ym, 0) + int(r.get("n", 0))
    out = {}
    for d, months in per_district.items():
        out[d] = [{"month": ym, "n": n} for ym, n in sorted(months.items())]
    return out


def agency_311_to_id(code: str, agency_ids: set[str]) -> str | None:
    if not code:
        return None
    low = code.lower()
    if low in agency_ids:
        return low
    return AGENCY_311_OVERRIDES.get(code.upper())


def build_districts_311(rows: list[dict], agency_ids: set[str]) -> dict:
    per_district: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "types": defaultdict(int), "agencies": defaultdict(int),
    })
    for r in rows:
        d = r.get("council_district")
        if not d:
            continue
        n = int(r.get("n", 0))
        rec = per_district[d]
        rec["total"] += n
        if r.get("complaint_type"):
            rec["types"][r["complaint_type"]] += n
        if r.get("agency"):
            rec["agencies"][r["agency"]] += n

    totals = sorted(((d, rec["total"]) for d, rec in per_district.items()), key=lambda kv: -kv[1])
    ranks = {d: i + 1 for i, (d, _t) in enumerate(totals)}

    out = {}
    for d, rec in per_district.items():
        top_types = sorted(rec["types"].items(), key=lambda kv: -kv[1])[:5]
        top_agencies = sorted(rec["agencies"].items(), key=lambda kv: -kv[1])[:5]
        out[str(int(d))] = {
            "total": rec["total"],
            "rank": ranks[d],
            "top_types": [{"type": t, "n": n} for t, n in top_types],
            "top_agencies": [
                {"code": a, "agency_id": agency_311_to_id(a, agency_ids), "n": n}
                for a, n in top_agencies
            ],
        }
    return out


# ── main ────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--archive", required=True,
                     help="path to a jehiah/nyc_legislation checkout "
                          "(must contain people/ and events/)")
    ap.add_argument("--skip-311", action="store_true",
                     help="skip the Socrata 311 fetch (for quick local iteration)")
    args = ap.parse_args()
    archive = Path(args.archive)
    if not (archive / "people").is_dir() or not (archive / "events").is_dir():
        print(f"ERROR: {archive} missing people/ or events/; pass the archive checkout root",
              file=sys.stderr)
        return 1

    doc = json.loads(MEMBERS_PATH.read_text())
    members = doc["members"]
    agencies_doc = json.loads(AGENCIES_PATH.read_text())
    agencies = agencies_doc["agencies"]
    agency_ids = {a["id"] for a in agencies}

    slug_to_member = {m["intro_nyc_slug"]: m["id"] for m in members if m.get("intro_nyc_slug")}
    sessions_by_member = {m["id"]: m.get("sessions") or [] for m in members}

    # committees
    committees_out: dict[str, dict] = {}
    people_dir = archive / "people"
    missing_people = []
    for m in members:
        slug = m.get("intro_nyc_slug")
        path = people_dir / f"{slug}.json"
        if not slug or not path.exists():
            missing_people.append(m["id"])
            continue
        person = json.loads(path.read_text())
        committees = build_committees(person.get("OfficeRecords") or [])
        if committees:
            committees_out[m["id"]] = committees

    # attendance
    print("Parsing roll calls from events/ (2014 on)...")
    attendance_out, att_stats = build_attendance(archive, slug_to_member, sessions_by_member)

    # agencies
    agencies_out = build_agencies_for_members(members, agencies)

    # 311
    citywide_311 = {}
    districts_311 = {}
    window_start = window_end = None
    if not args.skip_311:
        today = TODAY
        # last 12 full months: from the 1st of (today - 12 months) to the 1st of this month
        end_month_first = today.replace(day=1)
        y, mo = end_month_first.year, end_month_first.month - 12
        while mo <= 0:
            mo += 12
            y -= 1
        window_start = date(y, mo, 1).isoformat()
        window_end = end_month_first.isoformat()
        print(f"Fetching 311 grouped counts {window_start} to {window_end}...")
        rows, n_rows = fetch_311(window_start, window_end)
        print(f"Fetched {n_rows} grouped (district, type, agency) rows.")
        districts_311 = build_districts_311(rows, agency_ids)

        print("Fetching 311 monthly grouped counts...")
        monthly_rows, n_monthly_rows = fetch_311_monthly(window_start, window_end)
        print(f"Fetched {n_monthly_rows} grouped (district, month) rows.")
        monthly_by_district = build_districts_311_monthly(monthly_rows)
        for d, rec in districts_311.items():
            months = monthly_by_district.get(d, [])
            rec["monthly"] = months
            month_sum = sum(m["n"] for m in months)
            assert month_sum == rec["total"], (
                f"district {d}: monthly sum {month_sum} != total {rec['total']}")
        print(f"Monthly check OK: sum(monthly) == total for all "
              f"{len(districts_311)} districts.")

        district_totals = sorted(v["total"] for v in districts_311.values())
        median = district_totals[len(district_totals) // 2] if district_totals else 0
        citywide_311 = {
            "median_district_total": median,
            "districts": len(districts_311),
        }

        # the monthly (district) counts come from a separate query, so the
        # per-district assertion above is the independent check on the totals
        print(f"Sum of district totals: {sum(v['total'] for v in districts_311.values()):,}")

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {
            "council_archive": "https://github.com/jehiah/nyc_legislation",
            "socrata_311": "https://data.cityofnewyork.us/resource/erm2-nwe9.json",
        },
        "window_311": {"start": window_start, "end": window_end},
        "citywide_311": citywide_311,
        "members": {},
        "districts_311": districts_311,
    }
    all_member_ids = set(committees_out) | set(attendance_out) | set(agencies_out)
    for mid in all_member_ids:
        entry = {}
        if mid in committees_out:
            entry["committees"] = committees_out[mid]
        if mid in attendance_out:
            entry["attendance"] = attendance_out[mid]
        if agencies_out.get(mid):
            entry["agencies"] = agencies_out[mid]
        out["members"][mid] = entry

    OUT_PATH.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size:,} bytes)")
    print(f"Committees: {len(committees_out)} of {len(members)} members "
          f"({len(missing_people)} missing a people/ file: {missing_people})")
    print(f"Attendance: {len(attendance_out)} members with roll call rows; "
          f"{att_stats['events_parsed']} events parsed, "
          f"{att_stats['events_with_rollcall']} with a roll call")
    print(f"Vote/attendance value vocabulary: {att_stats['vocabulary']}")
    print(f"Agencies: {sum(1 for v in agencies_out.values() if v)} members with at least one agency row")
    return 0


if __name__ == "__main__":
    sys.exit(main())
