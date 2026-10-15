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
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
COUNCIL = HERE.parent.parent / "legislation_implementation_tracker"
sys.path.insert(0, str(COUNCIL / "pipeline"))
sys.path.insert(0, str(HERE))
import extract_obligations as eo  # noqa: E402
import law_definitions  # noqa: E402
from effective_date import parse_effective  # noqa: E402
import effective_date as efd  # noqa: E402
import chapter_lookup  # noqa: E402
import agency_resolve_nys  # noqa: E402
from validate_duties import PASSIVE_SUBJECT  # noqa: E402  (J1 reuses the validator's detection)

MAX_CHARS = 120_000
REASK_MANUAL = HERE / "reask_manual.json"
REASK_MANUAL_DATA = DATA / "reask_manual.json"      # J7: confirmed audit misses by night, merged into data/reask on every ingest
TEXT_MARKED = HERE / "cache" / "text_marked"
EXTRACTED = HERE / "cache" / "extracted"
LOCAL_GROUPS = {"town": "Towns", "village": "Villages", "city": "Cities", "county": "Counties"}
NYC_MARKERS = re.compile(r"city of new york|new york city|\bnyc\b|mayor of the city|council of the city", re.I)


# ── Prompt: the Council prompt with NYC wording swapped for state and local government ─────────────────────────────
def _sub(s, old, new):
    if old not in s:
        raise SystemExit("Council prompt no longer contains: %r (update extract_duties.py)" % old[:60])
    return s.replace(old, new)


PROMPT_V2_RULES = HERE / "prompt_v2_rules.txt"


def build_prompt(version=1):
    """version 1 is the production prompt; version 2 adds the bullets of prompt_v2_rules.txt before '- Do not invent obligations'."""
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
    if version == 2:
        rules += [ln.rstrip() for ln in PROMPT_V2_RULES.read_text().splitlines() if ln.strip()]
    elif version != 1:
        raise SystemExit("unknown prompt version %r" % (version,))
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
SCHEMA_V2 = copy.deepcopy(SCHEMA)                   # prompt v2: optional top-level list of sentences the model judged not to be records
SCHEMA_V2["properties"]["excluded_sentences"] = {"type": "array", "items": {"type": "object", "properties": {"start": {"type": "string"}, "reason": {"type": "string"}},
                                                                            "required": ["start", "reason"], "additionalProperties": False}}
EXCLUDED_COUNT = {}                                 # law key -> number of excluded_sentences the model listed (stored on the cache file, otherwise ignored)


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
        if "take effect" not in text and (HERE / "cache" / "text" / (law["key"] + ".txt")).exists():       # M19: the marked text may end before the act clause
            full = (HERE / "cache" / "text" / (law["key"] + ".txt")).read_text()
            if "take effect" in full:
                text = full
        tab[law["key"]] = parse_effective(text, law["signed_date"], resolver=chapter_lookup.resolve)
    return tab


def prepare(law, raw):
    """Replace the model's effective clause with the deterministic parse (the model still answers the schema field)."""
    if "excluded_sentences" in raw:
        EXCLUDED_COUNT[law["key"]] = EXCLUDED_COUNT.get(law["key"], 0) + len(raw["excluded_sentences"])
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


LOCAL_ACTOR_NOUN = re.compile(r"\b(?:town|city|village|county|counties|school district|district|municipalit\w*|local board|mayor|supervisors?|legislature|assessors?|clerk|treasurer)\b", re.I)
STATE_GENERIC_ACTOR = re.compile(r"^(?:the |such |said |each |any )?(?:authority|department|commissioner|division|office|superintendent)$", re.I)


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
        # M2 (Oct 10 2026): the quote's locality fills the actor only when the actor text names a local-government noun, or is unresolved
        # without a generic State officer noun; "the authority" / "the department" / "the commissioner" never takes a locality from the quote
        local_noun = any(LOCAL_OFFICERS.search(x) or LOCAL_ACTOR_NOUN.search(x) for x in actor_text)
        state_generic = bool(STATE_GENERIC_ACTOR.match(re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip())))
        if local_noun or (not o.get("agency_matched") and not state_generic):
            loc = named_locality(o.get("quote") or "", o.get("action_summary") or "")
        elif state_generic:
            bump("m2_state_actor_keeps_state")
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


# M35 (Oct 15 2026): 'authorized and directed' / 'empowered and directed' is a command to the actor, a duty, whatever the grant words around it.
AUTH_DIRECTED = re.compile(r"\b(?:authorized|empowered)\s+and\s+directed\b|\bdirected\s+and\s+(?:authorized|empowered)\b", re.I)


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
                     r"|\b(?:after|following) (?:the )?(?:receipt|filing|submission)\b|\bin the event\b|\bon the date of (?:its |the )?(?:dissolution|termination)\b"
                     r"|\b(?:prior to|before) submitting\b|\b(?:wants?|wish(?:es)?|seeks?|elects?|chooses?) to\b|\bthat applies\b|\bprior to (?:the )?(?:filing|approval|issuance)\b", re.I)
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


# Oct 15 2026 (prompt v2 go-live): the act's effective-date/sunset clause is never a record, and a government body that must pay a cost is a duty
def _act_words(s):
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


ACT_CLAUSE_START = re.compile(r"^(?:this act shall take effect|this act shall expire|provided,? however,? that the amendments made by section)")


def is_act_clause_quote(quote, act_clause=None):
    """True when the quote begins with the act clause's opening words or is contained in the law's own act_clause text."""
    q = _act_words(quote)
    if not q:
        return False
    if ACT_CLAUSE_START.match(" ".join(re.findall(r"[a-z0-9,]+", (quote or "").lower()))) or q.startswith(("this act shall take effect", "this act shall expire")):
        return True
    a = _act_words(act_clause)
    return len(q) >= 25 and q in a


GOV_NOUN = r"(?:village|town|city|county|state|school district|district|municipality|authority|department|board|commissioner|comptroller|office|division|agency|corporation|governor|director|superintendent|treasurer|legislature|college|university)"
COST_DUTY = re.compile(r"\b" + GOV_NOUN + r"\b(?:(?!\bshall\b)[^.;]){0,80}?\bshall (?:pay|bear|reimburse|be borne by)\b", re.I)


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


PLACE_EXCEPTION = re.compile(r"^(?:\([\w-]{1,6}\)|\d+\.|\W)*notwithstanding the provisions of (?:paragraph|subdivision|section)\b[^,]{0,80},.*\bwithin (?:two hundred|200) feet\b", re.I | re.S)
STATE_UNIT_EXCLUDED = {"Counties", "Cities", "Towns", "Villages", "School districts", "Boards of elections", "Municipalities", "Municipalities (all)",
                       "Fire districts", "Library districts", "Public libraries", "Social services districts", "Sheriffs", "BOCES", "Local agencies and authorities"}
_UNIT_UPPER = {"ny": "NY", "nys": "NYS", "nyc": "NYC", "ii": "II", "iii": "III"}


def unit_title(s):
    """M5: the model's unit name in title case ('start-up ny approval board' -> 'Start-up NY Approval Board'); small words stay lower."""
    small = {"of", "the", "and", "in", "on", "for", "to", "a"}
    out = []
    for i, w in enumerate(re.sub(r"\s+", " ", (s or "").strip(" .,;")).split()):
        lw = w.lower()
        out.append(_UNIT_UPPER.get(lw) or (w if (i and lw in small) else w[:1].upper() + w[1:]))
    return " ".join(out)


def post_amendment(seg):
    """A text segment as the law reads after the amendment: [deleted] matter and {{ }} markers removed, spacing tidied."""
    seg = re.sub(r"\{\{|\}\}", "", _mask_deleted(seg))
    seg = re.sub(r"\s+", " ", seg).strip()
    return re.sub(r"\s+([,;.:])", r"\1", seg)


