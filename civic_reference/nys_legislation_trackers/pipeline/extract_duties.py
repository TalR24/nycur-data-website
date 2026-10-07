#!/usr/bin/env python3
"""NYS Legislation Trackers, phase 2: duties and powers of State and local government from signed laws.

Runs on the Max plan as PACKETS, no API key and no model call:
    python3 extract_duties.py --emit-packets DIR   one prompt file per signed law (laws over 120,000 characters are
                                                   listed in data/deferred_long.json instead)
    (subagents answer each packet into DIR/results/<key>.json)
    python3 extract_duties.py --ingest DIR         validate, resolve agencies, write data/duties.json + data/powers.json

Reuses the Council extractor (civic_reference/legislation_implementation_tracker/pipeline/extract_obligations.py): its
schema, duty/power/neither definitions, quote checks, deadline arithmetic, packet emit/ingest and agency matcher. Only the
prompt wording (state and local government instead of NYC agencies) and the agency crosswalk are NYS-specific.
"""
import argparse, json, os, re, sys, time
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

MAX_CHARS = 120_000
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
    return bool(GRANT_WORD.search(quote or "")) and not MANDATORY.search(q)


CAP_RE = re.compile(r"\b(?:shall not|may not|must not)\b[^.;]{0,100}\b(?:issue|exceed)\b|\baggregate principal amount exceeding\b|\bno\b[^.;]{0,60}\b(?:bonds?|notes?|obligations?)\b[^.;]{0,120}\b(?:on or after|after)\b", re.I)
STATE_MARK = re.compile(r"\b(state|department of taxation and finance|commissioner of taxation|tax commission)\b", re.I)
TRIGGER = re.compile(r"\b(upon|whenever|when|promptly|as soon as|as needed|until|if|unless|in response to)\b|\breceipt of\b|\breceives?\b|\bat the request\b", re.I)
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
            if name and not GENERIC_LEAD.match(name.split()[0]):
                units.add((LOCAL_GROUPS[kind], _title("%s of %s" % (kind, name))))
    if len(units) > 1:
        units = {u for u in units if u[0] != "Counties"} or units
    return units.pop() if len(units) == 1 else None


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
            attach_jurisdiction(o)
            # 5. DTF only when the quote or actor names the State; a locality's tax office is the locality
            if o.get("agency") == "DTF" and not STATE_MARK.search((o.get("quote") or "") + " " + (o.get("actor_raw") or "")):
                ll = law_locality(text, law["title"])
                if ll:
                    o.update(agency=ll[0], agency_full=ll[0], agency_matched=True, jurisdiction="local", agency_org_type="local government group", agency_group=ll[0], agency_unit=ll[1])
                    bump("dtf_to_locality")
            quote = o.get("quote") or ""
            o["extends_existing"] = bool(res.get("extends_model", {}).get(o["obligation_id"])) or extends_by_text(quote, text)
            if not o["extends_existing"] and relocated(quote, text):          # D4
                o["extends_existing"] = True; bump("d4_relocated")
            # 3. a grant with no mandatory verb is a power
            if kind == "duty" and grant_only(quote) and not CAP_RE.search(quote):
                kind = "power"; o["kind_adjusted"] = "grant_only"; bump("grant_only_to_power")
            # 4. D3: bond caps and issuance cutoffs are duties (a prohibition on the actor) with no deadline
            if CAP_RE.search(quote) and kind in ("duty", "power"):
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
                   "effective_date": sec_date, "effective_rule": eff["rule"] if sec_src == "law" else "section_" + sec_src, "law_expires_date": eff["expires_date"],
                   "openleg_url": law["openleg_url"], "extraction_model": res.get("model")}
            (law_p if kind == "power" else law_d).append(rec)
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


def build_request(law, text, ttl=None):
    """(custom_id, params): fixed instructions as the cached first block, the law text last. ttl '1h' inside batches."""
    import claude_batch
    content = claude_batch.cached_content(FIXED_PROMPT, render_variable_prompt(law, text), ttl=ttl)
    return law["key"], {"model": MODEL, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": content}],
                        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}}}


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


def run_batches(todo, resume_only=False, max_wait_s=300 * 60):
    """Submit every unanswered law as Message Batches (chunked), then collect. A later call resumes pending chunks."""
    import claude_batch
    client = _client()
    state = json.loads(BATCH_STATE.read_text()) if BATCH_STATE.exists() else {"chunks": []}
    if not resume_only:
        in_flight = {k for c in state["chunks"] for k in c["keys"]}
        todo_new = [(l, t) for l, t in pending(todo) if l["key"] not in in_flight]
        reqs = [build_request(l, t, ttl="1h") for l, t in todo_new]
        for cs in chunks_of(reqs):
            n = len(state["chunks"]) + 1
            sp = HERE / ("batch_state_%03d.json" % n)
            claude_batch.run_batch(client, cs, sp, max_wait_s=0)           # submit and return at once
            state["chunks"].append({"state": sp.name, "keys": [c for c, _ in cs]})
            BATCH_STATE.write_text(json.dumps(state, indent=1))
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
        BATCH_STATE.write_text(json.dumps(state, indent=1))
    else:
        BATCH_STATE.unlink(missing_ok=True)
    print(usage.line())
    print("answered %d of %d laws; %d batch chunks still pending" % (len(todo) - len(pending(todo)), len(todo), len(left_chunks)))


def main():
    global EFFECTIVE
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-packets", metavar="DIR")
    ap.add_argument("--ingest", metavar="DIR")
    ap.add_argument("--api", action="store_true", help="call the Anthropic API (billed): needs --canary N, --batch or --resume")
    ap.add_argument("--batch", action="store_true", help="with --api: submit the unanswered laws as Message Batches")
    ap.add_argument("--resume", action="store_true", help="with --api: collect pending batches only")
    ap.add_argument("--canary", type=int, metavar="N", help="with --api: N real laws synchronously, usage and cost projection")
    ap.add_argument("--session", type=int, action="append", help="restrict to a session (repeatable); default all nine")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--per-session", action="store_true", help="write data/duties/{Y}.json, data/powers/{Y}.json instead of single files")
    a = ap.parse_args()
    full = bool(a.api or a.per_session or a.session)
    sessions = (a.session or PILOT_SESSIONS) if full else None
    todo, deferred = load_todo(sessions)
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
        duties, powers, excluded = build_records([l for l, _ in todo])
        stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        if full:     # one file would pass ~25 MB: per-session files
            (DATA / "duties").mkdir(exist_ok=True); (DATA / "powers").mkdir(exist_ok=True)
            for y in sorted({l["session"] for l, _ in todo}):
                json.dump({"generated_at": stamp, "obligations": [o for o in duties if o["session"] == y]}, open(DATA / "duties" / ("%d.json" % y), "w"), separators=(",", ":"), ensure_ascii=False)
                json.dump({"generated_at": stamp, "powers": [o for o in powers if o["session"] == y]}, open(DATA / "powers" / ("%d.json" % y), "w"), separators=(",", ":"), ensure_ascii=False)
        else:
            json.dump({"generated_at": stamp, "obligations": duties}, open(DATA / "duties.json", "w"), indent=1, ensure_ascii=False)
            json.dump({"generated_at": stamp, "powers": powers}, open(DATA / "powers.json", "w"), indent=1, ensure_ascii=False)
        print("ingested %d laws, %d left (missing or invalid result); duties %d, powers %d, excluded (private or neither) %d" % (len(done), len(left), len(duties), len(powers), excluded))
        print("rules applied:", json.dumps(STATS, sort_keys=True))


if __name__ == "__main__":
    main()
