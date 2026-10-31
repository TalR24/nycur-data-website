"""Second-pass agency resolver for NYS duties and powers (Oct 8 2026, fix 2b and 3).

attach_jurisdiction() in extract_duties.py matches the actor through the NYS crosswalk, named localities and the Council
crosswalk for NYC. This pass takes what is still unmatched, tries the model's own actor_resolved name first (it often names the
body the raw 'the authority' / 'the commissioner' stands for), then, in order:
  1. curated aliases onto crosswalk entries (State Liquor Authority -> ABC) and the NYC crosswalk for NYC acronyms (TLC, DCAS)
  2. group classes (state agencies, courts, boards of elections, social services districts, library and fire districts ...)
  3. a body the text names ('state energy planning board', 'division of the lottery'): recorded under its own proper name
  4. a generic title ('the authority', 'the board of directors') resolved to the body the act creates ('to be known as ...')
  5. else agency 'Unspecified' with actor_unresolved true (the law goes to re-ask)
Offline, no model calls.
"""
import re

# curated aliases: normalised phrase -> canonical in the NYS crosswalk (checked first)
ALIASES = {
    "division of alcoholic beverage control": "ABC", "state liquor authority": "ABC", "liquor authority": "ABC", "new york state liquor authority": "ABC",
    "department of education": "SED", "state education department": "SED", "education department": "SED",
    "banking department": "DFS", "state banking department": "DFS", "superintendent of banks": "DFS",
    "department of economic development": "ESD", "commissioner of economic development": "ESD",
    "commissioner of the new york state department of economic development": "ESD",
    "new york state department of economic development": "ESD", "state department of economic development": "ESD",
    "division of veterans' affairs": "DVS", "division of veterans affairs": "DVS", "state division of veterans' affairs": "DVS",
    "director of the new york state division of the budget": "DOB", "director of the budget": "DOB", "division of the budget": "DOB",
    "director of state operations": "Governor", "governor's office of employee relations": "OER", "director of employee relations": "OER",
    "state office for the aging": "NYSOFA", "office for the aging": "NYSOFA", "new york state office for the aging": "NYSOFA",
    "commissioner of mental retardation and developmental disabilities": "OPWDD", "office of mental retardation and developmental disabilities": "OPWDD",
    "municipal bond bank agency": "State of New York Municipal Bond Bank Agency",
    "new york state and local employees' retirement system": "State Comptroller", "state and local employees' retirement system": "State Comptroller",
    "the state": "State of New York", "state of new york": "State of New York", "this state": "State of New York",
}
# group classes: (regex on the normalised phrase, canonical name, jurisdiction, org_type). Canonical names not in the NYS
# crosswalk are created here as groups.
GROUPS = [
    (r"^(?:state )?(?:agency|agencies)$|^state (?:agency|agencies|departments?|officers?|entit(?:y|ies))\b|^all state agencies|^(?:state )?contracting agenc|^authorized state entit|^(?:state )?(?:agency|agencies) (?:and|or) (?:authorit|commission)|^state (?:commissions?|councils?)\b", "State agencies", "state", "state agency group"),
    (r"^state (?:authorit(?:y|ies)|financing agenc)|^public (?:authorit(?:y|ies)|benefit corporations?)|^subsidiary public benefit|^(?:every )?member, officer or employee of a state authority|^(?:state authorities|public authorities)", "State authorities", "state", "state agency group"),
    (r"^(?:state|local) (?:and|or) (?:local|state|municipal)\b|^all state and local|^state and local", "State and local bodies", "state", "state agency group"),
    (r"^(?:local )?(?:authorit(?:y|ies)|agenc(?:y|ies)|municipal commissions?|municipal corporations?)$|^local (?:authorit|agenc|offic)|^municipal commission", "Local agencies and authorities", "local", "local government group"),
    (r"^(?:municipalit(?:y|ies)|governmental (?:entit(?:y|ies)|agenc(?:y|ies))|public bod(?:y|ies)|governmental agencies|special assessing units?|cities that are special|special assessing)", "Municipalities (all)", "local", "local government group"),
    (r"^(?:county )?boards? of elections?|^(?:central )?boards? of inspectors|^(?:the )?inspectors?(?: of election)?$|^(?:clerks or )?inspectors|^each polling place|^any polling place|^election inspectors|^bipartisan team of inspectors|^boards of election", "Boards of elections", "local", "local government group"),
    (r"^social services (?:district|official)", "Social services districts", "local", "local government group"),
    (r"^(?:the )?(?:courts?|court of this state|court having jurisdiction|courts having jurisdiction|new york state courts|judge|justice(?! center)|any judge|trier of fact|unspecified court)\b|^(?:courts|court)$|^(?:a )?court\b", "Unified Court System", "state", "judiciary"),   # Oct 27 2026: 'justice center' is the Justice Center, not a court
    (r"^(?:(?:family|supreme|surrogate'?s|county|criminal|local criminal|sentencing|appointing|superior|human trafficking)\s+)+courts?\b|^(?:the )?sentencing court|^court of (?:competent jurisdiction|appeals)|^appellate (?:division|term)|^justices? of the supreme court", "Unified Court System", "state", "judiciary"),   # Oct 29 2026 K1
    (r"^temporary president(?: of the senate)?$|^speaker(?: of the assembly)?$|^(?:minority|majority) leaders? of the (?:senate|assembly)$|^chairs? of the senate finance and (?:the )?assembly ways and means committees?$", "State Legislature", "state", "state agency group"),   # Oct 29 2026 K2
    (r"^sheriffs?\b", "Sheriffs", "local", "local government group"),
    (r"^boards? of cooperative educational|^boces", "BOCES", "local", "local government group"),
    (r"^(?:public )?employers?$|^(?:such )?public employers?|^each participating employer|^participating employers?", "Public employers", "state", "state agency group"),
    (r"^(?:school districts?|school boards?|boards? of education)$", "School districts", "local", "local government group"),
]
GROUP_REGEX = [(re.compile(p, re.I), c, j, t) for p, c, j, t in GROUPS]

BODY_NOUN = re.compile(r"\b(authority|agency|board|commission|corporation|department|division|office|committee|council|task force|system|bank|fund|foundation|administration|institute|library|conservancy|trust|center|bureau|panel|service|district|school|college|university|association|commissioner|director|superintendent|chancellor|adjutant general|treasurer|comptroller|clerk|board of trustees)\b", re.I)
STOP = set("the of and for a an to in on by or such said each every any no new york state city county local this that its their".split())
BODY_WORDS = set("authority agency board commission corporation department division office committee council task force system bank fund foundation administration institute library conservancy trust center bureau panel service district school college university association commissioner director directors superintendent chancellor trustees members retirement actuary".split())
GENERIC_TITLE = re.compile(r"^(?:the |such |said |each |every |any |a |an )?(?:authority|corporation|board|commission|committee|agency|department|division|office|council|task force|directors?|board of directors|trustees|board of trustees|retirement system|retirement board|district|bank|fund|foundation|administration|commissioner|chairman|chair|principal|actuary|superintendent|chancellor|county|city|town|village|support collection unit|employer|officer|people|it|interest|district corporations?)s?$", re.I)
CREATED_BY_NOUN = {
    "authority": "Authority", "corporation": "Corporation", "board": "Board|Commission|Council|Authority", "directors": "Authority|Corporation|Commission|Board",
    "board of directors": "Authority|Corporation|Commission", "trustees": "Authority|Corporation|Board|Library|District", "board of trustees": "Authority|Corporation|Board|Library|District",
    "commission": "Commission", "committee": "Committee|Commission", "council": "Council", "agency": "Agency|Authority", "task force": "Task Force",
    "foundation": "Foundation", "land bank": "Land Bank", "bank": "Bank",
}
LOCAL_NOUN = re.compile(r"\b(district|library|town|village|county|school|fire company)\b", re.I)