AMEND_INSTR = re.compile(r"\b(?:is|are) (?:hereby )?(?:amended|repealed|renumbered)\b|\bamended by (?:adding|inserting|striking|renumbering)\b", re.I)


EXEMPT_SENT = re.compile(r"\bshall\s+not\s+(?:apply|be\s+applicable|be\s+construed)\b|\bshall\s+not\s+apply\b|\bexcept\b|\bnothing\s+in\s+this\b|\b(?:does|do)\s+not\s+apply\b", re.I)
RELOC_MODAL = re.compile(r"\b(?:shall|may|must|is\s+authorized|are\s+authorized|is\s+hereby\s+authorized)\b", re.I)
_ACTOR_STOP = {"the", "of", "and", "new", "york", "state", "city", "such", "said", "each", "any", "a", "an", "office", "department"}


def _actor_head(actor_raw):
    return [w for w in re.findall(r"[a-z]+", (actor_raw or "").lower()) if w not in _ACTOR_STOP and len(w) > 3]


def relocate_quote(quote, text, actor_raw=None):
    """M6 (Oct 10 2026). An extension record whose quote sits in reprinted unchanged text: returns the verbatim post-amendment sentence that
    holds the nearest {{ }} span of the same act section, or None (no marker, quote already overlaps new matter, or no braced span in the section)."""
    if "{{" not in text:
        return None
    sp = locate_span(quote, text)
    if not sp or in_braces(sp[0], sp[1], text):
        return None
    hdr, sec = section_of_span(sp, text)
    if not sec:
        return None
    start = text.find(sec)
    near = [(min(abs(x - sp[1]), abs(y - sp[0])), x, y) for x, y in braced_intervals(text) if start <= x < start + len(sec)]
    if not near:
        return None
    heads = _actor_head(actor_raw)
    for _, x, y in sorted(near):         # M23 (Oct 13 2026): nearest first, skipping a braced span inside an amending instruction
        sent, (sl, sr) = context_sentence((x, y), text)
        if AMEND_INSTR.search(sent):
            continue
        new = post_amendment(sent)
        new = re.sub(r"^(?:\d+(?:-\w+)?\.\s+)", "", new)
        # M26 (Oct 13 2026): never an exemption or applicability sentence; prefer one with a modal or the actor's head noun
        if EXEMPT_SENT.search(new) or not (RELOC_MODAL.search(new) or any(h in new.lower() for h in heads)):
            continue
        vm = re.search(r"\b(?:shall|may|must|is\s+authorized\s+to)\s+(?:not\s+)?(?:be\s+)?([a-z]{4,})", quote or "", re.I)
        if vm and vm.group(1).lower()[:5] not in new.lower():        # the original operative verb ('may deny') must survive in the new sentence
            continue
        if len(new) >= 20 and locate_span(new, text):
            return new
    return None


_DAY_W = r"(?:(?:twenty|thirty)[\s-]*)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth)|twentieth|thirtieth|\d{1,2}(?:st|nd|rd|th)?"
SUBMIT_DATE = re.compile(r"\bshall\s+submit\s+(?:such|the\s+(?:final\s+)?)\s*(?:study|report|findings)\b[^.]*?(?:(?:on\s+or\s+before|no\s+later\s+than|not\s+later\s+than)\s+)((?:"
                         + efd.MONTH_RE + r")\s+(" + _DAY_W + r"),?\s+((?:two\s+thousand(?:\s+(?:and\s+)?[a-z-]+){0,2})|\d{4}))", re.I)
NEXT_SUBDIV = re.compile(r"\n\n\s*(?:\{\{)?(?:§|Section)\s*\d+\.|\n\n\s*(?:\{\{)?\d+(?:-\w+)?\.\s")


def _wordy_date(month, day, year):
    mo = efd.MONTHS.get(month.lower())
    d = int(re.sub(r"\D", "", day)) if day[0].isdigit() else efd.words_to_int(day)
    if year.isdigit():
        y = int(year)
    else:
        rest = re.sub(r"^two\s+thousand\s*(?:and\s+)?", "", year.lower()).strip()
        n = efd.words_to_int(rest) if rest else 0
        y = 2000 + n if n is not None else None
    try:
        return efd.date(y, mo, d).isoformat() if (mo and d and y) else None
    except (ValueError, TypeError):
        return None


def study_submission_date(o, text):
    """M29 (Oct 13 2026). A study or report record with no deadline whose own subdivision, in the following sentences (up to six, same subdivision), says 'The department
    shall submit such study to the governor ... on or before November first, two thousand sixteen': returns (ISO date, phrase) or None."""
    if o.get("deliverable_type") not in ("study or audit", "report") or o.get("deadline_kind") not in (None, "none"):
        return None
    sp = locate_span(o.get("quote") or "", text)
    if not sp:
        return None
    _, (sl, sr) = context_sentence(sp, text)
    tail = text[sr:sr + 4000]
    cut = NEXT_SUBDIV.search(tail)
    tail = post_amendment(tail[:cut.start()] if cut else tail)
    sents = re.split(r"(?<=[.;])\s+(?=[A-Z(])", tail)[:6]
    for sent in sents:
        m = SUBMIT_DATE.search(sent)
        if m:
            iso = _wordy_date(m.group(1).split()[0], m.group(2), m.group(3).strip())
            if iso:
                return iso, re.search(r"(?:on\s+or\s+before|no\s+later\s+than|not\s+later\s+than)\s+.*$", m.group(0), re.I).group(0)
    return None


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


BENEFIT_RE = re.compile(r"\b(?:shall|will)\s+(?:also\s+)?(?:receive|be eligible to receive|be eligible for|be entitled to|be exempt(?:ed)?)\b", re.I)


PASSIVE_BENEFIT = re.compile(r"\binterest\s+shall\s+be\s+allowed\b|\bshall\s+not\s+be\s+required\s+to\s+pay\b|\bshall\s+be\s+credited\s+(?:with|for)\b|\bshall\s+be\s+reimbursed\b", re.I)


AWARDED_BENEFIT = re.compile(r"\bshall\s+be\s+awarded\b(?!\s+(?:by|pursuant|in\s+accordance))", re.I)


SALARY_INCREASE = re.compile(r"\b(?:salary|salaries|compensation|wages?)\b[^.;]{0,200}?\bshall\s+be\s+increased\b|\bshall\s+receive\s+an?\s+(?:\w+\s+)?salary\s+increase\b", re.I)
CONDITION_PRECEDENT = re.compile(r"\bshall\s+not\s+be\s+(?:implemented|paid|effective|operative)\b[^.;]{0,60}?\buntil\b[^.;]{0,400}?\b(?:shall|have|has)\s+(?:have\s+)?(?:delivered|certified|approved|filed|submitted|received|issued)\b", re.I)
# M36 (Oct 15 2026): 'No expenditure may be made ... until a certificate ...', 'shall not occur until', 'shall not take place until' are conditions on another provision
CONDITION_PRECEDENT_M36 = re.compile(r"\bno\s+(?:expenditure|payment|disbursement)s?\s+(?:may|shall)\s+be\s+made\b[^.;]{0,300}?\buntil\b|\bshall\s+not\s+(?:occur|take\s+place)\s+until\b", re.I)


def salary_entitlement(q):
    """M32 (Oct 14 2026): 'the basic annual salary of officers and employees ... shall be increased by two percent': the salary is the
    subject, no government actor precedes the modal and none is named as the one who increases it."""
    m = SALARY_INCREASE.search(q or "")
    if not m or GOV_ACTOR.search(q[:m.start()]) or GOV_ACTOR.search(q[m.start():m.end()].replace("officers", "").replace("employees", "")):
        return False
    return not re.match(r"\s*by\s+(?:the|such|said)\s", q[m.end():m.end() + 20], re.I)


