#!/usr/bin/env python3
"""Build worker/ask_index.json for the premium "Ask the Trackers" tool.

Reads the Legislation Implementation Tracker (obligations, powers, laws,
report filings), the Fiscal Impacts Tracker, and the council members list,
and writes one compact record per duty, power, fiscal estimate, and law,
plus a keyword posting list, to $PREMIUM_DIR/worker/ask_index.json. The
Cloudflare Worker (nycur-data-premium/worker/index.js) bundles that file and
does BM25 retrieval over it before calling Claude.

Reuses agency_canon.py naming and the overdue-report logic in
send_alerts.py (is_overdue) rather than re-deriving either.

Env:
    PREMIUM_DIR   path to a checkout of nycur-data-premium (required)

The tokenizer here (`tokenize`, `law_number_tokens`) must stay in lockstep
with worker/index.js's copy — see tests/tokenizer_parity in this folder's
README note in section 7b of the build orders. Any change here needs the
matching change there.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import unicodedata
import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
COUNCIL_TRACKERS_DIR = PIPELINE_DIR.parent
DATA_WEBSITE_ROOT = COUNCIL_TRACKERS_DIR.parent.parent
LIT_DATA = DATA_WEBSITE_ROOT / "civic_reference" / "legislation_implementation_tracker" / "data"
FISCAL_DATA = DATA_WEBSITE_ROOT / "civic_reference" / "nyc_council_fiscal_impacts_tracker" / "data"
COUNCIL_DATA = COUNCIL_TRACKERS_DIR / "data"

sys.path.insert(0, str(DATA_WEBSITE_ROOT / "pipeline"))
AGENCY_CROSSWALK_PATH = DATA_WEBSITE_ROOT / "pipeline" / "agency_crosswalk.json"

# Generic words that appear in most agency full names and so don't help
# the retrieval scorer tell agencies apart; excluded when building the
# distinctive agency-token boost list below.
GENERIC_AGENCY_WORDS = {
    "department", "city", "new", "york", "office", "nyc", "board",
    "commission", "agency", "authority", "division", "bureau", "mayor",
}

LAW_LINK_BASE = "https://data.nycuriosity.com/civic_reference/legislation_implementation_tracker/law/?law="

# ── tokenizer (keep in sync with worker/index.js) ──────────────────────────

STOPWORDS = set(
    "a an the of to in for and or is are was were be been being on at by with "
    "from as that this these those it its into about over under between "
    "within without which who whom whose what when where why how not no nor "
    "so than then too very can will would should could shall must may might "
    "do does did have has had i you he she we they them their our your "
    "since given any all each every other such there also just now still even here".split()
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_LOCAL_LAW_OF_RE = re.compile(r"local\s+law\s+(?:no\.?\s*)?(\d+)\s+of\s+(\d{4})")
_LL_SLASH_RE = re.compile(r"\bll\s*(\d+)\s*[/-]\s*(\d{4})\b")
_BARE_SLASH_RE = re.compile(r"\b(\d+)\s*/\s*(\d{4})\b")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, stopwords and single-char tokens dropped."""
    if not text:
        return []
    # accents folded so "Aviles" finds "Avilés" (same folding in worker/index.js)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = _WORD_RE.findall(text.lower())
    return [w for w in words if len(w) > 1 and w not in STOPWORDS]


def law_number_tokens(text: str) -> list[str]:
    """Extract 'll<N>-<YYYY>' tokens from free text: 'Local Law 13 of 2026',
    'LL 13/2026', 'LL13-2026', or bare '13/2026' all normalise to one form."""
    if not text:
        return []
    low = text.lower()
    out = []
    for rx in (_LOCAL_LAW_OF_RE, _LL_SLASH_RE, _BARE_SLASH_RE):
        for m in rx.finditer(low):
            out.append(f"ll{m.group(1)}-{m.group(2)}")
    return out


# ── helpers ─────────────────────────────────────────────────────────────


def load(path: Path):
    return json.loads(path.read_text())


def is_overdue(o: dict, filings: dict, today: str) -> bool:
    """Same rule as send_alerts.py:is_overdue."""
    filing = filings.get(o["obligation_id"]) or {}
    status = filing.get("status")
    dd = o.get("deadline_date")
    return status == "overdue" or (status == "never filed" and dd is not None and dd < today)


def status_phrase(o: dict, filings: dict, today: str) -> str:
    filing = filings.get(o["obligation_id"])
    if not filing:
        return "no DORIS filing record"
    status = filing["status"]
    overdue = is_overdue(o, filings, today)
    if overdue and status != "overdue":
        return f"{status} (overdue as of {today})"
    return status