# S2 (Oct 17 2026): a county unit must be one of New York's 62 counties; 'any other entity county' / 'such county' never yield a unit.
COUNTIES = ["Albany", "Allegany", "Bronx", "Broome", "Cattaraugus", "Cayuga", "Chautauqua", "Chemung", "Chenango", "Clinton", "Columbia", "Cortland",
            "Delaware", "Dutchess", "Erie", "Essex", "Franklin", "Fulton", "Genesee", "Greene", "Hamilton", "Herkimer", "Jefferson", "Kings", "Lewis",
            "Livingston", "Madison", "Monroe", "Montgomery", "Nassau", "New York", "Niagara", "Oneida", "Onondaga", "Ontario", "Orange", "Orleans",
            "Oswego", "Otsego", "Putnam", "Queens", "Rensselaer", "Richmond", "Rockland", "St. Lawrence", "Saratoga", "Schenectady", "Schoharie",
            "Schuyler", "Seneca", "Steuben", "Suffolk", "Sullivan", "Tioga", "Tompkins", "Ulster", "Warren", "Washington", "Wayne", "Westchester",
            "Wyoming", "Yates"]
_COUNTY_BY_LOWER = {c.lower().replace("saint ", "st. "): c for c in COUNTIES}
_COUNTY_ALT = "|".join(sorted((re.escape(c) for c in COUNTIES), key=len, reverse=True))
COUNTY_FIRST = re.compile(r"^(%s)\b" % _COUNTY_ALT, re.I)
COUNTY_BEFORE = re.compile(r"\b(%s)\s+county\b" % _COUNTY_ALT, re.I)


def county_name(name):
    """The canonical county a name STARTS with ('onondaga for any county purpose' -> 'Onondaga'), else None."""
    m = COUNTY_FIRST.match(re.sub(r"\s+", " ", (name or "").strip()).replace("Saint ", "St. ").replace("saint ", "st. "))
    return _COUNTY_BY_LOWER.get(m.group(1).lower()) if m else None


def county_before_word(text):
    """The canonical county in '<Name> county' (case-insensitive) in the text, else None."""
    m = COUNTY_BEFORE.search(text or "")
    return _COUNTY_BY_LOWER.get(m.group(1).lower()) if m else None


def norm(s):
    s = re.sub(r"\([^)]*\)", " ", (s or "").lower())
    s = s.replace("’", "'")
    s = re.sub(r"\s+", " ", s).strip(" .,;:")
    return s


def strip_art(s):
    return re.sub(r"^(?:the|such|said|each|every|any|a|an)\s+", "", s)


_SMALL = {"of", "the", "and", "in", "on", "for", "to", "a"}


def _cap_part(p):
    """Capitalise one hyphen part; O'Brien / D'Angelo capitalise after the apostrophe, Hell's does not."""
    p = p[:1].upper() + p[1:]
    return re.sub(r"^([A-Za-z])'([a-z])", lambda m: m.group(1) + "'" + m.group(2).upper(), p)


def title_case(s):
    """Per-word title case including after hyphens and apostrophes (R3, Oct 27 2026); small words stay lower unless first."""
    out = []
    for i, w in enumerate(s.split()):
        parts = w.split("-")
        out.append("-".join(pt.lower() if ((i or j) and pt.lower() in _SMALL) else _cap_part(pt) for j, pt in enumerate(parts)))
    return " ".join(out)


def distinctive(s):
    """A named body: it has a body noun and at least one word that is neither a body noun nor a stop word."""
    toks = re.findall(r"[a-z0-9']+", s)
    rest = [t for t in toks if t not in STOP and t not in BODY_WORDS]
    return bool(BODY_NOUN.search(s)) and len(rest) >= 1


def act_created_body(text, noun):
    """The body the act creates or names, ending in the generic noun ('authority' -> 'Montgomery, Otsego, Schoharie Solid Waste
    Management Authority'). Searches 'to be known as ...' and 'Name (hereinafter ...)' definitions in the unmarked text."""
    suffix = CREATED_BY_NOUN.get(noun)
    if not suffix:
        return None
    plain = re.sub(r"\{\{|\}\}", "", text)
    plain = re.sub(r"\s+", " ", plain)
    pats = [r"to be known as (?:the )?([A-Z][^.;]{3,140}?(?:%s))\b" % suffix,
            r"\b([A-Z][A-Za-z'’\-]*(?:,? (?:and )?[A-Za-z'’\-]+){0,10}? (?:%s))\s*\((?:hereinafter|the \"?(?:authority|corporation|commission|board|council|committee)|\"?the (?:authority|corporation))" % suffix,
            r"\b(?:the|The) ([A-Z][A-Za-z'’\-]*(?:,? (?:and |of |for )?[A-Z][A-Za-z'’\-]*){0,9} (?:%s))\b" % suffix]
    for p in pats:
        m = re.search(p, plain)
        if m:
            name = m.group(1).strip(" ,")
            name = re.sub(r"^(?:the|The)\s+", "", name)
            if 2 <= len(name.split()) <= 14:
                return name
    return None