def benefit_entitlement(o, q):
    """M13 (Oct 11 2026). 'Eligible dwelling units ... shall receive a partial abatement', 'such property shall be exempt', 'the owner shall be
    entitled to': the grammatical subject is the beneficiary. Dropped when no government noun precedes the modal and the record's
    actor_raw does not appear in the quote."""
    if salary_entitlement(q):
        return True
    am_ = AWARDED_BENEFIT.search(q or "")      # M27: 'shall be awarded' to a beneficiary; 'awarded by the board' / 'contracts shall be awarded' is the board's act
    if am_ and not GOV_ACTOR.search(q[:am_.start()]) and not re.search(r"\bcontracts?\b", q[:am_.start()], re.I):
        actor0 = re.sub(r"^(?:the|a|an|such|each|any)\s+", "", (o.get("actor_raw") or "").strip().lower())
        if not actor0 or actor0 not in q.lower():
            return True
    pm = PASSIVE_BENEFIT.search(q or "")      # M22 (Oct 13 2026): 'Interest shall be allowed', 'shall not be required to pay': the subject is an amount or a beneficiary
    if pm and not GOV_ACTOR.search(q[:pm.start()]):
        actor0 = re.sub(r"^(?:the|a|an|such|each|any)\s+", "", (o.get("actor_raw") or "").strip().lower())
        # M27 (Oct 13 2026): only an actor_raw named BEFORE the modal is the subject; 'adopted by the village of Penn Yan' after it is not
        if not GOV_ACTOR.search(actor0) or actor0 not in q[:pm.start()].lower():
            return True
    m = BENEFIT_RE.search(q or "")
    if not m or GOV_ACTOR.search(q[:m.start()]) or len(re.findall(r"[A-Za-z]+", q[:m.start()])) < 2:      # a quote that starts at the modal names no subject: the record stays
        return False
    if GRANT_WORD.search(q[:m.start()]) or re.search(r"\b(?:notice|training|instruction)\b", q[m.end():m.end() + 60], re.I):
        return False        # an authorization comes first ('is hereby authorized ... any increase shall be exempt'), or receiving notice or training is the government's duty to give
    actor = re.sub(r"^(?:the|a|an|such|each|any)\s+", "", (o.get("actor_raw") or "").strip().lower())
    return bool(actor) and actor not in q.lower()


HEREBY_AUTH = re.compile(r"\bhereby\s+(?:further\s+)?authoriz(?:es|ed)\b", re.I)
HEREBY_AUTHORIZES = re.compile(r"\bhereby\s+(?:further\s+)?authorizes\s+((?:the|such|said|each)\s+[\w'-]+(?:\s+[\w'-]+){0,3}?)(?=\s+(?:and|to)\b|[,.;]|$)", re.I)
BDC_NOTIFY = re.compile(r"shall\s+notify\s+the\s+legislative\s+bill\s+drafting\s+commission", re.I)


def gate_record(o, text, has_markers):
    """Returns (rule, reason) when the record must be dropped, else None. Rules 1-3 of phase 3b."""
    if not o.get("quote_verified"):
        return "unverified_quote", "quote not found in the law text"
    q = o.get("quote") or ""
    if BDC_NOTIFY.search(q):
        return "act_clause_boilerplate", "act-clause notice to the legislative bill drafting commission, a publishing courtesy that binds no program"
    if CONDITION_PRECEDENT.search(q) or (APPLY_M36 and CONDITION_PRECEDENT_M36.search(q)):
        return "condition_precedent", "an implementation precondition ('shall not be implemented until X shall have delivered ...'): a condition on another provision, not a duty of the certifying officials"
    if benefit_entitlement(o, q):
        return "benefit_entitlement", "the subject is the beneficiary (it receives, is entitled to or is exempt from), not a government actor"
    span = locate_span(q, text)
    # 3. no-record classes
    if STRONG_EXEMPT_RE.search(q) or (EXEMPT_RE.search(q) and not MANDATORY.search(EXEMPT_RE.sub(" ", q))):
        return "exemption_or_applicability", "exemption, residency or refund-review applicability clause, binds no government actor"
    if span:
        hdr, sec = section_of_span(span, text)
        if sec and re.search(r"\b11\.00\b[^.]{0,80}local finance law|local finance law[^.]{0,80}\b11\.00\b", hdr + " " + sec[:400], re.I):
            return "local_finance_useful_life", "Local Finance Law section 11.00 period of probable usefulness"
        sent, (sl, sr) = context_sentence(span, text)
        if not VERBISH.search(q) and not VERBISH.search(sent) and not (WILL_DUTY.search(q) or WILL_DUTY.search(sent)):      # M11: 'the director will report' is a duty
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
                elif HEREBY_AUTH.search(q):
                    # M28 (Oct 13 2026): 'the state of New York hereby authorizes the city ...' / 'the board is hereby authorized': a power of the
                    # authorized body, never a designation without an actor
                    o["kind_from_lead_in"] = "power"
                    am = HEREBY_AUTHORIZES.search(q)
                    if am:
                        o["actor_raw"] = am.group(1).strip()
                    o["rescued_hereby_authorizes"] = True; bump("m28_hereby_authorizes_power")
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


_NAME_STOP = {"New", "York", "State", "Tier", "Law", "Section", "Article", "Act", "Department", "Authority", "Board", "City", "County", "Town", "Village", "The", "Such", "Upon",
              "Commissioner", "Comptroller", "Governor", "Court", "Education", "Public", "Service", "Services", "Chapter", "Laws", "Code", "Fund", "School", "District", "Office"}


def proper_names(q):
    """Capitalised words that do not start a sentence and are not generic institution words (personal and place names)."""
    toks = (q or "").split()
    out = set()
    for i, t in enumerate(toks):
        w = re.sub(r"[^A-Za-z'-]", "", t)
        if i and re.fullmatch(r"[A-Z][a-z]{2,}", w) and w not in _NAME_STOP and not re.search(r"[.;:]$", toks[i - 1]):
            out.add(w)
    return out


MONEY_RE = re.compile(r"\$\s?[\d,]+(?:\.\d+)?(?:\s+(?:million|billion|thousand))?", re.I)
FUND_RE = re.compile(r"\b(?:[A-Z][\w'-]*\s+){1,5}Fund\b")


