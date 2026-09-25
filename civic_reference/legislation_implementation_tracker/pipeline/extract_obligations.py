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

Outputs data/obligations.json (duties) and data/powers.json (powers, split by is_power()). Per-law raw extractions checkpoint to
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
import difflib
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DATA = HERE.parent / "data"
TEXT_CACHE = HERE / "cache" / "text"
EXTRACT_CACHE = HERE / "cache" / "extracted"
LAWS_JSON = DATA / "laws.json"
CROSSWALK_JSON = DATA / "agency_crosswalk.json"
OUT_JSON = DATA / "obligations.json"
POWERS_JSON = DATA / "powers.json"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

DELIVERABLE_TYPES = [
    "rulemaking", "report", "study or audit", "plan or strategy",
    "program or service", "database or data publication",
    "signage or installation", "outreach or education", "training",
    "enforcement or inspection", "monitoring or testing",
    "notice or posting", "designation or staffing", "other",
]

# Duty / power / neither, as the model is asked to judge it. The same wording
# the blind reviewers applied in the Sep 2026 audit (methodology page).
KIND_DEFINITIONS = """- duty: the provision REQUIRES a NYC government agency, office, board or official to do something, or to refrain from something ("shall", "must", "is required to"). A prohibition on the government actor ("no agency may purchase", "the board may not approve") is a duty. "Shall have the power and duty to" is a duty. A provision that requires anything of the government actor is a duty even if it also grants discretion ("shall inspect and may impose a fee"). Street co-naming ("the following street name is hereby designated") is a duty (DOT signage).
- power: the provision AUTHORIZES a NYC government agency, office, board or official to act, and it may choose not to ("may", "is authorized to", "is empowered to", "shall have the power/authority to").
- neither: a right, option, duty or prohibition of a private party ("a tenant may elect", "the owner shall post", "no person shall"), a definition, or text that neither requires nor authorizes a government actor.
Judge the provision the quote comes from: the clause it sits in (an "except that" or "provided that" clause is its own provision), its full sentence, and for a bare list item the list's lead-in. If the quote spans several sentences or clauses and any imposes a duty on a named government actor, it is a duty."""
KINDS = ["duty", "power", "neither"]
# How the code rule and the model label combine into `kind`, chosen by
# measurement against the 350 blind reviewer labels (Sep 24 2026): the model
# decides (85 of 90 on the round neither was tuned on, rule 78), except for a
# provision with no verb of its own (a list item, a report-content fragment),
# where the rule reads the lead-in ("the report shall include: ... the number
# of ...") and the model tends to call the item neither (86 of 90 with this
# exception; 327 of 350 overall, 287 of 294 high-confidence).


def final_kind(rule: str | None, model: str | None, list_item: bool = False) -> str:
    """The published kind: the model label, except the rule for a bare list item."""
    if list_item and rule in KINDS:
        return rule
    if model in KINDS:
        return model
    return rule or "duty"


RECURRENCES = [
    "one-time", "ongoing", "daily", "weekly", "monthly", "every 2 months",
    "quarterly", "three times a year", "semiannual", "annual", "biennial",
    "every 3 years", "every 4 years", "every 5 years", "every 6 years",
    "every 8 years", "every 10 years", "as-needed", "multiple schedules",
]
OFFSET_UNIT_DAYS = {"days": 1, "months": 30, "years": 365}   # house convention, see compute_date


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


_OFFSET = _nullable({
    "type": "object",
    "properties": {"amount": {"type": "integer"},
                   "unit": {"type": "string", "enum": list(OFFSET_UNIT_DAYS)}},
    "required": ["amount", "unit"], "additionalProperties": False})

# Enforces the option lists the prompt describes. Off-list values used to reach
# the data unchecked (33 invented deadline kinds that silently lost their date,
# the "every N years" placeholder); an enum makes them impossible.
OBLIGATIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "effective_clause": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["immediate", "days_after_enactment", "fixed_date", "other"]},
                "offset": _OFFSET,
                "fixed_date": _nullable({"type": "string"}),
                "text": {"type": "string"},
            },
            "required": ["kind", "offset", "fixed_date", "text"], "additionalProperties": False,
        },
        "obligations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "actor_raw": {"type": "string"},
                    "actor_resolved": {"type": "string"},
                    "action_summary": {"type": "string"},
                    "deliverable_type": {"type": "string", "enum": DELIVERABLE_TYPES},
                    "citation": {"type": "string"},
                    "quote": {"type": "string"},
                    "deadline": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": [
                                "none", "fixed_date", "days_after_effective", "days_after_enactment",
                                "on_effective_date", "days_after_other"]},
                            "fixed_date": _nullable({"type": "string"}),
                            "offset": _OFFSET,
                            "text": _nullable({"type": "string"}),
                        },
                        "required": ["kind", "fixed_date", "offset", "text"], "additionalProperties": False,
                    },
                    "recurrence": {"type": "string", "enum": RECURRENCES},
                    "provision_kind": {"type": "string", "enum": ["duty", "power", "neither"]},
                    "affected_groups": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["actor_raw", "actor_resolved", "action_summary", "deliverable_type", "provision_kind",
                             "citation", "quote", "deadline", "recurrence", "affected_groups"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["effective_clause", "obligations"], "additionalProperties": False,
}


def _offset_to_days(block: dict | None) -> None:
    """Downstream code reads offset_days; derive it here from the law's own unit."""
    if not isinstance(block, dict):
        return
    off = block.pop("offset", None)
    block["offset_days"] = (off["amount"] * OFFSET_UNIT_DAYS[off["unit"]]) if off else None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract_obligations")