def resolve_unmatched(o, text, law, deps):
    """Mutates o. Returns the rule name that resolved it, or 'unresolved'."""
    eo, LOOKUP, BY_CANON = deps["eo"], deps["LOOKUP"], deps["BY_CANON"]
    NYC_LOOKUP, NYC_BY, NYC_MARKERS = deps["NYC_LOOKUP"], deps["NYC_BY"], deps["NYC_MARKERS"]
    named_locality = deps["named_locality"]
    r27 = fix_20261027(o, text, LOOKUP, BY_CANON, eo.match_agency)          # R1, R2, R4 (Oct 27 2026)
    if r27:
        return r27
    raw = (o.get("actor_raw") or "").strip()
    cands = []
    for c in (o.get("actor_resolved_model"), o.get("agency"), raw):
        n = norm(c)
        if n and n not in ("unspecified", "not stated", "n/a") and n not in cands:
            cands.append(n)
    if not cands:
        return _unspecified(o)

    def set_canon(canon, by, jur, rule):
        a = by[canon]
        o.update(agency=canon, agency_full=a.get("full_name") or canon, agency_matched=True, jurisdiction=jur,
                 agency_org_type=a.get("org_type"), agency_group=canon if a.get("org_type") == "local government group" else None,
                 agency_source=rule)
        o.setdefault("agency_unit", None)
        return rule

    def set_named(name, jur, otype, rule, group=None, unit=None):
        o.update(agency=group or name, agency_full=group or name, agency_matched=True, jurisdiction=jur, agency_org_type=otype,
                 agency_group=group, agency_unit=unit, agency_source=rule)
        return rule

    if strip_art(norm(raw)) == "authority" and re.match(r"\s*Alcoholic Beverage Control Law\b", o.get("citation") or "") and "ABC" in BY_CANON:
        return set_canon("ABC", BY_CANON, BY_CANON["ABC"]["jurisdiction"], "abc_law_authority")        # M2: 'the authority' in the ABC Law is the State Liquor Authority
    for c in cands:                                       # 1. aliases and the two crosswalks
        for v in (c, strip_art(c)):
            if v in ALIASES and ALIASES[v] in BY_CANON:
                return set_canon(ALIASES[v], BY_CANON, BY_CANON[ALIASES[v]]["jurisdiction"], "alias")
        nyc = bool(NYC_MARKERS.search(c)) or c in ("tlc", "dcas", "dof", "dep", "dot", "doe") or re.fullmatch(r"nyc\w+ .*", c) is not None
        if nyc:
            canon, _ = eo.match_agency(c, NYC_LOOKUP, NYC_BY)
            if canon:
                return set_canon(canon, NYC_BY, "nyc", "nyc_crosswalk")
        canon, _ = eo.match_agency(c, LOOKUP, BY_CANON)
        if canon and not NYC_MARKERS.search(c):
            return set_canon(canon, BY_CANON, BY_CANON[canon]["jurisdiction"], "crosswalk_retry")
    for c in cands:                                       # 2. group classes (after articles are stripped)
        v = strip_art(c)
        for rx, canon, jur, otype in GROUP_REGEX:
            if rx.search(v) or rx.search(c):
                if canon in BY_CANON:
                    return set_canon(canon, BY_CANON, jur, "group")
                return set_named(canon, jur, otype, "group", group=canon if otype == "local government group" else None)
    for c in cands:                                       # 3. library, fire and school districts, named
        v = strip_art(c)
        m = re.search(r"\b((?:[a-z][a-z.'-]*\s+){0,5}?(?:public library|library district|free library|memorial library|library))\b", v)
        if m and not NYC_MARKERS.search(v):
            name = title_case(re.sub(r"^(?:board of trustees of|trustees of)\s+(?:the\s+)?", "", m.group(1)))
            grp = "Library districts" if "district" in v else "Public libraries"
            return set_named(name, "local", "local government group", "library", group=grp, unit=title_case(re.sub(r"^board of trustees of (?:the )?", "", v)) if "district" in v else name)
    for c in cands:                                       # 4. a body the text names, under its own proper name
        v = strip_art(c)
        if GENERIC_TITLE.match(v) or not distinctive(v) or re.match(r"^(?:no|each|every|any|all)\b", c):
            continue
        if v.startswith("board of trustees of ") or v.startswith("board of directors of "):
            v = strip_art(v.split(" of ", 2)[2]) if v.count(" of ") >= 2 else v
        if len(v.split()) > 14:
            continue
        jur = "nyc" if NYC_MARKERS.search(v) else ("local" if LOCAL_NOUN.search(v) else "state")
        otype = "public authority" if re.search(r"authority|corporation|bank", v) else ("board/commission" if re.search(r"board|commission|council|committee|task force", v) else "named body")
        return set_named(title_case(v), jur, otype, "named_body")
    for c in [norm(raw)] + cands:                         # 5. generic title -> the body the act creates
        v = strip_art(c)
        v = re.sub(r"^(?:board of )?(directors|trustees) of (?:the |such )?(authority|corporation|commission)$", r"\2", v)
        v = re.sub(r"^(board of directors|board of trustees)$", lambda m: m.group(1), v)
        v = re.sub(r"^(?:board|directors)$", "board" if v == "board" else v, v)
        noun = v if v in CREATED_BY_NOUN else None
        if not noun:
            continue
        name = act_created_body(text, noun)
        if not name and noun in ("board", "directors", "board of directors", "trustees", "board of trustees", "agency", "committee"):
            name = act_created_body(text, "authority") or act_created_body(text, "corporation") or act_created_body(text, "commission")
        if name:
            return set_named(name, "state", "public authority" if re.search(r"Authority|Corporation|Agency", name) else "board/commission", "act_created")
    return _unspecified(o)


def _unspecified(o):
    o.update(agency="Unspecified", agency_full="Unspecified", agency_matched=False, jurisdiction=None, agency_org_type=None,
             agency_group=None, agency_unit=None, actor_unresolved=True, agency_source="unresolved")
    return "unresolved"


# M8 (Oct 11 2026): a generic role noun is not a named body. These exact phrases resolve to the State agencies group.
GENERIC_ROLE = re.compile(r"^(?:the |such |said |each |the same )?(?:appointing (?:authorit(?:y|ies)|officers?)(?: or authorit(?:y|ies))?|head of the agency|agency heads?)$|^the public employer$", re.I)


def fix_generic_role(o):
    """Mutates o and returns True when actor_raw is exactly a generic role noun; a role qualified by a body ('the appointing authority
    for the advisory council') is left to the other rules."""
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if not GENERIC_ROLE.match(raw):
        return False
    o.update(agency="State agencies", agency_full="State agencies", agency_matched=True, jurisdiction="state", agency_org_type="state agency group",
             agency_group=None, agency_unit=None, agency_source="generic_role")
    o.pop("actor_unresolved", None)
    return True


# O2 (Oct 16 2026): 'the state' / 'the State of New York' as the acting body, with no agency resolved, is the State agencies group (unit: State of New York).
STATE_ACTOR = re.compile(r"^(?:the )?state(?: of new york)?$|^this state$", re.I)


def fix_state_actor(o):
    """Mutates o and returns True when actor_raw is exactly 'the state' / 'the State of New York' and the agency is Unspecified."""
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if not STATE_ACTOR.match(raw) or o.get("agency") not in (None, "Unspecified"):
        return False
    o.update(agency="State agencies", agency_full="State agencies", agency_matched=True, jurisdiction="state", agency_org_type="state agency group",
             agency_group=None, agency_unit="State of New York", agency_source="state_actor")
    o.pop("actor_unresolved", None)
    return True


# M12 (Oct 11 2026): boards of cooperative educational services are BOCES, never School districts or Unspecified.
BOCES_RE = re.compile(r"\bboards? of cooperative educational services?\b|\bboces\b", re.I)
SCHOOL_ALSO = re.compile(r"school district|board of education|schools?\b|\bdepartment\b|\bcommissioner\b", re.I)


def fix_boces(o):
    """Mutates o and returns True when actor_raw names a BOCES and no other body (a compound such as 'school districts and boards of
    cooperative educational services' keeps its sibling-record split)."""
    raw = o.get("actor_raw") or ""
    if not BOCES_RE.search(raw):
        return False
    rest = BOCES_RE.sub(" ", re.sub(r"\([^)]*\)", " ", raw))
    if SCHOOL_ALSO.search(rest) and not re.search(r"board of education of the board of cooperative", raw, re.I):
        return False
    o.update(agency="BOCES", agency_full="BOCES", agency_matched=True, jurisdiction="local", agency_org_type="local government group",
             agency_group="BOCES", agency_unit=None, agency_source="boces")
    o.pop("actor_unresolved", None)
    return True


# M15 (Oct 12 2026): actors the model left generic that the text resolves. Only records still stored as Unspecified are touched.
BOROUGH_PRESIDENT = re.compile(r"^(?:the |such |each |every )?(?:borough presidents?|presidents? of the borough(?: of [A-Za-z ]+)?)$", re.I)
ENFORCEMENT_ACTOR = re.compile(r"^(?:the |such |each |every |an? |any )?(?:(?:code )?enforcement (?:officers?|officials?)|officials? of this state\b[^.]*?\bcharged with the enforcement\b.*)$", re.I)
STATE_OFFICIAL = re.compile(r"^(?:no |any |an? |the |each |every )?(?:(?:officials?|officers?) of (?:this|the) state(?: of new york)?|state (?:officials?|officers?))$", re.I)
LOCAL_WORDS = re.compile(r"\b(?:cit(?:y|ies)|count(?:y|ies)|towns?|villages?|municipal(?:ity|ities)?|local)\b", re.I)


