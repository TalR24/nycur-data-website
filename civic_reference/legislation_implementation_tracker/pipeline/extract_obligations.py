#!/usr/bin/env python3
"""
NYC Legislation Implementation Tracker — Step 2: extract agency obligations.

For every law in data/laws.json (text cached by fetch_enacted_laws.py), asks
Claude to list each concrete action the law requires of a NYC government
entity: who must act, what they must produce, by when, and the exact statutory
language imposing the duty.

Safeguards:
  - Every quoted passage is mechanically verified as a substring of the source
    text (whitespace/punctuation-normalized). Unverified quotes are flagged and
    the law is retried once with a corrective message.
  - Deadline arithmetic happens in Python, not in the model: Claude returns
    relative components ("90 days after the effective date"), and this script
    computes absolute dates from the Legistar enactment date.
  - Agency names are normalized through data/agency_crosswalk.json (built from
    NYC Open Data t3jq-9nkf), so "DOT", "Dept of Transportation", and
    "Department of Transportation" all resolve to one canonical agency.

Outputs data/obligations.json. Per-law raw extractions checkpoint to
cache/extracted/{matter_id}.json so interrupted runs resume for free.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 pipeline/extract_obligations.py                    # all laws
    python3 pipeline/extract_obligations.py --limit 10         # test batch
    python3 pipeline/extract_obligations.py --matters 7681684  # specific laws
    python3 pipeline/extract_obligations.py --incremental      # skip cached
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
TEXT_CACHE = HERE / "cache" / "text"
EXTRACT_CACHE = HERE / "cache" / "extracted"
LAWS_JSON = DATA / "laws.json"
CROSSWALK_JSON = DATA / "agency_crosswalk.json"
OUT_JSON = DATA / "obligations.json"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

DELIVERABLE_TYPES = [
    "rulemaking", "report", "study or audit", "plan or strategy",
    "program or service", "database or data publication",
    "signage or installation", "outreach or education", "training",
    "enforcement or inspection", "monitoring or testing",
    "notice or posting", "designation or staffing", "other",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract_obligations")

EXTRACTION_PROMPT = """You are analyzing the full text of an enacted New York City local law. Extract every concrete obligation the law imposes on a NYC GOVERNMENT entity (an agency, department, office, commission, board, or officer such as "the commissioner", "the mayor", "the department", "the office"). This is for a public implementation-tracking dashboard.

Return ONLY a JSON object with this exact structure (no markdown, no explanation):

{
 "effective_clause": {
   "kind": "immediate" | "days_after_enactment" | "fixed_date" | "other",
   "offset_days": <integer or null>,
   "fixed_date": "YYYY-MM-DD" or null,
   "text": "<the effective-date sentence, verbatim>"
 },
 "obligations": [
   {
     "actor_raw": "<the responsible entity exactly as the law names it, e.g. 'the department of transportation', 'the commissioner of health and mental hygiene', 'the mayor', 'a designated agency'>",
     "actor_resolved": "<the actual agency name if the law defines 'the department'/'the commissioner' elsewhere in the text or via the administrative code title being amended; otherwise repeat actor_raw>",
     "action_summary": "<one plain-English sentence: what must be done. Start with a verb, e.g. 'Establish a cultural passport program encouraging visitation to participating sites in each borough.'>",
     "deliverable_type": <one of: {deliverable_types}>,
     "citation": "<where the duty lives, e.g. 'NYC Admin. Code § 20-563.2(b)' if the law adds/amends that section, else 'Section 3 of the local law'>",
     "quote": "<verbatim contiguous excerpt from the law text containing the operative language imposing this duty, 10-60 words, copied EXACTLY character-for-character including capitalization>",
     "deadline": {
       "kind": "none" | "fixed_date" | "days_after_effective" | "days_after_enactment" | "on_effective_date",
       "fixed_date": "YYYY-MM-DD" or null,
       "offset_days": <integer or null; convert months to days as months*30, years to days as years*365>,
       "text": "<the deadline phrase verbatim, e.g. 'no later than 180 days after the effective date of this local law', or null if none stated>"
     },
     "recurrence": "one-time" | "annual" | "biennial" | "quarterly" | "monthly" | "every N years" | "ongoing",
     "affected_groups": ["<who benefits or is regulated, e.g. 'tenants', 'small businesses', 'older adults'>", ...]
   }
 ]
}