def money_and_funds(q):
    """M41 (Oct 15 2026): dollar amounts and capitalised fund names in a quote."""
    q = q or ""
    return ({re.sub(r"[\s,]", "", m.group(0)).lower() for m in MONEY_RE.finditer(q)}
            | {re.sub(r"^(?:The|Such|Said|Of|From|To|In)\s+", "", m.group(0)) for m in FUND_RE.finditer(q)})


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
    na, nb = proper_names(a.get("quote")), proper_names(b.get("quote"))
    if APPLY_M31 and (na - nb) and (nb - na):          # M31 (Oct 14 2026): parallel provisions for different named persons or places
        bump("m31_distinct_names"); return True
    if APPLY_M41:           # M41 (Oct 15 2026): parallel appropriation directives that differ in amount, fund or object
        ma, mb = money_and_funds(a.get("quote")), money_and_funds(b.get("quote"))
        if (ma - mb) and (mb - ma):
            bump("m41_distinct_amounts"); return True
        if re.search(r"\bappropriation\b", (a.get("quote") or "") + " " + (b.get("quote") or ""), re.I):
            sa, sb = {w for w in _words(a.get("quote")) if len(w) >= 6 and not w.isdigit()} - _DIFF_STOP - _NUMW - _DATEW, {w for w in _words(b.get("quote")) if len(w) >= 6 and not w.isdigit()} - _DIFF_STOP - _NUMW - _DATEW
            if (sa - sb) and (sb - sa) and len(sa - sb) <= 3 and len(sb - sa) <= 3:
                bump("m41_distinct_appropriation_object"); return True
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
# M11 (Oct 11 2026): "will" + report/submit/provide/publish/notify/post with a government noun as the subject is a duty modal
WILL_DUTY = re.compile(r"\b(?:the|a|an|each|such)\s+(?:[\w'-]+\s+){0,3}?(?:" + GOV_ACTOR.pattern[3:-3] + r")(?:\s+of\s+(?:the\s+)?[\w'-]+(?:\s+[\w'-]+){0,3}?)?\s+will\s+(?:also\s+)?(?:report|submit|provide|publish|notify|post)\b", re.I)
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
    # J5 (Oct 10 2026): a list entry or designation dropped for having no actor, whose own words name a government body or officer
    des = [d.get("quote") or "" for d in dropped if d.get("rule") == "designation_no_actor"
           and (DROPPED_GOV_SUBJECT.search(d.get("quote") or "") or re.match(r"\W*to\s", d.get("quote") or "", re.I))]
    if des:
        flags.append({"check": "dropped_designation_with_actor", "detail": "%d dropped list entries or designations that name a government body or officer" % len(des), "sentences": des[:12]})
    # J6: an applicability sentence dropped by the exemption gate whose new matter is a date or number (a sunset extension, not an exemption)
    ext = []
    for d in dropped:
        if d.get("rule") != "exemption_or_applicability":
            continue
        sp = locate_span(d.get("quote") or "", text)
        if not sp:
            continue
        sent = context_sentence(sp, text)[0]
        blocks = [m.group(1) for m in re.finditer(r"\{\{(.*?)\}\}", sent, re.S)]
        if blocks and APPLIES_RE.search(sent) and all(_only_extension(b) for b in blocks):
            ext.append(d.get("quote") or "")
    if ext:
        flags.append({"check": "exemption_sunset_extension", "detail": "%d dropped applicability sentences whose new matter is only a date or number" % len(ext), "sentences": ext[:12]})
    return flags


COMPOUND_LOCAL = re.compile(r"\b(?:town|city|village|county)\b[^;]*?\band\b[^;]*?\b(?:district|authority|agency|corporation)\b", re.I)
PRE_2017 = range(2009, 2017)
APPLY_M31 = True
APPLY_M35 = APPLY_M36 = APPLY_M37 = APPLY_M38 = APPLY_M39 = APPLY_M41 = APPLY_J15 = True        # Oct 15 2026 fixes; each can be switched off on its own
DROPPED_GOV_SUBJECT = re.compile(r"\b(?:trustees?|board|commissioner|university|department|authority|council|office)\b", re.I)
APPLIES_RE = re.compile(r"\bshall (?:not )?(?:only )?(?:be applicable|apply)\b|\b(?:does|do) not apply\b", re.I)


APPROVER_BEFORE = re.compile(r"(?:\bapproved\s+by|\bsubject\s+to\s+the\s+(?:prior\s+|written\s+)?approval\s+of|\bwith\s+the\s+(?:prior\s+|written\s+)?approval\s+of|\bupon\s+(?:the\s+)?approval\s+by)\s+(?:the\s+)?$", re.I)


def approver_only_actor(r):
    """J9: every mention of the record's actor_raw in its quote follows an approval phrase."""
    actor = re.sub(r"^(?:the|a|an|such|each|any)\s+", "", (r.get("actor_raw") or "").strip().lower())
    q = r.get("quote") or ""
    if len(actor) < 4:
        return False
    low = q.lower()
    hits = [m.start() for m in re.finditer(re.escape(actor), low)]
    return bool(hits) and all(APPROVER_BEFORE.search(q[max(0, h - 40):h]) for h in hits)


AID_RECIPIENT = re.compile(r"\bshall\s+be\s+(?:awarded|apportioned\s+and\s+paid|paid)\b(?!\s+(?:over|into|out|by|through|in\s+advance|on\s+the\s+(?:audit|warrant)))|\bshall\s+(?:also\s+)?receive\b[^.;]{0,120}\b(?:aid|payments?|grants?)\b", re.I)


def aid_recipient_actor(r):
    """J11 (Oct 13 2026): actor_raw is the government that RECEIVES the money ('surviving municipalities ... shall be awarded additional
    annual aid'): the recipient names the subject of a passive award or payment, the payer is the acting body."""
    q = r.get("quote") or ""
    m = AID_RECIPIENT.search(q)
    actor = re.sub(r"^(?:the|a|an|such|each|any)\s+", "", (r.get("actor_raw") or "").strip().lower())
    return bool(m and actor and actor in q[:m.start()].lower() and GOV_ACTOR.search(actor) and
                not re.search(r"\b(?:by|from)\s+(?:the\s+)?" + re.escape(actor), q[:m.start()].lower()))


JOINT_OPINION = re.compile(r"\bin\s+the\s+(?:opinion|discretion|judgment)\s+of\s+(?:the\s+)?([\w'-]+(?:\s+[\w'-]+){0,6}?)\s+and\s+(?:of\s+)?(?:the\s+)?([\w'-]+(?:\s+[\w'-]+){0,6}?)(?=\s*[,;.]|\s+(?:such|that|the|it)\b)", re.I)
JOINT_MODAL = re.compile(r"\b(?:the\s+)?([\w'-]+(?:\s+[\w'-]+){0,5}?)\s+and\s+(?:the\s+)?([\w'-]+(?:\s+[\w'-]+){0,5}?)\s+(?:may|shall)\b", re.I)


def joint_actor_single(r, records):
    """J13 (Oct 14 2026): the quote vests the power or duty jointly in two officials ('in the opinion of the director of the budget and the
    director of employee relations', 'the A and the B may') but the record names only one and no sibling record carries the same quote."""
    q = r.get("quote") or ""
    actor = re.sub(r"^(?:the|a|an|such|each|any)\s+", "", (r.get("actor_raw") or "").strip().lower())
    if not actor or any(x is not r and x.get("quote") == q for x in records):
        return False
    for rx in (JOINT_OPINION, JOINT_MODAL):
        m = rx.search(q)
        if not m:
            continue
        pa, pb = m.group(1).strip().lower(), m.group(2).strip().lower()
        if not (GOV_ACTOR.search(pa) and GOV_ACTOR.search(pb)) or pa == pb:
            continue
        ha, hb = actor in pa or pa in actor, actor in pb or pb in actor
        if ha != hb:
            return True
    return False