def money(n) -> str:
    if n is None:
        return "n/a"
    return f"${n:,.0f}" if n else "$0"


def distinctive_agency_tokens() -> list[str]:
    """Tokens the retrieval scorer should weight heavily: agency
    abbreviations, and the identifying words from each agency's full name
    (with generic words like 'department' and 'city' dropped, since those
    would boost almost every record instead of picking out one agency)."""
    cw = json.loads(AGENCY_CROSSWALK_PATH.read_text())
    toks: set[str] = set()
    for a in cw.get("agencies", []):
        canon = a.get("canonical") or ""
        if canon and canon.isupper() and len(canon) <= 6:
            toks.add(canon.lower())
        for w in tokenize(a.get("full_name") or ""):
            if len(w) > 3 and w not in GENERIC_AGENCY_WORDS:
                toks.add(w)
    return sorted(toks)


def agency_tokens(agency: str | None, agency_full: str | None) -> list[str]:
    toks = []
    if agency:
        toks.append(agency.lower())
    if agency_full:
        toks.extend(tokenize(agency_full))
    return toks


def clip(text: str, n: int) -> str:
    """Cut at a word boundary so the model never reads a half word."""
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0] + "..."


# totals_basis -> what the figure is (fiscal-impacts-tracker skill: the Full
# Fiscal Impact column is an ANNUAL cost at full implementation)
BASIS_LABEL = {
    "full_impact_column": "annual amount at full implementation",
    "last_year_column": "annual amount in the last fiscal year shown",
    "sum_of_columns": "sum of the fiscal years shown",
    "document_stated": "figure as the statement states it",
    "program_life_sum": "total over the program's life",
}


def net_phrase(n) -> str:
    """Tracker sign convention: net < 0 costs the city."""
    if n is None:
        return "net impact not stated"
    if n < 0:
        return f"net cost to the city {money(-n)}"
    if n > 0:
        return f"net revenue for the city {money(n)}"
    return "no net fiscal impact"


def year_of(d) -> int | None:
    return int(str(d)[:4]) if d and str(d)[:4].isdigit() else None


# Aliases that are ordinary words in questions ("the Council gave",
# "which law") and would scope every question to one body.
ALIAS_STOP = {"law", "council", "city council", "the council", "mayor", "city",
              "public", "schools", "police", "fire", "health", "parks", "all",
              "any", "new", "report", "reports", "core", "loft", "cab"}


def agency_aliases() -> dict:
    """Lowercase phrase -> canonical agency, used by the Worker to spot an
    agency named in a question. Acronyms, full names, display names, and full
    names without a leading 'New York City '."""
    cw = json.loads(AGENCY_CROSSWALK_PATH.read_text())
    out = {}
    for a in cw.get("agencies", []):
        canon = a.get("canonical") or ""
        if not canon:
            continue
        names = {canon, a.get("full_name") or "", a.get("display_name") or ""}
        for nm in list(names):
            if nm.lower().startswith("new york city "):
                names.add(nm[14:])
        for nm in names:
            nm = nm.strip().lower()
            if len(nm) >= 3 and nm not in GENERIC_AGENCY_WORDS and nm not in ALIAS_STOP:
                out.setdefault(nm, canon)
    # the city school system is still called DOE by most readers
    if "NYCPS" in out.values():
        out.setdefault("doe", "NYCPS")
        out.setdefault("department of education", "NYCPS")
    return out


CANON_AGENCIES = {a.get("canonical") for a in
                  json.loads(AGENCY_CROSSWALK_PATH.read_text()).get("agencies", [])} - {"Unspecified"}


def agency_records(records: list[dict]) -> dict:
    out: dict[str, list[int]] = {}
    for i, r in enumerate(records):
        for a in r.get("a", []):
            out.setdefault(a, []).append(i)
    return out


_ISO = re.compile(r"\b(20\d\d|19\d\d)-(\d\d)-(\d\d)\b")
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def tidy(x: str) -> str:
    """ISO dates -> "January 3, 2026" (answers quote them), single spaces."""
    x = _ISO.sub(lambda m: f"{_MONTHS[int(m[2]) - 1]} {int(m[3])}, {m[1]}"
                 if 1 <= int(m[2]) <= 12 else m[0], x)
    return re.sub(r"\s{2,}", " ", x)


def add_record(records, postings, rtype, x, u, extra_tokens, agencies=(), year=None):
    idx = len(records)
    x = tidy(x)
    rec = {"t": rtype, "x": x, "u": u}
    if agencies:
        rec["a"] = sorted({a for a in agencies if a})
    if year:
        rec["y"] = year
    records.append(rec)
    seen = set()
    for tok in extra_tokens:
        if tok and tok not in seen:
            seen.add(tok)
            postings.setdefault(tok, [])
            if idx not in postings[tok]:
                postings[tok].append(idx)
    return idx


