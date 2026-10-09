#!/usr/bin/env python3
"""NYS Legislation Trackers, phase 2: duties and powers of State and local government from signed laws.

Runs on the Max plan as PACKETS, no API key and no model call:
    python3 extract_duties.py --emit-packets DIR   one prompt file per signed law (laws over 120,000 characters are
                                                   listed in data/deferred_long.json instead)
    (subagents answer each packet into DIR/results/<key>.json)
    python3 extract_duties.py --ingest DIR --session Y   validate, resolve agencies, write data/duties/Y.json, powers/Y.json, reask/Y.json, dropped/Y.json

Reuses the Council extractor (civic_reference/legislation_implementation_tracker/pipeline/extract_obligations.py): its
schema, duty/power/neither definitions, quote checks, deadline arithmetic, packet emit/ingest and agency matcher. Only the
prompt wording (state and local government instead of NYC agencies) and the agency crosswalk are NYS-specific.
"""
import argparse, json, os, re, sys, time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
COUNCIL = HERE.parent.parent / "legislation_implementation_tracker"
sys.path.insert(0, str(COUNCIL / "pipeline"))
sys.path.insert(0, str(HERE))
import extract_obligations as eo  # noqa: E402
import law_definitions  # noqa: E402
from effective_date import parse_effective  # noqa: E402
import chapter_lookup  # noqa: E402
import agency_resolve_nys  # noqa: E402
from validate_duties import PASSIVE_SUBJECT  # noqa: E402  (J1 reuses the validator's detection)

MAX_CHARS = 120_000
REASK_MANUAL = HERE / "reask_manual.json"
TEXT_MARKED = HERE / "cache" / "text_marked"
EXTRACTED = HERE / "cache" / "extracted"
LOCAL_GROUPS = {"town": "Towns", "village": "Villages", "city": "Cities", "county": "Counties"}
NYC_MARKERS = re.compile(r"city of new york|new york city|\bnyc\b|mayor of the city|council of the city", re.I)


# ── Prompt: the Council prompt with NYC wording swapped for state and local government ─────────────────────────────
def _sub(s, old, new):
    if old not in s:
        raise SystemExit("Council prompt no longer contains: %r (update extract_duties.py)" % old[:60])
    return s.replace(old, new)


def build_prompt():
    p = eo.EXTRACTION_PROMPT
    p = _sub(p, 'an enacted New York City local law. Extract every concrete obligation the law imposes on, and every power it grants to, a NYC GOVERNMENT entity (an agency, department, office, commission, board, or officer such as "the commissioner", "the mayor", "the department", "the office").',
             'an enacted New York State law (a chapter of the Laws of New York). Extract every concrete obligation the law imposes on, and every power it grants to, a NEW YORK GOVERNMENT entity: a State agency, department, division, office, board, commission or public authority; a statewide elected official (the governor, the comptroller, the attorney general); the courts; a LOCAL GOVERNMENT (a county, city, town, village, school district, or municipalities in general); or an officer of any of these, such as "the commissioner", "the director of the budget", "the superintendent", "the department", "the office". "The commissioner" means the State commissioner the law names or defines (for example the commissioner of health in the public health law).')
    p = _sub(p, "'the commissioner of health and mental hygiene', 'the mayor', 'a designated agency'", "'the commissioner of health', 'the governor', 'the town of hempstead', 'a designated agency'")
    p = _sub(p, "the administrative code title being amended", "the State law being amended (the public health law's 'department' is the department of health)")
    p = _sub(p, "sits inside a city agency or that a city agency convenes or staffs", "sits inside a State or local agency or that a State or local agency convenes or staffs")
    p = _sub(p, "the mayor's office when the mayor creates or appoints it and no agency is named", "the governor when the governor creates or appoints it and no agency is named")
    p = _sub(p, "e.g. 'NYC Admin. Code § 20-563.2(b)' if the law adds/amends that section, else 'Section 3 of the local law'", "e.g. 'Public Health Law § 2805-x(2)' if the act adds/amends that section, else 'Section 3 of the act'")
    p = _sub(p, "reporting to mayor/council/public", "reporting to the governor, the legislature or the public")
    p = _sub(p, "effective date of this local law", "effective date of this act")
    p = _sub(p, "Include ONLY duties of NYC government entities.", "Include ONLY duties of State government entities and local governments.")
    p = _sub(p, "(employers, landlords, businesses)", "(employers, landlords, businesses, insurers, hospitals and other private providers)")
    i = p.index("- Street co-naming laws:")
    j = p.index("\n", i)
    p = p[:i] + ("- Local governments and named entities: a duty or power of a local government is recorded with actor_resolved set to the group ('counties', 'cities', 'towns', 'villages', 'school districts', 'municipalities') or to the named unit exactly as the law names it ('town of hempstead'). A duty of the City of New York or of a New York City agency named in this State law (the mayor of the city of new york, the NYC department of education) is recorded too, under that name. A special act that only authorizes one named locality to do something (accept a tax-exemption application, elect a retirement provision) records a power of that locality.") + p[j:]
    p = _sub(p, "taken from Legistar's underline styling", "taken from the bill's underlined (new matter) text")
    p = _sub(p, "If a law's text carries no braces at all, fall back to the amendment rule below.", "If a law's text carries no braces at all, fall back to the amendment rule below. A section of the act that does not amend existing law (a study, a report, a local authorization, 'is hereby established', an appropriation, a free-standing finding or definition) is entirely new law: extract from it even though it carries no braces.")
    p = _sub(p, "In NYC Council drafting, text enclosed", "In New York State bill drafting, text enclosed")
    p = _sub(p, "(in Legistar's published text, the underlined portions)", "(the braced, underlined portions)")
    p = _sub(p, 'which Council drafting calls "biannual"', 'which State drafting calls "biannual"')
    p = _sub(p, 'Use kind=days_after_other with no offset, even when the clause says "within 60 days".', 'Use kind none, even when the clause says "within 60 days"; never use days_after_other without a stated period.')
    rules = [
        "- When the only new matter extends or changes an existing duty or power (a new expiry date, a changed amount or limit, an added place, district or class of things), still record it and set extends_existing true; otherwise false.",
        "- A deletion that widens an existing duty or power (striking '[born and]' or '[under the jurisdiction of the department]') is a record: set extends_existing true.",
        "- A bond cap or issuance cutoff ('shall not issue ... exceeding X', 'no bonds on or after DATE') is a duty with deadline kind none: a cutoff date is not a deadline.",
        "- actor_resolved is always the government body that holds the duty or power. In a passive sentence ('moneys may be withdrawn', 'the application shall be reviewed'), name the body that acts, usually the one the section empowers or the named locality; never the grammatical subject.",
        "- A named locality is written exactly as the law names it ('town of cornwall', 'copenhagen central school district'), without 'in the county of X'; its assessor, tax department, chief fiscal officer or governing body is that locality, never a State agency.",
        "- A duty that begins when the law takes effect (a setup duty with no stated deadline) uses deadline kind on_effective_date; a duty triggered by a request, event, precondition or 'promptly' uses kind none.",
        "- The act clause's early-rulemaking boilerplate ('rules and regulations necessary for the implementation of this act on its effective date are authorized to be made ... on or before such date') produces NO record.",
        "- Do NOT record: an exemption from a cap or residency rule that imposes nothing on a government actor, Local Finance Law useful-life entries, program goals or findings, or appropriation amount changes.",
    ]
    p = _sub(p, '- Do not invent obligations', "\n".join(rules) + '\n- Do not invent obligations')
    p = _sub(p, '- Do not invent obligations', '- A deadline counted from "the date this act shall have become a law" or from signing is days_after_enactment; one counted from "the effective date of this act" is days_after_effective.\n- Do not invent obligations')
    p = (p.replace("{deliverable_types}", json.dumps(eo.DELIVERABLE_TYPES))
          .replace("{recurrences}", json.dumps(eo.RECURRENCES))
          .replace("{kind_definitions}", eo.KIND_DEFINITIONS))
    p = _sub(p, "REQUIRES a NYC government agency, office, board or official", "REQUIRES a New York State or local government agency, office, board or official")
    p = _sub(p, "AUTHORIZES a NYC government agency, office, board or official", "AUTHORIZES a New York State or local government agency, office, board or official")
    p = _sub(p, ' Street co-naming ("the following street name is hereby designated") is a duty (DOT signage).', "")
    left = [m.group(0) for m in re.finditer(r"(?i:legistar)|\bNYC\b|Council|local law|\bcity agency|DOT\b", p)]
    left = [l for l in left if l.lower() != "nyc"]   # kept: my own text names the NYC department of education
    if left:
        raise SystemExit("Council wording left in the NYS prompt: %s" % sorted(set(left)))
    fixed, rest = p.split(eo._SPLIT_MARKER, 1)
    return fixed, eo._SPLIT_MARKER + rest


FIXED_PROMPT, VARIABLE_TEMPLATE = build_prompt()
import copy  # noqa: E402
SCHEMA = copy.deepcopy(eo.OBLIGATIONS_SCHEMA)       # Council schema plus one optional boolean (not required: older answers lack it)
SCHEMA["properties"]["obligations"]["items"]["properties"]["extends_existing"] = {"type": "boolean"}


def render_variable_prompt(law, text):
    meta = json.dumps({k: law[k] for k in ("session", "print_no", "chapter_number", "chapter_year", "signed_date", "title", "act_clause", "law_section")}, indent=1)
    return (VARIABLE_TEMPLATE.replace("{metadata}", meta)
            .replace("{definitions}", law_definitions.defining_sentences(text) or "(none found)")
            .replace("{law_text}", text))


# ── Laws ────────────────────────────────────────────────────────────────────────────────────────────────────────
PILOT_SESSIONS = list(range(2009, 2026, 2))


def signed_laws(sessions=None):
    """Signed laws of the given sessions (default: the pilot's bills.json). Full sessions come from data/signed/{Y}.json."""
    import fetch_bills
    out = []
    if sessions is None:
        for b in json.load(open(DATA / "bills.json")):
            if b.get("chapter"):
                out.append(fetch_bills.law_record(b))
        return out
    pilot = None
    for y in sessions:
        sg = DATA / "signed" / ("%d.json" % y)
        if sg.exists():
            out += json.loads(sg.read_text())
        else:
            if pilot is None:
                pilot = signed_laws()
            out += [l for l in pilot if l["session"] == y]
    return out


def load_todo(sessions=None):
    todo, deferred = [], []
    for law in signed_laws(sessions):
        tp = TEXT_MARKED / (law["key"] + ".txt")
        if not tp.exists():
            continue
        text = tp.read_text()
        if len(text) > MAX_CHARS:
            deferred.append({"key": law["key"], "chapter": law["chapter_number"], "year": law["chapter_year"], "chars": len(text), "title": law["title"]})
        else:
            todo.append((law, text))
    return todo, deferred