NARROW_MUNICIPALITY = re.compile(r"[\"“”']municipalit(?:y|ies)[\"“”']\s+(?:shall\s+)?means?\s+[^.;]{0,200}?(?:located\s+in\s+(?:the\s+)?count(?:y|ies)\s+of|within\s+(?:the\s+)?count(?:y|ies)\s+of|population\s+of|having\s+a\s+population)", re.I)


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
    if "{{" in text:        # M6: an extension record whose quote could not be moved onto the new matter
        outside = []
        for r in records:
            if r.get("extends_existing") and not r.get("quote_relocated") and not r.get("lead_in_existing") and not r.get("kind_from_lead_in"):
                sp = locate_span(r.get("quote") or "", text)
                if sp and not in_braces(sp[0], sp[1], text):
                    outside.append(r["quote"])
        if outside:
            flags.append({"check": "quote_outside_new_matter", "detail": "%d extension records whose quote sits in unchanged text, not in the new matter" % len(outside),
                          "sentences": outside[:12]})
    ap = [r for r in records if approver_only_actor(r)]
    if ap:        # J9 (Oct 13 2026)
        flags.append({"check": "approver_as_actor", "detail": "%d records whose actor_raw appears in the quote only as the approver ('approved by X'): the acting body is the one whose action X approves" % len(ap),
                      "sentences": [r["quote"] for r in ap][:12]})
    ar_ = [r for r in records if aid_recipient_actor(r)]
    if ar_:        # J11 (Oct 13 2026)
        flags.append({"check": "aid_recipient_as_actor", "detail": "%d records whose actor_raw is the government that receives the aid or payment: the acting body is the one that pays or awards it" % len(ar_),
                      "sentences": [r["quote"] for r in ar_][:12]})
    jo = [r for r in records if joint_actor_single(r, records)]
    if jo:        # J13 (Oct 14 2026)
        flags.append({"check": "joint_actor_single", "detail": "%d records whose quote vests the power or duty in two named officials but the record names one: one record per named agency" % len(jo),
                      "sentences": [r["quote"] for r in jo][:12]})
    if APPLY_J15 and NARROW_MUNICIPALITY.search(text or ""):        # J15 (Oct 15 2026)
        mu = [r for r in records if r.get("agency") == "Municipalities (all)" and not r.get("agency_unit")]
        if mu:
            flags.append({"check": "municipality_defined_narrowly", "detail": "%d records resolved to all municipalities, but the law defines 'municipality' as a specific county, city or population class: name that class as the actor" % len(mu),
                          "sentences": [r["quote"] for r in mu][:12]})
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
    manual_confirmed = json.loads(REASK_MANUAL_DATA.read_text())["laws"] if REASK_MANUAL_DATA.exists() else {}
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
        if law["key"] in manual_confirmed:     # J7: data/reask_manual.json, merged on every ingest
            sents = []
            for it in manual_confirmed[law["key"]]:
                if it["sentence"] not in sents:
                    sents.append(it["sentence"])
            fl.insert(0, {"check": "audit_confirmed_miss", "detail": "%d provisions the nightly audits confirmed missing (%s)" % (len(sents), ", ".join(sorted({it["night"] for it in manual_confirmed[law["key"]]}))),
                       "sentences": sents})
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


# ── Max-plan re-ask (Oct 15 2026): a COMPLETE fresh answer per law, from packets/{Y}/results_reask/{LAW}.json ─────
REASK_MARK = "RE-ASK. "


def stored_records(key, data_dir=None):
    """Stored duty and power records of one law, from data/duties/{Y}.json and data/powers/{Y}.json."""
    dd = Path(data_dir) if data_dir else DATA
    y = key.split("-")[0]
    out = []
    for sub, field in (("duties", "obligations"), ("powers", "powers")):
        f = dd / sub / (y + ".json")
        if f.exists():
            out += [o for o in json.loads(f.read_text())[field] if o.get("matter_id") == key]
    return sorted(out, key=lambda o: o.get("obligation_id") or "")


def reask_block(key, entry, stored):
    """The RE-ASK text inserted before the law text of an original packet."""
    lines = [REASK_MARK + "This law was answered before. Your answer REPLACES the earlier one, so give a COMPLETE fresh answer for the whole law: keep the earlier "
             "records that are correct, fix the ones that are wrong, and add the ones that were missed.",
             "", "EARLIER RECORDS FOR THIS LAW (%d):" % len(stored)]
    for o in stored:
        dl = o.get("deadline_text") or o.get("deadline_kind") or "none"
        q = re.sub(r"\s+", " ", o.get("quote") or "").strip()
        lines.append("- %s | actor: %s | kind: %s | deadline: %s | extends existing law: %s | quote: %s" % (
            o.get("obligation_id"), o.get("actor_raw"), o.get("kind"), dl, "yes" if o.get("extends_existing") else "no", q))
    if not stored:
        lines.append("(none stored)")
    lines += ["", "CHECKS THAT FLAGGED THIS LAW: " + "; ".join("%s (%s)" % (r.get("check"), r.get("detail")) for r in entry["reasons"]),
              "", reask_instruction(entry), "", ""]
    return "\n".join(lines)


def upgrade_packet_v2(packet, strict=False):
    """A version-1 packet re-headed with the version-2 prompt (build_prompt(2)) and the SCHEMA_V2 footer; the variable part (header,
    marked law text) and the footer path are untouched. A packet that is already version 2 is returned as is; strict=True raises on a packet that is neither."""
    f2 = build_prompt(2)[0]
    if packet.startswith(f2):
        return packet
    if not packet.startswith(FIXED_PROMPT):
        if strict:
            raise ValueError("packet does not start with the version-1 prompt")
        return packet          # not a production packet (hand-made test text): left as is
    out = f2 + packet[len(FIXED_PROMPT):]
    j = out.rfind("\n\nANSWER FORMAT:")
    k = out.find(":\n", j)
    if j < 0 or k < 0 or out[k + 2:] != json.dumps(SCHEMA):
        raise ValueError("packet footer does not end with the version-1 schema")
    return out[:k + 2] + json.dumps(SCHEMA_V2)


def regen_unanswered_packets(root):
    """Rewrite root/{Y}/{LAW}.txt with the version-2 head for every law that has neither results/{LAW}.json nor results_reask/{LAW}.json.
    Returns {year: [regenerated, left_as_is]}."""
    root = Path(root)
    counts = {}
    for yd in sorted(p for p in root.iterdir() if p.is_dir() and p.name.isdigit()):
        n = [0, 0]
        for f in sorted(yd.glob("*.txt")):
            if (yd / "results" / (f.stem + ".json")).exists() or (yd / "results_reask" / (f.stem + ".json")).exists():
                n[1] += 1
                continue
            t = f.read_text()
            u = upgrade_packet_v2(t, strict=True)
            if u != t:
                f.write_text(u)
            n[0] += 1
        counts[yd.name] = n
    return counts


def reask_packet_text(packet, key, entry, stored, out_path):
    """Original packet text, re-headed with the version-2 prompt, with the RE-ASK block before the law text and an ANSWER FORMAT footer that names out_path."""
    packet = upgrade_packet_v2(packet)
    cut = packet.rfind("\n\nANSWER FORMAT:")
    head, foot = (packet[:cut], packet[cut:]) if cut >= 0 else (packet, "")
    i = head.rfind("\nLAW TEXT:\n")
    block = reask_block(key, entry, stored)
    head = head[:i + 1] + block + head[i + 1:] if i >= 0 else head + "\n\n" + block
    k = foot.find(":\n", foot.find("ANSWER FORMAT:") if foot else 0)
    schema_json = foot[k + 2:] if foot and k >= 0 else ""
    return (head + "\n\nANSWER FORMAT: this is a re-ask. Write ONLY a JSON object matching this schema, the COMPLETE answer for the whole law, "
            "to the exact path " + str(out_path) + " (never to results/):\n" + schema_json)


def reask_overlay(d, todo, tmp, schema=None):
    """Packet-results view for eo.ingest_packets: for each law, results_reask/{key}.json (when it parses and fits the schema)
    stands in for results/{key}.json; otherwise the original answer stands. Returns (overlay_dir, {key: tag})."""
    d, tmp = Path(d), Path(tmp)
    (tmp / "results").mkdir(parents=True, exist_ok=True)
    (tmp / "manifest.json").write_text((d / "manifest.json").read_text())
    for f in (d / "results").glob("*.json"):
        (tmp / "results" / f.name).write_text(f.read_text())
    reasked = {}
    for law, _ in todo:
        k = law["key"]
        rp = d / "results_reask" / (k + ".json")
        if not rp.exists():
            continue
        try:
            raw = json.loads(rp.read_text())
        except json.JSONDecodeError:
            continue
        if not eo.validate_against_schema(raw, schema or SCHEMA):
            continue
        (tmp / "results" / (k + ".json")).write_text(json.dumps(raw))
        tf = d / "reask" / (k + ".tag")
        reasked[k] = tf.read_text().strip() if tf.exists() else "unknown"
    return tmp, reasked