def main() -> int:
    premium_dir = os.environ.get("PREMIUM_DIR")
    if not premium_dir:
        print("PREMIUM_DIR env var is required", file=sys.stderr)
        return 1
    premium_dir = Path(premium_dir)
    out_path = premium_dir / "worker" / "ask_index.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    obligations_doc = load(LIT_DATA / "obligations.json")
    powers_doc = load(LIT_DATA / "powers.json")
    laws_doc = load(LIT_DATA / "laws.json")
    filings_doc = load(LIT_DATA / "report_filings.json")
    fiscal_doc = load(FISCAL_DATA / "fiscal_impacts.json")

    filings = filings_doc.get("filings", {})
    filings_as_of = str(filings_doc.get("generated") or "")[:10] or None

    freshness_dates = []
    for doc, key in (
        (obligations_doc, "generated_at"),
        (powers_doc, "generated_at"),
        (laws_doc, "generated_at"),
        (filings_doc, "generated"),
    ):
        v = doc.get(key)
        if v:
            freshness_dates.append(str(v)[:10])
    fiscal_last_updated = fiscal_doc.get("metadata", {}).get("last_updated")
    if fiscal_last_updated:
        freshness_dates.append(str(fiscal_last_updated)[:10])
    data_as_of = min(freshness_dates) if freshness_dates else None
    today = max(freshness_dates) if freshness_dates else data_as_of

    records: list[dict] = []
    postings: dict[str, list[int]] = {}

    counts = {"duty": 0, "power": 0, "fiscal": 0, "law": 0}

    # ── duties + powers ────────────────────────────────────────────────
    def emit_duty_or_power(o: dict, rtype: str):
        agency = o.get("agency") or o.get("actor_raw") or "an agency"
        agency_full = o.get("agency_full") or agency
        law_disp = o.get("law_number_display") or o.get("file_number") or ""
        law_title = clip(o.get("law_title") or "", 90)
        action = (o.get("action_summary") or "").strip()
        if len(action) > 260:
            action = action[:257] + "..."
        deadline = o.get("deadline_text") or o.get("deadline_date") or "none stated"
        recurrence = o.get("recurrence") or "unspecified"
        existing_code = " Existing code." if o.get("origin") == "existing code" else ""
        kind_word = "duty" if rtype == "duty" else "power"
        status_bit = ""
        if rtype == "duty" and (o.get("deliverable_type") == "report"):
            status_bit = f" Filing status: {status_phrase(o, filings, today)} (as of {filings_as_of})."
        if o.get("agency") in CANON_AGENCIES:
            who = f"{agency_full} ({agency})"
        else:
            who = f"Agency as the law names it: '{o.get('actor_raw') or agency}'"
        x = (
            f"{who} {kind_word} under {law_disp}: {law_title}. "
            f"{action} Deliverable: {o.get('deliverable_type') or 'unspecified'}; "
            f"deadline {deadline} ({recurrence}).{status_bit}{existing_code}"
        )
        u = LAW_LINK_BASE + o.get("matter_id", "")
        # Plural aliases: the tokenizer has no stemming, so a query asking
        # about "duties" or "powers" (plural, as most questions do) would
        # otherwise never match the singular "duty"/"power" word in x.
        plural_alias = ["powers"] if rtype == "power" else ["duties", "obligations"]
        tokens = (
            tokenize(x)
            + agency_tokens(o.get("agency"), o.get("agency_full"))
            + law_number_tokens(law_disp)
            + tokenize(o.get("prime_sponsor") or "")
            + plural_alias
        )
        add_record(records, postings, rtype, x, u, tokens,
                   [o.get("agency")], year_of(o.get("enactment_date")))
        counts[rtype] += 1

    for o in obligations_doc.get("obligations", []):
        emit_duty_or_power(o, "duty")
    for o in powers_doc.get("powers", []):
        emit_duty_or_power(o, "power")

    # ── laws ───────────────────────────────────────────────────────────
    # laws.json carries no counts; obligations.json's law rows do
    counts_by_law = {l["matter_id"]: (l.get("obligation_count") or 0, l.get("power_count") or 0)
                     for l in obligations_doc.get("laws", [])}
    by_matter: dict[str, list] = {}
    for o in obligations_doc.get("obligations", []) + powers_doc.get("powers", []):
        by_matter.setdefault(o.get("matter_id"), []).append(o)
    for law in laws_doc.get("laws", []):
        law_disp = law.get("law_number_display") or law.get("file_number") or ""
        title = clip(law.get("title") or "", 200)
        prime = law.get("prime_sponsor") or "unknown"
        co_sponsors = max((law.get("sponsor_count") or 1) - 1, 0)
        x = (
            f"{law_disp}: {title}. Enacted {law.get('enactment_date') or 'unknown date'}. "
            f"Prime sponsor {prime}; {co_sponsors} co-sponsor{'s' if co_sponsors != 1 else ''}. "
            f"{counts_by_law.get(law.get('matter_id'), (0, 0))[0]} duties, "
            f"{counts_by_law.get(law.get('matter_id'), (0, 0))[1]} powers."
        )
        u = LAW_LINK_BASE + law.get("matter_id", "")
        tokens = tokenize(x) + law_number_tokens(law_disp) + tokenize(prime)
        law_agencies = sorted({o.get("agency") for o in by_matter.get(law.get("matter_id"), [])})
        add_record(records, postings, "law", x, u, tokens, law_agencies,
                   year_of(law.get("enactment_date")))
        counts["law"] += 1

    # ── fiscal estimates ──────────────────────────────────────────────
    for r in fiscal_doc.get("records", []):
        bill = r.get("legistar_file") or r.get("file_number") or ""
        title = clip(r.get("title") or "", 160)
        agencies = ", ".join(r.get("agencies_abbrev") or []) or "no agency listed"
        basis = r.get("totals_basis") or "unspecified basis"
        label = BASIS_LABEL.get(basis, "figure as the statement states it")
        in_plan = (" The statement says these costs are already in the city's financial plan."
                   if r.get("costs_already_in_financial_plan") else "")
        if r.get("time_limited_program") and r.get("outlasts_statement"):
            end = f" through FY20{r['program_end_fy']:02d}" if r.get("program_end_fy") else ""
            in_plan += (f" Time-limited program{end}; the statement prices only its first years,"
                        " so the figures are annual.")
        elif r.get("time_limited_program") and basis == "program_life_sum":
            end = f", ending FY20{r['program_end_fy']:02d}" if r.get("program_end_fy") else ""
            in_plan += f" Time-limited program{end}; the figures cover its whole run."
        capital = (f", capital {money(r['total_capital'])} (sum of the fiscal years shown)"
                   if r.get("total_capital") else "")
        x = (
            f"Fiscal estimate for {bill}: {title}. Agencies: {agencies}. "
            f"Expenditure {money(r.get('total_expenditure'))} and revenue "
            f"{money(r.get('total_revenue'))} (each the {label}){capital}; "
            f"{net_phrase(r.get('net_fiscal_impact'))}, counting all of these. "
            f"Prepared {r.get('date_prepared') or 'unknown date'}.{in_plan}"
        )
        u = r.get("legistar_url") or LAW_LINK_BASE + r.get("matter_id", "")
        tokens = (
            tokenize(x)
            + [a.lower() for a in (r.get("agencies_abbrev") or [])]
            + tokenize(" ".join(r.get("agencies_full") or []))
            + tokenize(r.get("prime_sponsor") or "")
        )
        add_record(records, postings, "fiscal", x, u, tokens,
                   r.get("agencies_abbrev") or [], year_of(r.get("date_prepared")))
        counts["fiscal"] += 1

    # ── member name tokens (added on top of any records already carrying
    #    a sponsor name; this also lets a full member name alone retrieve
    #    laws/fiscal records where the sponsor field only has a last name) ──

    out = {
        "built_at": None,
        "data_as_of": data_as_of,
        "records": records,
        "postings": postings,
        "agency_tokens": distinctive_agency_tokens(),
        "agency_aliases": agency_aliases(),
        # canonical agency -> record indexes, so the Worker never scans every record
        "agency_records": agency_records(records),
    }
    from datetime import datetime, timezone

    out["built_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    raw = json.dumps(out, separators=(",", ":"), ensure_ascii=False)
    out_path.write_text(raw, encoding="utf-8")

    raw_size = len(raw.encode("utf-8"))
    gz_size = len(gzip.compress(raw.encode("utf-8"), compresslevel=9))
    print(f"records: duty={counts['duty']} power={counts['power']} "
          f"fiscal={counts['fiscal']} law={counts['law']} total={len(records)}")
    print(f"postings terms: {len(postings)}")
    print(f"data_as_of: {data_as_of}")
    print(f"raw size: {raw_size:,} bytes ({raw_size/1_000_000:.2f} MB)")
    print(f"gzip size: {gz_size:,} bytes ({gz_size/1_000_000:.2f} MB)")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