EXTRACTION_PROMPT = """You are analyzing the full text of an enacted New York City local law. Extract every concrete obligation the law imposes on, and every power it grants to, a NYC GOVERNMENT entity (an agency, department, office, commission, board, or officer such as "the commissioner", "the mayor", "the department", "the office"). This is for a public implementation-tracking dashboard.

Return a JSON object with this structure (the API enforces the schema; the notes below say what each field means):

{
 "effective_clause": {
   "kind": "immediate" | "days_after_enactment" | "fixed_date" | "other",
   "offset": {"amount": <integer>, "unit": "days" | "months" | "years"} or null,
   "fixed_date": "YYYY-MM-DD" or null,
   "text": "<the effective-date sentence, verbatim>"
 },
 "obligations": [
   {
     "actor_raw": "<the responsible entity exactly as the law names it, e.g. 'the department of transportation', 'the commissioner of health and mental hygiene', 'the mayor', 'a designated agency'>",
     "actor_resolved": "<the actual agency name. Laws almost always define generic references: check the definitions section ('the term department means...'), the administrative code title being amended, and 'established within the department of X' phrasing. NEVER return a bare generic like 'the department', 'the center', 'the office', 'the commission', 'the task force' - resolve it to the specific agency, or to the full name of the body the law creates (e.g. 'center for older workforce development'), or if genuinely undeterminable (e.g. 'an agency designated by the mayor') return exactly 'unspecified'>",
     "action_summary": "<one plain-English sentence: what must be done. Start with a verb, e.g. 'Establish a cultural passport program encouraging visitation to participating sites in each borough.'>",
     "deliverable_type": <one of: {deliverable_types}>,
     "citation": "<where the duty lives, e.g. 'NYC Admin. Code § 20-563.2(b)' if the law adds/amends that section, else 'Section 3 of the local law'>",
     "quote": "<verbatim contiguous excerpt from the law text containing the operative language imposing this duty, 10-60 words, copied EXACTLY character-for-character including capitalization>",
     "deadline": {
       "kind": "none" | "fixed_date" | "days_after_effective" | "days_after_enactment" | "on_effective_date" | "days_after_other",
       "fixed_date": "YYYY-MM-DD" or null,
       "offset": {"amount": <integer>, "unit": "days" | "months" | "years"} or null (the number and unit exactly as the law states them),
       "text": "<the deadline phrase verbatim, e.g. 'no later than 180 days after the effective date of this local law', or null if none stated>"
     },
     "recurrence": one of {recurrences} ("semiannual" = twice a year, which Council drafting calls "biannual"; "biennial" = every two years),
     "affected_groups": ["<who benefits or is regulated, e.g. 'tenants', 'small businesses', 'older adults'>", ...],
     "provision_kind": "duty" | "power" | "neither"
   }
 ]
}

RULES:
- Include ONLY duties of NYC government entities. Obligations the law imposes on private parties (employers, landlords, businesses) are NOT obligations records — but if the law directs an agency to enforce, administer, or write rules for those private-party requirements, THOSE agency duties are included.
- Record both kinds of provision: duties the law imposes ("shall", "must", "is required to") and powers it grants ("may", "is authorized to", "shall have the power to"). Quote the sentence that actually imposes or grants it, and do not describe a power as a duty in action_summary.
- provision_kind sorts each record for the public tables, by these definitions:
{kind_definitions}
- One record per distinct duty. A recurring report is ONE record with the appropriate recurrence, not one record per year.
- A duty shared by multiple named agencies: create one record per named agency, same quote allowed.
- "Ongoing" recurrence is for continuous operational duties (maintain, enforce, operate, post and keep updated). "One-time" is for single deliverables.
- The quote must be copied character-for-character from the law text — it will be mechanically checked, and paraphrased quotes are rejected.
- deliverable_type: rulemaking = promulgating rules; report = periodic/one-time reporting to mayor/council/public; "database or data publication" includes websites, dashboards, posting datasets; "notice or posting" = required notices, translations, distributions of information; "monitoring or testing" = required sampling, testing, or ongoing measurement.
- Street co-naming laws: designating a thoroughfare name implies the department of transportation must fabricate and install the street name signs. Record ONE obligation for the department of transportation with deliverable_type "signage or installation" covering all designations in the law. This DOT inference applies ONLY to streets and thoroughfares: a park or playground renaming implies the department of parks and recreation (not DOT), and other facility renamings imply the agency that operates the facility.
- {{Double braces}} mark NEW matter: text this law actually adds to the code, taken from Legistar's underline styling. When a section is introduced by "is amended to read as follows", everything OUTSIDE the braces is pre-existing law being reprinted, and you must NOT extract an obligation from it, however clearly it states a duty. Extract only duties whose operative language sits inside braces. If a law's text carries no braces at all, fall back to the amendment rule below.
- QUOTE THE LAW AS IT READS AFTER THE AMENDMENT. In an amended section, copy the text with the bracketed matter left out and the braced matter left in. Do not stitch a deleted word to its replacement: "[fourteen] {{14}} of whom" is quoted as "14 of whom", never as "fourteen 14 of whom".
- Square brackets mark DELETED matter. In NYC Council drafting, text enclosed in [brackets] is being struck from the code by this law. NEVER extract an obligation from text inside brackets: that duty is being repealed, not created. A bracketed span can run for several sentences, so check whether an unclosed "[" precedes the passage you are quoting. If the law strikes a duty and re-enacts it elsewhere in the same law, quote the re-enacted (unbracketed) copy.
- Deadlines anchored to an event the law does not date are NOT effective-date deadlines. This covers recurring or per-case events (each application received, each hearing held, each review completed, the occurrence of a vacancy) AND one-time future events (the conclusion of a pilot, the commencement of a program, the completion of a study, the formation of a body, the filing of construction documents). Use kind=days_after_other with no offset, even when the clause says "within 60 days". Only a clock the law expressly ties to enactment or the effective date gets days_after_enactment or days_after_effective.
- Amendment texts ("is amended to read as follows"): the restated body of the amended section is PRE-EXISTING law. Only newly added matter (in Legistar's published text, the underlined portions) can create obligations for this law. Never extract a duty whose operative language exists unchanged in the prior law.
- "In consultation with X" or "in coordination with X" does not make X a duty-holder. Record the obligation only for the lead agency; list consulted agencies nowhere.
- If the actor is genuinely undetermined (e.g. "an agency designated by the mayor"), set actor_resolved to "unspecified" and keep the phrase in actor_raw; do not guess.
- Deadlines: if the law says "within 18 months of the effective date", use kind=days_after_effective, offset={"amount": 18, "unit": "months"}. If no deadline is stated for a duty that begins at effectiveness, use kind=on_effective_date only when the duty clearly starts then; otherwise kind=none.
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


# Legistar publishes an amended section with the deleted matter still visible in
# [square brackets]. A model quoting the operative post-amendment sentence
# correctly skips that struck text, which made the verifier call the quote
# unverified: an August 2026 diagnosis found 267 records failing this way, plus
# 40 differing only in punctuation and 25 carrying pypdf's spurious intra-word
# spaces ("the d epartment"). Verifying against a bracket-free copy of the law,
# on alphanumeric characters only, accepts all three and still REJECTS a quote
# drawn from deleted text, which is what we want it to catch.
_BRACKET_SPAN = re.compile(r"\[[^\[\]]{0,4000}?\]", re.S)


def operative_text(s: str) -> str:
    """The law with struck matter removed, i.e. what it says after amendment."""
    prev = None
    out = s or ""
    while out != prev:                       # nested brackets do occur
        prev = out
        out = _BRACKET_SPAN.sub(" ", out)
    return out


def alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_quote(s))


_LOWER_BRACKET_RUN = re.compile(r"\[[a-z][^\[\]]{0,300}?\]")


def clean_stored_quote(quote: str, law_text: str | None) -> tuple[str, bool]:
    """Strip {{new-matter}} markers from a stored quote; if a lowercase-start
    [bracketed] run (deleted matter Legistar publishes in brackets) survived
    into the quote, drop that run when the remainder still verifies against
    the law. Returns (cleaned_quote, quote_has_deleted_text)."""
    q = (quote or "").replace("{{", "").replace("}}", "")
    if not _LOWER_BRACKET_RUN.search(q):
        return q, False
    candidate = _LOWER_BRACKET_RUN.sub("", q)
    candidate = re.sub(r"\s{2,}", " ", candidate).strip()
    if law_text and quote_present(candidate, law_text):
        return candidate, False
    return q, True


def quote_present(quote: str, law_text: str, operative: str | None = None) -> bool:
    """Is this quote in the law, allowing for markup, punctuation and PDF spacing?"""
    q = normalize_quote(quote or "")
    if not q:
        return False
    if q in normalize_quote(law_text):
        return True
    qa = alnum(quote)
    if not qa:
        return False
    op = operative if operative is not None else operative_text(law_text)
    return qa in alnum(op)


def normalize_quote(s: str) -> str:
    """Loosen whitespace/typography differences for quote verification.

    Also drops the {{...}} new-matter markers the fetcher preserves from
    Legistar's underline styling, so a quote verifies whether or not it spans
    a marker boundary.
    """
    s = s.replace("{{", "").replace("}}", "")
    s = s.lower()
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[\s ]+", " ", s)
    return s.strip()


ACTOR_PREFIXES = re.compile(
    r"^(the\s+)?(new\s+york\s+city\s+|nyc\s+|city\s+)?", re.I)

# ── Duty, power, or neither ───────────────────────────────────────────────────
# The obligations table tracks what a law REQUIRES of an agency. A law also
# grants powers ("the department may inspect", "shall have the power to
# impose penalties"); those go to powers.json and never carry a deadline.
# Options a law gives private parties ("an owner may apply") are neither and
# are published in no table. The sort is decided in code from the full
# provision the quote comes from (its sentence, the clause the quote sits in,
# and a list lead-in for a bare item), read from the cached law text at
# extraction time and stored on the record as `kind`, so CI (no text cache)
# reproduces it exactly. Rules, in order: the month "May" is ignored; a
# prohibition ("no agency may", "may not") is a duty; "power(s) and duty" is
# a duty; a grant ("shall have the power to", "is authorized to") with no
# other mandatory verb is a power; any mandatory verb outside a relative
# clause is a duty; "may" is a power unless its subject is a private party.
# Only the provision's main verb counts: a modal inside a subordinate or
# complement clause ("may determine that X shall") does not; "may" of
# possibility ("may have been", "as may be necessary") is ignored; a passive
# grant ("may be issued") is a power; definitions and a private party's own
# duty or option are neither.
# Validated Sep 24 2026 against two blind reviews, 170 records (methodology page).

MONTH_MAY = re.compile(r"\bMay\s+\d{1,2}(st|nd|rd|th)?\b|\bMay,?\s+\d{4}\b"
                       r"|\bMay\s+(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|"
                       r"twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|"
                       r"twentieth|twenty-\w+|thirtieth|thirty-first)\b"
                       r"|\b(of|in|by|before|after|until|through)\s+May\b")
# "may" of possibility or reference, not permission
EPISTEMIC = re.compile(r"\bmay\s+have\s+been\b|\bmay\s+(be|become)\s+(necessary|appropriate|applicable|needed|"
                       r"required|warranted|relevant|available|practicable|feasible|convenient|affected)\b"
                       r"|\b\w+s\s+or\s+may\s+\w+|\bas\s+may\b"
                       r"|\bas\s+(the\s+)?[\w']+(\s+[\w']+){0,3}\s+may\s+(deem|determine|consider|find|require|specify|prescribe|direct|approve)\b|\bsuch\s+(other\s+)?[^,;]{0,60}?\bas\s+(\w+\s+){0,5}?may\b", re.I)
DEFINITION = re.compile(r"\b(the term|as used in this)\b.{0,300}?\bmeans?\b|\bshall mean\b"
                        r"|^\W*[\"“][^\"”]{1,80}[\"”]\s+(shall\s+)?means?\b", re.I | re.S)
READER_NOTE = re.compile(r"^\W*(refer to|see)\b", re.I)
POWER_AND_DUTY = re.compile(r"\bpowers?\s+and\s+(the\s+)?dut(y|ies)\b|\bdut(y|ies)\s+and\s+(the\s+)?powers?\b", re.I)
GRANT = re.compile(r"\b(shall|is|are)\s+(hereby\s+)?(have|has|be|been)?\s*(all\s+(of\s+)?)?(the\s+)?"
                   r"(powers?|authority|authorized|empowered)\b"
                   r"|\b(is|are)\s+(hereby\s+)?(authorized|empowered)\b", re.I)
MODAL = re.compile(r"\b(shall|must|is required|are required|is hereby required|may)\b", re.I)
MANDATORY_WORD = {"shall", "must", "is required", "are required", "is hereby required"}
# a modal inside a subordinate clause does not govern the provision
# ...unless the relative pronoun has its own verb ("each agency that employs
# covered employees shall ensure"): then the modal belongs to the main clause
SUBORDINATE = re.compile(r"(?<!except )(?<!provided )(?<!so )(?<!however )(?<!however, )(?<!further )\b(that|which|who|whom|how|whether|where|when|if)\b"
                         r"(?!\s+(is|are|was|were|has|have|had|(?!the\b|such\b|a\b|an\b|any\b|each\b|this\b|its\b|his\b|her\b|their\b)\w+(s|ed))\b)"
                         r"[^;:,]{0,150}?\b(shall|must|may)\b", re.I)
COMPLEMENT = re.compile(r"\b(ensure|determine|require|provide|find|certify|decide|direct)s?\s+(that\s+)?"
                        r"[^;:]{0,150}?\b(shall|must)\b", re.I)
COORDINATED_MANDATORY = re.compile(r"(,\s*|\s)(and|but|or)\s+((the|such|said)\s+[\w\s]{1,40}?\s+)?(shall|must)\b"
                                   r"(?!\s+(have|has)\s+(all\s+)?(the\s+)?(powers?|authority)\b|\s+be\s+(authorized|empowered)\b)", re.I)
PROHIBITION = re.compile(r"\bmay not\b|\bshall not\b|\bmust not\b|\b(no|neither|nor)\b[^.;:]{0,120}?\b(may|shall)\b", re.I)
GOV_VERB_PASSIVE = re.compile(r"may\s+be\s+(issued|designated|established|imposed|granted|approved|promulgated|"
                              r"adopted|revoked|suspended|waived|extended|modified|added|deleted|amended|"
                              r"assessed|collected|enforced|inspected|audited|charged|awarded|certified|"
                              r"licensed|permitted|registered|appointed|removed|seized|recovered|made|set|"
                              r"determined|prescribed|authorized|required|renewed|denied|reduced|increased|"
                              r"deferred|forgiven|compromised|remitted|abated|closed|sealed|towed|impounded)\b", re.I)
AGENT_GOV = re.compile(r"\bby\s+(rule\s+of\s+|rules\s+of\s+|any\s+authorized\s+(employee|officer|agent)s?\s+(or\s+agent\s+)?of\s+|a\s+determination\s+(by|of)\s+)?(the\s+)?(department|commissioner|agency|office|board|"
                       r"mayor|city|commission|director|council|comptroller|administrator|chair|"
                       r"police|fire|corporation counsel|chancellor|authority|coordinator)\b", re.I)
GOV = re.compile(r"\b(department|commissioner|agency|agencies|office|board|mayor|city|commission|"
                 r"director|council|borough president|comptroller|administrator|chair(person)?|"
                 r"police|fire|corporation counsel|chancellor|authority|coordinator|advocate|"
                 r"task force|secretary|division|bureau|court|center|311|public advocate|trust|corporation of the city|"
                 r"district attorneys?|sheriff|marshal|panel|committee|mayor's office|administration)\b", re.I)
PRIVATE = re.compile(r"\b(owners?|tenants?|persons?|applicants?|employers?|employees?|landlords?|"
                     r"members? of the public|residents?|contractors?|subcontractors?|operators?|"
                     r"licensees?|permittees?|registrants?|business(es)?|individuals?|occupants?|"
                     r"vendors?|drivers?|retail stores?|stores?|delivery services?|cafes?|restaurants?|establishments?|"
                     r"shops?|not-for-profits?|nonprofits?|organizations?|developers?|lessees?|licensed \w+|"
                     r"companies|company|corporations?|providers?|carriers?|"
                     r"urinals?|devices?|vehicles?|signs?)\b", re.I)
NOUN_ITEM = re.compile(r"^\W*(\(?[0-9ivxa-z]{1,4}[.)]\s*)?(a|an|the|any|each|all)?\s*(list|number|description|copy|"
                       r"copies|summary|statement|breakdown|explanation|total|percentage|analysis|"
                       r"identification|records?|information|data|documentation|documents?|name|names|"
                       r"amount|date|dates|status|results?|recommendations?|assessment|procedures?|process|policy|policies|"
                       r"steps|methods?|criteria|types?|sources?|reasons?)\b", re.I)

_BOUND = re.compile(r"(?<=[.;])\s+(?=[A-Z(\d])|\n\s*\n")
_ITEM_AT_END = re.compile(r"(^|[\s;:])\(?[0-9ivxa-z]{1,4}[.)]\s*$", re.I)
_ITEM_AT_START = re.compile(r"^\s*\(?[0-9ivxa-z]{1,4}[.)]\s", re.I)
# provisos, "except that", and enumerated sub-items are separate provisions
CLAUSE_SPLIT = re.compile(r"[;,]?\s+(?=provided(,)?\s+(that|however|further)\b)|,?\s+(?=except that\b)"
                          r"|(?<=[;:])\s*(?=(and\s+|or\s+)?\([ivx]{1,4}\)\s|(and\s+|or\s+)?\([a-z0-9]{1,3}\)\s)", re.I)


def _norm(s):
    s = s.replace("{{", "").replace("}}", "")
    return re.sub(r"\s+", " ", s)


def provision_context(quote, text):
    """(lead_in, sentence, offset_of_quote_in_sentence) or None."""
    if not quote or not text:
        return None
    t = _norm(re.sub(r"\[[^\[\]]{0,4000}?\]", " ", text))
    keep = [(i, c.lower()) for i, c in enumerate(t) if c.isalnum()]
    hay = "".join(c for _, c in keep)
    q = "".join(c.lower() for c in _norm(re.sub(r"\[[^\[\]]{0,400}?\]", " ", quote)) if c.isalnum())
    if len(q) < 12:
        return None
    at = -1
    for n in (240, 120, 60, 30):       # longest unambiguous prefix first
        at = hay.find(q[:n])
        if at >= 0:
            break
    if at < 0:
        return None
    pos = keep[at][0]
    qend = keep[min(at + len(q) - 1, len(keep) - 1)][0]
    start = 0
    for m in _BOUND.finditer(t, 0, min(len(t), pos + 1)):
        start = m.end()
    end_m = re.search(r"[.;](\s|$)", t[pos:])
    end = pos + end_m.end() if end_m else len(t)
    raw = t[start:end]
    sentence = raw.strip()
    lpad = len(raw) - len(raw.lstrip())
    offset = pos - start - lpad
    qend_in = min(len(sentence), qend - start - lpad)
    lead = ""
    before = t[max(0, start - 4000):start].rstrip()
    if before.endswith(":") or _ITEM_AT_END.search(before) or _ITEM_AT_START.match(sentence):
        colon = before.rfind(":")
        if colon >= 0:
            seg = before[:colon + 1]
            ls = max(seg.rfind(". ", 0, colon - 1), seg.rfind("; ", 0, colon - 1))
            cand = seg[ls + 1:].strip() if ls >= 0 else seg[-400:].strip()
            if (len(cand) < 600 and not re.search(r"read as follows|be it enacted|following meanings", cand, re.I)
                    and not DEFINITION.search(cand)):
                lead = cand
    more = []
    cur = end
    while cur < qend and len(more) < 4:
        nxt = re.search(r"[.;](\s|$)", t[cur:])
        stop = cur + nxt.end() if nxt else len(t)
        piece = t[cur:stop].strip()
        if piece:
            more.append(piece)
        cur = stop
    # clauses of this sentence after the first one the quote covers
    cuts = [0] + [m.end() for m in CLAUSE_SPLIT.finditer(sentence)] + [len(sentence)]
    later = [sentence[a:b] for a, b in zip(cuts, cuts[1:]) if a > offset and a < qend_in]
    return lead, sentence, max(0, offset), later + more


def _clause(sentence, offset):
    cuts = [0] + [m.end() for m in CLAUSE_SPLIT.finditer(sentence)] + [len(sentence)]
    for a, b in zip(cuts, cuts[1:]):
        if a <= offset < b:
            return sentence[a:b]
    return sentence


def _subject_is_private(window):
    window = re.split(r"[;:]|,\s", window)[-1]
    return bool(PRIVATE.search(window)) and not GOV.search(window)


def _strip_subordinate(t, after):
    """Remove modals that sit in a subordinate or complement clause after position `after`."""
    head, tail = t[:after], t[after:]
    tail = SUBORDINATE.sub(lambda m: m.group(0)[:m.start(3) - m.start(0)], tail)
    tail = COMPLEMENT.sub(lambda m: m.group(0)[:m.start(3) - m.start(0)], tail)
    return head + tail


def classify_text(t):
    t = MONTH_MAY.sub(" ", t or "")
    t = EPISTEMIC.sub(" ", t)
    if READER_NOTE.match(t):
        return "neither"
    if DEFINITION.search(t) and not re.search(r"\b(shall|must)\s+(not\s+)?(\w+\s+){0,2}(establish|provide|submit|post|report|maintain|issue|develop|create|conduct|notify)\b", t, re.I):
        return "neither"
    if POWER_AND_DUTY.search(t):
        return "duty"
    t = _strip_subordinate(t, 0)
    # "permits that are authorized to be issued" describes, it grants nothing
    t = re.sub(r"\b(that|which|who)\s+(is|are)\s+(hereby\s+)?(authorized|empowered)\b", " ", t, flags=re.I)
    g = GRANT.search(t)
    m = MODAL.search(t)
    if g and (m is None or g.start() <= m.start()):
        rest = _strip_subordinate(t, g.end())[g.end():]
        return "duty" if COORDINATED_MANDATORY.search(rest) else "power"
    if m is None:
        return "duty"
    # everything after the main modal: drop modals in subordinate/complement clauses
    main = _strip_subordinate(t, m.end())
    word = m.group(1).lower()
    before = main[max(0, m.start() - 160):m.start()]
    p = PROHIBITION.search(main, max(0, m.start() - 125))
    if p and p.start() <= m.end():
        return "neither" if _subject_is_private(main[max(0, p.start() - 160):p.start()]) else "duty"
    if word in MANDATORY_WORD:
        if re.match(r"(shall|must)\s+be\s+\w+ed\b", main[m.start():m.start() + 60], re.I) and AGENT_GOV.search(main[m.start():m.start() + 140]):
            return "duty"
        return "neither" if _subject_is_private(before) else "duty"
    # "may" is the main verb
    if COORDINATED_MANDATORY.search(main[m.end():]):
        return "duty"
    after = main[m.start():m.start() + 200]
    if GOV_VERB_PASSIVE.match(after) or (re.match(r"may\s+be\s+\w+ed\b", after, re.I)
                                           and AGENT_GOV.search(after[:120])):
        return "power"
    if re.match(r"may\s+be\s+\w+ed\b", after, re.I) and not GOV.search(main):
        return "neither"
    if _subject_is_private(before):
        return "neither"
    return "power"


def _gov_duty(x):
    """A later sentence counts only as a duty a named government actor carries."""
    if classify_text(x) != "duty":
        return False
    t = _strip_subordinate(EPISTEMIC.sub(" ", MONTH_MAY.sub(" ", x)), 0)
    m = MODAL.search(t)
    return bool(m) and m.group(1).lower() in MANDATORY_WORD and bool(
        GOV.search(re.split(r"[;:]|,\s", t[max(0, m.start() - 160):m.start()])[-1] or t[:m.start()]))


def classify(quote, text=None):
    ctx = provision_context(quote, text) if text else None
    if not ctx:
        return classify_text(quote)
    lead, sentence, offset, more = ctx
    clause = _clause(sentence, offset)
    own = MODAL.search(_strip_subordinate(EPISTEMIC.sub(" ", MONTH_MAY.sub(" ", clause)), 0))
    if lead and (not own or NOUN_ITEM.match(clause)):
        kinds = [classify_text(lead + " " + clause)]
    else:
        kinds = [classify_text(clause)]
    # a quote that runs into later sentences covers them too; a duty in any wins
    kinds += ["duty" for x in more if _gov_duty(x)]
    for k in ("duty", "power", "neither"):
        if k in kinds:
            return k

def is_list_item(quote, text=None) -> bool:
    """A provision with no verb of its own: a bare list item under a lead-in, or a
    verbless fragment ("the number of complaints ...") that is content some duty
    requires. The rule, not the model, sorts these (needs the law text)."""
    ctx = provision_context(quote, text) if text else None
    if not ctx:
        return False
    lead, sentence, offset, _more = ctx
    clause = _clause(sentence, offset)
    own = MODAL.search(_strip_subordinate(EPISTEMIC.sub(" ", MONTH_MAY.sub(" ", clause)), 0))
    return not own or (bool(lead) and bool(NOUN_ITEM.match(clause)))


def is_power(quote, text=None):
    return classify(quote, text) == "power"


def _kind(o: dict) -> str:
    """Published kind from the stored rule and model labels (quote-only rule as a last resort)."""
    rule = o.get("kind_rule") or o.get("kind") or classify(o.get("quote"))
    return final_kind(rule, o.get("kind_model"), bool(o.get("kind_list_item")))


# Bare generic actor references that must never surface as agency tags.
# When one of these survives unmatched, the record is labeled "Unspecified"
# (the raw phrase stays visible as actor_raw in the row detail).
VAGUE_ACTOR = re.compile(
    r"^(the|a|an|each|every|any|such|all)?\s*"
    r"(city\s+)?(center|department|office|commission|commissioner|agency|"
    r"agencies|board|director|division|administrator|coordinator|"
    r"task\s*force|taskforce|committee|panel|unit|entity|organization|"
    r"chair|city|speaker|working\s+group|unspecified)s?$", re.I)

# Phrases that describe an undetermined actor without naming one:
# "the administering agency", "an office or agency designated by the mayor",
# "the head of each agency", "each such agency".
UNDETERMINED_PHRASES = re.compile(
    r"^(the|an?|each|every|any)\s+"
    r"((administering|supervising|designated|responsible|relevant|"
    r"appropriate|applicable|implementing|contracted|lead)\s+"
    r"(agency|office|entity|department|body)|"
    r"(agency|office|entity|department|body)"
    r"(,?\s+(office|entity|department)s?)*"
    r"(\s+or\s+(agency|office|entity|department|entities|offices|agencies))*"
    r"\s+(designated|selected|responsible|established|charged)\b|"
    r"head\s+of\s+(each|every|the|any|such)\s+(city\s+)?agency|"
    r"such\s+(city\s+)?(agency|office|department|entity))", re.I)


# Actor phrases the law leaves open-ended even though they run long enough to
# escape the patterns above: mayoral-designation constructions ("the department
# or another agency designated by the mayor"), class references ("each agency
# that provides the survey form"), and sentence fragments the extractor
# occasionally lifts in place of an actor ("all solicitations for contracts...").
OPEN_ENDED_ACTOR = re.compile(
    # "designated by X" leaves the actor to be named later, whoever X is. The
    # first version of this only matched "designated by the mayor", so
    # "any other department designated by the department of sanitation"
    # survived as an agency tag.
    r"(designated\s+by\s+(the|such|a|an)\b|as\s+(the\s+\w+(\s+\w+)?\s+)?(shall|may)\s+designate|"
    r"as\s+may\s+be\s+designated|"
    r"or\s+(another|other|such\s+other)\s+(agency|office|department|entity))", re.I)

CLASS_ACTOR = re.compile(
    r"^(each|every|any|all)\s+(city\s+)?"
    r"(agency|agencies|office|offices|department|departments|entity|entities|"
    r"person|website|websites|solicitation|solicitations|copies|owner|owners|"
    r"animal\s+shelter|temporary\s+location|participating\s+agency|"
    r"other\s+agencies|providers)\b", re.I)

# An agency described only by what it does ("an agency that issues a notice of
# violation") names no institution, and some phrases are not actors at all
# ("Copies of any reports submitted to...", "There shall be an interagency
# task force").
DESCRIBED_AGENCY = re.compile(
    r"^(an?|the|relevant|city)\s*(city\s+)?agenc(y|ies)\b.*\b(that|which|to\s+which|"
    r"responsible\s+for|including)\b", re.I)

NOT_AN_ACTOR = re.compile(
    r"^(copies\s+of|for\s+city-owned|there\s+shall\s+be|all\s+solicitations)\b", re.I)


# A duty the law places on every city agency (Charter s 1150 defines "agency"
# to include community boards and other city bodies). This is a specific class,
# not an undetermined actor, so it gets its own tag instead of "Unspecified" —
# otherwise a citywide duty is invisible to every agency that has to do it.
ALL_AGENCIES = re.compile(
    r"^(the\s+)?(each|every|all)\s+(city\s+|nyc\s+|new\s+york\s+city\s+)?"
    r"(government\s+|mayoral\s+)?agenc(y|ies)$", re.I)


def is_all_agencies(s: str) -> bool:
    return bool(ALL_AGENCIES.match(re.sub(r"\s*\([^)]*\)", "", (s or "")).strip()))


# "X, in consultation with Y" names one duty-holder, X. The prompt already says
# to record only the lead agency; this makes the resolver agree when the model
# hands back the whole phrase.
CO_ACTOR = re.compile(r",?\s+(in\s+(consultation|coordination|conjunction|partnership)\s+with|"
                      r"together\s+with|jointly\s+with)\b.*$", re.I)


def lead_actor(s: str) -> str:
    return CO_ACTOR.sub("", (s or "")).strip().rstrip(",")


def is_vague_actor(s: str) -> bool:
    s = re.sub(r"\s*\([^)]*\)", "", (s or "")).strip()
    if VAGUE_ACTOR.match(s) or UNDETERMINED_PHRASES.match(s):
        return True
    # A phrase that names no institution but describes one by role or class,
    # or that is not an actor at all, must not surface as an agency tag.
    return bool(OPEN_ENDED_ACTOR.search(s) or CLASS_ACTOR.match(s)
                or DESCRIBED_AGENCY.match(s) or NOT_AN_ACTOR.match(s))


# Curated per-law actor resolutions (pipeline/actor_overrides.json):
# {matter_id: {actor_phrase: "resolved name" | "resolved | parent: X" | null}}
# Built from a context pass that read each law's definitions. null means the
# law genuinely leaves the actor undetermined -> tag Unspecified.
# Obligations whose verbatim quote sits in text a law only reprints (see
# pipeline/sweep_restated_duties.py). Flagged rather than deleted: a spot check
# put the sweep at ~86% precision, and the misses are laws that did touch the
# provision (renumbering it, or amending the same duty), so deleting on the
# signal alone would drop real duties.
# DORIS filing status per report obligation, built by build_report_filings.py.
# Joined here so every view gets it without a second fetch. Method and status
# vocabulary follow Josh Greenman's NYC Overdue Reports tracker.
_FILINGS_PATH = HERE.parent / "data" / "report_filings.json"
REPORT_FILINGS: dict = {}
if _FILINGS_PATH.exists():
    REPORT_FILINGS = json.loads(_FILINGS_PATH.read_text()).get("filings", {})

_RESTATED_PATH = HERE / "restated_candidates.json"
RESTATED_IDS: set = set()
if _RESTATED_PATH.exists():
    RESTATED_IDS = {
        c["obligation_id"]
        for c in json.loads(_RESTATED_PATH.read_text()).get("candidates", [])
    }

_OVERRIDES_PATH = HERE / "actor_overrides.json"
ACTOR_OVERRIDES: dict = (json.loads(_OVERRIDES_PATH.read_text())
                         if _OVERRIDES_PATH.exists() else {})


# ── Sep 25 2026: build-time re-attribution of reprinted duties ──────────────
# A law that amends a code section reprints the whole section, with the parts
# it actually changes underlined ({{...}} in cache/text). A duty whose quote
# sits entirely OUTSIDE the underlined runs is text this law only reprints,
# not text it enacts. Computed fresh from cache/text every rebuild (not from
# the one-off restated_candidates.json a prior sweep wrote), via the same
# split_markers/restated_spans/condense/locate logic sweep_restated_duties.py
# uses to find these blocks in the first place.
from sweep_restated_duties import (  # noqa: E402
    split_markers, restated_spans, condense, locate, AMENDED,
)


def _sim_norm(s: str) -> str:
    """Normalize a quote for similarity comparison (marker/case/space-blind)."""
    s = (s or "").replace("{{", "").replace("}}", "")
    for a, b in (("“", '"'), ("”", '"'), ("‘", "'"),
                 ("’", "'"), ("–", "-"), ("—", "-")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s.lower()).strip()


_SECTION_RE = re.compile(r"§+\s*([0-9]+(?:-[0-9]+)?(?:\.[0-9]+)?)")


def _code_section(citation: str | None) -> str | None:
    """The code section a citation names ('... Code § 19-160(b)(1)' -> '19-160')."""
    m = _SECTION_RE.search(citation or "")
    return m.group(1) if m else None


def _subdivision(citation: str | None) -> str | None:
    """The subdivision path after the section ('§ 28-202.1(2)' -> '(2)';
    '§ 28-202.1, item 1' -> '(1)'), or None when the citation names none."""
    c = citation or ""
    m = _SECTION_RE.search(c)
    if not m:
        return None
    rest = c[m.end():]
    item = re.match(r"\s*,?\s*(?:item|paragraph|subdivision)\s+([0-9a-z]+)", rest, re.I)
    if item:
        return f"({item.group(1).lower()})"
    parts = re.match(r"((?:\([0-9a-z]+\))+)", rest.strip(), re.I)
    return parts.group(1).lower() if parts else None


def _same_provision(a: dict, b: dict) -> bool:
    """Same section, and the same subdivision whenever both name one."""
    sa, sb = _subdivision(a.get("citation")), _subdivision(b.get("citation"))
    return not (sa and sb and sa != sb)


def _same_actor(a: dict, b: dict) -> bool:
    """Same duty holder: identical labels (case-blind), or one side not matched
    to a known agency (a label variant such as "the chief privacy officer" for
    OIP). Two DIFFERENT matched agencies are a transfer of the duty, not a
    duplicate, so the reprint stays as existing code under the new agency."""
    la, lb = (a.get("agency") or "").lower(), (b.get("agency") or "").lower()
    if la and la == lb:
        return True
    return not (a.get("agency_matched") and b.get("agency_matched"))


def quote_similarity(a: str, b: str) -> float:
    """Normalized text similarity: difflib.SequenceMatcher ratio on quotes
    stripped of new-matter markers, case-folded, and whitespace-collapsed.
    0.9+ is treated as "the same statutory sentence"."""
    a, b = _sim_norm(a), _sim_norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def reattribute_reprints(flat: list[dict], powers: list[dict],
                         law_by_id: dict) -> tuple[list, dict]:
    """Split every duty/power whose quote is 100% reprinted (new-matter
    fraction 0) into a dropped duplicate (an earlier-enacted tracked law
    already records the same duty for the same agency) or a kept
    `existing code` record. Returns (dropped_ids, restated_links)."""
    marked_text: dict[str, str] = {}
    for mid in {o["matter_id"] for o in flat + powers}:
        p = TEXT_CACHE / f"{mid}.txt"
        if p.exists():
            t = p.read_text(errors="ignore")
            if "{{" in t and AMENDED.search(t):
                marked_text[mid] = t

    parsed: dict[str, tuple] = {}          # matter_id -> (hay, idx, flags, spans)
    for mid, marked in marked_text.items():
        plain, flags = split_markers(marked)
        spans = restated_spans(plain)
        hay, idx = condense(plain)
        parsed[mid] = (hay, idx, flags, spans)

    # Bucket every record by the code section its citation names. A reprint
    # only duplicates a record for the SAME section: boilerplate sentences
    # recur across chapters (a courier duty in 20-1507 read like a Fair
    # Workweek duty in 20-1207; Sep 25 2026 review found 9 such false links).
    # Records with no parsable section are never dropped.
    buckets: dict[str, list[dict]] = {}
    for o in flat + powers:
        sec = _code_section(o.get("citation"))
        if sec:
            buckets.setdefault(sec, []).append(o)

    reprint_candidates = []
    for o in flat + powers:
        mid = o["matter_id"]
        if mid not in parsed:
            continue                 # no text here (CI): keep prior flags
        o.pop("restated", None)
        o.pop("origin", None)
        hay, idx, flags, spans = parsed[mid]
        frac = locate(hay, idx, flags, o.get("quote") or "", spans)
        if frac == 0.0:
            reprint_candidates.append(o)

    dropped_ids: set = set()
    links: dict[str, list] = {}
    for o in reprint_candidates:
        mid = o["matter_id"]
        law = law_by_id.get(mid, {})
        my_enacted = law.get("enactment_date") or ""
        sec = _code_section(o.get("citation"))
        best = None
        for other in (buckets.get(sec, []) if sec else []):
            if other["matter_id"] == mid or not _same_actor(o, other) or not _same_provision(o, other):
                continue
            other_law = law_by_id.get(other["matter_id"], {})
            other_enacted = other_law.get("enactment_date") or ""
            if not other_enacted or not my_enacted or other_enacted >= my_enacted:
                continue          # not earlier-enacted
            sim = quote_similarity(o.get("quote"), other.get("quote"))
            if sim >= 0.9 and (best is None or other_enacted < best[1]):
                best = (other, other_enacted, sim)
        if best:
            origin, _, sim = best
            dropped_ids.add(o["obligation_id"])
            links.setdefault(mid, []).append({
                "obligation_id": o["obligation_id"],
                "quote": o.get("quote"),
                "agency": o.get("agency"),
                "origin_obligation_id": origin["obligation_id"],
                "origin_matter_id": origin["matter_id"],
                "origin_law": origin.get("law_number_display"),
            })
        else:
            o["restated"] = True
            o["origin"] = "existing code"

    return dropped_ids, links


def resolve_actor(matter_id: str, actors: list[str], lookup: dict,
                  agencies_by_canon: dict) -> tuple[str | None, str | None, str]:
    """Resolve an actor through overrides, then the crosswalk.

    `actors` are candidate phrasings in priority order (actor_raw first, then
    the model's actor_resolved / a previously stored agency string).
    Returns (canon, full, display_actor): canon/full are None when unmatched;
    display_actor is what the agency tag falls back to ("Unspecified" for
    vague or override-null actors, a created body's proper name otherwise)."""
    ov = ACTOR_OVERRIDES.get(str(matter_id), {})
    candidates = []
    for a in actors:
        if not a:
            continue
        candidates.append(a)
        trimmed = lead_actor(a)
        if trimmed and trimmed != a:
            candidates.append(trimmed)
    for a in candidates:
        if a in ov:
            resolved = ov[a]
            if resolved is None:
                return None, None, "Unspecified"
            main, _, parent = resolved.partition(" | parent: ")
            canon, full = match_agency(main, lookup, agencies_by_canon)
            if canon is None and parent:
                canon, full = match_agency(parent, lookup, agencies_by_canon)
            if canon:
                return canon, full, main
            # a created body with no matchable parent: keep its proper name
            return None, None, main[:1].upper() + main[1:]
    for a in candidates:
        canon, full = match_agency(a, lookup, agencies_by_canon)
        if canon:
            return canon, full, a
    if any(is_all_agencies(a) for a in candidates):
        return None, None, "All agencies"
    fallback = next((a for a in candidates if not is_vague_actor(a)), None)
    return None, None, (fallback if fallback else "Unspecified")


def match_agency(actor: str, lookup: dict[str, str],
                 agencies_by_canon: dict[str, dict]) -> tuple[str | None, str | None]:
    """Resolve a free-text actor name to (canonical_abbrev, full_name)."""
    if not actor:
        return None, None
    raw_actor = actor
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

    # Last resort: an actor like "the enforcing agency (Department of
    # Consumer and Worker Protection or designated agency)" names a concrete
    # agency inside a parenthetical or an "X or Y" alternative. Match the
    # parts; accept only when exactly ONE distinct agency emerges.
    parts = []
    for m in re.finditer(r"\(([^)]+)\)", raw_actor):
        parts += re.split(r"\s+or\s+|,", m.group(1))
    parts += re.split(r"\s+or\s+|,", re.sub(r"\([^)]*\)", "", raw_actor))
    canons = set()
    for p in parts:
        p = p.strip()
        if not p or is_vague_actor(p):
            continue
        for cand in (p, ACTOR_PREFIXES.sub("", p).strip()):
            c = lookup.get(norm_lookup_key(cand))
            if c:
                canons.add(c)
                break
    if len(canons) == 1:
        canon = canons.pop()
        return canon, agencies_by_canon.get(canon, {}).get("full_name", canon)
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


# The model phrases the same cadence several ways; collapse synonyms so the
# recurrence filters stay short and their frequency ordering meaningful.
RECURRENCE_ALIASES = {
    "every 2 years": "biennial",
    # Council drafting uses "biannual" to mean twice-yearly (verified against
    # laws pairing it with two dates per year, e.g. "each January 31 and July
    # 31"; Aug 2026 data audit). Never map it to biennial.
    "biannual": "semiannual",
    "biannually": "semiannual",
    "three times annual": "three times a year",
    "three times annually": "three times a year",
    "every 6 months": "semiannual",
    "every 180 days": "semiannual",
    "semi-annual": "semiannual",
    "twice a year": "semiannual",
    "every 90 days": "quarterly",
    "every 60 days": "every 2 months",
    "monthly and annual": "multiple schedules",
    "quarterly, semi-annual, and annual": "multiple schedules",
}


def normalize_recurrence(r: str | None) -> str:
    r = (r or "one-time").strip().lower()
    return RECURRENCE_ALIASES.get(r, r)


def sanitize_deadline(deadline_date: str | None,
                      enactment_date: str | None) -> str | None:
    """Reject impossible deadline dates.

    A law cannot set a deadline earlier than its own enactment: such dates
    are extraction artifacts (usually a historical date mentioned in the code
    section being amended) or clauses that lapsed before signing. Also rejects
    malformed dates ("12-01") and anything more than 40 years out. The
    deadline clause text is preserved on the record either way.
    """
    if not deadline_date:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", deadline_date):
        return None
    try:
        datetime.strptime(deadline_date, "%Y-%m-%d")
    except ValueError:
        return None
    if enactment_date and deadline_date < enactment_date:
        return None
    if enactment_date and int(deadline_date[:4]) > int(enactment_date[:4]) + 40:
        return None
    return deadline_date


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


# Sep 25 2026 audit fix: `days_after_enactment` is only right when the
# deadline text actually names enactment/"becomes law"/the effective date. A
# clause anchored to an EVENT ("receives", "receipt", "after the/such/each
# <event>") has no fixed date, no matter what the model computed one from.
_ENACT_ANCHOR = re.compile(r"enact|becomes?\s+(a\s+)?law|effective date", re.I)
_EVENT_TEXT_ANCHOR = re.compile(
    r"receives\b|receipt|after (the|such|each) [a-z]", re.I)


def fix_event_anchored_deadline(o: dict) -> bool:
    """Downgrade a wrongly-dated event-anchored deadline in place.
    Returns True if the record changed."""
    if o.get("deadline_kind") != "days_after_enactment":
        return False
    text = o.get("deadline_text") or ""
    if _ENACT_ANCHOR.search(text):
        return False
    if not _EVENT_TEXT_ANCHOR.search(text):
        return False
    o["deadline_kind"] = "event"
    o["deadline_date"] = None
    return True


# Two fixed calendar dates a law repeats every year ("no later than each July
# 31 and January 31 thereafter") is a semiannual cadence, not the placeholder
# "biennial"/"annual" the model sometimes stores. Only fires when BOTH dates
# recur ("thereafter"/"each year"/"annually") so a one-time two-date range
# ("between March 1 and March 15, 2025") is not mistaken for a schedule.
_TWO_FIXED_DATES = re.compile(
    r"each\s+([A-Za-z]+\s+\d{1,2})\s+and\s+([A-Za-z]+\s+\d{1,2})"
    r"\s+(?:thereafter|of each year|annually|each year)", re.I)


def fix_two_fixed_dates_semiannual(o: dict) -> bool:
    text = " ".join(filter(None, [o.get("deadline_text"), o.get("quote")]))
    if not _TWO_FIXED_DATES.search(text):
        return False
    if o.get("recurrence") == "semiannual":
        return False
    o["recurrence"] = "semiannual"
    return True


def merge_split_list_duplicates(obs: list[dict]) -> int:
    """Merge duplicate list-item splits within one law: same agency, same
    deliverable type, one quote a sub-span of the other's sentence. Keeps the
    longest quote's record, drops the rest. Mutates `obs` in place and returns
    the number of records merged away."""
    groups: dict[tuple, list[dict]] = {}
    for o in obs:
        groups.setdefault((o.get("agency"), o.get("deliverable_type")), []).append(o)
    to_drop: set[int] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            if id(a) in to_drop:
                continue
            qa = alnum(a.get("quote") or "")
            if not qa:
                continue
            for b in group[i + 1:]:
                if id(b) in to_drop:
                    continue
                qb = alnum(b.get("quote") or "")
                if not qb:
                    continue
                # never merge records whose schedules differ: a semiannual
                # report and an annual one in the same sentence are two duties
                if any((a.get(k) or None) != (b.get(k) or None)
                       for k in ("deadline_kind", "deadline_date", "recurrence")):
                    continue
                if qa in qb or qb in qa:
                    loser = a if len(qa) < len(qb) else b
                    to_drop.add(id(loser))
    if not to_drop:
        return 0
    n = len(to_drop)
    obs[:] = [o for o in obs if id(o) not in to_drop]
    return n


# ── Claude call ───────────────────────────────────────────────────────────────

def call_claude(client, model: str, prompt: str, retry_note: str | None = None):
    content = prompt + ("\n\n" + retry_note if retry_note else "")
    # Streamed: required for attachment-scale laws (the plain create() call
    # drops the connection on very large prompts) and harmless for normal ones.
    with client.messages.stream(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": OBLIGATIONS_SCHEMA}},
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "max_tokens":
        raise json.JSONDecodeError("output truncated at max_tokens", "", 0)
    result = json.loads(next(b.text for b in msg.content if b.type == "text"))
    _offset_to_days(result.get("effective_clause"))
    for o in result.get("obligations", []):
        _offset_to_days(o.get("deadline"))
    return result


# A law longer than the model can read in one pass used to be handled by
# keeping the head and the tail and dropping the middle, which silently lost
# every duty written in between. Splitting on the law's own section boundaries
# and extracting each window preserves them. The threshold is generous: only a
# dozen laws in the corpus are anywhere near it, so ordinary laws still make
# exactly one call and behave as before.
CHUNK_THRESHOLD = 400_000
CHUNK_TARGET = 350_000
CHUNK_OVERLAP = 5_000      # a duty straddling a cut must appear whole in one window
MAX_WINDOWS = 24           # beyond this, stop and shout rather than spend
_BILL_SECTION = re.compile(r"(?m)^\s*(?:§+\s*\d+|Section\s+\d+)\b")


def _safe_cut(text: str, pos: int) -> int:
    """Move a cut forward off any position that would split a {{...}} marker."""
    opened = text.rfind("{{", 0, pos)
    if opened != -1 and text.find("}}", opened) >= pos:
        closed = text.find("}}", opened)
        return closed + 2 if closed != -1 else pos
    return pos


def _safe_start(text: str, pos: int) -> int:
    """Move a window start back so it cannot begin inside a {{...}} marker.

    The overlap moves each start earlier, which can land it between "{{" and
    "}}" even when the cut itself was safe. That leaves a window holding a
    closing marker with no opening one, and the extractor then reads marked
    new matter as ordinary text.
    """
    if pos <= 0:
        return 0
    opened = text.rfind("{{", 0, pos)
    closed = text.rfind("}}", 0, pos)
    return opened if opened > closed else pos


def split_for_extraction(text: str, target: int = CHUNK_TARGET) -> list[str]:
    """Split a long law at its own section boundaries into overlapping windows.

    Windows overlap so a duty written across a cut still appears whole in one
    of them, and no cut is allowed to land inside a new-matter marker pair,
    which would strip the very signal the prompt relies on.
    """
    if len(text) <= CHUNK_THRESHOLD:
        return [text]
    bounds = [m.start() for m in _BILL_SECTION.finditer(text)] or [0]
    if bounds[0] != 0:
        bounds.insert(0, 0)
    bounds.append(len(text))
    cuts, start = [], bounds[0]
    for i in range(1, len(bounds)):
        if bounds[i] - start >= target:
            cuts.append(_safe_cut(text, bounds[i]))
            start = bounds[i]
    chunks, prev = [], 0
    for c in cuts:
        chunks.append(text[_safe_start(text, max(0, prev - CHUNK_OVERLAP)):c])
        prev = c
    chunks.append(text[_safe_start(text, max(0, prev - CHUNK_OVERLAP)):])
    # a single section larger than the target still has to be broken up
    out = []
    for c in chunks:
        while len(c) > target * 1.6:
            cut = _safe_cut(c, target)
            out.append(c[:cut])
            c = c[_safe_start(c, max(0, cut - CHUNK_OVERLAP)):]
        out.append(c)
    return [c for c in out if c.strip()]


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
              .replace("{recurrences}", json.dumps(RECURRENCES))
              .replace("{kind_definitions}", KIND_DEFINITIONS)
              .replace("{metadata}", metadata)
              .replace("{law_text}", text))

    # Long law: extract each section window, then merge. Every other law takes
    # the single-pass path below unchanged.
    windows = split_for_extraction(text)
    if len(windows) > 1:
        log.info(f"  long law ({len(text):,} chars): extracting in "
                 f"{len(windows)} section windows")
        if len(windows) > MAX_WINDOWS:
            log.error("%s needs %d windows, above MAX_WINDOWS=%d: refusing to "
                      "extract rather than spend unbounded tokens. Split the law "
                      "or raise the cap deliberately.",
                      law["matter_id"], len(windows), MAX_WINDOWS)
            return {"matter_id": law["matter_id"], "model": model,
                    "extracted_at": datetime.now().isoformat(timespec="seconds"),
                    "effective_clause": {"text": None},
                    "effective_date": law.get("effective_date"),
                    "windows_refused": len(windows), "obligations": []}
        merged, seen = [], set()
        eff_clause, eff_date = None, None
        for wi, window in enumerate(windows, 1):
            sub = extract_law(client, model, law, window, lookup, agencies_by_canon)
            if eff_clause is None:
                eff_clause = (sub.get("effective_clause") or {}).get("text")
            if eff_date is None:
                eff_date = sub.get("effective_date")
            for o in sub.get("obligations", []):
                key = (normalize_quote(o.get("quote", ""))[:160], o.get("citation", ""))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(o)
        for i, o in enumerate(merged, 1):
            o["obligation_id"] = f"{law['matter_id']}-{i:02d}"
        return {"matter_id": law["matter_id"],
                "model": model,
                "extracted_at": datetime.now().isoformat(timespec="seconds"),
                "effective_clause": {"text": eff_clause},
                "effective_date": eff_date or law.get("effective_date"),
                "windows": len(windows),
                "obligations": merged}

    norm_text = normalize_quote(text)
    op_text = operative_text(text)
    result = None
    for attempt in range(2):
        retry_note = None
        if attempt == 1 and result is not None:
            bad = [o["quote"] for o in result.get("obligations", [])
                   if not quote_present(o.get("quote", ""), text, op_text)]
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
                      if not quote_present(o.get("quote", ""), text, op_text)]
        if not unverified:
            break
        log.warning(f"  {len(unverified)} unverified quotes (attempt {attempt+1})")

    # Post-process
    enactment = law.get("enactment_date") or None
    effective = resolve_effective_date(result.get("effective_clause", {}), enactment)
    obligations = []
    for i, o in enumerate(result.get("obligations", []), 1):
        quote_ok = quote_present(o.get("quote", ""), text, op_text)
        canon, full, actor = resolve_actor(
            law["matter_id"],
            [o.get("actor_raw") or "", o.get("actor_resolved") or ""],
            lookup, agencies_by_canon)
        dtype = o.get("deliverable_type", "other")
        if dtype not in DELIVERABLE_TYPES:
            dtype = "other"
        deadline_date = sanitize_deadline(
            resolve_deadline(o.get("deadline", {}), enactment, effective), enactment)
        obligations.append({
            "obligation_id": f"{law['matter_id']}-{i:02d}",
            "matter_id": law["matter_id"],
            "actor_raw": o.get("actor_raw", ""),
            "agency": canon or actor,
            "agency_full": full or (
                "Not specified in the law text" if actor == "Unspecified"
                else "Every city agency" if actor == "All agencies"
                else actor),
            "agency_matched": canon is not None,
            "action_summary": o.get("action_summary", ""),
            "deliverable_type": dtype,
            "citation": o.get("citation", ""),
            "quote": o.get("quote", ""),
            "quote_verified": quote_ok,
            "kind_rule": classify(o.get("quote", ""), text),
            "kind_list_item": is_list_item(o.get("quote", ""), text),
            "kind_model": o.get("provision_kind"),
            "deadline_kind": (o.get("deadline") or {}).get("kind", "none"),
            "deadline_text": (o.get("deadline") or {}).get("text"),
            "deadline_date": deadline_date,
            "recurrence": normalize_recurrence(o.get("recurrence")),
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
                       "effective_date", "legistar_url", "law_sunset_date",
                       "quotes_restated_text", "filing"}
        # "restated"/"origin" are kept: in CI only newly fetched laws have
        # cached text, so every other law must keep its prior re-attribution
        # powers live in their own file; without them here, CI (no cache)
        # would drop every power on its next rebuild
        prev_powers = (json.loads(POWERS_JSON.read_text()).get("powers", [])
                       if POWERS_JSON.exists() else [])
        for o in prev.get("obligations", []) + prev_powers:
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
    excluded = []      # kind "neither": published nowhere
    flat = []          # duties -> obligations.json
    powers = []        # powers -> powers.json
    law_summaries = []
    quotes_cleaned = quotes_deleted_flagged = deadlines_event_fixed = 0
    semiannual_fixed = merged_away = 0
    _law_text_cache: dict[str, str] = {}
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
            "obligation_count": sum(1 for o in res["obligations"] if _kind(o) == "duty"),
            "power_count": sum(1 for o in res["obligations"] if _kind(o) == "power"),
            "sunset_clause": law.get("sunset_clause"),
            "sunset_date": law.get("sunset_date"),
        })
        law_flat, law_powers = [], []
        for o in res["obligations"]:
            # guards also apply to previously cached extractions
            o["deadline_date"] = sanitize_deadline(
                o.get("deadline_date"), law.get("enactment_date"))
            o["recurrence"] = normalize_recurrence(o.get("recurrence"))
            # Step 2 mechanical fixes (Sep 25 2026 audit): quote cleanup,
            # event-anchored deadlines, two-fixed-dates-a-year recurrence.
            mid = res["matter_id"]
            if "{{" in (o.get("quote") or "") or re.search(r"\[[a-z]", o.get("quote") or ""):
                if mid not in _law_text_cache:
                    tp = TEXT_CACHE / f"{mid}.txt"
                    _law_text_cache[mid] = tp.read_text(errors="ignore") if tp.exists() else ""
                cleaned, has_deleted = clean_stored_quote(o.get("quote"), _law_text_cache[mid])
                if cleaned != o.get("quote"):
                    o["quote"] = cleaned
                    quotes_cleaned += 1
                if has_deleted:
                    o["quote_has_deleted_text"] = True
                    quotes_deleted_flagged += 1
            if fix_event_anchored_deadline(o):
                deadlines_event_fixed += 1
            if fix_two_fixed_dates_semiannual(o):
                semiannual_fixed += 1
            kind = _kind(o)
            if kind == "neither":        # a private party's option: in no table
                excluded.append(o["obligation_id"])
                continue
            if kind == "power":          # a power is never due by a date
                o["deadline_kind"] = "none"
                o["deadline_date"] = None
            (law_powers if kind == "power" else law_flat).append({
                **o,
                "file_number": law["file_number"],
                "law_number_display": law["law_number_display"],
                "law_title": law["title"],
                "committee": law["committee"],
                "prime_sponsor": law["prime_sponsor"],
                "enactment_date": law["enactment_date"],
                "effective_date": res["effective_date"],
                "legistar_url": law["legistar_url"],
                "law_sunset_date": law.get("sunset_date"),
                "quotes_restated_text": o["obligation_id"] in RESTATED_IDS,
                **({"filing": REPORT_FILINGS[o["obligation_id"]]}
                   if o["obligation_id"] in REPORT_FILINGS and kind == "duty" else {}),
                "kind": kind,
            })
        merged_away += merge_split_list_duplicates(law_flat)
        merged_away += merge_split_list_duplicates(law_powers)
        flat.extend(law_flat)
        powers.extend(law_powers)

    # Sep 25 2026: re-attribute duties/powers a law only reprints from an
    # earlier tracked law (duplicates dropped, linked in restated_links.json)
    # or existing code the law carries forward (kept, flagged).
    dropped_ids, restated_links = reattribute_reprints(flat, powers, law_by_id)
    if dropped_ids:
        flat = [o for o in flat if o["obligation_id"] not in dropped_ids]
        powers = [o for o in powers if o["obligation_id"] not in dropped_ids]
    restated_kept = sum(1 for o in flat + powers if o.get("restated"))
    # recomputed only for laws whose text is cached; every other law keeps
    # its saved links (CI has text only for the laws it just fetched)
    links_path = DATA / "restated_links.json"
    saved_links = json.loads(links_path.read_text()) if links_path.exists() else {}
    with_text = {mid for mid in {o["matter_id"] for o in flat + powers}
                 if (TEXT_CACHE / f"{mid}.txt").exists()}
    merged_links = {m: v for m, v in saved_links.items() if m not in with_text}
    merged_links.update(restated_links)
    restated_links = merged_links
    links_path.write_text(json.dumps(restated_links, indent=1, ensure_ascii=False))
    # Per-law counts exclude both dropped duplicates and kept existing-code
    # records: a law's checklist and count are what IT enacted, not what it
    # reprinted (Step 1, Sep 25 2026).
    _law_counts: dict[str, dict] = {}
    for o in flat:
        if o.get("restated"):
            continue
        _law_counts.setdefault(o["matter_id"], {"obligation_count": 0, "power_count": 0})
        _law_counts[o["matter_id"]]["obligation_count"] += 1
    for o in powers:
        if o.get("restated"):
            continue
        _law_counts.setdefault(o["matter_id"], {"obligation_count": 0, "power_count": 0})
        _law_counts[o["matter_id"]]["power_count"] += 1
    for ls in law_summaries:
        counts = _law_counts.get(ls["matter_id"], {"obligation_count": 0, "power_count": 0})
        ls["obligation_count"] = counts["obligation_count"]
        ls["power_count"] = counts["power_count"]

    log.info(f"Step 2 mechanical fixes: quotes cleaned {quotes_cleaned}, "
             f"quote_has_deleted_text {quotes_deleted_flagged}, "
             f"event-anchored deadlines fixed {deadlines_event_fixed}, "
             f"semiannual-from-two-dates {semiannual_fixed}, "
             f"list-item duplicates merged {merged_away}")
    log.info(f"Step 1 re-attribution: reprint candidates dropped as duplicates "
             f"{len(dropped_ids)}, kept as existing code {restated_kept}")

    # obligation_id must be unique: hand edits and cache syncs have twice
    # produced a matter with the same id on two records, which silently breaks
    # any join keyed on it (the restated-text flag, per-record links).
    from collections import Counter as _Counter
    _dupes = [i for i, c in _Counter(o["obligation_id"] for o in flat + powers).items() if c > 1]
    if _dupes:
        log.error("duplicate obligation_ids (fix the cache file, then rebuild): %s",
                  ", ".join(sorted(_dupes)))

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
    POWERS_JSON.write_text(json.dumps({
        "generated_at": out["generated_at"],
        "model": args.model,
        "power_count": len(powers),
        "powers": powers,
    }, separators=(",", ":")))

    # CSV companion for the Download CSV button
    import csv as csvmod
    csv_path = DATA / "obligations.csv"
    csv_cols = ["law_number_display", "file_number", "agency", "agency_full",
                "action_summary", "deliverable_type", "deadline_date",
                "deadline_text", "recurrence", "citation", "committee",
                "prime_sponsor", "enactment_date", "effective_date",
                "quote", "legistar_url",
                "filing_status", "filing_last_filed", "filing_days_late"]
    for row in flat:
        fil = row.get("filing") or {}
        row["filing_status"] = fil.get("status", "")
        row["filing_last_filed"] = fil.get("last_filed") or ""
        row["filing_days_late"] = fil.get("days_late") if fil.get("days_late") is not None else ""
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csvmod.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
        w.writeheader()
        for o in flat:
            w.writerow(o)
    log.info(f"Wrote {csv_path}")
    powers_csv = DATA / "powers.csv"
    power_cols = [c for c in csv_cols if not c.startswith(("deadline", "filing"))]
    with open(powers_csv, "w", newline="", encoding="utf-8") as f:
        w = csvmod.DictWriter(f, fieldnames=power_cols, extrasaction="ignore")
        w.writeheader()
        for o in powers:
            w.writerow(o)
    log.info(f"Wrote {powers_csv}: {len(powers)} powers; "
             f"{len(excluded)} records classified neither (private parties' options) left out")

    verified = sum(1 for o in flat if o["quote_verified"])
    matched = sum(1 for o in flat if o["agency_matched"])
    log.info(f"Wrote {OUT_JSON}: {len(flat)} obligations across "
             f"{len(law_summaries)} laws "
             f"({verified}/{len(flat)} quotes verified, "
             f"{matched}/{len(flat)} agencies matched)")


if __name__ == "__main__":
    main()