def fix_resolvable_actor(o, nyc_by):
    """Mutates o and returns the rule name when an Unspecified record's actor_raw is a borough president (NYC crosswalk 'Borough
    Presidents'), or an enforcement officer or official: State agencies when the quote names the State (alone or with local
    officials), Local agencies and authorities when it names only local ones; no State or local wording leaves the record alone."""
    if o.get("agency") != "Unspecified":
        return None
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if BOROUGH_PRESIDENT.match(raw) and "Borough Presidents" in nyc_by:
        a = nyc_by["Borough Presidents"]
        o.update(agency="Borough Presidents", agency_full=a.get("full_name") or "Borough Presidents", agency_matched=True, jurisdiction="nyc",
                 agency_org_type=a.get("org_type"), agency_group=None, agency_unit=None, agency_source="borough_president")
        o.pop("actor_unresolved", None)
        return "m15_borough_president"
    if STATE_OFFICIAL.match(raw):          # R10 (Oct 31 2026)
        o.update(agency="State agencies", agency_full="State agencies", agency_matched=True, jurisdiction="state", agency_org_type="state agency group",
                 agency_group=None, agency_unit=None, agency_source="state_official")
        o.pop("actor_unresolved", None)
        return "r10_state_official"
    if ENFORCEMENT_ACTOR.match(raw):
        ctx = (o.get("quote") or "") + " " + raw
        state, local = bool(re.search(r"\b(?:this state|state)\b", ctx, re.I)), bool(LOCAL_WORDS.search(ctx))
        if state:
            o.update(agency="State agencies", agency_full="State agencies", agency_matched=True, jurisdiction="state", agency_org_type="state agency group",
                     agency_group=None, agency_unit=None, agency_source="enforcement_official")
        elif local:
            o.update(agency="Local agencies and authorities", agency_full="Local agencies and authorities", agency_matched=True, jurisdiction="local",
                     agency_org_type="local government group", agency_group="Local agencies and authorities", agency_unit=None, agency_source="enforcement_official")
        else:
            return None
        o.pop("actor_unresolved", None)
        return "m15_enforcement_official"
    return None


# M16 (Oct 12 2026): 'a public body' in the Open Meetings and Public Officers Laws covers State and local bodies (existing crosswalk group).
PUBLIC_BODY = re.compile(r"^(?:a |an |the |any |each |every |such |said )?public bod(?:y|ies)$", re.I)


def fix_public_body(o):
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if not PUBLIC_BODY.match(raw):
        return False
    o.update(agency="State and local bodies", agency_full="State and local bodies", agency_matched=True, jurisdiction="state", agency_org_type="state agency group",
             agency_group=None, agency_unit=None, agency_source="public_body")
    o.pop("actor_unresolved", None)
    return True


# M33 (Oct 14 2026): in a law that amends the New York City school governance provisions (Education Law article 52-A, section 2590-x, or
# 'the city school district of the city of New York'), the principal, board of education, chancellor and community superintendent are the
# NYC Public Schools actors (NYC crosswalk NYCPS). A bare 'the chancellor' needs the city school district named: CUNY and SUNY have chancellors too.
NYC_SCHOOL_LAW = re.compile(r"article\s+52-?A\b|\bsections?\s+2590(?:-\w+)?\b|city\s+school\s+district\s+of\s+the\s+city\s+of\s+new\s+york|city\s+school\s+district\s+having\s+a\s+population\s+of\s+(?:one\s+million|1,000,000)", re.I)
NYC_SCHOOL_ACTOR = re.compile(r"^(?:the |such |each |said )?(?:principals?(?: of (?:each|any|such|the) (?:public )?schools?)?|board of education|chancellor|community superintendents?)$"
                              r"|^(?:the |such |said )?chancellor of the city school district(?: of the city of new york)?$|^the district$", re.I)          # T2 (Oct 18 2026): chancellor wording, 'the District'



# R9 (Oct 31 2026): a named_body agency that is only a generic office phrase ('Principal of Each Public School') is not a named body.
GENERIC_OFFICE_AGENCY = re.compile(r"^(?:the )?(?:principals?|superintendents?|chancellors?|commissioners?|directors?|board of education|board)\b(?:\s+of\s+(?:each|any|such|the|every)\b.*)?$", re.I)


def fix_nyc_school_actor(o, text, nyc_by):
    """Mutates o and returns the rule name when actor_raw is a school-governance officer of a law about the NYC school system and the record is
    Unspecified or a School districts record with no named unit."""
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if not NYC_SCHOOL_ACTOR.match(raw) or "NYCPS" not in nyc_by:
        return None
    generic_named = o.get("agency_source") == "named_body" and GENERIC_OFFICE_AGENCY.match(o.get("agency") or "")          # R9 (Oct 31 2026)
    if not (o.get("agency") == "Unspecified" or generic_named or (o.get("agency") == "School districts" and not o.get("agency_unit"))):
        return None
    if not NYC_SCHOOL_LAW.search(text or ""):
        return None
    if re.search(r"chancellor", raw, re.I) and not re.search(r"city\s+school\s+district", text or "", re.I):
        return None
    a = nyc_by["NYCPS"]
    o.update(agency="NYCPS", agency_full=a.get("full_name") or "NYCPS", agency_matched=True, jurisdiction="nyc", agency_org_type=a.get("org_type"),
             agency_group=None, agency_unit=None, agency_source="nyc_school_actor")
    o.pop("actor_unresolved", None)
    return "m33_nyc_school_actor"


# T1 (Oct 18 2026): in a law about industrial development agencies (General Municipal Law article 18-A) 'each agency' / 'the agency' is an IDA, a local
# public benefit corporation, never All agencies or State agencies.
IDA_LAW = re.compile(r"industrial\s+development\s+agenc(?:y|ies)", re.I)
IDA_ACTOR = re.compile(r"^(?:the |each |an? |every |any |such |said )?agency$", re.I)


def fix_ida_agency(o, text, title, by_canon):
    """Mutates o and returns True when actor_raw is a bare 'agency' in a law whose title or text names industrial development agencies."""
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if not IDA_ACTOR.match(raw) or "Industrial development agencies" not in by_canon:
        return False
    if o.get("agency") not in (None, "Unspecified", "All agencies", "State agencies"):
        return False
    if not (IDA_LAW.search(title or "") or IDA_LAW.search(text or "")):
        return False
    a = by_canon["Industrial development agencies"]
    o.update(agency="Industrial development agencies", agency_full=a.get("full_name") or "Industrial development agencies", agency_matched=True, jurisdiction="local",
             agency_org_type="local government group", agency_group="Industrial development agencies", agency_unit=None, agency_source="ida_agency")
    o.pop("actor_unresolved", None)
    return True


