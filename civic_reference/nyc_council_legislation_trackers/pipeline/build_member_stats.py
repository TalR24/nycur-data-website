#!/usr/bin/env python3
"""
Join the council member roster with both tracker datasets and produce
data/members.json for the Council Members page.

Inputs:
  data/council_members.json            — roster (people, party, district, sessions)
  ../nyc_council_fiscal_impacts_tracker/data/fiscal_impacts.json
  ../legislation_implementation_tracker/data/obligations.json

Sponsor matching:
  - Implementation tracker stores FULL sponsor names ("Adrienne E. Adams"):
    matched on normalized first+last tokens, falling back to last name if
    unique among members serving in the law's year.
  - Fiscal tracker stores LAST NAMES only ("Lee", "X (Speaker)"): matched on
    last name among members whose service overlaps the bill's year; ambiguous
    cases resolve through MANUAL_MATCH or are reported as unmatched.

Output: data/members.json — one record per member with per-tracker stats and
the full list of their matched legislation. Unmatched sponsor strings are
listed in the output for manual triage; the build never guesses.

Usage:
    python3 pipeline/build_member_stats.py
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
DATA = BASE / "data"
ROSTER = DATA / "council_members.json"
FISCAL = BASE.parent / "nyc_council_fiscal_impacts_tracker" / "data" / "fiscal_impacts.json"
IMPL = BASE.parent / "legislation_implementation_tracker" / "data" / "obligations.json"
# Every enacted law (sponsorship source). obligations.json lags it by a build,
# so it only supplies the per-law obligation count.
LAWS = BASE.parent / "legislation_implementation_tracker" / "data" / "laws.json"
OUT = DATA / "members.json"

# last-name (as it appears in fiscal data) + bill year -> roster full_name,
# for cases where the last name alone is ambiguous in that year
MANUAL_MATCH: dict[tuple[str, int], str] = {
    # ("Diaz", 2021): "Ruben Diaz",
}

# Misspellings and renames in the fiscal tracker's sponsor strings
TYPO_ALIASES = {
    "abreau": "abreu",
    "carbrera": "cabrera",
    "landers": "lander",
    "koslowtiz": "koslowitz",
    "ampry-sammuel": "ampry-samuel",
    "samuel": "ampry-samuel",
    "ferreras": "ferreras-copeland",
    "richardson": "richardson jordan",
    "shulman": "schulman",
    "borrelli": "borelli",
}

# Label under which Public Advocate sponsors are counted in unmatched_sponsors.
# The Public Advocate may sponsor bills but holds no Council seat, so these
# are never credited to a member.
PA_LABEL = "Public Advocate (not a Council member)"
PA_RE = re.compile(r"^\s*(the\s+)?public\s+advocate\b", re.I)

# Non-council sponsors that appear in fiscal records: the Public Advocate
# (who may sponsor legislation but holds no council seat). "Williams" in
# 2020-2021 is PA Jumaane Williams, handled by the service-year filter
# refusing to guess.
SKIP_SPONSORS = {"james", "the speaker", "public advocate"}

# A bare surname shared by a Council member and a Public Advocate in the same
# years cannot be resolved by name alone; it is checked against the bill's
# Legistar sponsor list (laws.json, or the archive with --archive).
PA_SURNAMES = {"williams"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm_name(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = re.sub(r"[.,'’]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def name_tokens(s: str) -> tuple[str, str]:
    """(first token, last token) of a normalized name, dropping suffixes."""
    toks = [t for t in norm_name(s).split() if t not in
            ("jr", "sr", "ii", "iii", "iv", "rev", "dr")]
    if not toks:
        return "", ""
    return toks[0], toks[-1]


SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def clean_sponsor(s: str) -> str:
    """'X (Speaker)' -> 'X'; strip trailing ', Jr.' style suffixes."""
    s = re.sub(r"\s*\((speaker|public advocate)[^)]*\)\s*$", "", s or "",
               flags=re.I).strip()
    s = re.sub(r",?\s+(jr|sr|ii|iii|iv)\.?$", "", s, flags=re.I).strip()
    return s.rstrip(",").strip()


def merge_suffix_fragments(sponsors: list[str]) -> list[str]:
    """Repair comma-split names: ['Rafael Salamanca', 'Jr.'] -> one entry."""
    out: list[str] = []
    for sp in sponsors:
        frag = norm_name(sp).rstrip(".")
        if frag in SUFFIXES and out:
            out[-1] = out[-1] + ", " + sp
        else:
            out.append(sp)
    return out


def year_served(m: dict, year: int) -> bool:
    terms = m.get("terms")
    if terms:  # stints from build_council_roster.py; honours gaps in service
        return any(int(s[:4]) <= year <= (int(e[:4]) if e else 9999)
                   for s, e in terms)
    start = m.get("start_year") or 1900
    end = m.get("end_year") or 9999
    return start <= year <= end


# Full names that differ from the roster's first name by nickname:
# (archive first, last token) -> roster first token.
NICKNAMES = {
    ("deborah", "rose"): "debi",
    ("james", "bramer"): "jimmy",
    ("joseph", "borelli"): "joe",
}


def first_compatible(a: str, b: str) -> bool:
    """First names that can be the same person: equal, one a prefix of the
    other ("Deb"/"Deborah"), or an initial ("P."/"Pierina"). "Peter" and
    "Paul" are not."""
    if not a or not b:
        return True
    return a == b or a.startswith(b) or b.startswith(a)


def slugify(name: str) -> str:
    s = norm_name(name).replace(" ", "-")
    return re.sub(r"[^a-z0-9\-]", "", s)


class Matcher:
    def __init__(self, members: list[dict]):
        self.members = members
        self.by_last: dict[str, list[dict]] = {}
        self.by_first_last: dict[tuple[str, str], list[dict]] = {}
        # last-name of compound surnames: "de la rosa" -> last token "rosa",
        # so also index the full multiword surname when derivable
        for m in members:
            first, last = name_tokens(m["full_name"])
            m["_first"], m["_last"] = first, last
            self.by_last.setdefault(last, []).append(m)
            self.by_first_last.setdefault((first, last), []).append(m)
            ln = norm_name(m.get("last_name") or "")
            if ln and ln != last:
                self.by_last.setdefault(ln, []).append(m)
        self.unmatched: dict[str, int] = {}

    def match_full(self, name: str, year: int | None) -> dict | None:
        if PA_RE.match(name or ""):
            self.unmatched[PA_LABEL] = self.unmatched.get(PA_LABEL, 0) + 1
            return None
        first, last = name_tokens(clean_sponsor(name))
        if not last:
            return None
        first = NICKNAMES.get((first, last), first)
        cands = self.by_first_last.get((first, last), [])
        if len(cands) == 1:
            m = cands[0]
            # enacted in the year or the year after the term ended (a law can
            # be signed in January for a bill passed in December)
            if year and not (year_served(m, year) or year_served(m, year - 1)):
                self._miss(name, year)
                return None
            return m
        # multiword surnames: try last two tokens as surname
        toks = norm_name(clean_sponsor(name)).split()
        if len(toks) >= 3:
            two = " ".join(toks[-2:])
            cands = self.by_last.get(two, [])
            if len(cands) == 1 and cands[0]["_first"] == toks[0]:
                return cands[0]
        # last-name fallback only for a first name that can be the same
        # person (a nickname), never for a namesake such as Peter Vallone Jr.
        return self.match_last(last, year, raw=name, first=first)

    def _miss(self, raw: str, year: int | None) -> None:
        key = raw + (f" [{year}]" if year else " [year unknown]")
        self.unmatched[key] = self.unmatched.get(key, 0) + 1

    def match_last(self, last: str, year: int | None, raw: str = "",
                   first: str | None = None, alt_year: int | None = None) -> dict | None:
        if PA_RE.match(last or ""):
            self.unmatched[PA_LABEL] = self.unmatched.get(PA_LABEL, 0) + 1
            return None
        cleaned = clean_sponsor(last)
        last_n = norm_name(cleaned)
        if last_n in SKIP_SPONSORS:
            if last_n == "james":
                self.unmatched[PA_LABEL] = self.unmatched.get(PA_LABEL, 0) + 1
            return None
        last_n = TYPO_ALIASES.get(last_n, last_n)
        key = (clean_sponsor(raw or last), year or 0)
        if key in MANUAL_MATCH:
            target = norm_name(MANUAL_MATCH[key])
            for m in self.members:
                if norm_name(m["full_name"]) == target:
                    return m
        # "P. Sanchez" -> first-initial + surname
        initial = None
        mm = re.match(r"^([a-z])\s+(.+)$", last_n)
        if mm:
            initial, last_n = mm.group(1), mm.group(2)
        cands = self.by_last.get(last_n.split()[-1] if last_n else "", [])
        cands = [m for m in cands if last_n.endswith(m["_last"]) or
                 norm_name(m.get("last_name") or "") == last_n]
        if initial:
            cands = [m for m in cands if m["_first"].startswith(initial)]
        if first:
            cands = [m for m in cands if first_compatible(first, m["_first"])]
        if year:
            # refuse to guess when the year rules out every candidate
            cands = [m for m in cands if year_served(m, year) or
                     (alt_year and year_served(m, alt_year))]
        uniq = list({id(m): m for m in cands}.values())
        if len(uniq) == 1:
            return uniq[0]
        if uniq or last_n not in SKIP_SPONSORS:
            self.unmatched[(raw or last) + (f" [{year}]" if year else "")] = \
                self.unmatched.get((raw or last) + (f" [{year}]" if year else ""), 0) + 1
        return None


def fiscal_year_of(rec: dict) -> int | None:
    m = re.search(r"\b(20\d\d)\b", rec.get("date_prepared") or "")
    if m:
        return int(m.group(1))
    # the Legistar file number ("Int 0839-2026") carries the session year
    m = re.search(r"-(20\d\d)\b", rec.get("legistar_file") or "")
    if m:
        return int(m.group(1))
    # file numbers look like "Int 0620-2014": the year follows the hyphen —
    # a bare 4-digit search would grab the bill number ("0620")
    fn = rec.get("file_number") or ""
    m = re.search(r"-(20\d\d)\b", fn) or re.search(r"\b(20\d\d)\b", fn)
    return int(m.group(1)) if m else None


def is_state_legislation(rec: dict) -> bool:
    """State Legislation Resolutions carry state bill numbers ("S.7509 /
    A.7668") and STATE legislators as sponsors — never council members."""
    return bool(re.match(r"^\s*[SA]\.", rec.get("file_number") or ""))


def archive_sponsors(archive: Path | None, rec: dict, year: int | None) -> list[str] | None:
    """Full sponsor names of a fiscal record's bill from the archive
    (introduction/<year>/<number>.json), or None if it cannot be found."""
    if not archive:
        return None
    mm = re.match(r"^\s*\w+\s+0*(\d+)-(20\d\d)", rec.get("legistar_file") or "")
    if not mm:
        return None
    path = archive / "introduction" / mm.group(2) / f"{int(mm.group(1)):04d}.json"
    if not path.exists():
        return None
    return [s.get("FullName") or "" for s in json.loads(path.read_text()).get("Sponsors") or []]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--archive", help="jehiah/nyc_legislation checkout; resolves bare "
                    "surnames shared with the Public Advocate from the bill's sponsor list")
    args = ap.parse_args()
    archive = Path(args.archive) if args.archive else None
    roster = json.loads(ROSTER.read_text())["members"]
    fiscal = json.loads(FISCAL.read_text())["records"]
    impl = json.loads(IMPL.read_text())
    oblig_by_matter = {l["matter_id"]: l.get("obligation_count") for l in impl["laws"]}
    impl_laws = json.loads(LAWS.read_text())["laws"]
    laws_by_matter = {l["matter_id"]: l for l in impl_laws}
    print(f"laws.json: {len(impl_laws)} laws; obligations.json: {len(oblig_by_matter)} "
          f"({len(set(laws_by_matter) - set(oblig_by_matter))} awaiting extraction)")

    for m in roster:
        m["id"] = slugify(m["full_name"])
        m["legislation"] = []

    matcher = Matcher(roster)

    # Fiscal tracker: last names
    for rec in fiscal:
        if is_state_legislation(rec):
            continue
        year = fiscal_year_of(rec)
        # A member counts as in office if they served in the year the fiscal
        # note was prepared OR the session in the Legistar file number
        # ("Int 0799-2015"): sponsors attach at introduction or join later, and
        # a note is prepared after an amendment (Dickens 2015 vs 2017)
        mfy = re.search(r"-(20\d\d)\b", rec.get("legistar_file") or "")
        alt_year = int(mfy.group(1)) if mfy else None
        match_year = year if year is not None else alt_year
        prime_raw = clean_sponsor(rec.get("prime_sponsor") or "")
        for sp in merge_suffix_fragments(rec.get("sponsors") or []):
            if re.search(r"\(\s*public advocate", sp, re.I):
                # "Williams (Public Advocate)": clean_sponsor would drop the
                # marker and leave a bare surname that matches a member
                matcher.unmatched[PA_LABEL] = matcher.unmatched.get(PA_LABEL, 0) + 1
                continue
            sp_clean = clean_sponsor(sp)
            if not sp_clean or norm_name(sp_clean) in SKIP_SPONSORS:
                continue
            if match_year is None:
                # no year means no service check; never guess
                matcher._miss(sp_clean, None)
                continue
            m = matcher.match_last(sp_clean, match_year, raw=sp_clean, alt_year=alt_year)
            if m is None:
                continue
            if norm_name(sp_clean) in PA_SURNAMES and match_year >= 2019:
                # Public Advocate Jumaane Williams shares the surname
                law = laws_by_matter.get(str(rec.get("matter_id")))
                names = ([law_sp for law_sp in (law.get("sponsors") or [])] if law
                         else archive_sponsors(archive, rec, match_year))
                if names is not None and not any(
                        name_tokens(n) == (m["_first"], m["_last"]) for n in names
                        if not PA_RE.match(n)):
                    matcher._miss(sp_clean + " (PA, not on sponsor list)", year)
                    continue
            m["legislation"].append({
                "tracker": "fiscal",
                "matter_id": rec.get("matter_id"),
                "label": rec.get("file_number"),
                "title": rec.get("title"),
                "year": year,
                "prime": sp_clean == prime_raw,
                "net_fiscal_impact": rec.get("net_fiscal_impact"),
                "legistar_url": rec.get("legistar_url"),
            })

    # Implementation tracker: full names
    for law in impl_laws:
        year = int(law["enactment_date"][:4]) if law.get("enactment_date") else None
        prime_n = norm_name(clean_sponsor(law.get("prime_sponsor") or ""))
        for sp in merge_suffix_fragments(law.get("sponsors") or []):
            m = matcher.match_full(sp, year)
            if m is None:
                continue
            m["legislation"].append({
                "tracker": "impl",
                "matter_id": law["matter_id"],
                "label": law.get("law_number_display") or law.get("file_number"),
                "title": law.get("title"),
                "year": year,
                "prime": norm_name(clean_sponsor(sp)) == prime_n,
                "obligation_count": oblig_by_matter.get(law["matter_id"]) or 0,
                "legistar_url": law.get("legistar_url"),
            })

    # Stats + dedupe (same person listed twice on one bill).
    # Legislation details are normalized into one lookup table keyed
    # "tracker:matter_id" — a 40-sponsor law stores its title once, and each
    # member keeps only {k, prime} references. Keeps members.json small.
    leg_table: dict[str, dict] = {}
    out_members = []
    for m in roster:
        seen = set()
        legs = []
        for l in m["legislation"]:
            k = (l["tracker"], l["matter_id"])
            if k in seen:
                continue
            seen.add(k)
            legs.append(l)
            tk = f'{l["tracker"]}:{l["matter_id"]}'
            if tk not in leg_table:
                leg_table[tk] = {kk: vv for kk, vv in l.items()
                                 if kk not in ("tracker", "matter_id", "prime")}
        legs.sort(key=lambda l: (-(l["year"] or 0), l["label"] or ""))
        fiscal_legs = [l for l in legs if l["tracker"] == "fiscal"]
        impl_legs = [l for l in legs if l["tracker"] == "impl"]
        stats = {
            "legislation_total": len(legs),
            "fiscal_bills": len(fiscal_legs),
            "fiscal_bills_prime": sum(1 for l in fiscal_legs if l["prime"]),
            "fiscal_net_sum": sum(l.get("net_fiscal_impact") or 0 for l in fiscal_legs),
            "fiscal_net_sum_prime": sum(l.get("net_fiscal_impact") or 0
                                        for l in fiscal_legs if l["prime"]),
            "impl_laws": len(impl_legs),
            "impl_laws_prime": sum(1 for l in impl_legs if l["prime"]),
            "obligations_sum": sum(l.get("obligation_count") or 0 for l in impl_legs),
            "obligations_sum_prime": sum(l.get("obligation_count") or 0
                                         for l in impl_legs if l["prime"]),
            "impl_pct_with_obligations": (
                round(100 * sum(1 for l in impl_legs if (l.get("obligation_count") or 0) > 0)
                      / len(impl_legs)) if impl_legs else None),
        }
        rec = {k: v for k, v in m.items() if not k.startswith("_")}
        rec["stats"] = stats
        rec["legislation"] = [
            {"k": f'{l["tracker"]}:{l["matter_id"]}', "prime": l["prime"]}
            for l in legs]
        out_members.append(rec)

    out_members.sort(key=lambda m: (not m["current"], m.get("district") or 99,
                                    m["full_name"]))
    OUT.write_text(json.dumps({
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "legislation": leg_table,
        "members": out_members,
        "unmatched_sponsors": dict(sorted(matcher.unmatched.items(),
                                          key=lambda x: -x[1])),
    }, separators=(",", ":")))
    total_leg = sum(m["stats"]["legislation_total"] for m in out_members)
    with_any = sum(1 for m in out_members if m["stats"]["legislation_total"])
    print(f"Wrote {OUT}: {len(out_members)} members, "
          f"{with_any} with legislation, {total_leg} sponsorship links, "
          f"{len(matcher.unmatched)} unmatched sponsor strings")
    if matcher.unmatched:
        print("Unmatched:", dict(list(matcher.unmatched.items())[:15]))


if __name__ == "__main__":
    main()