def mark_reasked(reasked, done, extracted_dir=None):
    """Stamp reasked/reask_tag on the cache files of the re-asked laws that ingested; build_records copies it to the records."""
    ed = Path(extracted_dir) if extracted_dir else EXTRACTED
    n = 0
    for k, tag in reasked.items():
        cp = ed / (k + ".json")
        if k in done and cp.exists():
            res = json.loads(cp.read_text())
            res["reasked"], res["reask_tag"] = True, tag
            cp.write_text(json.dumps(res, indent=1, ensure_ascii=False))
            n += 1
    return n


# ── Ingest ──────────────────────────────────────────────────────────────────────────────────────────────────────
def write_cache(mid, res):
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    if mid in EXT_MODEL:
        res["extends_model"] = EXT_MODEL[mid]
        res["actor_model"] = ACTOR_MODEL[mid]
    if mid in EXCLUDED_COUNT:
        res["excluded_sentences_count"] = EXCLUDED_COUNT[mid]
    (EXTRACTED / (mid + ".json")).write_text(json.dumps(res, indent=1, ensure_ascii=False))


DL_OFFSET = re.compile(r"\b(" + efd.NUM_WORDS + r"|\d+)[\s-]+(months?|years?)\b", re.I)


def calendar_deadline(o, bases):
    """M7 (Oct 11 2026). The Council extractor stores 'N months' as 30 N days and 'N years' as 365 N days. A month or year offset in the
    deadline text is calendar arithmetic from the same base (same day-of-month, clamped to month end). Only a stored date that equals the
    30/365-day figure from a base is replaced; returns the new ISO date or None."""
    if o.get("deadline_kind") not in ("days_after_effective", "days_after_enactment") or not o.get("deadline_date"):
        return None
    ms = [m for m in DL_OFFSET.findall(o.get("deadline_text") or "") if m[0].strip()]
    if len(ms) != 1 or re.search(r"\bdays?\b", o.get("deadline_text") or "", re.I):
        return None
    n = efd.words_to_int(ms[0][0]) if not ms[0][0].isdigit() else int(ms[0][0])
    if not n:
        return None
    months, per = (n, 30) if ms[0][1].lower().startswith("month") else (12 * n, 365)
    for base in bases:
        if not base:
            continue
        b = datetime.strptime(base, "%Y-%m-%d").date()
        old = (b + timedelta(days=n * per)).isoformat()
        if o["deadline_date"] == old:
            return efd.add_months(b, months).isoformat()
    return None


# M37 (Oct 15 2026): a stated calendar date in deadline_text that the model left as deadline_kind none becomes a fixed_date. 'December 31, 2010' is
# the date itself; 'on or before the first day of February each year' is the first such day on or after the law's effective date (Council rule,
# Sep 29 2026), with the recurrence kept. A period ('for sixty months') or a date inside 'such school year' names no calendar deadline.
_DL_DAY = r"(?:(?:%s)|\d{1,2}(?:st|nd|rd|th)?)" % efd.ORD_WORD
_DL_MON = r"(" + efd.MONTH_RE + r")"
_DL_PREFIX = r"\b(?:on or before|no later than|not later than|by|before)\s+(?:the\s+)?"
_DL_YEAR_W = r"two\s+thousand(?:\s+(?:and\s+)?(?:" + efd.NUM_WORDS + r"))?"
DL_FULL = re.compile(_DL_PREFIX + _DL_MON + r"\s+(" + _DL_DAY + r"),?\s+(\d{4}|" + _DL_YEAR_W + r")\b", re.I)
DL_RECUR = re.compile(_DL_PREFIX + r"(?:(" + _DL_DAY + r")\s+day\s+of\s+" + _DL_MON + r"|" + _DL_MON + r"\s+(" + _DL_DAY + r"))\b,?\s*(?:of|in)\s+(?:each|every|any)\s+(?:calendar\s+|fiscal\s+)?year\b", re.I)


def _dl_day(tok):
    tok = tok.strip().lower()
    return int(re.sub(r"\D", "", tok)) if re.match(r"\d", tok) else efd.words_to_int(tok)


def dated_deadline(text, base):
    """(ISO date, 'full'|'recurring') for a calendar date in the deadline text, else None. base: ISO effective (or enactment) date for a recurring day."""
    t = re.sub(r"\s+", " ", text or "")
    m = DL_FULL.search(t)
    if m:
        day = _dl_day(m.group(2))
        yr = m.group(3)
        if not yr.isdigit():
            rest = re.sub(r"(?i)^two\s+thousand\s*(?:and\s+)?", "", yr).strip()
            yr = 2000 + (efd.words_to_int(rest) if rest else 0)
        try:
            return date(int(yr), efd.MONTHS[m.group(1).lower()], day).isoformat(), "full"
        except (TypeError, ValueError):
            return None
    m = DL_RECUR.search(t)
    if m and base:
        day = _dl_day(m.group(1) or m.group(4))
        mon = efd.MONTHS[(m.group(2) or m.group(3)).lower()]
        b = date.fromisoformat(base)
        for yr in (b.year, b.year + 1):
            try:
                d = date(yr, mon, day)
            except (TypeError, ValueError):
                return None
            if d >= b:
                return d.isoformat(), "recurring"
    return None


# M38 (Oct 15 2026): a duty tied to each election ('at each general election', 'prior to each election', 'before each annual election', 'notice of such
# election') waits for that election: triggered, no effective-date deadline.
ELECTION_TRIGGER = re.compile(r"\b(?:at|prior to|before|for|during|after|in advance of|upon|of)\s+(?:the\s+)?(?:each|every|any|such)\s+(?:general\s+|annual\s+|special\s+|primary\s+|biennial\s+)?election\b", re.I)


# M17 (Oct 12 2026): who bears a cost is a standing allocation, never a one-time deliverable due on the effective date
COST_BEARING = re.compile(r"\bshall be borne by\b|\bshall be paid by\b(?!\s+(?:\d|(?:january|february|march|april|may|june|july|august|september|october|november|december)\b))|\bshall bear the (?:cost|costs|expense|expenses)\b|\bat the expense of\b", re.I)
# Switched off (Oct 12 2026): the literal rule flipped 312 records across 2009-2015 (73, 65, 163, 11), over the 80 the orders allow; Tal decides.
APPLY_M18 = False


