#!/usr/bin/env python3
"""
Refresh data/council_members.json (the roster every member builder keys on)
from the jehiah/nyc_legislation archive's people/ files, which mirror the
Legistar OfficeRecords for body "City Council".

What is regenerated for every roster member (matched by intro_nyc_slug):
  terms         list of continuous stints [start, end], from the archive
  term_start    start of the latest continuous stint (a gap over 31 days
                starts a new stint, so Brewer's 2002-2013 and 2022- are two)
  term_end      end of the latest stint; omitted while the member is current
  start_year    year of term_start. The Council Members page labels it
                "since <start_year>", so it is the start of the CURRENT
                continuous stint, not first-ever service
  first_year    first year of any service (new field; Brewer 2002)
  end_year      year of term_end, null while current
  sessions      standard Council sessions overlapping any stint
  current       latest stint has no end or ends after today

Kept as written (the archive has no value for them): party, notes, canonical
name, email, website, district_office, legistar_person_id, ids. The Public
Advocate's records (MemberType PRIMARY PUBLIC ADVOCATE) are not Council
membership and are ignored.

With --council-site (default on; network errors only warn) the current
district/borough/party list at https://council.nyc.gov/districts/ is read:
borough is updated from it ("Staten Island, Brooklyn" becomes
"Staten Island/Brooklyn"); a district whose listed name does not contain the
roster member's last name, or a party mismatch, is printed as a CONFLICT and
not applied.

A person with Council records in or after 2014 who is not in the roster is
added as a stub (district and party from the site when the name matches) and
reported as NEW MEMBER; the build exits 1 so a human fills the gaps.

Usage:
    python3 pipeline/build_council_roster.py --archive /path/to/nyc_legislation
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROSTER = HERE.parent / "data" / "council_members.json"
SITE_URL = "https://council.nyc.gov/districts/"
FIRST_TRACKED = date(2014, 1, 1)

# Hand-verified values the archive gets wrong (the archive's Felder record
# concatenates a Manhattan ZIP onto his Brooklyn office).
FIXES = {
    "simcha-felder": {"district_office": "1514 60th Street, Room 703, Brooklyn, NY 11219"},
}


def sessions_list() -> list[tuple[str, date, date]]:
    out = [("2014-2017", date(2014, 1, 1), date(2017, 12, 31)),
           ("2018-2021", date(2018, 1, 1), date(2021, 12, 31)),
           ("2022-2023", date(2022, 1, 1), date(2023, 12, 31)),
           ("2024-2025", date(2024, 1, 1), date(2025, 12, 31)),
           ("2026-2029", date(2026, 1, 1), date(2029, 12, 31))]
    y = 2030
    while y < 2050:
        out.append((f"{y}-{y + 3}", date(y, 1, 1), date(y + 3, 12, 31)))
        y += 4
    return out


def pdate(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def council_records(person: dict) -> list[tuple[date, date | None]]:
    recs = []
    for r in person.get("OfficeRecords") or []:
        if (r.get("BodyName") or "").strip() != "City Council":
            continue
        if "PUBLIC ADVOCATE" in (r.get("MemberType") or ""):
            continue
        s = pdate(r.get("Start"))
        if s:
            recs.append((s, pdate(r.get("End"))))
    return sorted(set(recs), key=lambda x: x[0])


def stints(recs: list[tuple[date, date | None]]) -> list[list]:
    out: list[list] = []
    for s, e in recs:
        if out and out[-1][1] is not None and s <= out[-1][1] + timedelta(days=31):
            if e is None or e > out[-1][1]:
                out[-1][1] = e
        else:
            out.append([s, e])
    return out


def fetch_site() -> dict[int, dict]:
    try:
        req = urllib.request.Request(SITE_URL, headers={"User-Agent": "nycur-roster-check"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except Exception as exc:  # network is optional
        print(f"WARNING: could not read {SITE_URL}: {exc}", file=sys.stderr)
        return {}
    rows: dict[int, dict] = {}
    for tr in re.split(r"<tr\b", html)[1:]:
        cells = [c.strip() for c in re.split(r"<[^>]+>", tr) if c.strip()]
        for i, c in enumerate(cells[:3]):
            if re.fullmatch(r"\d{1,2}", c) and i + 3 < len(cells):
                d = int(c)
                if 1 <= d <= 51:
                    rows[d] = {"name": cells[i + 1], "borough": cells[i + 2],
                               "party": cells[i + 3]}
                break
    return rows


def norm_party(p: str) -> str:
    p = (p or "").lower()
    return "democratic" if p.startswith("democrat") else p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--archive", required=True, help="jehiah/nyc_legislation checkout (people/)")
    ap.add_argument("--no-council-site", action="store_true",
                    help="skip the council.nyc.gov district list check")
    args = ap.parse_args()
    people = Path(args.archive) / "people"
    if not people.is_dir():
        print(f"ERROR: {people} not found", file=sys.stderr)
        return 1

    today = date.today()
    doc = json.loads(ROSTER.read_text())
    members = doc["members"]
    sess = sessions_list()
    site = {} if args.no_council_site else fetch_site()
    changed: list[str] = []
    conflicts: list[str] = []

    def apply(m: dict, person: dict) -> None:
        st = stints(council_records(person))
        if not st:
            conflicts.append(f"{m['full_name']}: no City Council records in archive")
            return
        last = st[-1]
        cur = last[1] is None or last[1] > today
        new = {
            "terms": [[s.isoformat(), e.isoformat() if e else None] for s, e in st],
            "term_start": last[0].isoformat(),
            "start_year": last[0].year,
            "first_year": st[0][0].year,
            "end_year": None if cur else last[1].year,
            "current": cur,
            "sessions": [n for n, a, b in sess
                         if any(s <= b and (e is None or e >= a) for s, e in st)],
        }
        if cur:
            m.pop("term_end", None)
        else:
            new["term_end"] = last[1].isoformat()
        for k, v in new.items():
            if m.get(k) != v:
                changed.append(f"{m['full_name']}: {k} {m.get(k)!r} -> {v!r}")
                m[k] = v

    by_slug = {m["intro_nyc_slug"]: m for m in members if m.get("intro_nyc_slug")}
    for slug, m in by_slug.items():
        path = people / f"{slug}.json"
        if not path.exists():
            conflicts.append(f"{m['full_name']}: archive people/{slug}.json missing")
            continue
        apply(m, json.loads(path.read_text()))
        for k, v in (FIXES.get(slug) or {}).items():
            if m.get(k) != v:
                changed.append(f"{m['full_name']}: {k} {m.get(k)!r} -> {v!r}")
                m[k] = v

    # Anyone with Council service since 2014 who is not in the roster
    new_members = []
    for path in sorted(people.glob("*.json")):
        person = json.loads(path.read_text())
        slug = person.get("Slug")
        if slug in by_slug:
            continue
        recs = council_records(person)
        if not recs or all(e is not None and e < FIRST_TRACKED for _, e in recs):
            continue
        name = re.sub(r"\s+", " ", person.get("FullName") or "").strip()
        stub = {"full_name": name, "canonical_name": name,
                "last_name": (person.get("LastName") or "").strip(),
                "party": None, "district": None, "borough": None,
                "notes": "Added from the Legistar archive; party, district and "
                         "borough need a human check",
                "intro_nyc_slug": slug, "legistar_person_id": person.get("ID"),
                "email": person.get("Email") or None,
                "website": person.get("WWW") or None,
                "district_office": None}
        apply(stub, person)
        members.append(stub)
        new_members.append(stub)
        print(f"NEW MEMBER: {name} ({slug}) added as a stub")

    # council.nyc.gov: current districts
    for m in members:
        if not m.get("current"):
            continue
        row = site.get(m.get("district") or 0)
        if not row:
            if site:
                conflicts.append(f"{m['full_name']}: district {m.get('district')} not on the site list")
            continue
        if strip_accents(m["last_name"]).lower() not in strip_accents(row["name"]).lower():
            conflicts.append(f"D{m['district']}: roster {m['full_name']} vs site {row['name']}")
            continue
        if norm_party(m.get("party")) != norm_party(row["party"]):
            conflicts.append(f"D{m['district']} {m['full_name']}: party {m.get('party')} vs site {row['party']}")
        boro = "/".join(b.strip() for b in row["borough"].split(","))
        if m.get("borough") != boro:
            changed.append(f"{m['full_name']}: borough {m.get('borough')!r} -> {boro!r}")
            m["borough"] = boro

    doc["members"] = members
    doc["last_refreshed"] = today.isoformat()
    doc["refreshed_from"] = ["https://github.com/jehiah/nyc_legislation (people/)"] + \
        ([SITE_URL] if site else [])
    ROSTER.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"Roster: {len(members)} members, {sum(1 for m in members if m['current'])} current, "
          f"{len(changed)} field changes, {len(conflicts)} conflicts, {len(new_members)} new")
    for c in changed:
        print("  changed:", c)
    for c in conflicts:
        print("  CONFLICT:", c)
    return 1 if new_members else 0


if __name__ == "__main__":
    sys.exit(main())
