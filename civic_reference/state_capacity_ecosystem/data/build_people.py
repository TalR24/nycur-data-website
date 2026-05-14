"""
Build people.json from problem_statement_seeds_v5.csv.

Schema (10 columns in source CSV):
  Name, Organization, Role, Jurisdiction, Problem Area, Problem Topic,
  Problem Details, Help + Source, Time Window, Contact

Jurisdiction is semicolon-separated in the source (e.g. "Federal; State; Local")
so we split it into a list. All other fields are treated as single values.
"""

import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV  = ROOT / "problem_statement_seeds_v5.csv"
OUT  = ROOT / "people.json"


def norm(v):
    return (v or "").strip()


def split_semi(v):
    return [s.strip() for s in (v or "").split(";") if s.strip()]


with open(CSV, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

people = []
for r in rows:
    name = norm(r.get("Name"))
    if not name:
        continue
    people.append({
        "id": len(people),
        "name": name,
        "organization": norm(r.get("Organization")),
        "role": norm(r.get("Role")),
        "jurisdictions": split_semi(r.get("Jurisdiction")),
        "problem_area": norm(r.get("Problem Area")),
        "problem_topic": norm(r.get("Problem Topic")),
        "problem_details": norm(r.get("Problem Details")),
        "help_source": norm(r.get("Help + Source")),
        "time_window": norm(r.get("Time Window")),
        "contact": norm(r.get("Contact")),
    })

OUT.write_text(json.dumps(people, indent=None, separators=(",", ":")))
print(f"Wrote {OUT} ({len(people)} people)")