RULES:
- Include ONLY duties of NYC government entities. Obligations the law imposes on private parties (employers, landlords, businesses) are NOT obligations records — but if the law directs an agency to enforce, administer, or write rules for those private-party requirements, THOSE agency duties are included.
- Mandatory duties only: "shall", "must", "is required to". Skip purely permissive language ("may") unless it establishes a program the law clearly expects to exist.
- One record per distinct duty. A recurring report is ONE record with the appropriate recurrence, not one record per year.
- A duty shared by multiple named agencies: create one record per named agency, same quote allowed.
- "Ongoing" recurrence is for continuous operational duties (maintain, enforce, operate, post and keep updated). "One-time" is for single deliverables.
- The quote must be copied character-for-character from the law text — it will be mechanically checked, and paraphrased quotes are rejected.
- deliverable_type: rulemaking = promulgating rules; report = periodic/one-time reporting to mayor/council/public; "database or data publication" includes websites, dashboards, posting datasets; "notice or posting" = required notices, translations, distributions of information; "monitoring or testing" = required sampling, testing, or ongoing measurement.
- Street co-naming laws: designating a thoroughfare or public place name implies the department of transportation must fabricate and install the street name signs. Record ONE obligation for the department of transportation with deliverable_type "signage or installation" covering all designations in the law.
- "In consultation with X" or "in coordination with X" does not make X a duty-holder. Record the obligation only for the lead agency; list consulted agencies nowhere.
- Permissive rulemaking ("the commissioner may promulgate rules") becomes an obligation ONLY when other provisions clearly presume the rules will exist (e.g. employers must follow "rules of the department"). Otherwise skip it.
- If the actor is genuinely undetermined (e.g. "an agency designated by the mayor"), keep actor_resolved as written; do not guess.
- Deadlines: if the law says "within 18 months of the effective date", use kind=days_after_effective, offset_days=540. If no deadline is stated for a duty that begins at effectiveness, use kind=on_effective_date only when the duty clearly starts then; otherwise kind=none.
- Do not invent obligations from the bill summary or title; use only the enacted text ("Be it enacted...").

LAW METADATA (for context only):
{metadata}