def effective_table(laws):
    tab = {}
    for law in laws:
        text = (TEXT_MARKED / (law["key"] + ".txt")).read_text()
        tab[law["key"]] = parse_effective(text, law["signed_date"], resolver=chapter_lookup.resolve)
    return tab


def prepare(law, raw):
    """Replace the model's effective clause with the deterministic parse (the model still answers the schema field)."""
    ACTOR_MODEL[law["key"]] = {"%s-%02d" % (law["key"], i): o.get("actor_resolved") for i, o in enumerate(raw.get("obligations", []), 1)}
    EXT_MODEL[law["key"]] = {"%s-%02d" % (law["key"], i): bool(o.get("extends_existing")) for i, o in enumerate(raw.get("obligations", []), 1)}
    e = EFFECTIVE[law["key"]]
    if e["rule"] == "immediately":
        raw["effective_clause"] = {"kind": "immediate", "offset_days": None, "fixed_date": None, "text": e["raw_clause"]}
    elif e["effective_date"]:
        raw["effective_clause"] = {"kind": "fixed_date", "offset_days": None, "fixed_date": e["effective_date"], "text": e["raw_clause"]}
    else:
        raw["effective_clause"] = {"kind": "other", "offset_days": None, "fixed_date": None, "text": e["raw_clause"]}


# ── Agencies: NYS crosswalk first, then named local units, then (NYC markers only) the Council crosswalk ───────────
CW = json.loads((DATA / "agency_crosswalk_nys.json").read_text())
LOOKUP = CW["lookup"]
BY_CANON = {a["canonical"]: a for a in CW["agencies"]}
_NYC = json.loads((COUNCIL / "data" / "agency_crosswalk.json").read_text())
NYC_LOOKUP = _NYC["lookup"]
NYC_BY = {a["canonical"]: a for a in _NYC["agencies"]}
RESOLVE_DEPS = {"eo": eo, "LOOKUP": LOOKUP, "BY_CANON": BY_CANON, "NYC_LOOKUP": NYC_LOOKUP, "NYC_BY": NYC_BY, "NYC_MARKERS": NYC_MARKERS}
EFFECTIVE = {}
EXT_MODEL = {}
ACTOR_MODEL = {}


def _title(s):
    small = {"of", "the", "and", "in", "on", "for"}
    return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(s.split()))


LOCALITY = [
    (re.compile(r"\b(town|village|city|county)\s+of\s+(?!the\b|new york\b)([a-z][a-z .'-]*?)(?=\s*(?:,|;|\(|\bin\s+the\b|\bwithin\b|\bwhich\b|\bthat\b|\bto\b|\band\b|\bor\b|$))", re.I), None),
    (re.compile(r"\b([A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){0,3}?)\s+((?:central |union free |city |common )?school district)\b", re.I), "School districts"),
    (re.compile(r"\b([A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){0,2}?)\s+(fire district)\b", re.I), "Fire districts"),
    (re.compile(r"\b([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,2})\s+(county)\b|\b([a-z]+)\s+(county)\b", re.I), "Counties"),
]
GENERIC_LEAD = re.compile(r"^(?:the|such|said|each|any|every|a|an|that|this|of|in|for|by|and|or|to|local|governing|county|city|town|village)$", re.I)
LOCAL_OFFICERS = re.compile(r"assessor|tax (?:office|department|receiver|collector)|governing body|board of (?:trustees|education|assessors)|town board|village board|city council|common council|county legislature|board of supervisors|mayor|supervisor|clerk|treasurer|comptroller of the (?:town|village|city|county)", re.I)


def named_locality(*texts):
    """(group, normalised unit name) for the first named locality in the texts, else None.
    'the town board of the town of cornwall, in the county of orange' -> ('Towns', 'Town of Cornwall')."""
    for t in texts:
        if not t or NYC_MARKERS.search(t):
            continue
        t = re.sub(r"\([^)]*\)", "", t)
        m = LOCALITY[0][0].search(t)
        if m:
            kind = m.group(1).lower()
            name = re.sub(r"\s+", " ", m.group(2)).strip(" .")
            name = re.sub(r"(?:\s+(?:assessors?|board|clerk|treasurer|supervisor|tax|department|office|shall|may|is|has|will))+$", "", name, flags=re.I)
            name = re.sub(r"\s+" + kind + r"$", "", name, flags=re.I)        # "Town of Brookhaven Town"
            if name and not GENERIC_LEAD.match(name.split()[0]):
                return LOCAL_GROUPS[kind], _title("%s of %s" % (kind, name))
        for rx, group in LOCALITY[1:3]:
            m = rx.search(t)
            if m:
                lead = m.group(1).strip()
                words = [w for w in lead.split() if not GENERIC_LEAD.match(w)]
                if words and not GENERIC_LEAD.match(lead.split()[-1]):
                    return group, _title(" ".join(words) + " " + m.group(2).lower())
        m = re.search(r"\b((?:[A-Z][A-Za-z.'-]*\s+){1,2})County\b", t) or re.search(r"\b([a-z]+(?:\s+[a-z]+)?)\s+county\b", t)
        if m:
            words = [w for w in m.group(1).split() if not GENERIC_LEAD.match(w)]
            if words and len(words) <= 2:
                return "Counties", _title(" ".join(words) + " county")
    return None


def attach_jurisdiction(o, quote_context=""):
    """Set agency (group, for filtering), agency_unit (the named locality), jurisdiction, org_type. Order: NYC markers,
    then a named locality, then the State crosswalk. Mutates the record."""
    names = [x for x in (o.get("actor_raw"), o.get("agency")) if x]
    o.setdefault("agency_unit", None)
    # 1. NYC first: "the New York city department of transportation" is the NYC agency, not NYSDOT
    for n in names:
        if NYC_MARKERS.search(n):
            canon, full = eo.match_agency(n, NYC_LOOKUP, NYC_BY)
            if canon:
                o.update(agency=canon, agency_full=full, agency_matched=True, jurisdiction="nyc", agency_org_type=NYC_BY[canon].get("org_type"), agency_group=None, agency_unit=None)
                return
    # 2. a named locality (or its assessor, tax office, governing body) resolves to the locality, never to a State agency
    state_hit = o.get("agency_matched") and o["agency"] in BY_CANON and BY_CANON[o["agency"]]["jurisdiction"] == "state"
    actor_text = [x for x in (o.get("actor_raw"), o.get("actor_resolved_model")) if x]
    loc = named_locality(*actor_text)
    if not loc and (not o.get("agency_matched") or (state_hit and any(LOCAL_OFFICERS.search(x) for x in actor_text))):
        loc = named_locality(o.get("quote") or "", o.get("action_summary") or "") if any(LOCAL_OFFICERS.search(x) for x in actor_text) or not o.get("agency_matched") else None
    if loc and (not state_hit or any(LOCAL_OFFICERS.search(x) for x in actor_text) or o["agency"] in ("DTF",)):
        group, unit = loc
        o.update(agency=group, agency_full=group, agency_matched=True, jurisdiction="local", agency_org_type="local government group", agency_group=group, agency_unit=unit)
        return
    if o.get("agency_matched") and o["agency"] in BY_CANON:
        a = BY_CANON[o["agency"]]
        o["jurisdiction"], o["agency_org_type"] = a["jurisdiction"], a["org_type"]
        o["agency_group"] = o["agency"] if a["org_type"] == "local government group" else None
        return
    o["jurisdiction"], o["agency_org_type"], o["agency_group"] = None, None, None


LOCAL_BOE = re.compile(r"\bboards?\s+of\s+elections?\b", re.I)


def fix_local_board_of_elections(o):
    """F2 (Oct 9 2026). Election Law names the State body 'state board of elections'; a 'board of elections' or 'county/local board
    of elections' without 'state' in the actor text is the local board. Same convention as other local actors: agency = the group
    ('Boards of elections', or 'Counties' when a county is named), agency_unit = the named county, jurisdiction local."""
    if o.get("agency") != "Board of Elections":
        return False
    names = [x for x in (o.get("actor_raw"), o.get("actor_resolved_model")) if x]
    joined = " ".join(names)
    if not LOCAL_BOE.search(joined) or re.search(r"\bstate\b", joined, re.I) or NYC_MARKERS.search(joined):
        return False
    loc = named_locality(*names)
    if loc:
        group, unit = loc
        o.update(agency=group, agency_full=group, agency_matched=True, jurisdiction="local", agency_org_type="local government group", agency_group=group, agency_unit=unit)
    else:
        o.update(agency="Boards of elections", agency_full="Boards of elections", agency_matched=True, jurisdiction="local", agency_org_type="local government group", agency_group="Boards of elections", agency_unit=None)
    return True


PAREN_TAIL = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")


def fix_parenthetical_actor(o):
    """F3 (Oct 9 2026). actor_raw 'voted ballots (board of elections)': the model annotated a passive subject with the acting body. When the
    text before the parenthesis does not itself resolve (crosswalk, named locality or a government noun) and the parenthetical does, the
    parenthetical becomes actor_raw (the model's text is kept in actor_raw_model) and the agency is resolved from it."""
    raw = (o.get("actor_raw") or "").strip()
    m = PAREN_TAIL.match(raw)
    if not m:
        return False
    pre, paren = m.group(1).strip(), m.group(2).strip()
    if not pre or not paren or len(paren.split()) > 8 or re.search(r"\d", paren):
        return False
    def resolves(x):
        return bool(eo.match_agency(x, LOOKUP, BY_CANON)[0]) or bool(named_locality(x)) or bool(GOV_ACTOR.search(x))
    if resolves(pre) or not resolves(paren):
        return False
    o["actor_raw_model"] = raw
    o["actor_raw"] = paren
    canon, full = eo.match_agency(paren, LOOKUP, BY_CANON)
    if canon:
        o.update(agency=canon, agency_full=full, agency_matched=True)
    else:
        o.update(agency=paren, agency_full=paren, agency_matched=False)
    return True


# ── extends_existing: the quote's braced new matter is only numbers, dates, number words or a place name ─────────────
_NUMW = set("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth twentieth thirtieth sixtieth ninetieth".split())
_DATEW = set("january february march april may june july august september october november december dollars dollar percent year years day days and".split())


def _only_extension(span):
    toks = re.findall(r"[A-Za-z0-9$%.,]+", span)
    toks = [t.strip(".,") for t in toks if t.strip(".,")]
    if not toks:
        return False
    if all(re.fullmatch(r"[$]?[\d,.]+%?", t) or t.lower() in _NUMW or t.lower() in _DATEW for t in toks) and any(not t.lower() == "and" for t in toks):
        return True
    return all(t[:1].isupper() and t.lower() not in ("the", "section", "act") for t in toks)        # a place name (HTML era keeps capitals)