# T5 (Oct 18 2026): 'the employer' in a State employee-contract law (the State is the employer: Civil Service Law article 14, State Finance Law salary acts) is
# the State agencies group, not Public employers.
EMPLOYER_ACTOR = re.compile(r"^(?:the |such |said )?(?:public )?employer$", re.I)
STATE_EMPLOYER_LAW = re.compile(r"article\s+(?:fourteen|14)\s+of\s+the\s+civil\s+service\s+law|\bthe\s+state,?\s+as\s+(?:the\s+)?employer\b|\bstate\s+as\s+(?:the\s+)?employer\b"
                                r"|section\s+2\d\d(?:-\w+)?\s+of\s+the\s+state\s+finance\s+law|\bstate\s+finance\s+law\b[^.]{0,80}\bsalar", re.I)


def fix_state_employer(o, text):
    """Mutates o and returns True when 'the employer' resolved to Public employers (or nothing) in a law where the State is the employer."""
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if not EMPLOYER_ACTOR.match(raw) or o.get("agency") not in (None, "Unspecified", "Public employers"):
        return False
    if not (STATE_EMPLOYER_LAW.search(text or "") or re.search(r"\bstate\b", o.get("actor_resolved_model") or "", re.I)):
        return False
    o.update(agency="State agencies", agency_full="State agencies", agency_matched=True, jurisdiction="state", agency_org_type="state agency group",
             agency_group=None, agency_unit="State of New York", agency_source="state_employer")
    o.pop("actor_unresolved", None)
    return True


# M34 (Oct 14 2026): an assessing unit is a municipality; the named county is context, never the actor.
ASSESSING_UNIT = re.compile(r"^(?:the |such |each |said |any |an? )?(?:approved\s+)?assessing\s+units?(?:\s+(?:located\s+)?in\s+the\s+county\s+of\s+([A-Za-z .'-]+?))?$", re.I)


def fix_assessing_unit(o):
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    m = ASSESSING_UNIT.match(raw)
    if not m or o.get("agency") == "Municipalities (all)":
        return False
    o.update(agency="Municipalities (all)", agency_full="Municipalities (all)", agency_matched=True, jurisdiction="local",
             agency_org_type="local government group", agency_group="Municipalities (all)", agency_unit=None, agency_source="assessing_unit")
    if m.group(1):
        o["actor_context"] = "County of " + m.group(1).strip().title()
    o.pop("actor_unresolved", None)
    return True


# M39 (Oct 15 2026): 'the city of New York, acting by and through the commissioner of parks and recreation' / 'acting through the tlc': the City
# acts through the named agency, so the record is that NYC agency (Council crosswalk), not 'New York City'.
NYC_ACTING = re.compile(r"^(?:the )?city of new york,?\s+acting\s+(?:by\s+and\s+)?through\s+(?:(?:its|the)\s+)?(?:(?:commissioner|director|head|chair(?:man|person)?|president)\s+of\s+(?:the\s+)?)?(.+?)(?:\s+of\s+(?:such|the)\s+city)?$", re.I)


