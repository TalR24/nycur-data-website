#!/usr/bin/env python3
"""
Build the agency-name crosswalk for the NYC Legislation Implementation Tracker.

Reads data/nyc_agencies_governance_orgs.csv (NYC Open Data t3jq-9nkf: NYC
Agencies and Governance Organizations) and produces data/agency_crosswalk.json:

  {
    "agencies": [ {canonical, full_name, display_name, org_type, variants[]} ],
    "lookup":   { "<normalized variant>": "<canonical>" }
  }

The lookup maps every naming variation of an agency (full name, acronym,
alternate/former names, "Dept of X" spellings, "X Department" inversions) to a
single canonical abbreviation, so obligations extracted from legislation text
are always credited to one agency record no matter how the law refers to it.

Usage:
    python3 pipeline/build_agency_crosswalk.py
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
SRC_CSV = DATA / "nyc_agencies_governance_orgs.csv"
OUT_JSON = DATA / "agency_crosswalk.json"

# Priority when two orgs claim the same variant string (higher wins).
ORG_TYPE_PRIORITY = {
    "Mayoral Agency": 5,
    "Elected Office": 4,
    "Division": 3,
    "Mayoral Office": 3,
    "Advisory or Regulatory Organization": 2,
    "Public Benefit or Development Organization": 2,
    "Pension Fund": 1,
    "State Government Agency": 1,
    "Nonprofit Organization": 0,
}

# Variants that legislation uses but the dataset doesn't list.
# Keyed by the dataset's raw acronym for the org.
EXTRA_VARIANTS = {
    "NYC DOT": ["department of transportation of the city of new york"],
    "DSNY": ["department of sanitation of the city of new york"],
    "NYPD": ["police department", "new york police department",
             "police department of the city of new york"],
    "FDNY": ["fire department", "fire department of the city of new york"],
    "DOHMH": ["department of health", "health department"],
    "HPD": ["department of housing preservation and development of the city of new york"],
    "DOB": ["department of buildings of the city of new york"],
    "DCWP": ["department of consumer affairs", "dca",
             "department of consumer and worker protection of the city of new york"],
    "DPR": ["parks department", "nyc parks department"],
    "DOE": ["board of education", "new york city public schools",
            "department of education of the city of new york"],
}

# Same idea, keyed by the dataset's name field (for orgs without an acronym
# or whose common variants stem from the name).
EXTRA_VARIANTS_BY_NAME = {
    # OLTPS was MOCEJ's predecessor office; laws 2014-2021 name it directly.
    # Mapped to MOCEJ like other renames (DCA->DCWP, DoITT->OTI). Added Aug 2026
    # after the data audit found ~46 unmatched OLTPS-actor obligations.
    "Mayor's Office of Climate and Environmental Justice": [
        "office of long-term planning and sustainability",
        "office of long term planning and sustainability",
        "mayor's office of long-term planning and sustainability",
        "mayor's office of long term planning and sustainability",
        "director of long-term planning and sustainability",
        "director of long term planning and sustainability",
        "oltps"],
    "New York City Employee Retirement System": [
        "new york city employees' retirement system",
        "employees' retirement system", "employees retirement system"],
    "City Commission on Human Rights": [
        "commission on human rights", "chr",
        "new york city commission on human rights"],
    "Fire Department Pension Fund and Related Funds": [
        "fire department pension fund",
        "new york city fire department pension fund"],
    "Teachers' Retirement System of City of New York": [
        "new york city teachers' retirement system", "nyc trs"],
    "Office of the Mayor": ["the mayor", "mayor"],
    # DSNY's newer statutory phrasing (seen in 2025-2026 local laws; Aug 2026 audit)
    "Department of Sanitation": [
        "department of sanitation and solid waste management",
        "commissioner of sanitation and solid waste management"],
    "NYC311": ["311 customer service center", "nyc 311",
               "311 customer service center established pursuant to section 23-301"],
    "Mayor's Office of Contract Services": [
        "director of contract services", "office of contract services",
        "city chief procurement officer", "chief procurement officer"],
    "Mayor's Office of Operations": ["office of operations",
                                     "director of operations"],
    "New York City Law Department": ["corporation counsel",
                                     "office of corporation counsel"],
    "Mayor's Office to End Domestic and Gender-Based Violence": [
        "office to end domestic and gender-based violence"],
    "Department for the Aging": ["department of aging", "aging department"],
    "NYC Health + Hospitals": ["correctional health services",
                               "health and hospitals corporation", "hhc",
                               "new york city health and hospitals corporation"],
    "Department of Social Services": ["division of aids services",
                                  "department of social services/human resources administration",
                                  "human resources administration/department of social services",
                                  "department of social services/human resources administration (dss/hra)"],
    "Board of Elections": ["board of elections in the city of new york"],
}

# Short canonical labels for orgs whose dataset row has no acronym, plus
# cases where the stripped acronym reads badly ("NYC AGING" -> "AGING").
CANONICAL_OVERRIDES = {
    "Office of the New York City Comptroller": "Comptroller",
    "Office of the New York City Public Advocate": "Public Advocate",
    "Office of the Mayor": "Mayor's Office",
    "Department for the Aging": "NYC Aging",
    "Fire Department Pension Fund and Related Funds": "Fire Pension Fund",
}


# Never allow these as lookup keys: a generic single word coming from an
# org's stripped name ("New York City Center" -> "Center") false-matches
# generic actor references in legislation ("the center", "the service").
GENERIC_KEY_BLOCKLIST = {
    "center", "city", "office", "board", "agency", "department", "commission",
    "division", "committee", "panel", "unit", "service", "services", "system",
    "trust", "fund", "authority", "corporation", "institute", "foundation",
}


def norm(s: str) -> str:
    """Normalize a name for lookup: lowercase, strip punctuation/whitespace."""
    s = s.lower().strip()
    s = s.replace("&", "and")
    s = re.sub(r"[.,'’]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def strip_nyc_prefix(name: str) -> str | None:
    for pref in ("New York City ", "NYC ", "The New York City ",
                 "City of New York ", "City "):
        if name.startswith(pref):
            return name[len(pref):]
    return None


def name_variants(name: str) -> set[str]:
    """Generate spelling variants for one name string (original casing)."""
    out = {name}
    stripped = strip_nyc_prefix(name)
    if stripped:
        out.add(stripped)
    for base in list(out):
        m = re.match(r"^Department of (.+)$", base)
        if m:
            out.add(f"Dept of {m.group(1)}")
            out.add(f"Dept. of {m.group(1)}")
            out.add(f"NYC Department of {m.group(1)}")
            # "Department of Transportation" -> "Transportation Department",
            # only for single-word remainders to avoid awkward inversions
            if " " not in m.group(1):
                out.add(f"{m.group(1)} Department")
    return out


def canonical_abbrev(row: dict) -> str:
    """Pick the canonical short label for an org."""
    if row["name"].strip() in CANONICAL_OVERRIDES:
        return CANONICAL_OVERRIDES[row["name"].strip()]
    acr = row["acronym"].strip()
    if acr:
        # "NYC DOT" -> "DOT": match the fiscal tracker's plain abbreviations
        return acr[4:] if acr.startswith("NYC ") else acr
    alt_acr = [a.strip() for a in row["alternate_or_former_acronyms"].split(";") if a.strip()]
    if alt_acr:
        return alt_acr[0]
    # No acronym anywhere: fall back to the shortest reasonable name
    stripped = strip_nyc_prefix(row["name"].strip())
    return stripped or row["name"].strip()


def main() -> None:
    rows = list(csv.DictReader(open(SRC_CSV, encoding="utf-8-sig")))
    agencies = []
    # lookup key -> (priority, canonical); resolves collisions by priority
    lookup: dict[str, tuple[int, str]] = {}
    collisions = []

    for row in rows:
        name = row["name"].strip()
        if not name:
            continue
        canon = canonical_abbrev(row)
        prio = ORG_TYPE_PRIORITY.get(row["organization_type"], 0)
        if row["operational_status"] != "Active":
            prio -= 10

        variants: set[str] = set()
        for nm in [name] + [a.strip() for a in row["alternate_or_former_names"].split(";") if a.strip()]:
            variants |= name_variants(nm)
        for acr in [row["acronym"]] + row["alternate_or_former_acronyms"].split(";"):
            acr = acr.strip()
            if acr:
                variants.add(acr)
                stripped = strip_nyc_prefix(acr)
                if stripped:
                    variants.add(stripped)
        variants |= set(EXTRA_VARIANTS.get(row["acronym"].strip(), []))
        variants |= set(EXTRA_VARIANTS_BY_NAME.get(name, []))
        variants.add(canon)

        display = strip_nyc_prefix(name) or name
        agencies.append({
            "canonical": canon,
            "full_name": name,
            "display_name": display,
            "org_type": row["organization_type"],
            "operational_status": row["operational_status"],
            "variants": sorted(variants),
        })

        for v in variants:
            key = norm(v)
            if not key or key in GENERIC_KEY_BLOCKLIST:
                continue
            if key in lookup and lookup[key][1] != canon:
                if prio > lookup[key][0]:
                    collisions.append((key, lookup[key][1], canon, "replaced"))
                    lookup[key] = (prio, canon)
                else:
                    collisions.append((key, lookup[key][1], canon, "kept existing"))
            else:
                lookup[key] = (prio, canon)

    out = {
        "source": "NYC Open Data t3jq-9nkf (NYC Agencies and Governance Organizations)",
        "agencies": agencies,
        "lookup": {k: v[1] for k, v in sorted(lookup.items())},
    }
    OUT_JSON.write_text(json.dumps(out, indent=1))
    print(f"Wrote {OUT_JSON}: {len(agencies)} agencies, {len(lookup)} lookup keys")
    if collisions:
        print(f"{len(collisions)} variant collisions:")
        for key, old, new, action in collisions:
            print(f"  '{key}': {old} vs {new} -> {action}")


if __name__ == "__main__":
    main()