def extends_by_text(quote, text):
    """True when the quote has braced new matter and ALL of it is numbers, dates, number words or a place name."""
    q = eo.alnum(quote)
    if len(q) < 10:
        return False
    text = eo.operative_text(text)           # the quote omits [deleted] matter, so the search text must too
    chars, flags, depth = [], [], 0
    for m in re.finditer(r"\{\{|\}\}|[A-Za-z0-9]", text):
        g = m.group(0)
        if g == "{{": depth = 1
        elif g == "}}": depth = 0
        else:
            chars.append(g.lower()); flags.append(m.start() if depth else -1)
    flat = "".join(chars)
    i = flat.find(q)
    if i < 0:
        return False
    pos = [f for f in flags[i:i + len(q)] if f >= 0]
    if not pos:
        return False
    spans = []
    for m in re.finditer(r"\{\{(.*?)\}\}", text, re.S):
        if any(m.start() <= f < m.end() for f in pos):
            spans.append(m.group(1))
    return bool(spans) and all(_only_extension(sp) for sp in spans)


# ── Phase 2d mechanical rules ───────────────────────────────────────────────────────────────────────────────────────
STATS = {}


def bump(k, n=1):
    STATS[k] = STATS.get(k, 0) + n


def _mask_deleted(text):
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\[[^\[\]]{0,4000}?\]", lambda m: " " * len(m.group(0)), text)
    return text


def locate(quote, text):
    """Offset in `text` where the quote starts (ignoring markers, punctuation, case and [deleted] matter), else None."""
    masked = _mask_deleted(text)
    flat, offs = [], []
    for m in re.finditer(r"[A-Za-z0-9]", masked):
        flat.append(m.group(0).lower()); offs.append(m.start())
    q = eo.alnum(quote)
    if len(q) < 8:
        return None
    i = "".join(flat).find(q)
    return offs[i] if i >= 0 else None


def act_section_of(quote, text):
    pos = locate(quote, text)
    if pos is None:
        return None
    last = None
    for m in re.finditer(r"(?m)^(?:§|Section)\s*(\d+)\.", text):
        if m.start() <= pos:
            last = int(m.group(1))
    return last


def _section_set(applies_to):
    m = re.match(r"\s*sections?\s+(.*?)\s+of this act", applies_to, re.I)
    if not m:
        return set()
    out = set()
    from effective_date import words_to_int
    for part in re.split(r",|\band\b", m.group(1)):
        n = words_to_int(part.strip()) if part.strip() else None
        if n:
            out.add(n)
    return out


def section_effective(o, text, eff):
    """The effective date that governs this record: a paragraph-level entry matching its citation, else the entry for the act
    section its quote sits in, else the law's own date (D1 in effective_date.py decides the values)."""
    cit = re.search(r"§\s*([\w.-]+)\s*\((\w+)\)\s*\((\w)\)", o.get("citation") or "")
    secno = act_section_of(o.get("quote") or "", text)
    for e in eff.get("section_dates") or []:                  # keyed to another law's expiration: the date is open, not the act's own
        if e.get("rule") == "on_expiration_of_other_law" and secno and secno in _section_set(e["applies_to"]):
            return None, "open"
    for e in eff.get("section_dates") or []:
        if not e.get("effective_date"):
            continue
        pm = re.search(r"paragraph (\w+) of subdivision (\w+) of section ([\w-]+)", e["applies_to"], re.I)
        if pm and cit and (cit.group(1).lower(), cit.group(2).lower(), cit.group(3).lower()) == (pm.group(3).lower(), pm.group(2).lower(), pm.group(1).lower()):
            return e["effective_date"], "paragraph"
    for e in eff.get("section_dates") or []:
        if e.get("effective_date") and secno and secno in _section_set(e["applies_to"]):
            return e["effective_date"], "section"
    return eff["effective_date"], "law"


GRANT_WORD = re.compile(r"\b(?:is|are|hereby|further)\s+(?:hereby\s+)?(?:further\s+)?(?:authorized|empowered)\b|\bmay\b(?!\s+not)|\b(?:has|have) the power\b|\b(?:is|are) permitted\b", re.I)
MANDATORY = re.compile(r"\b(shall|must|is required|are required|required to|is directed|are directed)\b", re.I)
GRANT_PHRASE = re.compile(r"\b(?:shall be|is|are) (?:hereby )?(?:further )?(?:authorized|empowered)(?: and (?:authorized|empowered))?\b|\bshall have (?:the )?(?:power|authority)\b", re.I)


def grant_only(quote):
    """A grant with no 'shall' aimed at the actor ('is hereby further authorized and empowered to ...', 'may ...')."""
    q = GRANT_PHRASE.sub(" ", quote or "")
    q = re.sub(r"\b(?:which|that|who|whom|whose)\s+(?:\w+\s+){0,3}?(?:shall|must)\b", " ", q)
    return bool(GRANT_WORD.search(quote or "")) and not MANDATORY.search(q)


CAP_RE = re.compile(r"\b(?:shall not|may not|must not)\b[^.;]{0,100}\b(?:issue|exceed)\b|\baggregate principal amount exceeding\b|\bno\b[^.;]{0,60}\b(?:bonds?|notes?|obligations?)\b[^.;]{0,120}\b(?:on or after|after)\b", re.I)
LIMIT_RE = re.compile(r"\b(?:shall|may|must) not (?:exceed|be (?:longer|greater|more|less|fewer|shorter)|extend beyond)\b|\bnot to exceed\b|\bno (?:longer|more|greater) than\b", re.I)
DEBT_WORDS = re.compile(r"\b(?:bonds?|notes?|obligations?|indebtedness|debt|borrow\w*)\b", re.I)
STATE_MARK = re.compile(r"\b(state|department of taxation and finance|commissioner of taxation|tax commission)\b", re.I)
TRIGGER = re.compile(r"\b(upon|whenever|when|promptly|as soon as|as needed|until|if|unless|in response to)\b|\breceipt of\b|\breceives?\b|\bat the request\b"
                     r"|\bon the (?:written )?requests?\b|\bupon (?:the )?(?:written )?requests?\b|\bat the date of\b|\b(?:at|on|upon) (?:the )?dissolution\b"
                     r"|\b(?:after|following) (?:the )?(?:receipt|filing|submission)\b|\bin the event\b|\bon the date of (?:its |the )?(?:dissolution|termination)\b", re.I)
PROHIBITION = re.compile(r"\b(?:shall not|may not|must not)\b|^\s*no\b", re.I)
SETUP_TYPES = {"rulemaking", "plan or strategy", "program or service", "designation or staffing", "database or data publication", "notice or posting", "training", "outreach or education"}


def law_locality(text, title):
    """The single named locality of a local act (title and text), else None."""
    units = set()
    for t in (title or "", _mask_deleted(text)):
        for m in LOCALITY[0][0].finditer(re.sub(r"\([^)]*\)", "", t)):
            kind = m.group(1).lower()
            name = re.sub(r"\s+", " ", m.group(2)).strip(" .")
            name = re.sub(r"(?:\s+(?:assessors?|board|clerk|treasurer|supervisor|tax|department|office|shall|may|is|has|will))+$", "", name, flags=re.I)
            name = re.sub(r"\s+" + kind + r"$", "", name, flags=re.I)        # "Town of Brookhaven Town"
            if name and not GENERIC_LEAD.match(name.split()[0]):
                units.add((LOCAL_GROUPS[kind], _title("%s of %s" % (kind, name))))
    if len(units) > 1:
        units = {u for u in units if u[0] != "Counties"} or units
    return units.pop() if len(units) == 1 else None


def law_localities(text, title):
    """Every named locality of a local act (title and text) as {(group, unit)}."""
    units = set()
    for t in (title or "", _mask_deleted(text)):
        for m in LOCALITY[0][0].finditer(re.sub(r"\([^)]*\)", "", t)):
            kind = m.group(1).lower()
            name = re.sub(r"\s+", " ", m.group(2)).strip(" .")
            name = re.sub(r"(?:\s+(?:assessors?|board|clerk|treasurer|supervisor|tax|department|office|shall|may|is|has|will))+$", "", name, flags=re.I)
            name = re.sub(r"\s+" + kind + r"$", "", name, flags=re.I)
            if name and not GENERIC_LEAD.match(name.split()[0]):
                units.add((LOCAL_GROUPS[kind], _title("%s of %s" % (kind, name))))
    return units