def fix_nyc_acting_through(o, nyc_lookup, nyc_by):
    """Mutates o and returns True when a 'New York City' record's actor_raw names the agency the City acts through and the Council crosswalk resolves it."""
    if o.get("agency") != "New York City":
        return False
    m = NYC_ACTING.match(re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:")))
    if not m:
        return False
    name = m.group(1).strip().lower()
    canon = None
    for cand in (name, "department of " + name, re.sub(r"^department of ", "", name), "the " + name):
        c = nyc_lookup.get(cand)
        if c and c in nyc_by:
            canon = c
            break
    if not canon:
        return False
    a = nyc_by[canon]
    o.update(agency=canon, agency_full=a.get("full_name") or canon, agency_matched=True, jurisdiction="nyc", agency_org_type=a.get("org_type"),
             agency_group=None, agency_unit=None, agency_source="nyc_acting_through")
    o.pop("actor_unresolved", None)
    return True


# U3 (Oct 19 2026): in a law whose title names one authority ('the dissolution of the Montgomery, Otsego, Schoharie solid waste management authority'),
# 'the authority' is that authority, never the Local agencies and authorities group.
TITLE_AUTHORITY = re.compile(r"\bthe\s+((?:[A-Z][\w'’-]*,?\s+(?:and\s+)?)+(?:[\w'’-]+\s+){0,5}?(?i:authority))\b")
AUTHORITY_ACTOR = re.compile(r"^(?:the |such |said )?authority$", re.I)
GENERIC_AGENCIES = {None, "Unspecified", "Local agencies and authorities", "State authorities", "State agencies", "All agencies", "State and local bodies", "Municipalities (all)"}


def fix_title_authority(o, title, lookup=None, by_canon=None):
    """Mutates o and returns True when actor_raw is 'the authority' / 'such authority' and the law title names exactly one authority."""
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if not AUTHORITY_ACTOR.match(raw) or o.get("agency") not in GENERIC_AGENCIES:
        return False
    names = {re.sub(r"\s+", " ", m.group(1)).strip().lower(): m.group(1) for m in TITLE_AUTHORITY.finditer(re.sub(r"\s+", " ", title or ""))}
    if len(names) != 1:
        return False
    low, name = next(iter(names.items()))
    name = title_case(re.sub(r"\s+", " ", name).strip())
    canon = (lookup or {}).get(low) or (lookup or {}).get(norm(name))
    if canon:
        a = (by_canon or {}).get(canon) or {}
        o.update(agency=canon, agency_full=a.get("full_name") or canon, agency_matched=True, jurisdiction=a.get("jurisdiction") or o.get("jurisdiction"),
                 agency_org_type=a.get("org_type") or o.get("agency_org_type"), agency_group=None, agency_unit=None, agency_source="title_authority")
        o.pop("actor_unresolved", None)
        return True
    words = [w.strip(",") for w in name.split()]
    local = bool(LOCAL_NOUN.search(name)) or any(county_name(" ".join(words[i:i + 1])) for i in range(len(words))) or bool(re.search(r"\b(?:counties|county|town|village|city|municipal|regional)\b", title or "", re.I))
    o.update(agency=name, agency_full=name, agency_matched=True, jurisdiction="local" if local else "state", agency_org_type="public authority",
             agency_group=None, agency_unit=None, agency_source="title_authority")
    o.pop("actor_unresolved", None)
    return True


# U8 (Oct 19 2026): 'city school district of Yonkers' / 'the Yonkers city school district' is School districts with the unit '<City> City School District'; the
# one of the City of New York is NYCPS. 'the court' / 'the family court' / 'the supreme court' is the Unified Court System, never a city or county.
CSD_NYC = re.compile(r"^(?:the )?city school district of (?:the )?(?:city of )?new york(?: city)?$|^(?:the )?new york(?: city)? city school district$", re.I)
CSD_OF = re.compile(r"^(?:the )?city school district of (?:the )?(?:city of )?([A-Za-z][A-Za-z .'-]*?)$", re.I)
CSD_NAMED = re.compile(r"^(?:the )?([A-Za-z][A-Za-z .'-]*?)\s+city school district$", re.I)
CSD_NOT_CITY = {"the", "of", "such", "said", "each", "any", "a", "an", "chancellor", "board", "superintendent", "president", "members", "member", "clerk", "trustees", "principal", "office", "department"}
COURT_ACTOR = re.compile(r"^(?:the |such |said |a )?(?:family |supreme |surrogate's |county |criminal )?court$", re.I)
LOCAL_COURT_GROUPS = {"Cities", "Counties", "Towns", "Villages", "Municipalities (all)", "Local agencies and authorities"}


def fix_city_school_district(o, nyc_by):
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if CSD_NYC.match(raw):
        if "NYCPS" not in nyc_by or o.get("agency") == "NYCPS":
            return False
        a = nyc_by["NYCPS"]
        o.update(agency="NYCPS", agency_full=a.get("full_name") or "NYCPS", agency_matched=True, jurisdiction="nyc", agency_org_type=a.get("org_type"),
                 agency_group=None, agency_unit=None, agency_source="city_school_district")
        o.pop("actor_unresolved", None)
        return True
    m = CSD_OF.match(raw) or CSD_NAMED.match(raw)
    if not m:
        return False
    city = title_case(re.sub(r"\s+", " ", m.group(1)).strip())
    if not city or len(city.split()) > 3 or any(w.lower() in CSD_NOT_CITY for w in city.split()):          # 'the chancellor of the city school district' names an officer
        return False
    unit = city + " City School District"
    o.update(agency="School districts", agency_full="School districts", agency_matched=True, jurisdiction="local", agency_org_type="local government group",
             agency_group="School districts", agency_unit=unit, agency_source="city_school_district")
    o.pop("actor_unresolved", None)
    return True


def fix_court_actor(o, by_canon):
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if not COURT_ACTOR.match(raw):
        return False
    unit = o.get("agency_unit") or ""
    if not (o.get("agency") in LOCAL_COURT_GROUPS or re.match(r"(?:City|County|Town|Village) of\b", unit)):
        return False
    a = by_canon.get("Unified Court System") or {}
    o.update(agency="Unified Court System", agency_full=a.get("full_name") or "Unified Court System", agency_matched=True, jurisdiction="state",
             agency_org_type=a.get("org_type") or "judiciary", agency_group=None, agency_unit=None, agency_source="court_actor")
    o.pop("actor_unresolved", None)
    return True


# ---- Oct 27 2026 night (R1-R5) ----------------------------------------------------------------------------------------------
OTB_REGIONS = ("Capital", "Catskill", "Nassau", "Suffolk", "Western")
OTB_BRANCH = re.compile(r"off-?track betting corporation(?:s)? branch offices?|branch offices? of (?:the |each |every |any |an? )?(?:(?:capital|catskill|nassau|suffolk|western)(?: district| region)? )?(?:regional )?off-?track betting corporations?", re.I)
OTB_GROUP = "Off-track betting corporations"


def _set_group(o, group, jur, otype, unit, rule):
    o.update(agency=group, agency_full=group, agency_matched=True, jurisdiction=jur, agency_org_type=otype,
             agency_group=group if otype == "local government group" else None, agency_unit=unit, agency_source=rule)
    o.pop("actor_unresolved", None)
    return rule


def fix_otb_branch(o):
    """R1: 'every off-track betting corporation branch office' is the regional off-track betting corporation the text names
    (Capital, Catskill, Nassau, Suffolk, Western), else the group; never a 'branch offices' body."""
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if not OTB_BRANCH.search(raw):
        return False
    hay = " ".join(str(o.get(k) or "") for k in ("actor_raw", "quote", "action_summary", "actor_resolved_model"))
    named = [r for r in OTB_REGIONS if re.search(r"\b%s(?:\s+(?:district|region))?(?:\s+regional)?\s+off-?track" % r, hay, re.I)]
    unit = ("%s Regional Off-Track Betting Corporation" % named[0]) if len(named) == 1 else None
    _set_group(o, OTB_GROUP, "local", "local government group", unit, "otb_branch")
    return True


STATE_COMMISSION = re.compile(r"^(?:the |such |said )?(state )?(?:commission|council) (?:of|on|for) (?!(?:the )?(?:cit(?:y|ies)|towns?|villages?|count(?:y|ies)|school|municipal|board of education)\b)(.+)$", re.I)


def fix_state_commission(o, lookup, by_canon, match):
    """R2: a named State commission or council resolves to its own crosswalk code; with no code it is State agencies (unit = its
    name), never State authorities. A record already on a crosswalk code is never demoted to a group."""
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    m = STATE_COMMISSION.match(raw)
    if not m:
        return False
    body = re.sub(r"^(?:the |such |said )", "", raw, flags=re.I)
    plain = re.sub(r"^state\s+", "", body, flags=re.I)
    canon = None
    for v in (body, plain, "state " + plain):
        canon, _ = match(v.lower(), lookup, by_canon)
        if canon:
            break
    if canon:
        if o.get("agency") == canon:
            return False
        a = by_canon[canon]
        o.update(agency=canon, agency_full=a.get("full_name") or canon, agency_matched=True, jurisdiction=a.get("jurisdiction") or "state",
                 agency_org_type=a.get("org_type"), agency_group=None, agency_unit=None, agency_source="state_commission")
        o.pop("actor_unresolved", None)
        return True
    cur = o.get("agency")
    if cur in by_canon and cur not in ("State authorities", "State agencies"):
        return False
    if cur == "State agencies" and o.get("agency_unit"):
        return False
    if not (m.group(1) or cur in (None, "Unspecified", "State authorities", "State agencies") or o.get("agency_source") in ("named_body", "group")):
        return False
    if o.get("jurisdiction") not in (None, "state"):
        return False
    _set_group(o, "State agencies", "state", "state agency group", title_case(plain), "state_commission")
    return True


LOC_UNIT = re.compile(r"^(City|Town|Village|County) of (.+)$")


def locality_title(unit):
    """R3: 'Village of Hastings-on-hudson' -> 'Village of Hastings-on-Hudson'; only 'City/Town/Village/County of X' units."""
    m = LOC_UNIT.match(unit or "")
    if not m:
        return unit
    return m.group(1) + " of " + title_case(m.group(2))


def fix_unit_casing(o):
    new = locality_title(o.get("agency_unit"))
    if new and new != o.get("agency_unit"):
        o["agency_unit"] = new
        return True
    return False


OFFICER_OF_AGENCY = re.compile(r"^(?:the |such |said |each |every )?(?:chief executive officer|chief executive|head|commissioner|director|chair(?:man|person)?|executive director|secretary|president|chief administrative officer)s? of (?:such|that|the said|said|each such|any such|the same) (?:state )?(?:agency|department|authority|office|board|commission|division)(?:,? (?:agency|department|authority|office|board|commission|division))*(?:,? (?:or|and) (?:agency|department|authority|office|board|commission|division))?$", re.I)


def fix_officer_phrase(o, text, lookup, by_canon):
    """R4: 'the chief executive officer of that agency' is an officer phrase, not an agency name. It resolves to the one crosswalk
    agency the sentence names (the quote), else State agencies."""
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if not OFFICER_OF_AGENCY.match(raw):
        return False
    if o.get("agency") in by_canon and o.get("agency") not in ("State agencies", "State authorities"):
        return False
    quote = (o.get("quote") or "")
    found = set()
    for k, canon in lookup.items():
        if len(k) >= 6 and canon in by_canon and re.search(r"\b%s\b" % re.escape(k), quote, re.I):
            found.add(canon)
    if len(found) == 1:
        c = next(iter(found)); a = by_canon[c]
        o.update(agency=c, agency_full=a.get("full_name") or c, agency_matched=True, jurisdiction=a.get("jurisdiction") or "state",
                 agency_org_type=a.get("org_type"), agency_group=None, agency_unit=None, agency_source="officer_phrase")
        o.pop("actor_unresolved", None)
        return True
    _set_group(o, "State agencies", "state", "state agency group", None, "officer_phrase")
    return True


SCHOOL_BOARD_ACTOR = re.compile(r"^(?:the |such |said |each )?(?:board of education|school board)(?:\s+of\s+(?:the\s+)?(?:city school district|city)(?:\s+of\s+(?:the\s+)?(?:city of\s+)?([A-Za-z][A-Za-z .'-]*))?)?$", re.I)


def fix_city_school_board(o):
    """R5: the board of education / school board of a named city is School districts with unit '<City> City School District',
    never the city (the Oct 19 U8 rule covers 'city school district of <city>' wording only). New York City is NYCPS (M33)."""
    if o.get("agency") not in ("Cities", "Towns", "Villages", "Counties") and not (o.get("agency_unit") or "").startswith("City of"):
        return False
    m = SCHOOL_BOARD_ACTOR.match(re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:")))
    if not m:
        return False
    um = re.match(r"^City of (.+)$", o.get("agency_unit") or "")
    city = title_case(m.group(1).strip()) if m.group(1) else (um.group(1) if um else None)
    if not city or re.fullmatch(r"(?i)(?:the )?new york(?: city)?", city) or len(city.split()) > 3 or any(w.lower() in CSD_NOT_CITY for w in city.split()):
        return False
    if um and um.group(1).lower() != city.lower():
        return False
    _set_group(o, "School districts", "local", "local government group", city + " City School District", "city_school_board")
    return True


# ---- Oct 29 2026 night (K1-K3) ----------------------------------------------------------------------------------------------
COURT_Q = r"(?:family|supreme|surrogate'?s|county|criminal|local criminal|sentencing|appointing|superior|human trafficking)"
K1_COURT = re.compile(r"^(?:(?:%s)\s+)+courts?\b(?:\s+(?:or|and)\s+(?:the\s+)?(?:%s\s+)+courts?)?\b|^courts? having jurisdiction\b|^court of (?:competent jurisdiction|appeals)\b|^appellate (?:division|term)\b|^justices? of the supreme court\b|^courts?$" % (COURT_Q, COURT_Q), re.I)
K2_LEADER = re.compile(r"^(?:temporary president(?: of the senate)?|speaker(?: of the assembly)?|(?:minority|majority) leaders? of the (?:senate|assembly)|chairs? of the senate finance (?:committee )?and (?:the )?assembly ways and means committees?)$", re.I)
K3_BODY = re.compile(r"^(?:applicable governing bod(?:y|ies) or (?:the )?tax departments?|governing body of (?:such|the) municipality)$", re.I)
LOC_IN_TEXT = re.compile(r"\b(City|Town|Village|County) of ((?:[A-Z][\w.'-]*)(?: [A-Z][\w.'-]*){0,2})")


# K4 (Oct 30 2026): 'the city' / 'such city' / 'the mayor' in a law that names the city of New York and no other city is New York City, not the Cities group.
K4_CITY_ACTOR = re.compile(r"^(?:(?:the|such|said) )?(?:city|mayor)(?:'?s)?$", re.I)
K4_NYC_TEXT = re.compile(r"city of new york|new york city", re.I)
K4_OTHER_CITY = re.compile(r"\b[Cc]ity of (?!New York\b)([A-Z][\w.'-]*)")


def fix_city_is_nyc(o, by_canon, text=""):
    """K4: True when a bare city/mayor actor in an NYC-only law was set to the New York City entry."""
    raw = strip_art(re.sub(r"\s+", " ", norm(o.get("actor_raw") or "")))
    if not K4_CITY_ACTOR.match(raw) or "New York City" not in by_canon:
        return False
    if o.get("agency") not in ("Cities", "Unspecified") or o.get("agency_unit"):
        return False
    blob = (text or "") + " " + (o.get("quote") or "")
    if not K4_NYC_TEXT.search(blob) or K4_OTHER_CITY.search(blob):
        return False
    a = by_canon["New York City"]
    o.update(agency="New York City", agency_full=a.get("full_name") or "New York City", agency_matched=True, jurisdiction="nyc",
             agency_org_type=a.get("org_type") or "local government group", agency_group="New York City", agency_unit=None, agency_source="city_is_nyc_k4")
    o.pop("actor_unresolved", None)
    return True


# ---- Oct 31 2026 night: the agency field holds a raw office title instead of the body --------------------------------------
OFFICE_TITLE = re.compile(r"^(?:the )?(?:commissioner|director|superintendent|president)\s+of\s+(?:the\s+)?(.+?)(?:\s+of\s+(?:the\s+)?(?:(city)|(state))(?:\s+of\s+new\s+york)?)?$", re.I)
MWBD_DIVISION = re.compile(r"^(?:the )?(?:director of the )?division of minority and women(?:-owned business|'s business|’s business| owned business) development$", re.I)
CHIEF_DIVERSITY = re.compile(r"^(?:the|an?)\s+chief diversity officer(?:\s+for\s+the\s+state)?$", re.I)
OFPC_ACTOR = re.compile(r"^(?:the )?(?:office of fire prevention and control|state fire administrator)$", re.I)
NAMED_LIBRARY = re.compile(r"^(?:([A-Za-z.'’-]+(?: [A-Za-z.'’-]+){0,3}?) (?:city |free |public )?library|public library of ([A-Za-z.'’ -]+))$", re.I)
COUNTY_BOE = re.compile(r"^(?:the |each |a |such )?(?:county )?board of elections(?: of (?:the |each )?county(?: of ([A-Za-z .'-]+))?)?$", re.I)
COUNTY_NAMED = re.compile(r"\b[Cc]ounty of ([A-Z][A-Za-z.'-]*(?: [A-Z][A-Za-z.'-]*){0,2})\b|\b([A-Z][A-Za-z.'-]*) [Cc]ounty\b")
LOCALITY_NAMED = re.compile(r"\b([Cc]ity|[Tt]own|[Vv]illage|[Cc]ounty) of ((?:[A-Z][\w.'-]*)(?: [A-Z][\w.'-]*){0,2})")
REGENTS_CHANCELLOR = re.compile(r"^(?:the )?chancellor(?: or the commissioner)?$|^(?:the )?chancellor of the (?:board of )?regents(?: of the university of the state of new york)?$", re.I)
ASSESSING_ANY = re.compile(r"^(?:the |such |each |said |any |all |an? )?(?:legislative body of (?:the |such |each |said |any |an? )?)?(?:(?:approved|special|participating)\s+)?assessing\s+units?(?:\s+(?:that is not a city|which is a city|that is a city|(?:located )?in the county of [A-Za-z .'-]+?))?$|^(?:the )?(?:approved|special|participating)?\s*assessing units$", re.I)
GOER_RE = re.compile(r"^governor(?:'|’)s office of employee relations$", re.I)
_NYC_CW = {}


def _nyc_cw():
    if not _NYC_CW:
        import json
        from pathlib import Path
        d = json.loads((Path(__file__).resolve().parent.parent.parent / "legislation_implementation_tracker" / "data" / "agency_crosswalk.json").read_text())
        _NYC_CW.update(lookup=d["lookup"], by={a["canonical"]: a for a in d["agencies"]})
    return _NYC_CW


def _set_body(o, a, canon, jur, unit, rule):
    o.update(agency=canon, agency_full=a.get("full_name") or canon, agency_matched=True, jurisdiction=jur, agency_org_type=a.get("org_type"),
             agency_group=None, agency_unit=unit, agency_source=rule)
    o.pop("actor_unresolved", None)
    return True


def fix_20261031(o, by_canon, lookup=None, text=""):
    """R1-R3 (Oct 31 2026). Returns True when a raw office title in `agency` (or the chief diversity officer in actor_raw) was
    replaced by the body it heads. Runs on matched and unmatched records; titles whose body the crosswalks cannot resolve are left alone."""
    ag = re.sub(r"\s+", " ", (o.get("agency") or "").strip(" .,;:"))
    raw = re.sub(r"\s+", " ", (o.get("actor_raw") or "").strip(" .,;:"))
    if CHIEF_DIVERSITY.match(raw) and o.get("agency") in (None, "Unspecified") and "Governor" in by_canon:
        return _set_body(o, by_canon["Governor"], "Governor", "state", "Chief Diversity Officer", "office_title_20261031")
    if OFPC_ACTOR.match(raw) and "DHSES" in by_canon and (o.get("agency") in (None, "Unspecified", "DOS", "DHSES") or ag not in by_canon):
        yr = (o.get("enactment_date") or "")[:4] or str(o.get("chapter_year") or "")
        if yr.isdigit() and int(yr) >= 2010:
            return _set_body(o, by_canon["DHSES"], "DHSES", "state", "Office of Fire Prevention and Control", "ofpc_to_dhses_r4")
        return False
    if COUNTY_BOE.match(raw) and o.get("agency") in ("Counties", "Unspecified"):
        unit = None
        for src in (raw, o.get("quote"), o.get("law_title"), text):
            mm = COUNTY_NAMED.search(src or "")
            if mm:
                unit = "County of " + (mm.group(1) or mm.group(2)).strip()
                break
        unit = unit or o.get("agency_unit")
        if unit and not str(unit).lower().startswith(("county of", "city of")):
            unit = None
        _set_group(o, "Boards of elections", "local", "local government group", unit, "county_boe_r6")
        return True
    if ASSESSING_ANY.match(raw) and o.get("agency") in ("Municipalities (all)", "Unspecified", "Counties", "Cities", "Towns", "Villages") and not (o.get("agency") == "Municipalities (all)" and o.get("agency_unit")):
        unit = None
        for src in (raw, o.get("quote"), o.get("law_title"), text):
            mm = LOCALITY_NAMED.search(src or "")
            if mm:
                unit = mm.group(1).title() + " of " + mm.group(2).strip()
                break
            mm = COUNTY_NAMED.search(src or "")
            if mm:
                unit = "County of " + (mm.group(1) or mm.group(2)).strip()
                break
        if unit:
            _set_group(o, "Municipalities (all)", "local", "local government group", unit, "assessing_unit_r7")
            return True
    if REGENTS_CHANCELLOR.match(raw or ag) and "Board of Regents" in by_canon and (o.get("agency") in (None, "Unspecified") or re.match(r"^chancellor of the (?:board of )?regents", ag, re.I)) \
            and (re.search(r"regents", (o.get("quote") or "") + " " + ag, re.I)):
        return _set_body(o, by_canon["Board of Regents"], "Board of Regents", "state", "Chancellor", "regents_chancellor_r8")
    m5 = NAMED_LIBRARY.match(strip_art(raw)) if raw else None
    if m5 and o.get("agency") in ("School districts", "Unspecified"):
        name = (m5.group(1) or m5.group(2) or "").strip()
        if name and not re.match(r"^(?:state|school|such|each|the|a|an|existing|public|free|city)$", name, re.I):
            _set_group(o, "Public libraries", "local", "local government group", title_case(strip_art(raw)), "named_library_r5")
            o["agency_group"] = "Public libraries"
            return True
    if not ag or ag in by_canon:
        return False
    if MWBD_DIVISION.match(ag) and "ESD" in by_canon:
        return _set_body(o, by_canon["ESD"], "ESD", "state", "Division of Minority and Women-Owned Business Development", "office_title_20261031")
    m = OFFICE_TITLE.match(ag)
    if not m:
        return False
    x = m.group(1).strip().lower()
    city = bool(m.group(2)) or o.get("jurisdiction") == "nyc"
    if GOER_RE.match(x) and "OER" in by_canon:
        return _set_body(o, by_canon["OER"], "OER", "state", None, "office_title_20261031")
    cands = (x, "department of " + x, "office of " + x)
    if city:
        cw = _nyc_cw()
        for c in cands:
            k = cw["lookup"].get(c)
            if k in cw["by"]:
                return _set_body(o, cw["by"][k], k, "nyc", None, "office_title_20261031")
        return False
    lk = lookup if lookup is not None else __import__("extract_duties").LOOKUP
    for c in cands:
        k = lk.get(c)
        if k in by_canon:
            return _set_body(o, by_canon[k], k, by_canon[k].get("jurisdiction") or "state", None, "office_title_20261031")
    return False


def fix_20261029(o, by_canon, text="", lookup=None):
    """K1 court actors, K2 legislative leaders, K3 'governing body' phrases. Returns True when it set the agency."""
    if fix_20261031(o, by_canon, lookup, text):
        return True
    raw = strip_art(re.sub(r"\s+", " ", norm(o.get("actor_raw") or "")))
    if not raw:
        return False
    if fix_city_is_nyc(o, by_canon, text):
        return True
    if K1_COURT.match(raw):
        if o.get("agency") not in LOCAL_COURT_GROUPS and o.get("agency") != "Unspecified":
            return False
        a = by_canon.get("Unified Court System") or {}
        o.update(agency="Unified Court System", agency_full=a.get("full_name") or "Unified Court System", agency_matched=True, jurisdiction="state",
                 agency_org_type=a.get("org_type") or "judiciary", agency_group=None, agency_unit=None, agency_source="court_actor_k1")
        o.pop("actor_unresolved", None)
        return True
    if K2_LEADER.match(raw):
        _set_group(o, "State Legislature", "state", "state agency group", o.get("agency_unit"), "legislative_leader_k2")
        return True
    if K3_BODY.match(raw):
        # Narrowed Oct 29 2026: a locality named anywhere (stored unit, quote or law text) keeps its specific group and unit.
        if o.get("agency_unit") or LOC_IN_TEXT.search(o.get("quote") or "") or LOC_IN_TEXT.search(text or ""):
            return False
        if o.get("agency") not in ("Villages", "Towns", "Cities", "Counties", "Unspecified"):
            return False
        _set_group(o, "Municipalities (all)", "local", "local government group", None, "governing_body_k3")
        return True
    return False


def fix_20261027(o, text, lookup, by_canon, match):
    """One entry point for R1-R5 (and R3 unit casing). `match` is eo.match_agency. Returns the rule name or None."""
    rule = None
    if fix_20261029(o, by_canon, text, lookup):
        return o.get("agency_source")
    if fix_otb_branch(o):
        rule = "r1_otb_branch"
    elif fix_state_commission(o, lookup, by_canon, match):
        rule = "r2_state_commission"
    elif fix_officer_phrase(o, text, lookup, by_canon):
        rule = "r4_officer_phrase"
    elif fix_city_school_board(o):
        rule = "r5_city_school_board"
    if fix_unit_casing(o) and not rule:
        rule = "r3_unit_casing"
    return rule