def label_only_braces(text):
    """M18 (Oct 12 2026): True when the law has braced new matter and every braced span is 8 characters or fewer (sub-paragraph
    labels like '(a)', numbers, years): the act renumbers or restructures existing text."""
    spans = re.findall(r"\{\{(.*?)\}\}", text, re.S)
    return bool(spans) and all(len(x.strip()) <= 8 for x in spans)


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
        label_only = label_only_braces(text)
        sx = [e for e in eff.get("section_dates") or [] if e.get("rule") == "section_expiry"]
        if sx and not eff.get("expires_date"):      # M21: a section-scoped sunset covers the law when every record sits in the expiring section(s)
            secs = {act_section_of(o.get("quote") or "", text) for o in res["obligations"]}
            exp_secs = set().union(*[_section_set(e["applies_to"]) for e in sx])
            if secs and None not in secs and secs <= exp_secs and len(sx) == 1:
                eff["expires_date"] = sx[0]["expires_date"]; bump("m21_expiry_from_records")
        law_d, law_p = [], []
        for o in res["obligations"]:
            o["deadline_date"] = eo.sanitize_deadline(o.get("deadline_date"), law["enactment_date"])
            cal = calendar_deadline(o, [res.get("effective_date"), eff.get("effective_date"), law["enactment_date"]])
            if cal:
                o["deadline_date"] = cal; bump("m7_calendar_month_deadline")
            if "{{" in (o.get("quote") or "") or re.search(r"\[[a-z]", o.get("quote") or ""):
                cleaned, has_deleted = eo.clean_stored_quote(o.get("quote"), text)
                o["quote"] = cleaned
                if has_deleted:
                    o["quote_has_deleted_text"] = True
            if eo.fix_actor(o, LOOKUP, BY_CANON, stage="private") == "private":
                excluded += 1
                continue
            if is_act_clause_quote(o.get("quote"), law.get("act_clause")):      # L2
                drop(o, "act_clause", "the quote is the act's effective-date or sunset clause, computed separately")
                continue
            kind = eo._kind(o)
            if kind == "neither" and o.get("kind_model") == "neither" and COST_DUTY.search(o.get("quote") or ""):      # L3
                kind = "duty"; o["kind_adjusted"] = "cost_duty"; bump("l3_cost_duty")
            if kind == "neither":
                excluded += 1
                continue
            if kind == "power" and o.get("kind_model") == "duty" and WILL_DUTY.search(o.get("quote") or "") and not GRANT_WORD.search(o.get("quote") or ""):
                kind = "duty"; o["kind_adjusted"] = "will_duty"; bump("m11_will_duty")        # M11: the quote has no 'shall', so the quote rule said power
            o["actor_resolved_model"] = res.get("actor_model", {}).get(o["obligation_id"])
            o["matter_id"] = law["key"]
            fix_parenthetical_actor(o) and bump("f3_parenthetical_actor")
            attach_jurisdiction(o)
            fix_local_board_of_elections(o) and bump("f2_local_board_of_elections")
            # 5. DTF only when the quote or actor names the State; a locality's tax office is the locality. A local act naming
            #    several localities resolves to the locality the sentence names, else to the group of the localities.
            if (o.get("agency") == "DTF" and not STATE_MARK.search((o.get("quote") or "") + " " + (o.get("actor_raw") or ""))
                    and not (STATE_GENERIC_ACTOR.match(re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip())) and STATE_MARK.search(o.get("actor_resolved_model") or ""))):     # M2: 'the commissioner' the model resolved to the State DTF stays State
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
            if agency_resolve_nys.fix_generic_role(o):          # M8
                bump("m8_generic_role_to_state_agencies")
            elif agency_resolve_nys.fix_boces(o):               # M12
                bump("m12_boces")
            elif agency_resolve_nys.fix_public_body(o):         # M16
                bump("m16_public_body")
            else:
                r15 = agency_resolve_nys.fix_resolvable_actor(o, NYC_BY)      # M15
                if r15:
                    bump(r15)
            if APPLY_M39 and agency_resolve_nys.fix_nyc_acting_through(o, NYC_LOOKUP, NYC_BY):      # M39
                bump("m39_nyc_acting_through")
            r33 = agency_resolve_nys.fix_nyc_school_actor(o, text, NYC_BY)      # M33
            if r33:
                bump(r33)
            elif agency_resolve_nys.fix_assessing_unit(o):                      # M34
                bump("m34_assessing_unit")
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
            if APPLY_M18 and not o["extends_existing"] and label_only:          # M18: new matter is only labels and numbers, the law restructures existing text
                o["extends_existing"] = True; bump("m18_label_only_braces_extends")
            if not o["extends_existing"] and (PLACE_EXCEPTION.search(quote) or (sp0 and PLACE_EXCEPTION.search(re.sub(r"\{\{|\}\}", "", context_sentence(sp0, text)[0])))):          # M3: a 200-foot-rule place exception widens an existing authority
                o["extends_existing"] = True; bump("m3_place_exception_extends")
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
            if APPLY_M35 and kind == "power" and o.get("kind_model") == "duty" and AUTH_DIRECTED.search(quote):          # M35: the rules above must not override the model's duty
                kind = "duty"; o["kind_adjusted"] = "authorized_and_directed"; bump("m35_authorized_and_directed_duty")
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
            per_election = False
            if (APPLY_M38 and kind == "duty" and (o.get("deadline_kind") == "on_effective_date" or (o.get("deadline_kind") == "none" and o.get("recurrence") == "one-time"))
                    and ELECTION_TRIGGER.search(quote) and not CAP_RE.search(quote)):          # a 'none' one-time duty would otherwise be stamped on the effective date by triggered_to_setup
                per_election = True
                o["deadline_kind"], o["deadline_date"] = "none", None
                o["recurrence"] = "annual" if re.search(r"\bannual\s+election\b", quote, re.I) else "as-needed"; bump("m38_per_election_triggered")
            if kind == "duty" and o.get("deadline_kind") == "on_effective_date" and TRIGGER.search(quote) and not CAP_RE.search(quote):
                o["deadline_kind"], o["deadline_date"] = "none", None; bump("setup_to_triggered")
            elif (kind == "duty" and o.get("deadline_kind") == "none" and o.get("recurrence") == "one-time"
                  and o.get("deliverable_type") in SETUP_TYPES and not TRIGGER.search(quote) and not CAP_RE.search(quote)
                  and not PROHIBITION.search(quote)):
                o["deadline_kind"] = "on_effective_date"; bump("triggered_to_setup")
            if COST_BEARING.search(quote) and (o.get("deadline_kind") != "none" or o.get("recurrence") != "ongoing" or o.get("deadline_date")):
                o["deadline_kind"], o["deadline_date"], o["recurrence"] = "none", None, "ongoing"; bump("m17_cost_bearing_ongoing")          # M17
            if (o.get("model_unit") and not o.get("agency_unit") and o.get("jurisdiction") == "state"
                    and o.get("agency_org_type") != "local government group" and o.get("agency") not in STATE_UNIT_EXCLUDED):
                o["agency_unit"] = unit_title(o["model_unit"]); bump("m5_unit_copied")           # M5
            if (o["extends_existing"] and "{{" in text and not o.get("lead_in_existing") and not o.get("kind_from_lead_in")
                    and sp0 and not in_braces(sp0[0], sp0[1], text)):                    # M6: the quote is reprinted text next to the new matter
                nq = relocate_quote(quote, text, o.get("actor_raw"))
                if nq:
                    o["quote_original"], o["quote"], o["quote_relocated"] = quote, nq, True
                    bump("m6_quote_relocated")
                else:
                    bump("m6_quote_outside_unresolved")
            if kind == "duty":
                ssd = study_submission_date(o, text)
                if ssd:
                    o["deadline_kind"], o["deadline_date"], o["deadline_text"] = "fixed_date", ssd[0], ssd[1]; bump("m29_study_submission_date")
            # 1. record dates per section; on_effective_date never null when the date is known
            sec_date, sec_src = section_effective(o, text, eff)
            if sec_src != "law":
                bump("section_dates_applied")
            if (APPLY_M37 and kind == "duty" and not per_election and o.get("deadline_kind") in (None, "none") and not o.get("deadline_date")
                    and o.get("deadline_text") and not CAP_RE.search(quote) and not COST_BEARING.search(quote)):
                dd = dated_deadline(o["deadline_text"], sec_date or law["enactment_date"])
                if dd and dd[0] >= law["enactment_date"]:
                    o["deadline_kind"], o["deadline_date"] = "fixed_date", dd[0]; bump("m37_dated_deadline_" + dd[1])
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
            if res.get("reasked"):
                rec["reasked"], rec["reask_tag"] = True, res.get("reask_tag")
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