def _words(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def relocated(quote, text):
    """D4: True when every braced block of the quote (6+ words) matches 80%+ of its words, in order, a [deleted] span of the act."""
    pos = locate(quote, text)
    if pos is None:
        return False
    end = pos + int(len(quote) * 1.3) + 20
    blocks = []
    for m in re.finditer(r"\{\{(.*?)\}\}", text, re.S):
        w = _words(m.group(1))
        if len(w) >= 6 and m.start() <= end and m.end() >= pos:
            blocks.append(w)
    if not blocks:
        return False
    dels = [_words(m.group(1)) for m in re.finditer(r"\[([^\[\]]{20,40000}?)\]", text, re.S)]
    import difflib
    def frac(a, b):
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        return sum(x.size for x in sm.get_matching_blocks()) / len(a)
    return all(any(frac(w, d) >= 0.8 for d in dels if len(d) >= 4) for w in blocks)


# ── Phase 3b: hard ingest gates (apply to every model and every run; each drop is counted and listed) ─────────────────
DROPPED = []


def drop(o, rule, reason, law_key=None):
    DROPPED.append({"obligation_id": o.get("obligation_id"), "matter_id": o.get("matter_id"), "rule": rule, "reason": reason,
                    "agency": o.get("agency"), "kind_model": o.get("kind_model"), "quote": (o.get("quote") or "")[:240]})
    bump("drop_" + rule)


def locate_span(quote, text):
    """(start, end) offsets of the quote in `text` (markers, punctuation, case and [deleted] matter ignored), else None."""
    masked = _mask_deleted(text)
    flat, offs = [], []
    for m in re.finditer(r"[A-Za-z0-9]", masked):
        flat.append(m.group(0).lower()); offs.append(m.start())
    q = eo.alnum(quote)
    if len(q) < 8:
        return None
    i = "".join(flat).find(q)
    if i < 0:
        return None
    return offs[i], offs[i + len(q) - 1] + 1


def braced_intervals(text):
    return [(m.start(), m.end()) for m in re.finditer(r"\{\{.*?\}\}", text, re.S)]


def in_braces(a, b, text):
    """Does the text between offsets a and b overlap a {{ }} new-matter span?"""
    return any(x < b and y > a for x, y in braced_intervals(text))


BOUNDARY = r"(?<!\bSt)(?<!\bNo)(?<!\bCo)(?<!\bInc)(?<!\bMr)(?<!\bMrs)(?<!\bDr)(?<!\bJr)(?<!\bSr)(?<!\bAve)(?<!\bU\.S)[.;](?:\}\})?\s+(?=[A-Z{(\d\[])|\n\n"


def context_sentence(span, text):
    """The sentence (or list item) around a span: from the previous '. ' / '; ' / paragraph break to the next one."""
    start, end = span
    left = max((m.end() for m in re.finditer(BOUNDARY, text[:start])), default=0)
    m = re.search(BOUNDARY, text[end:])
    right = end + m.start() + 1 if m else len(text)
    return text[left:right], (left, right)


HDR = re.compile(r"(?m)^(?:§|Section)\s*(\d+)\.")
AMENDED = re.compile(r"\b(?:is|are) (?:hereby )?amended\b|\bamended by (?:adding|inserting|striking)", re.I)


def section_of_span(span, text):
    """(header paragraph, section text) of the act section the span sits in, else (None, None)."""
    hs = list(HDR.finditer(text))
    cur = None
    for k, m in enumerate(hs):
        if m.start() <= span[0]:
            cur = k
    if cur is None:
        return None, None
    a = hs[cur].start()
    b = hs[cur + 1].start() if cur + 1 < len(hs) else len(text)
    sec = text[a:b]
    return sec.split("\n\n", 1)[0], sec


EXEMPT_RE = re.compile(
    r"\b(?:shall not|does not|do not|will not) apply\b|\bshall not be applicable\b|\bnot apply to\b"
    r"|\bshall not (?:prevent|prohibit|preclude)\b[^.;]{0,100}\bfrom (?:holding|serving|being|acting)\b"
    r"|\bexempt(?:ed)? from\b|\bnotwithstanding\b[^.;]{0,160}\bresiden"
    r"|\brequiring (?:a|an|any|the) [\w ]{0,30}to be (?:a )?residents?\b|\bresidency requirements?\b", re.I)
STRONG_EXEMPT_RE = re.compile(
    r"\bshall not (?:prevent|prohibit|preclude)\b[^.;]{0,100}\bfrom (?:holding|serving|being|acting)\b"
    r"|\bnotwithstanding\b[^.;]{0,160}\bresiden|\brequiring (?:a|an|any|the) [\w ]{0,30}to be (?:a )?residents?\b|\bresidency requirements?\b"
    r"|\bdetermination denying (?:such |the )?refund\b|\bapplication for (?:the )?refund\b[^.]{0,250}\bdenying\b", re.I)
CONDITION_RE = re.compile(r"^\W*(?:no\b[^.;]{0,160}\bunless\b|subject to\b|provided,? (?:that|however)\b|except (?:as|that)\b)|\bshall be subject to\b", re.I)
REVIEW_DUTY_RE = re.compile(r"\bshall be subject to (?:the )?(?:\w+ )?(?:review|audit)\b", re.I)         # "subject to review/audit by X" is X's review duty
APPROVAL_COND_RE = re.compile(r"\bsubject to (?:the )?(?:prior |written |advance )?(?:approval|consent|authorization)\b", re.I)
ITEM_LABEL = re.compile(r"^\W*(?:\{\{)?\(?[A-Za-z0-9]{1,3}[.)]\s")
VERBISH = re.compile(r"\b(shall|must|may|required|authorized|empowered|directed|power|duty|responsible|is to|are to|shall be)\b", re.I)
RELATIVE = re.compile(r"\b(?:which|that|who|whom|whose)\s+(?:\w+\s+){0,3}?(?:shall|must)\b", re.I)
STOP_KEYWORDS = {"department", "commissioner", "effective", "provisions", "section", "subdivision", "program", "agency", "authority", "service", "services"}


def _wset(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _tail(q):
    m = re.search(r"\b(?:shall|must|may|is authorized|are authorized)\b", q or "", re.I)
    return (q or "")[m.end():] if m else None


def _head(q):
    m = re.search(r"\b(?:shall|must|may|is authorized|are authorized)\b", q or "", re.I)
    return (q or "")[:m.start()] if m else None


def same_provision(a, b):
    """70%+ overlap of the whole quote AND of what follows the modal verb (the action), so two provisions built on one template
    ('Upon application ... the department shall search' / 'Upon acceptance ... the department shall ...') stay separate."""
    if overlap(a, b) < 0.7:
        return False
    ta, tb = _tail(a), _tail(b)
    if ta is not None and tb is not None and overlap(ta, tb) < 0.7:
        return False
    ha, hb = _head(a), _head(b)           # the trigger before the modal: different triggers are different provisions
    if ha and hb and len(ha.split()) >= 5 and len(hb.split()) >= 5 and overlap(ha, hb) < 0.6:
        return False
    return True


def overlap(a, b):
    import difflib
    wa, wb = re.findall(r"[a-z0-9]+", (a or "").lower()), re.findall(r"[a-z0-9]+", (b or "").lower())
    if not wa or not wb:
        return 0.0
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    return sum(x.size for x in sm.get_matching_blocks() if x.size >= 4) / min(len(wa), len(wb))      # runs of 4+ shared words


DEADLINE_ONLY = re.compile(r"\b(?:shall|must)\s+(?:begin|commence|start|launch|be (?:established|implemented|completed|launched|operational|available|in place))\b[^.;]{0,60}\b(?:no later than|not later than|within|by|on or before)\b", re.I)


PAREN_ITEM = re.compile(r"^\W*(?:\{\{)?\(\w{1,4}\)\s")
TO_VERB = re.compile(r"(?:^|[\s.;:}])To (?:[a-z]{3,})\b|\bpowers? and duties\b|\bduties? and powers?\b")
INLINE_LABEL = re.compile(r"\(\w{1,4}\)\s")


def inline_lead_in(span, text):
    """A list run inside one paragraph ('... topics including: (a) ...; (e) {{new}} ...'): (lead-in text before the first inline
    label, True when that lead-in is existing unbraced text), else None."""
    a = text.rfind("\n", 0, span[0]) + 1
    para_to_span = text[a:span[0]]
    labels = list(INLINE_LABEL.finditer(para_to_span))
    if not labels:
        return None
    lead = para_to_span[:labels[0].start()]
    if not (VERBISH.search(lead) or TO_VERB.search(lead)):
        return None
    return lead, "{{" not in lead


def list_lead_in(span, text):
    """For a lettered or numbered list entry: the lead-in paragraph above the list (ends with ':' or 'following'), else None."""
    paras = [(m.start(), m.end()) for m in re.finditer(r"[^\n]+", text)]
    idx = next((i for i, (a, b) in enumerate(paras) if a <= span[0] < b), None)
    if idx is None or not ITEM_LABEL.match(text[paras[idx][0]:paras[idx][1]]):
        return None
    j = idx - 1
    # walk back over the other (parenthesised) list items; a numbered paragraph ("28. The center shall ...:") is the lead-in, not an item
    while j >= 0 and (PAREN_ITEM.match(text[paras[j][0]:paras[j][1]]) or not text[paras[j][0]:paras[j][1]].strip()):
        j -= 1
    if j < 0:
        return None
    para = text[paras[j][0]:paras[j][1]]
    return para if re.search(r"(?:[:;]|\bfollowing|\bensuring|\bthat)\s*(?:\}\})?\s*$", para) else None


def gate_record(o, text, has_markers):
    """Returns (rule, reason) when the record must be dropped, else None. Rules 1-3 of phase 3b."""
    if not o.get("quote_verified"):
        return "unverified_quote", "quote not found in the law text"
    q = o.get("quote") or ""
    span = locate_span(q, text)
    # 3. no-record classes
    if STRONG_EXEMPT_RE.search(q) or (EXEMPT_RE.search(q) and not MANDATORY.search(EXEMPT_RE.sub(" ", q))):
        return "exemption_or_applicability", "exemption, residency or refund-review applicability clause, binds no government actor"
    if span:
        hdr, sec = section_of_span(span, text)
        if sec and re.search(r"\b11\.00\b[^.]{0,80}local finance law|local finance law[^.]{0,80}\b11\.00\b", hdr + " " + sec[:400], re.I):
            return "local_finance_useful_life", "Local Finance Law section 11.00 period of probable usefulness"
        sent, (sl, sr) = context_sentence(span, text)
        if not VERBISH.search(q) and not VERBISH.search(sent):
            lead = list_lead_in(span, text)
            if lead and (VERBISH.search(lead) or TO_VERB.search(lead)):          # a list entry: the duty is in the lead-in sentence
                o["lead_in"] = re.sub(r"\s+", " ", re.sub(r"\{\{|\}\}", "", lead)).strip()[:400]
                o["kind_from_lead_in"] = "duty" if MANDATORY.search(lead) else "power"
                if o["kind_from_lead_in"] == "duty" and o.get("kind_model") == "power" and LIMIT_RE.search(lead) and not MANDATORY.search(LIMIT_RE.sub(" ", lead)) and not DEBT_WORDS.search(lead + " " + q):
                    o["kind_from_lead_in"] = "power"; bump("lead_in_limit_stays_power")     # 'shall not exceed' on a court's order is a limit on a power
                bump("list_entry_attached_to_lead_in")
            else:
                il = inline_lead_in(span, text)
                if il:             # the list is inside one paragraph and its lead-in sits in the same subdivision
                    o["lead_in"] = re.sub(r"\s+", " ", re.sub(r"\{\{|\}\}", "", il[0])).strip()[:400]
                    o["kind_from_lead_in"] = "duty" if MANDATORY.search(il[0]) else "power"
                    o["lead_in_existing"] = il[1]
                    bump("list_entry_inline_lead_in")
                else:
                    return "designation_no_actor", "a designation or list entry with no lead-in duty or power"
        # 2. new matter
        if has_markers and hdr and AMENDED.search(hdr) and not in_braces(sl, sr, text) and not re.search(r"\[[^\[\]]{2,}\]", sent):
            return "reprinted_existing_text", "amended section, no new matter in the quote's sentence"
    return None


def _stems(s):
    skip = {"depart", "commis", "provis", "subdiv", "sectio", "effect", "applic", "author", "agency", "board", "within", "which", "shall"}
    return {w[:6] for w in re.findall(r"[a-z]{5,}", (s or "").lower())} - skip


def drop_conditions(lst):
    """A 'no ... unless' / 'subject to' / 'provided that' clause is a condition on another record of the same actor, not a duty
    or power of its own: dropped when it shares a content stem with that record."""
    out = list(lst)
    for r in list(out):
        if r not in out or not CONDITION_RE.search(r.get("quote") or ""):
            continue
        q = r.get("quote") or ""
        ms = MODAL_SENT.search(q)
        if REVIEW_DUTY_RE.search(q):
            bump("review_duty_kept"); continue
        if re.match(r"^\W*provided", q, re.I) and ms and GOV_ACTOR.search(q[max(0, ms.start() - 140):ms.start()]):
            continue            # a proviso with its own grant or mandate aimed at the actor is a separate provision
        own_modal = any(not re.match(r"\s+(?:also\s+)?be subject to\b", q[m.end():]) for m in re.finditer(r"\b(?:shall|must|may)\b", q))
        approval = bool(APPROVAL_COND_RE.search(q)) and not own_modal
        for o in out:
            if o is r or ((o.get("agency"), o.get("agency_unit")) != (r.get("agency"), r.get("agency_unit")) and not approval):
                continue         # 'subject to the approval of X' qualifies another actor's record: same-actor test waived
            if _stems(r["quote"]) & _stems(o["quote"]) and not CONDITION_RE.search(o["quote"]):
                out.remove(r); drop(r, "condition_of_other_record", "a condition on %s, same actor and object" % o["obligation_id"])
                break
    return out


PROVISO_START = re.compile(r"^\W*provided\b", re.I)


def proviso_widens_existing(quote, text):
    """F4 (Oct 9 2026). A quote that opens with 'Provided' / 'Provided, further' / 'Provided, however' and whose words are braced new matter
    inside an amended section that keeps existing prose widens an existing provision: extends_existing is true even though the proviso
    sentence stands alone (wholly_new would clear it)."""
    if not PROVISO_START.match(quote or ""):
        return False
    sp = locate_span(quote, text)
    if not sp or not in_braces(sp[0], sp[0] + 1, text):
        return False
    hdr, sec = section_of_span(sp, text)
    if not hdr or not AMENDED.search(hdr):
        return False
    body = sec[len(hdr):]
    body = re.sub(r"\{\{.*?\}\}", " ", body, flags=re.S)
    body = re.sub(r"\[[^\[\]]*\]", " ", body)
    return sum(1 for c in body if c.isalpha()) > 40


def wholly_new(span, text):
    """True when the sentence around the span has no existing text outside {{ }} (apart from a subdivision label such as '2.'):
    a wholly new provision, not an extension."""
    _, (sl, sr) = context_sentence(span, text)
    iv = braced_intervals(text)
    if not any(x < sr and y > sl for x, y in iv):
        return False
    deleted = [(m.start(), m.end()) for m in re.finditer(r"\[[^\[\]]*\]", text[:sr + 1])]
    outside = [c for k, c in enumerate(text[sl:sr], start=sl)
               if c.isalpha() and not any(x <= k < y for x, y in iv) and not any(x <= k < y for x, y in deleted)]
    return len(outside) <= 3


def _cit_parts(c):
    c = (c or "").lower()
    m = re.search(r"§+\s*([\w.-]+)((?:\s*\(\w+\))*)", c)
    if not m:
        return None
    return m.group(1), re.findall(r"\((\w+)\)", m.group(2))


_DIFF_STOP = {"shall", "authority", "section", "subdivision", "paragraph", "provisions", "pursuant", "thereof", "therein", "herein", "hereby", "respectively", "whether", "which", "having", "within", "between"}


def distinct_provisions(a, b):
    """True when two same-actor records are different provisions despite overlapping wording: their citations name different
    sections or non-nested sub-parts ('2041-w(2)(A)' vs '(2)(C)'), or each quote carries a noun the other lacks (4+ in all, numbers and dates aside:
    'transfer stations' vs 'landfills')."""
    ca, cb = _cit_parts(a.get("citation")), _cit_parts(b.get("citation"))
    if ca and cb:
        if ca[0] != cb[0]:
            return True
        pa, pb = ca[1], cb[1]
        if pa and pb and pa[:len(pb)] != pb[:len(pa)]:
            return True
    skip = _DIFF_STOP | _NUMW | _DATEW
    wa = {w for w in _words(a.get("quote")) if len(w) >= 6 and not w.isdigit()} - skip
    wb = {w for w in _words(b.get("quote")) if len(w) >= 6 and not w.isdigit()} - skip
    ua, ub = wa - wb, wb - wa
    return len(ua) >= 1 and len(ub) >= 1 and len(ua) + len(ub) >= 4


def dedupe_law(lst):
    """Rule 4: same actor, quotes overlapping 70%+: keep the one with a stated deadline, else the longer quote. A deadline
    clause split off as its own duty ('The campaign shall begin no later than 90 days ...') merges into the main duty."""
    out = list(lst)
    for a in list(out):
        if a not in out:
            continue
        for b in list(out):
            if b is a or b not in out or a not in out:
                continue
            same_actor = (a.get("agency"), a.get("agency_unit")) == (b.get("agency"), b.get("agency_unit"))
            if not same_actor:
                continue
            if same_provision(a.get("quote"), b.get("quote")) and a.get("kind") == b.get("kind"):
                if distinct_provisions(a, b):
                    bump("dedupe_kept_distinct"); continue
                has_a, has_b = a.get("deadline_kind") not in (None, "none"), b.get("deadline_kind") not in (None, "none")
                keep, lose = (a, b) if (has_a and not has_b) or (has_a == has_b and len(a["quote"]) >= len(b["quote"])) else (b, a)
                out.remove(lose); drop(lose, "duplicate_provision", "overlaps %s by 70%%+" % keep["obligation_id"])
                if lose is a:
                    break
    for b in list(out):             # a deadline clause split off as its own duty
        if b not in out or not DEADLINE_ONLY.search(b.get("quote") or "") or b.get("deadline_kind") in (None, "none"):
            continue
        keys = {w for w in _wset(b["quote"]) if len(w) >= 6} - STOP_KEYWORDS - {"effective", "january", "february", "december"}
        for a in out:
            if a is b or (a.get("agency"), a.get("agency_unit")) != (b.get("agency"), b.get("agency_unit")) or a.get("kind") != b.get("kind"):
                continue
            if keys & _wset(a.get("quote")) and a.get("deadline_kind") in (None, "none", "on_effective_date"):
                for k in ("deadline_kind", "deadline_date", "deadline_text"):
                    a[k] = b.get(k)
                out.remove(b); drop(b, "deadline_split", "deadline clause merged into %s" % a["obligation_id"])
                break
    return out


# ── Phase 3c: recall checks and the re-ask list ─────────────────────────────────────────────────────────────────────
MODAL_SENT = re.compile(r"\b(?:shall|must|may|is authorized|are authorized|is hereby authorized|empowered|is required|are required)\b", re.I)
GOV_ACTOR = re.compile(r"\b(department|commissioner|office|officer|board|commission|authority|agency|agencies|governor|comptroller|attorney general|court|judge|council|legislature|director|superintendent|secretary|division|bureau|trustees?|assessor|clerk|treasurer|mayor|supervisor|corporation|university|state|town|village|city|county|municipalit\w*|district|chair\w*|president|inspector|administrator|RJSCB|panel)\b", re.I)
DEFINITIONAL = re.compile(r"^\W*(?:the term|as used in|for (?:the )?purposes of)\b", re.I)
SKIP_SENT = re.compile(r"\btake effect\b|\bshall have become a law\b|\bis hereby repealed\b", re.I)


FUNCTION_ITEM = re.compile(r"^\W*(?:\d+(?:-\w+)?\.\s*)?(?:\(\w{1,4}\)\s*)?(?:\{\{)?\s*To [a-z]{3,}\b")
PRIVATE_SENT = re.compile(r"\b(?:bar association|attorney[- ]client|privilege[ds]?|physician[- ]patient|licensee|policyholder)\b", re.I)


def _subdivisions(text):
    """[(start, end)] of each numbered subdivision paragraph run ('5-a. ...') up to the next one or the next act section."""
    marks = [m.start() for m in re.finditer(r"(?m)^\W*(?:\{\{)?\s*\d+(?:-\w+)?\.\s|^(?:§|Section)\s*\d+\.", text)] + [len(text)]
    return list(zip(marks[:-1], marks[1:]))


def sentences_with_offsets(text):
    """[(start, end, sentence)] over the whole marked text, split at sentence ends, paragraph breaks and list items."""
    out, pos = [], 0
    for m in list(re.finditer(BOUNDARY, text)) + [None]:
        end = (m.start() + 1) if m else len(text)
        seg = text[pos:end]
        if seg.strip():
            out.append((pos, end, seg.strip()))
        pos = m.end() if m else len(text)
    return out


def _covered(sent_span, spans):
    return any(a < sent_span[1] and b > sent_span[0] for a, b in spans)


def recall_flags(key, text, records, dropped):
    """The reasons this law should be re-asked (empty list: none). Checks a, b, c of phase 3c."""
    spans = []
    for q in [r.get("quote") or "" for r in records] + [d.get("quote") or "" for d in dropped]:
        sp = locate_span(q, text)
        if sp:
            spans.append(sp)
    iv = braced_intervals(text)
    sents = sentences_with_offsets(text)
    flags = []
    subs = _subdivisions(text)
    rec_quotes = [(locate_span(r.get("quote") or "", text), r.get("quote") or "") for r in records]

    def _parallel(a, b, t):
        """re-ask noise: the sentence shares a subdivision with a stored record and repeats its wording (parallel sentences of one provision)."""
        for (sa, sb) in subs:
            if sa <= a < sb:
                return any(sp and sa <= sp[0] < sb and overlap(t, q) >= 0.4 for sp, q in rec_quotes)
        return False
    # a. new matter that is only digits, dates and amounts: fewer extends_existing records than amended clauses
    blocks = [m.group(1) for m in re.finditer(r"\{\{(.*?)\}\}", text, re.S)]
    if blocks and all(_only_extension(b) for b in blocks):
        clauses = [(a, b, t) for a, b, t in sents if any(x < b and y > a for x, y in iv)]
        n_ext = sum(1 for r in records if r.get("extends_existing"))
        if n_ext < len(clauses) <= 30:
            miss = [t for a, b, t in clauses if not _covered((a, b), spans)]
            flags.append({"check": "a_numbers_only_fewer_extends", "detail": "%d amended clauses, %d extends_existing records" % (len(clauses), n_ext), "sentences": miss[:12]})
    # b. modal sentences inside new matter versus records
    modal = []
    for a, b, t in sents:
        hdr_sec = section_of_span((a, b), text)[0]
        new = any(x < b and y > a for x, y in iv) or (hdr_sec is not None and not AMENDED.search(hdr_sec))
        ms = MODAL_SENT.search(t)
        if (new and ms and not SKIP_SENT.search(t) and not EXEMPT_RE.search(t) and not DEFINITIONAL.search(t) and len(t) > 30
                and GOV_ACTOR.search(t[max(0, ms.start() - 140):ms.start()] or t[:ms.start()])
                and not PRIVATE_SENT.search(t)):
            modal.append((a, b, t))
        elif new and FUNCTION_ITEM.match(t) and len(t) > 30 and not SKIP_SENT.search(t):
            modal.append((a, b, t))             # a functions-list item ("{{To carry out investigations ...}}"): the actor sits in the lead-in
    if 2 <= len(modal) <= 40:           # a law with hundreds of sentences (a repeal act, an appropriation) is not re-asked
        unc = [t for a, b, t in modal if not _covered((a, b), spans) and not _parallel(a, b, t)]
        cov = 1 - len(unc) / len(modal)
        if cov < 0.8:
            flags.append({"check": "b_modal_sentence_coverage", "detail": "%d of %d new-matter shall/may sentences covered (%.0f%%)" % (len(modal) - len(unc), len(modal), 100 * cov), "sentences": unc[:12]})
    # c. a list lead-in with items but fewer records than items
    paras = [(m.start(), m.end()) for m in re.finditer(r"[^\n]+", text)]
    k = 0
    while k < len(paras):
        a, b = paras[k]
        para = text[a:b]
        if re.search(r":\s*(?:\}\})?\s*$", para) and MODAL_SENT.search(para) and GOV_ACTOR.search(para):
            items = []
            j = k + 1
            while j < len(paras) and ITEM_LABEL.match(text[paras[j][0]:paras[j][1]]):
                items.append(paras[j]); j += 1
            if len(items) >= 2 and sum(len(text[x:y].split()) for x, y in items) / len(items) >= 7:     # sentences, not a list of names
                missing = [text[x:y] for x, y in items if not _covered((x, y), spans)]
                if missing:
                    flags.append({"check": "c_list_items_fewer_records", "detail": "%d items, %d without a record" % (len(items), len(missing)),
                                  "lead_in": re.sub(r"\s+", " ", para)[:300], "sentences": missing[:12]})
            k = j
        else:
            k += 1
    # e. (J4, Oct 9 2026) an application-window or time-limit change in an amended clause ('until March first, two thousand [eleven] {{fifteen}}')
    #    and a new-matter 'At any time after ...' power whose subject is not a body: neither is caught by b, so ask for it
    cand = []
    for a, b, t in sents:
        seg = text[a:b]
        if _covered((a, b), spans):
            continue
        if (re.search(r"\[[^\[\]]+\]\s*\{\{[^{}]+\}\}", seg) and re.search(r"\b(?:until|through|prior to|on or before|no later than|not later than)\b[^\[\]{}]{0,60}[\[{]", seg, re.I)
                and re.search(r"\b(?:may|shall)\b", t) and not SKIP_SENT.search(t)):
            cand.append(t)
        elif (any(x < b and y > a for x, y in iv) and re.match(r"^\W*(?:\{\{)?\W*(?:\(\w{1,4}\)\s*)?at any time (?:after|before|prior to|during)\b", t, re.I)
                and re.search(r"\bmay\b", t) and not SKIP_SENT.search(t)):
            cand.append(t)
    if cand:
        flags.append({"check": "e_window_or_timing_power", "detail": "%d application-window or timing sentences without a record" % len(cand), "sentences": cand[:12]})
    return flags


COMPOUND_LOCAL = re.compile(r"\b(?:town|city|village|county)\b[^;]*?\band\b[^;]*?\b(?:district|authority|agency|corporation)\b", re.I)
PRE_2017 = range(2009, 2017)


def judgment_flags(text, records):
    """J1-J3 (Oct 9 2026): judgment classes the audits confirmed. Each returns the record's quote so the re-ask packet carries the sentence."""
    flags = []
    ps = [r for r in records if PASSIVE_SUBJECT.match((r.get("actor_raw") or "").strip())]
    if ps:
        flags.append({"check": "passive_subject_actor", "detail": "%d records whose actor_raw is the passive subject of the sentence, not the acting body" % len(ps),
                      "sentences": [r["quote"] for r in ps][:12]})
    only = []
    for r in records:
        try:
            sess = int(r.get("session"))
        except (TypeError, ValueError):
            continue
        if sess not in PRE_2017:
            continue
        sp = locate_span(r.get("quote") or "", text)
        if not sp:
            continue
        blocks = [m.group(1) for m in re.finditer(r"\{\{(.*?)\}\}", text, re.S) if m.start() < sp[1] and m.end() > sp[0]]
        if len(blocks) != 1:
            continue
        toks = re.findall(r"[A-Za-z0-9$%]+", blocks[0])
        if (len(toks) == 1 and toks[0].isalpha() and toks[0].lower() not in _NUMW | _DATEW
                and not re.fullmatch(r"(?i)[ivxlcdm]{1,4}", toks[0])):
            only.append(r["quote"])
    if only:
        flags.append({"check": "condition_only_new_matter", "detail": "%d records whose only new matter is one word (%s): check the record is a duty and not an existing one" % (len(only), "a changed condition or term"),
                      "sentences": only[:12]})
    comp = [r for r in records if COMPOUND_LOCAL.search(r.get("actor_raw") or "")]
    if comp:
        flags.append({"check": "compound_local_actor", "detail": "%d records whose actor_raw joins a locality and a named district or authority: one record each" % len(comp),
                      "sentences": [r["quote"] for r in comp][:12]})
    return flags


def build_reask(todo, duties, powers):
    """data/reask.json content: {key: {reasons: [...]}} for the laws whose recall checks flag."""
    by_law = defaultdict(list)
    for o in duties + powers:
        by_law[o["matter_id"]].append(o)
    drops = defaultdict(list)
    for d in DROPPED:
        drops[d["matter_id"]].append(d)
    out = {}
    manual = json.loads(REASK_MANUAL.read_text()) if REASK_MANUAL.exists() else {}
    for law, text in todo:
        if not (EXTRACTED / (law["key"] + ".json")).exists():
            continue                     # no answer yet: nothing to re-ask (it is still unanswered, not under-covered)
        fl = recall_flags(law["key"], text, by_law.get(law["key"], []), drops.get(law["key"], []))
        unres = [r for r in by_law.get(law["key"], []) if r.get("actor_unresolved") and not GOV_ACTOR.search(r.get("actor_raw") or "")]
        if unres:      # fix 2b: a passive-subject actor no rule could resolve: ask the model who acts
            fl.append({"check": "d_actor_unresolved", "detail": "%d records whose acting body could not be resolved" % len(unres),
                       "sentences": [r["quote"] for r in unres][:12]})
        fl += judgment_flags(text, by_law.get(law["key"], []))
        if law["key"] in manual:     # fix 11: missed items the audits found
            sents = []
            for frag in manual[law["key"]]:
                sp = locate_span(frag.split("...")[0], text)
                sents.append(re.sub(r"\s+", " ", context_sentence(sp, text)[0]).strip() if sp else frag)
            fl.append({"check": "audit_missed", "detail": "provisions the blind audits found missing", "sentences": sents})
        if fl:
            out[law["key"]] = {"reasons": fl}
    return out


def load_reask():
    """All per-session re-ask files merged: {key: entry}."""
    out = {}
    for f in sorted((DATA / "reask").glob("*.json")):
        out.update(json.loads(f.read_text())["laws"])
    return out


def reask_instruction(entry):
    sents = []
    for r in entry["reasons"]:
        for t in r["sentences"]:
            t = re.sub(r"\{\{|\}\}", "", re.sub(r"\s+", " ", t)).strip()[:300]
            if t not in sents:
                sents.append(t)
    lead = [r.get("lead_in") for r in entry["reasons"] if r.get("lead_in")]
    return ("ADDITIONAL INSTRUCTION. A first pass over this law missed some provisions. The law's new matter also contains these sentences:\n"
            + "\n".join("%d. %s" % (i, t) for i, t in enumerate(sents[:15], 1))
            + ("\n(List entries above belong to the lead-in: " + lead[0] + ")" if lead else "")
            + "\nRecord each of them that is a duty or power of a government actor, with the same fields and the same rules as above. "
              "Quote each verbatim from the law text. Record nothing else, and nothing that is only an exemption, a condition or a definition.")


def merge_reask(todo, results_dir, model):
    """Merge results/<key>__reask.json answers into cache/extracted/<key>.json (ids continue; the dedup gate runs at build)."""
    n = 0
    for law, text in todo:
        rp = results_dir / (law["key"] + "__reask.json")
        cp = EXTRACTED / (law["key"] + ".json")
        if not rp.exists() or not cp.exists():
            continue
        raw = json.loads(rp.read_text())
        if not eo.validate_against_schema(raw, SCHEMA):
            continue
        for o in raw.get("obligations", []):
            eo._offset_to_days(o.get("deadline"))
        raw["effective_clause"] = {"kind": "other", "offset_days": None, "fixed_date": None, "text": ""}
        res2 = eo.finalize_extraction(raw, law, text, eo.operative_text(text), LOOKUP, BY_CANON, model)
        res = json.loads(cp.read_text())
        base = len(res["obligations"])
        for i, (o, ro) in enumerate(zip(res2["obligations"], raw["obligations"]), 1):
            nid = "%s-%02d" % (law["key"], base + i)
            o["obligation_id"] = nid
            o["from_reask"] = True
            res["obligations"].append(o)
            res.setdefault("extends_model", {})[nid] = bool(ro.get("extends_existing"))
            res.setdefault("actor_model", {})[nid] = ro.get("actor_resolved")
            n += 1
        cp.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return n


# ── Ingest ──────────────────────────────────────────────────────────────────────────────────────────────────────
def write_cache(mid, res):
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    if mid in EXT_MODEL:
        res["extends_model"] = EXT_MODEL[mid]
        res["actor_model"] = ACTOR_MODEL[mid]
    (EXTRACTED / (mid + ".json")).write_text(json.dumps(res, indent=1, ensure_ascii=False))


def build_records(laws):
    by_key = {l["key"]: l for l in laws}
    STATS.clear()
    DROPPED.clear()
    duties, powers, excluded = [], [], 0
    for f in sorted(EXTRACTED.glob("*.json")):
        res = json.loads(f.read_text())
        law = by_key.get(res["matter_id"])
        if not law:
            continue
        text = (TEXT_MARKED / (law["key"] + ".txt")).read_text()
        eff = EFFECTIVE[law["key"]]
        law_d, law_p = [], []
        for o in res["obligations"]:
            o["deadline_date"] = eo.sanitize_deadline(o.get("deadline_date"), law["enactment_date"])
            if "{{" in (o.get("quote") or "") or re.search(r"\[[a-z]", o.get("quote") or ""):
                cleaned, has_deleted = eo.clean_stored_quote(o.get("quote"), text)
                o["quote"] = cleaned
                if has_deleted:
                    o["quote_has_deleted_text"] = True
            if eo.fix_actor(o, LOOKUP, BY_CANON, stage="private") == "private":
                excluded += 1
                continue
            kind = eo._kind(o)
            if kind == "neither":
                excluded += 1
                continue
            o["actor_resolved_model"] = res.get("actor_model", {}).get(o["obligation_id"])
            o["matter_id"] = law["key"]
            fix_parenthetical_actor(o) and bump("f3_parenthetical_actor")
            attach_jurisdiction(o)
            fix_local_board_of_elections(o) and bump("f2_local_board_of_elections")
            # 5. DTF only when the quote or actor names the State; a locality's tax office is the locality. A local act naming
            #    several localities resolves to the locality the sentence names, else to the group of the localities.
            if o.get("agency") == "DTF" and not STATE_MARK.search((o.get("quote") or "") + " " + (o.get("actor_raw") or "")):
                ll = named_locality(o.get("quote") or "", o.get("action_summary") or "") or law_locality(text, law["title"])
                units = None
                if not ll:
                    units = law_localities(text, law["title"])
                    if len(units) > 1:
                        groups = {u[0] for u in units}
                        grp = groups.pop() if len(groups) == 1 else "Municipalities (all)"
                        ll = (grp, "; ".join(sorted(u[1] for u in units)))
                        bump("dtf_to_locality_group")
                if ll:
                    o.update(agency=ll[0], agency_full=ll[0], agency_matched=True, jurisdiction="local", agency_org_type="local government group", agency_group=ll[0], agency_unit=ll[1])
                    bump("dtf_to_locality")
                else:                                   # never DTF without State wording
                    o.update(agency="Unspecified", agency_full="Unspecified", agency_matched=False, jurisdiction=None, agency_org_type=None, agency_group=None, agency_unit=None, actor_unresolved=True)
                    bump("dtf_to_unspecified")
            if not o.get("agency_matched") and o.get("agency") != "All agencies":      # fix 2b, 3: second-pass resolver
                bump("agency_" + agency_resolve_nys.resolve_unmatched(o, text, law, {**RESOLVE_DEPS, "named_locality": named_locality}))
            quote = o.get("quote") or ""
            g = gate_record(o, text, "{{" in text)
            if g:
                drop(o, g[0], g[1])
                continue
            o["extends_existing"] = bool(res.get("extends_model", {}).get(o["obligation_id"])) or extends_by_text(quote, text)
            if not o["extends_existing"] and relocated(quote, text):          # D4
                o["extends_existing"] = True; bump("d4_relocated")
            sp0 = locate_span(quote, text)
            if o["extends_existing"] and sp0 and wholly_new(sp0, text):     # an extension has existing text around the new matter
                o["extends_existing"] = False; bump("extends_cleared_wholly_new")
            if not o["extends_existing"] and proviso_widens_existing(quote, text):          # F4: after the wholly_new clear
                o["extends_existing"] = True; bump("f4_proviso_extends")
            if o.get("lead_in_existing"):
                o["extends_existing"] = True; bump("extends_lead_in_existing")
            if o.get("kind_from_lead_in"):
                kind = o["kind_from_lead_in"]
            if (kind == "duty" and o.get("kind_model") == "power" and o.get("kind_list_item") and not o.get("kind_from_lead_in")
                    and not MANDATORY.search(quote) and not DEBT_WORDS.search(quote)):
                kind = "power"; o["kind_adjusted"] = "model_power_kept"; bump("list_item_keeps_model_power")     # no mandatory verb aimed at the actor
            # 3. a grant with no mandatory verb is a power
            sp = locate_span(quote, text)
            ctx = context_sentence(sp, text)[0] if sp else ""
            if kind == "duty" and (grant_only(quote) or (ctx and grant_only(RELATIVE.sub(" ", ctx)))) and not CAP_RE.search(quote):
                kind = "power"; o["kind_adjusted"] = "grant_only"; bump("grant_only_to_power")
            # 4. D3: bond caps and issuance cutoffs are duties (a prohibition on the actor) with no deadline
            if CAP_RE.search(quote) and kind in ("duty", "power") and not (kind == "power" and o.get("kind_model") == "power" and not DEBT_WORDS.search(quote)):
                if kind != "duty":
                    o["kind_adjusted"] = "cap_cutoff"; bump("cap_to_duty")
                kind = "duty"
                if o.get("deadline_kind") != "none" or o.get("deadline_date"):
                    bump("cap_deadline_cleared")
                o["deadline_kind"], o["deadline_date"] = "none", None
                bump("cap_cutoff_records")
            if kind == "power":
                o["deadline_kind"], o["deadline_date"] = "none", None
            # 6. setup / triggered consistency
            if kind == "duty" and o.get("deadline_kind") == "on_effective_date" and TRIGGER.search(quote) and not CAP_RE.search(quote):
                o["deadline_kind"], o["deadline_date"] = "none", None; bump("setup_to_triggered")
            elif (kind == "duty" and o.get("deadline_kind") == "none" and o.get("recurrence") == "one-time"
                  and o.get("deliverable_type") in SETUP_TYPES and not TRIGGER.search(quote) and not CAP_RE.search(quote)
                  and not PROHIBITION.search(quote)):
                o["deadline_kind"] = "on_effective_date"; bump("triggered_to_setup")
            # 1. record dates per section; on_effective_date never null when the date is known
            sec_date, sec_src = section_effective(o, text, eff)
            if sec_src != "law":
                bump("section_dates_applied")
            if kind == "duty" and o.get("deadline_kind") == "on_effective_date":
                if o.get("deadline_date") != sec_date:
                    bump("on_effective_date_filled")
                o["deadline_date"] = sec_date
            elif o.get("deadline_kind") in (None, "none") and o.get("deadline_date") and o["deadline_date"] == res.get("effective_date"):
                o["deadline_date"] = None
            rec = {**o, "kind": kind, "chapter": law["chapter_number"], "chapter_year": law["chapter_year"],
                   "session": law["session"], "print_no": law["print_no"], "law_number_display": law["law_number_display"],
                   "law_title": law["title"], "prime_sponsor": law["sponsor"], "enactment_date": law["enactment_date"],
                   "effective_date": sec_date, "effective_rule": eff["rule"] if sec_src == "law" else ("open_on_expiration_of_other_law" if sec_src == "open" else "section_" + sec_src), "law_expires_date": eff["expires_date"],
                   "openleg_url": law["openleg_url"], "extraction_model": res.get("model")}
            (law_p if kind == "power" else law_d).append(rec)
        law_d = drop_conditions(dedupe_law(law_d))
        law_p = drop_conditions(dedupe_law(law_p))
        for lst in (law_d, law_p):       # never merge across jurisdictions or named localities
            keep = []
            for jur in {(o.get("jurisdiction"), o.get("agency_unit")) for o in lst}:
                grp = [o for o in lst if (o.get("jurisdiction"), o.get("agency_unit")) == jur]
                eo.merge_split_list_duplicates(grp)
                keep += grp
            lst[:] = sorted(keep, key=lambda o: o["obligation_id"])
        duties += law_d
        powers += law_p
    return duties, powers, excluded


# ── API mode (phase 3a): Message Batches or a synchronous canary, same prompt, schema and ingest as the packets ─────
MODEL = eo.DEFAULT_MODEL                 # claude-sonnet-5, the Council default
MAX_TOKENS = 18000                       # largest pilot answer 15,930 bytes (about 4,500 tokens); about 4x
API_DIR = HERE / "cache" / "api"         # packet-shaped: manifest.json + results/<key>.json, so --ingest reads it unchanged
BATCH_STATE = HERE / "batch_state.json"  # manifest of submitted chunks; each chunk has its own claude_batch state file
BATCH_MAX_REQUESTS = 2500                # chunk limits stay well under the Batches API caps (100,000 requests, 256 MB)
BATCH_MAX_BYTES = 150_000_000
PRICE = {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write_mult": 1.25}   # $ per MTok (Tal, Oct 7 2026)


def build_request(law, text, ttl=None, extra=None):
    """(custom_id, params): fixed instructions as the cached first block, the law text last. ttl '1h' inside batches."""
    import claude_batch
    content = claude_batch.cached_content(FIXED_PROMPT, render_variable_prompt(law, text), ttl=ttl)
    if extra:                                     # the re-ask: a short instruction after the law text
        content.append({"type": "text", "text": extra})
    params = {"model": MODEL, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": content}],
              "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}}}
    # NYS_THINKING (Oct 7 2026): Sonnet 5 runs adaptive thinking when the param is omitted; the first canary averaged
    # 5,490 output tokens a law (3 of 20 hit the cap) against ~550 for the answer itself. "off" disables thinking,
    # "low" keeps it at low effort; "default" leaves the model's adaptive default.
    mode = os.environ.get("NYS_THINKING", "default")
    if mode == "off":
        params["thinking"] = {"type": "disabled"}
    elif mode in ("low", "medium", "high"):
        params["output_config"]["effort"] = mode
    return law["key"] + ("__reask" if extra else ""), params


def project_cost(n_laws, avg_uncached_in, avg_out, fixed_tokens, batch=True, cached=True):
    """Projected dollars for n_laws from per-law averages. fixed_tokens is the cached instruction prefix: written once, then
    read per law (or billed as plain input when cached=False). Batch pricing is half of every token."""
    pi, po, pr = PRICE["input"], PRICE["output"], PRICE["cache_read"]
    per_law_in = avg_uncached_in * pi + (fixed_tokens * pr if cached else fixed_tokens * pi)
    total = n_laws * (per_law_in + avg_out * po) + (fixed_tokens * pi * PRICE["cache_write_mult"] if cached else 0)
    total /= 1e6
    return total / 2 if batch else total


def _client():
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic()


def _save_answer(key, msg):
    """Write one answer in the packet results format; returns True when it parsed and matches the schema."""
    (API_DIR / "results").mkdir(parents=True, exist_ok=True)
    if getattr(msg, "stop_reason", None) == "max_tokens":
        return False
    try:
        raw = json.loads(next(b.text for b in msg.content if b.type == "text"))
    except Exception:  # noqa: BLE001
        return False
    if not eo.validate_against_schema(raw, SCHEMA):
        return False
    (API_DIR / "results" / (key + ".json")).write_text(json.dumps(raw))
    return True


def write_manifest(todo):
    m = {}
    if (API_DIR / "manifest.json").exists():
        m = json.loads((API_DIR / "manifest.json").read_text())
    m.update({law["key"]: {"windows": 1} for law, _ in todo})
    (API_DIR / "manifest.json").write_text(json.dumps(m, indent=1))


def pending(todo):
    return [(l, t) for l, t in todo if not (API_DIR / "results" / (l["key"] + ".json")).exists()]


def run_canary(todo, n):
    """n real laws, synchronously (cache ttl 5 min), usage and a projected full-run cost."""
    import claude_batch
    client = _client()
    step = max(1, len(todo) // n)
    pick = todo[::step][:n]
    usage = claude_batch.Usage()
    ok = 0
    for law, text in pick:
        key, params = build_request(law, text)
        with client.messages.stream(**params) as st:
            msg = st.get_final_message()
        usage.add(msg)
        good = _save_answer(key, msg)
        ok += good
        print("  %s: %s, %d output tokens" % (key, "ok" if good else "REJECTED (%s)" % msg.stop_reason, msg.usage.output_tokens))
    write_manifest(pick)
    print(usage.line())
    c = max(usage.calls, 1)
    fixed = usage.cache_write if usage.cache_write else (usage.cache_read // max(c - 1, 1))
    avg_in = usage.input / c
    avg_out = usage.output / c
    # the full run has every law's text as uncached input; the canary's laws are a spread sample of the same population
    full = len(todo)
    print("canary: %d of %d answers valid; per law avg %.0f uncached input + %.0f output tokens; cached prefix %d tokens" % (ok, c, avg_in, avg_out, fixed))
    for label, batch, cached in (("batch + caching", True, True), ("batch, caching not honoured", True, False)):
        print("projected %d laws, %s: $%.2f" % (full, label, project_cost(full, avg_in, avg_out, fixed, batch, cached)))
    print("projected %d laws, synchronous + caching: $%.2f" % (full, project_cost(full, avg_in, avg_out, fixed, False, True)))


def chunks_of(requests):
    """Split [(id, params)] into chunks under the request and size caps."""
    out, cur, size = [], [], 0
    for cid, params in requests:
        b = len(json.dumps(params))
        if cur and (len(cur) >= BATCH_MAX_REQUESTS or size + b > BATCH_MAX_BYTES):
            out.append(cur); cur, size = [], 0
        cur.append((cid, params)); size += b
    if cur:
        out.append(cur)
    return out


def run_batches(todo, resume_only=False, max_wait_s=300 * 60, reask=None):
    """Submit every unanswered law as Message Batches (chunked), then collect. A later call resumes pending chunks."""
    import claude_batch
    client = _client()
    manifest = HERE / ("batch_state_reask.json" if reask is not None else "batch_state.json")
    prefix = "batch_state_reask_%03d.json" if reask is not None else "batch_state_%03d.json"
    state = json.loads(manifest.read_text()) if manifest.exists() else {"chunks": []}
    if not resume_only:
        in_flight = {k for c in state["chunks"] for k in c["keys"]}
        if reask is not None:
            todo_new = [(l, t) for l, t in todo if l["key"] in reask and not (API_DIR / "results" / (l["key"] + "__reask.json")).exists()
                        and (l["key"] + "__reask") not in in_flight]
            reqs = [build_request(l, t, ttl="1h", extra=reask_instruction(reask[l["key"]])) for l, t in todo_new]
        else:
            todo_new = [(l, t) for l, t in pending(todo) if l["key"] not in in_flight]
            reqs = [build_request(l, t, ttl="1h") for l, t in todo_new]
        for cs in chunks_of(reqs):
            n = len(state["chunks"]) + 1
            sp = HERE / (prefix % n)
            claude_batch.run_batch(client, cs, sp, max_wait_s=0)           # submit and return at once
            state["chunks"].append({"state": sp.name, "keys": [c for c, _ in cs]})
            manifest.write_text(json.dumps(state, indent=1))
        if reask is None:
            write_manifest(todo_new)
    usage = claude_batch.Usage()
    start = time.time()
    left_chunks = []
    for c in state["chunks"]:
        sp = HERE / c["state"]
        if not sp.exists():
            continue
        out = claude_batch.run_batch(client, [], sp, max_wait_s=max(0, max_wait_s - int(time.time() - start)))
        if out is None:
            left_chunks.append(c); continue
        bad = 0
        for key, (status, payload) in out.items():
            if status == "succeeded":
                usage.add(payload)
                if not _save_answer(key, payload):
                    bad += 1
            else:
                bad += 1
        print("chunk %s: %d results, %d unusable (they stay unanswered; run resume)" % (c["state"], len(out), bad))
        claude_batch.clear_state(sp)
    state["chunks"] = left_chunks
    if left_chunks:
        manifest.write_text(json.dumps(state, indent=1))
    else:
        manifest.unlink(missing_ok=True)
    print(usage.line())
    if reask is None:
        print("answered %d of %d laws; %d batch chunks still pending" % (len(todo) - len(pending(todo)), len(todo), len(left_chunks)))
    else:
        print("re-ask: %d laws flagged; %d batch chunks still pending" % (len(reask), len(left_chunks)))


def main():
    global EFFECTIVE
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-packets", metavar="DIR")
    ap.add_argument("--ingest", metavar="DIR")
    ap.add_argument("--api", action="store_true", help="call the Anthropic API (billed): needs --canary N, --batch or --resume")
    ap.add_argument("--batch", action="store_true", help="with --api: submit the unanswered laws as Message Batches")
    ap.add_argument("--resume", action="store_true", help="with --api: collect pending batches only")
    ap.add_argument("--reask", action="store_true", help="with --api: re-send only the laws in data/reask.json with the added instruction")
    ap.add_argument("--canary", type=int, metavar="N", help="with --api: N real laws synchronously, usage and cost projection")
    ap.add_argument("--session", type=int, action="append", help="restrict to a session (repeatable); default all nine")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--pilot-only", action="store_true", help="restrict to the 52 audited pilot laws (data/bills.json signed)")
    ap.add_argument("--per-session", action="store_true", help="write data/duties/{Y}.json, data/powers/{Y}.json instead of single files")
    a = ap.parse_args()
    full = bool(a.api or a.per_session or a.session)
    sessions = (a.session or PILOT_SESSIONS) if full else None
    todo, deferred = load_todo(sessions)
    if a.pilot_only:
        pb = json.load(open(DATA / "bills.json"))
        pb = pb.get("bills", pb) if isinstance(pb, dict) else pb
        keys = {"%d-%s" % (b["session"], b["print_no"]) for b in pb if b.get("signed")}
        keys |= {"%d-%s" % (b["session"], b.get("base_print_no") or b["print_no"]) for b in pb if b.get("signed")}
        todo = [(l, t) for l, t in todo if l["key"] in keys]
        print("pilot-only: %d of the audited pilot laws have text" % len(todo))
    if a.limit:
        todo = todo[:a.limit]
    laws = [l for l, _ in todo] + [l for l in signed_laws(sessions) if l["key"] in {d["key"] for d in deferred}]
    EFFECTIVE = effective_table([l for l, _ in todo])
    if full:
        (DATA / "effective_dates").mkdir(exist_ok=True)
        for y in sorted({l["session"] for l, _ in todo}):
            json.dump({k: v for k, v in EFFECTIVE.items() if k.startswith("%d-" % y)}, open(DATA / "effective_dates" / ("%d.json" % y), "w"), separators=(",", ":"))
    else:
        json.dump(EFFECTIVE, open(DATA / "effective_dates.json", "w"), indent=1)
    json.dump({"rule": "signed laws whose marked text exceeds %d characters (budget bills, recodifications) wait for a later phase" % MAX_CHARS,
               "laws": deferred}, open(DATA / "deferred_long.json", "w"), indent=1)
    if a.api:
        API_DIR.mkdir(parents=True, exist_ok=True)
        print("laws with text: %d (deferred long %d)" % (len(todo), len(deferred)))
        if a.canary:
            return run_canary(pending(todo) or todo, a.canary)
        if a.reask:
            flagged = load_reask()
            return run_batches(todo, reask=flagged)
        if a.batch or a.resume:
            return run_batches(todo, resume_only=a.resume and not a.batch)
        sys.exit("--api needs --canary N, --batch or --resume")
    if a.emit_packets:
        d = Path(a.emit_packets)
        (d / "results").mkdir(parents=True, exist_ok=True)
        eo.emit_packets(d, todo, fixed_prompt=FIXED_PROMPT, render=render_variable_prompt, schema=SCHEMA)
        sizes = sorted(os.path.getsize(d / (l["key"] + ".txt")) for l, _ in todo)
        print("packets %d (signed laws %d, deferred long %d); bytes min %d median %d max %d" % (len(todo), len(laws), len(deferred), sizes[0], sizes[len(sizes) // 2], sizes[-1]))
        return
    if a.ingest:
        d = Path(a.ingest)
        done, left = eo.ingest_packets(d, todo, LOOKUP, BY_CANON, "claude-sonnet-5" if full else "max-subagent", writer=write_cache, prepare=prepare, schema=SCHEMA)
        merged = merge_reask(todo, d / "results", "claude-sonnet-5" if full else "max-subagent")
        duties, powers, excluded = build_records([l for l, _ in todo])
        stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        reask = build_reask(todo, duties, powers)
        print("re-ask merged %d records; recall checks flag %d laws" % (merged, len(reask)))
        sess = sorted({l["session"] for l, _ in todo})
        for sub_dir in ("reask", "dropped"):
            (DATA / sub_dir).mkdir(exist_ok=True)
        for y in (sess if full else []):               # per-session files: an ingest of one session never overwrites another's
            json.dump({"generated_at": stamp, "laws": {k: v for k, v in reask.items() if k.startswith("%d-" % y)}}, open(DATA / "reask" / ("%d.json" % y), "w"), indent=1, ensure_ascii=False)
            json.dump({"generated_at": stamp, "dropped": [d for d in DROPPED if (d.get("matter_id") or "").startswith("%d-" % y)]}, open(DATA / "dropped" / ("%d.json" % y), "w"), indent=1, ensure_ascii=False)
        if full:     # one file would pass ~25 MB: per-session files, the single store (the pilot laws are in their session's file)
            (DATA / "duties").mkdir(exist_ok=True); (DATA / "powers").mkdir(exist_ok=True)
            for y in sess:
                json.dump({"generated_at": stamp, "obligations": [o for o in duties if o["session"] == y]}, open(DATA / "duties" / ("%d.json" % y), "w"), separators=(",", ":"), ensure_ascii=False)
                json.dump({"generated_at": stamp, "powers": [o for o in powers if o["session"] == y]}, open(DATA / "powers" / ("%d.json" % y), "w"), separators=(",", ":"), ensure_ascii=False)
        else:        # pilot-only tests write the single legacy files
            json.dump({"generated_at": stamp, "obligations": duties}, open(DATA / "duties.json", "w"), indent=1, ensure_ascii=False)
            json.dump({"generated_at": stamp, "powers": powers}, open(DATA / "powers.json", "w"), indent=1, ensure_ascii=False)
        print("ingested %d laws, %d left (missing or invalid result); duties %d, powers %d, excluded (private or neither) %d" % (len(done), len(left), len(duties), len(powers), excluded))
        print("rules applied:", json.dumps(STATS, sort_keys=True))


if __name__ == "__main__":
    main()