LAW TEXT:
{law_text}
"""


# ── Normalization helpers ─────────────────────────────────────────────────────

def norm_lookup_key(s: str) -> str:
    """Must match build_agency_crosswalk.norm()."""
    s = s.lower().strip()
    s = s.replace("&", "and")
    s = re.sub(r"[.,'’]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_quote(s: str) -> str:
    """Loosen whitespace/typography differences for quote verification."""
    s = s.lower()
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[\s ]+", " ", s)
    return s.strip()


ACTOR_PREFIXES = re.compile(
    r"^(the\s+)?(new\s+york\s+city\s+|nyc\s+|city\s+)?", re.I)


def match_agency(actor: str, lookup: dict[str, str],
                 agencies_by_canon: dict[str, dict]) -> tuple[str | None, str | None]:
    """Resolve a free-text actor name to (canonical_abbrev, full_name)."""
    if not actor:
        return None, None
    # drop parenthetical asides the model sometimes appends
    actor = re.sub(r"\s*\([^)]*\)", "", actor).strip()
    if not actor:
        return None, None
    candidates = [actor]
    # "the fire commissioner" / "the police commissioner"
    m = re.match(r"(?:the\s+)?(\w[\w\s]*?)\s+commissioner$", actor, re.I)
    if m:
        candidates.append(f"{m.group(1)} department")
        candidates.append(f"department of {m.group(1)}")
    # "the division of X within the department of Y" -> try the parent agency
    m = re.match(r".*\bwithin\s+(?:the\s+)?(.+)$", actor, re.I)
    if m:
        candidates.append(m.group(1))
    # "the commissioner of/for X", "the commissioner of the department of X"
    m = re.match(r"(?:the\s+)?commissioner\s+(?:of|for)\s+(.+)", actor, re.I)
    if m:
        rest = m.group(1)
        candidates.append(rest)
        if not re.search(r"\bdepartment\b", rest, re.I):
            candidates.append(f"department of {rest}")
    # "the office of X"
    m = re.match(r"(?:the\s+)?(?:mayor'?s\s+)?office\s+of\s+(.+)", actor, re.I)
    if m:
        candidates.append(f"mayor's office of {m.group(1)}")
        candidates.append(f"office of {m.group(1)}")
    # every candidate also tries with leading the/NYC/city prefixes stripped
    expanded = []
    for cand in candidates:
        expanded.append(cand)
        stripped = cand
        for _ in range(3):
            new = ACTOR_PREFIXES.sub("", stripped).strip()
            if new == stripped:
                break
            stripped = new
        if stripped and stripped != cand:
            expanded.append(stripped)
    for cand in expanded:
        canon = lookup.get(norm_lookup_key(cand))
        if canon:
            full = agencies_by_canon.get(canon, {}).get("full_name", canon)
            return canon, full
    return None, None


def compute_date(base: str | None, offset_days: int | None) -> str | None:
    if not base:
        return None
    try:
        d = datetime.strptime(base, "%Y-%m-%d").date()
    except ValueError:
        return None
    if offset_days:
        d = d + timedelta(days=offset_days)
    return d.isoformat()


def resolve_effective_date(clause: dict, enactment_date: str | None) -> str | None:
    kind = (clause or {}).get("kind")
    if kind == "immediate":
        return enactment_date
    if kind == "days_after_enactment":
        return compute_date(enactment_date, clause.get("offset_days"))
    if kind == "fixed_date":
        return clause.get("fixed_date")
    return None


def resolve_deadline(dl: dict, enactment_date: str | None,
                     effective_date: str | None) -> str | None:
    kind = (dl or {}).get("kind")
    if kind == "fixed_date":
        return dl.get("fixed_date")
    if kind == "days_after_enactment":
        return compute_date(enactment_date, dl.get("offset_days"))
    if kind == "days_after_effective":
        return compute_date(effective_date, dl.get("offset_days"))
    if kind == "on_effective_date":
        return effective_date
    return None


# ── Claude call ───────────────────────────────────────────────────────────────

def call_claude(client, model: str, prompt: str, retry_note: str | None = None):
    messages = [{"role": "user", "content": prompt}]
    if retry_note:
        messages.append({"role": "assistant", "content": "{"})
        messages = [{"role": "user", "content": prompt + "\n\n" + retry_note}]
    resp = client.messages.create(
        model=model,
        max_tokens=16000,
        messages=messages,
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    return json.loads(raw)


def extract_law(client, model: str, law: dict, text: str,
                lookup: dict, agencies_by_canon: dict) -> dict:
    metadata = json.dumps({
        "file_number": law["file_number"],
        "law_number": law["law_number_display"],
        "title": law["title"],
        "committee": law["committee"],
        "enactment_date": law["enactment_date"],
        "legistar_indexes": law.get("legistar_indexes", []),
    }, indent=1)
    prompt = (EXTRACTION_PROMPT
              .replace("{deliverable_types}", json.dumps(DELIVERABLE_TYPES))
              .replace("{metadata}", metadata)
              .replace("{law_text}", text))

    norm_text = normalize_quote(text)
    result = None
    for attempt in range(2):
        retry_note = None
        if attempt == 1 and result is not None:
            bad = [o["quote"] for o in result.get("obligations", [])
                   if normalize_quote(o.get("quote", "")) not in norm_text]
            retry_note = (
                "IMPORTANT: On a previous attempt, these quotes were NOT found "
                "verbatim in the law text. Re-extract, copying each quote "
                "character-for-character from the LAW TEXT above:\n"
                + json.dumps(bad, indent=1))
        try:
            result = call_claude(client, model, prompt, retry_note)
        except json.JSONDecodeError as e:
            log.warning(f"  JSON decode failed (attempt {attempt+1}): {e}")
            result = {"obligations": [], "extraction_error": str(e)}
            continue
        unverified = [o for o in result.get("obligations", [])
                      if normalize_quote(o.get("quote", "")) not in norm_text]
        if not unverified:
            break
        log.warning(f"  {len(unverified)} unverified quotes (attempt {attempt+1})")

    # Post-process
    enactment = law.get("enactment_date") or None
    effective = resolve_effective_date(result.get("effective_clause", {}), enactment)
    obligations = []
    for i, o in enumerate(result.get("obligations", []), 1):
        quote_ok = normalize_quote(o.get("quote", "")) in norm_text
        actor = o.get("actor_resolved") or o.get("actor_raw") or ""
        canon, full = match_agency(actor, lookup, agencies_by_canon)
        dtype = o.get("deliverable_type", "other")
        if dtype not in DELIVERABLE_TYPES:
            dtype = "other"
        deadline_date = resolve_deadline(o.get("deadline", {}), enactment, effective)
        obligations.append({
            "obligation_id": f"{law['matter_id']}-{i:02d}",
            "matter_id": law["matter_id"],
            "actor_raw": o.get("actor_raw", ""),
            "agency": canon or actor,
            "agency_full": full or actor,
            "agency_matched": canon is not None,
            "action_summary": o.get("action_summary", ""),
            "deliverable_type": dtype,
            "citation": o.get("citation", ""),
            "quote": o.get("quote", ""),
            "quote_verified": quote_ok,
            "deadline_kind": (o.get("deadline") or {}).get("kind", "none"),
            "deadline_text": (o.get("deadline") or {}).get("text"),
            "deadline_date": deadline_date,
            "recurrence": o.get("recurrence", "one-time"),
            "affected_groups": o.get("affected_groups", []),
        })

    return {
        "matter_id": law["matter_id"],
        "model": model,
        "extracted_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "effective_clause": result.get("effective_clause"),
        "effective_date": effective,
        "extraction_error": result.get("extraction_error"),
        "obligations": obligations,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--matters", nargs="+", default=None)
    ap.add_argument("--incremental", action="store_true")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")
    import anthropic
    client = anthropic.Anthropic()

    EXTRACT_CACHE.mkdir(parents=True, exist_ok=True)
    laws = json.loads(LAWS_JSON.read_text())["laws"]
    cw = json.loads(CROSSWALK_JSON.read_text())
    lookup = cw["lookup"]
    agencies_by_canon = {a["canonical"]: a for a in cw["agencies"]}

    if args.matters:
        laws = [l for l in laws if l["matter_id"] in set(args.matters)]
    if args.limit:
        laws = laws[:args.limit]

    # Prior results let --incremental work in CI, where cache/ doesn't exist:
    # reconstruct per-law results from the committed obligations.json
    prior: dict[str, dict] = {}
    if args.incremental and OUT_JSON.exists():
        prev = json.loads(OUT_JSON.read_text())
        obs_by_matter: dict[str, list] = {}
        joined_keys = {"file_number", "law_number_display", "law_title",
                       "committee", "prime_sponsor", "enactment_date",
                       "effective_date", "legistar_url"}
        for o in prev.get("obligations", []):
            obs_by_matter.setdefault(o["matter_id"], []).append(
                {k: v for k, v in o.items() if k not in joined_keys})
        for l in prev.get("laws", []):
            prior[l["matter_id"]] = {
                "matter_id": l["matter_id"],
                "effective_clause": {"text": l.get("effective_clause_text")},
                "effective_date": l.get("effective_date"),
                "obligations": obs_by_matter.get(l["matter_id"], []),
            }

    all_results = []
    for i, law in enumerate(laws, 1):
        cache_file = EXTRACT_CACHE / f"{law['matter_id']}.json"
        # cache first: renormalize_agencies.py updates the cache, so it is
        # fresher than the prior obligations.json
        if args.incremental and cache_file.exists():
            all_results.append(json.loads(cache_file.read_text()))
            continue
        if args.incremental and law["matter_id"] in prior:
            all_results.append(prior[law["matter_id"]])
            continue
        text_file = TEXT_CACHE / f"{law['matter_id']}.txt"
        if not text_file.exists():
            log.warning(f"[{i}] no cached text for {law['file_number']}; skipping")
            continue
        text = text_file.read_text()
        log.info(f"[{i}/{len(laws)}] {law['file_number']} "
                 f"{law['law_number_display']} ({len(text)} chars)")
        try:
            res = extract_law(client, args.model, law, text, lookup, agencies_by_canon)
        except Exception as e:
            log.error(f"  extraction failed: {e}")
            continue
        cache_file.write_text(json.dumps(res, indent=1))
        all_results.append(res)
        n = len(res["obligations"])
        nv = sum(1 for o in res["obligations"] if not o["quote_verified"])
        nm = sum(1 for o in res["obligations"] if not o["agency_matched"])
        log.info(f"  -> {n} obligations ({nv} unverified quotes, {nm} unmatched agencies)")
        time.sleep(0.5)

    # Flatten, joining law metadata the frontend needs on every record
    law_by_id = {l["matter_id"]: l for l in laws}
    flat = []
    law_summaries = []
    for res in all_results:
        law = law_by_id.get(res["matter_id"])
        if not law:
            continue
        law_summaries.append({
            **{k: law[k] for k in [
                "matter_id", "legistar_url", "file_number", "law_number",
                "law_number_display", "title", "summary", "committee",
                "sponsors", "prime_sponsor", "sponsor_count",
                "enactment_date", "legistar_indexes"]},
            "effective_date": res["effective_date"],
            "effective_clause_text": (res.get("effective_clause") or {}).get("text"),
            "obligation_count": len(res["obligations"]),
        })
        for o in res["obligations"]:
            flat.append({
                **o,
                "file_number": law["file_number"],
                "law_number_display": law["law_number_display"],
                "law_title": law["title"],
                "committee": law["committee"],
                "prime_sponsor": law["prime_sponsor"],
                "enactment_date": law["enactment_date"],
                "effective_date": res["effective_date"],
                "legistar_url": law["legistar_url"],
            })

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "model": args.model,
        "law_count": len(law_summaries),
        "obligation_count": len(flat),
        "laws": sorted(law_summaries,
                       key=lambda l: (l.get("enactment_date") or "", l["file_number"]),
                       reverse=True),
        "obligations": flat,
    }
    # compact separators: the file is large (8k+ obligations) and every
    # tracker page fetches it; GitHub Pages gzips it over the wire
    OUT_JSON.write_text(json.dumps(out, separators=(",", ":")))

    # CSV companion for the Download CSV button
    import csv as csvmod
    csv_path = DATA / "obligations.csv"
    csv_cols = ["law_number_display", "file_number", "agency", "agency_full",
                "action_summary", "deliverable_type", "deadline_date",
                "deadline_text", "recurrence", "citation", "committee",
                "prime_sponsor", "enactment_date", "effective_date",
                "quote", "legistar_url"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csvmod.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
        w.writeheader()
        for o in flat:
            w.writerow(o)
    log.info(f"Wrote {csv_path}")

    verified = sum(1 for o in flat if o["quote_verified"])
    matched = sum(1 for o in flat if o["agency_matched"])
    log.info(f"Wrote {OUT_JSON}: {len(flat)} obligations across "
             f"{len(law_summaries)} laws "
             f"({verified}/{len(flat)} quotes verified, "
             f"{matched}/{len(flat)} agencies matched)")


if __name__ == "__main__":
    main()