def emit_pilot_packets(root, todo, keys, version):
    """Pilot packets (prompt v2 harness): one text file per listed law under root/{Y}/{LAW}.txt, built from the same marked text
    (cache/text_marked via load_todo) and render_variable_prompt the production packets use, with the ANSWER FORMAT footer naming the
    absolute path root/{Y}/results/{LAW}.json. Chunk lists root/chunks/NNN.lst use next_packet_batch.make_chunks (400 KB, 30 laws).
    Returns (packets written, chunk list paths, total bytes, {key: reason} for listed laws that could not be emitted)."""
    import next_packet_batch as nb
    root = Path(root).resolve()
    fixed = FIXED_PROMPT if version == 1 else build_prompt(version)[0]
    schema = SCHEMA if version == 1 else SCHEMA_V2
    have = {l["key"]: (l, t) for l, t in todo}
    skipped = {k: "no marked text, or over %d characters (deferred long)" % MAX_CHARS for k in keys if k not in have}
    files = []
    for y in sorted({k.split("-")[0] for k in keys if k in have}):
        d = root / y
        (d / "results").mkdir(parents=True, exist_ok=True)
        sub = [have[k] for k in sorted(keys) if k in have and k.split("-")[0] == y]
        eo.emit_packets(d, sub, fixed_prompt=fixed, render=render_variable_prompt, schema=schema)
        for f in sorted(d.glob("*.txt")):
            f.write_text(re.sub(r"schema to results/([^\s:]+\.json):", lambda m: "schema to %s:" % (d / "results" / m.group(1)), f.read_text(), count=1))
            files.append(f)
    chunks = nb.make_chunks(files, len(files) or 1, 400_000, 30)
    lists = nb.write_lists(chunks, root / "chunks") if chunks else []
    return len(files), lists, sum(f.stat().st_size for f in files), skipped


def main():
    global EFFECTIVE, EXTRACTED
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
    ap.add_argument("--prompt-version", type=int, choices=(1, 2), default=2, help="2 (default): add prompt_v2_rules.txt and the optional excluded_sentences field; 1: the old production prompt")
    ap.add_argument("--regen-packets", metavar="DIR", help="rewrite the unanswered laws' packets under DIR/{Y}/ with the version-2 head (answered laws untouched)")
    ap.add_argument("--laws", metavar="FILE", help="with --emit-packets: JSON with a \"laws\" list of keys; packets go to DIR/{Y}/{LAW}.txt with chunk lists in DIR/chunks/")
    ap.add_argument("--data-dir", metavar="DIR", help="with --ingest: write every output file (data files and the extracted cache) under DIR with the same layout; inputs are still read from data/")
    a = ap.parse_args()
    if a.regen_packets:
        for y, (n, m) in regen_unanswered_packets(a.regen_packets).items():
            print("%s regenerated %d left as is %d" % (y, n, m))
        return
    full = bool(a.api or a.per_session or a.session)
    sessions = (a.session or PILOT_SESSIONS) if full else None
    pilot_keys = None
    if a.laws:
        if not a.emit_packets:
            sys.exit("--laws needs --emit-packets")
        lj = json.load(open(a.laws))["laws"]
        pilot_keys = sorted(lj)
        sessions = sorted({int(k.split("-")[0]) for k in pilot_keys})
        todo, deferred = load_todo(sessions)
        todo = [(l, t) for l, t in todo if l["key"] in set(pilot_keys)]
        n, lists, nbytes, skipped = emit_pilot_packets(a.emit_packets, todo, pilot_keys, a.prompt_version)
        print("packets written %d of %d listed laws (prompt version %d), %d bytes; chunk lists %d" % (n, len(pilot_keys), a.prompt_version, nbytes, len(lists)))
        for l in lists:
            print("  " + l)
        for k, why in sorted(skipped.items()):
            print("skipped %s: %s" % (k, why))
        return
    out = Path(a.data_dir) if a.data_dir else DATA
    if a.data_dir:
        EXTRACTED = out / "cache" / "extracted"
    schema = SCHEMA if a.prompt_version == 1 else SCHEMA_V2
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
        (out / "effective_dates").mkdir(parents=True, exist_ok=True)
        for y in sorted({l["session"] for l, _ in todo}):
            json.dump({k: v for k, v in EFFECTIVE.items() if k.startswith("%d-" % y)}, open(out / "effective_dates" / ("%d.json" % y), "w"), separators=(",", ":"))
    else:
        json.dump(EFFECTIVE, open(out / "effective_dates.json", "w"), indent=1)
    json.dump({"rule": "signed laws whose marked text exceeds %d characters (budget bills, recodifications) wait for a later phase" % MAX_CHARS,
               "laws": deferred}, open(out / "deferred_long.json", "w"), indent=1)
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
        eo.emit_packets(d, todo, fixed_prompt=FIXED_PROMPT if a.prompt_version == 1 else build_prompt(a.prompt_version)[0], render=render_variable_prompt, schema=schema)
        sizes = sorted(os.path.getsize(d / (l["key"] + ".txt")) for l, _ in todo)
        print("packets %d (signed laws %d, deferred long %d); bytes min %d median %d max %d" % (len(todo), len(laws), len(deferred), sizes[0], sizes[len(sizes) // 2], sizes[-1]))
        return
    if a.ingest:
        d = Path(a.ingest)
        import tempfile
        with tempfile.TemporaryDirectory() as tmpd:       # a valid results_reask answer replaces results/ for its law
            view, reasked = reask_overlay(d, todo, tmpd, schema)
            done, left = eo.ingest_packets(view, todo, LOOKUP, BY_CANON, "claude-sonnet-5" if full else "max-subagent", writer=write_cache, prepare=prepare, schema=schema)
        print("re-ask answers used: %d laws" % mark_reasked(reasked, set(done)))
        merged = merge_reask(todo, d / "results", "claude-sonnet-5" if full else "max-subagent")
        duties, powers, excluded = build_records([l for l, _ in todo])
        if full:      # M21: build_records may add a law-wide expires_date from a section-scoped sunset
            for y in sorted({l["session"] for l, _ in todo}):
                json.dump({k: v for k, v in EFFECTIVE.items() if k.startswith("%d-" % y)}, open(out / "effective_dates" / ("%d.json" % y), "w"), separators=(",", ":"))
        stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        reask = build_reask(todo, duties, powers)
        print("re-ask merged %d records; recall checks flag %d laws" % (merged, len(reask)))
        sess = sorted({l["session"] for l, _ in todo})
        for sub_dir in ("reask", "dropped"):
            (out / sub_dir).mkdir(parents=True, exist_ok=True)
        for y in (sess if full else []):               # per-session files: an ingest of one session never overwrites another's
            json.dump({"generated_at": stamp, "laws": {k: v for k, v in reask.items() if k.startswith("%d-" % y)}}, open(out / "reask" / ("%d.json" % y), "w"), indent=1, ensure_ascii=False)
            json.dump({"generated_at": stamp, "dropped": [d for d in DROPPED if (d.get("matter_id") or "").startswith("%d-" % y)]}, open(out / "dropped" / ("%d.json" % y), "w"), indent=1, ensure_ascii=False)
        if full:     # one file would pass ~25 MB: per-session files, the single store (the pilot laws are in their session's file)
            (out / "duties").mkdir(parents=True, exist_ok=True); (out / "powers").mkdir(parents=True, exist_ok=True)
            for y in sess:
                json.dump({"generated_at": stamp, "obligations": [o for o in duties if o["session"] == y]}, open(out / "duties" / ("%d.json" % y), "w"), separators=(",", ":"), ensure_ascii=False)
                json.dump({"generated_at": stamp, "powers": [o for o in powers if o["session"] == y]}, open(out / "powers" / ("%d.json" % y), "w"), separators=(",", ":"), ensure_ascii=False)
        else:        # pilot-only tests write the single legacy files
            json.dump({"generated_at": stamp, "obligations": duties}, open(out / "duties.json", "w"), indent=1, ensure_ascii=False)
            json.dump({"generated_at": stamp, "powers": powers}, open(out / "powers.json", "w"), indent=1, ensure_ascii=False)
        print("ingested %d laws, %d left (missing or invalid result); duties %d, powers %d, excluded (private or neither) %d" % (len(done), len(left), len(duties), len(powers), excluded))
        print("rules applied:", json.dumps(STATS, sort_keys=True))


if __name__ == "__main__":
    main()
