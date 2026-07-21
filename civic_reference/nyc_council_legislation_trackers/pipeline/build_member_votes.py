#!/usr/bin/env python3
"""
Build per-member voting records for the Council Members page from the
jehiah/nyc_legislation archive (https://github.com/jehiah/nyc_legislation).

Source of truth: introduction/<year>/<file>.json in that archive. Each bill
carries a History array; entries for committee and full-council votes carry a
Votes list of {FullName, Vote} records (the events/ files hold only attendance
roll calls, not per-item votes). Recorded votes on introductions go back to
2014 in the archive.

Vote vocabulary observed: Affirmative, Negative, Absent, plus leave/abstention
values (Excused, Medical, Maternity, Paternity, Parental, Bereavement,
Jury Duty, Conflict, Abstain, Non-voting) which are bucketed as "other".

Voter names are matched to data/members.json ids on normalized first+last
tokens (accents, periods, commas, suffixes stripped) plus an explicit alias
table for nickname mismatches; anything unresolved is reported, never guessed.

Output: data/member_votes.json (compact) —
  { generated_at, coverage,
    members: { <member id>: {
      totals: {affirmative, negative, absent, other},
      negative_votes: [ {file, matter_id, law, date, item} ... all of them ],
      recent: [ up to 30 most recent, same shape + "vote" ] } } }

matter_id / law are filled when the bill's file number matches an enacted law
in ../legislation_implementation_tracker/data/laws.json.

Usage:
    python3 pipeline/build_member_votes.py --archive /path/to/nyc_legislation
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
DATA = BASE / "data"
MEMBERS = DATA / "members.json"
LAWS = BASE.parent / "legislation_implementation_tracker" / "data" / "laws.json"
OUT = DATA / "member_votes.json"

FIRST_YEAR = 2014  # trackers cover 2014 on; archive vote detail starts here
RECENT_CAP = 30
ITEM_TITLE_MAX = 140

# Archive FullName (normalized "first last") -> roster member id, for
# nickname mismatches the token matcher cannot bridge.
ALIASES = {
    "deborah rose": "debi-rose",
    "james van bramer": "jimmy-van-bramer",
    "joseph borelli": "joe-borelli",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm_name(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = re.sub(r"[.,'’]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def name_keys(full: str) -> set[str]:
    n = norm_name(full)
    toks = n.split()
    keys = {n}
    if len(toks) >= 2:
        keys.add(toks[0] + " " + toks[-1])                # drop middle names
        keys.add(toks[0] + " " + " ".join(toks[-2:]))     # two-word surnames
    return keys


def classify(vote: str) -> str:
    v = (vote or "").strip().lower()
    if v == "affirmative":
        return "affirmative"
    if v == "negative":
        return "negative"
    if v == "absent":
        return "absent"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--archive", required=True,
                    help="path to a jehiah/nyc_legislation checkout "
                         "(must contain introduction/<year>/*.json)")
    args = ap.parse_args()
    intro = Path(args.archive) / "introduction"
    if not intro.is_dir():
        print(f"ERROR: {intro} not found — pass the archive checkout root",
              file=sys.stderr)
        return 1

    members = json.loads(MEMBERS.read_text())["members"]
    member_lookup: dict[str, set[str]] = {}
    for m in members:
        for k in name_keys(m["full_name"]):
            member_lookup.setdefault(k, set()).add(m["id"])

    laws_by_file: dict[str, dict] = {}
    for law in json.loads(LAWS.read_text())["laws"]:
        if law.get("file_number"):
            laws_by_file[law["file_number"]] = law

    year_dirs = sorted(
        d for d in intro.iterdir()
        if d.is_dir() and d.name.isdigit() and int(d.name) >= FIRST_YEAR
    )

    per_member: dict[str, list[dict]] = {}
    unmatched: dict[str, int] = {}
    files_parsed = 0
    votes_total = 0
    min_date, max_date = None, None

    for ydir in year_dirs:
        for path in sorted(ydir.glob("*.json")):
            try:
                bill = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                print(f"WARN: skipping {path}: {e}", file=sys.stderr)
                continue
            files_parsed += 1
            file_no = bill.get("File") or ""
            item = (bill.get("Name") or bill.get("Title") or "").strip()
            if len(item) > ITEM_TITLE_MAX:
                item = item[:ITEM_TITLE_MAX - 1].rstrip() + "…"
            law = laws_by_file.get(file_no)
            for entry in bill.get("History") or []:
                votes = entry.get("Votes") or []
                if not votes:
                    continue
                date = (entry.get("Date") or "")[:10]
                for v in votes:
                    full = v.get("FullName") or ""
                    cands: set[str] = set()
                    for k in name_keys(full):
                        if k in ALIASES:
                            cands.add(ALIASES[k])
                        cands |= member_lookup.get(k, set())
                    if len(cands) != 1:
                        unmatched[full] = unmatched.get(full, 0) + 1
                        continue
                    mid = cands.pop()
                    votes_total += 1
                    if date:
                        min_date = date if min_date is None else min(min_date, date)
                        max_date = date if max_date is None else max(max_date, date)
                    per_member.setdefault(mid, []).append({
                        "file": file_no,
                        "matter_id": law["matter_id"] if law else None,
                        "law": law["law_number_display"] if law else None,
                        "date": date,
                        "item": item,
                        "vote": classify(v.get("Vote")),
                    })

    out_members: dict[str, dict] = {}
    for mid, rows in sorted(per_member.items()):
        totals = {"affirmative": 0, "negative": 0, "absent": 0, "other": 0}
        for r in rows:
            totals[r["vote"]] += 1
        rows.sort(key=lambda r: (r["date"], r["file"]), reverse=True)
        negatives = [
            {k: r[k] for k in ("file", "matter_id", "law", "date", "item")}
            for r in rows if r["vote"] == "negative"
        ]
        out_members[mid] = {
            "totals": totals,
            "negative_votes": negatives,
            "recent": rows[:RECENT_CAP],
        }

    coverage = f"{(min_date or '')[:4]}-{(max_date or '')[:4]}"
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coverage": coverage,
        "members": out_members,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))

    print(f"Parsed {files_parsed} introduction files in "
          f"{year_dirs[0].name}-{year_dirs[-1].name}")
    print(f"Matched {votes_total} votes across {len(out_members)} members; "
          f"coverage {coverage}")
    print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    if unmatched:
        print("UNMATCHED voter names (excluded, fix via ALIASES):")
        for name, n in sorted(unmatched.items(), key=lambda kv: -kv[1]):
            print(f"  {name!r}: {n} votes")
    else:
        print("No unmatched voter names.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
