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
    "state liquor authority": "ABC", "liquor authority": "ABC", "new york state liquor authority": "ABC",
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
    (r"^(?:state )?(?:agency|agencies)$|^state (?:agency|agencies|departments?|officers?|entit(?:y|ies))\b|^all state agencies|^(?:state )?contracting agenc|^authorized state entit|^(?:state )?(?:agency|agencies) (?:and|or) (?:authorit|commission)", "State agencies", "state", "state agency group"),
    (r"^state (?:authorit(?:y|ies)|financing agenc|commission)|^public (?:authorit(?:y|ies)|benefit corporations?)|^subsidiary public benefit|^(?:every )?member, officer or employee of a state authority|^(?:state authorities|public authorities)", "State authorities", "state", "state agency group"),
    (r"^(?:state|local) (?:and|or) (?:local|state|municipal)\b|^all state and local|^state and local", "State and local bodies", "state", "state agency group"),
    (r"^(?:local )?(?:authorit(?:y|ies)|agenc(?:y|ies)|municipal commissions?|municipal corporations?)$|^local (?:authorit|agenc|offic)|^municipal commission", "Local agencies and authorities", "local", "local government group"),
    (r"^(?:municipalit(?:y|ies)|governmental (?:entit(?:y|ies)|agenc(?:y|ies))|public bod(?:y|ies)|governmental agencies|special assessing units?|cities that are special|special assessing)", "Municipalities (all)", "local", "local government group"),
    (r"^(?:county )?boards? of elections?|^(?:central )?boards? of inspectors|^(?:the )?inspectors?(?: of election)?$|^(?:clerks or )?inspectors|^each polling place|^any polling place|^election inspectors|^bipartisan team of inspectors|^boards of election", "Boards of elections", "local", "local government group"),
    (r"^social services (?:district|official)", "Social services districts", "local", "local government group"),
    (r"^(?:the )?(?:courts?|court of this state|court having jurisdiction|courts having jurisdiction|new york state courts|judge|justice|any judge|trier of fact|unspecified court)\b|^(?:courts|court)$|^(?:a )?court\b", "Unified Court System", "state", "judiciary"),
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


def norm(s):
    s = re.sub(r"\([^)]*\)", " ", (s or "").lower())
    s = s.replace("’", "'")
    s = re.sub(r"\s+", " ", s).strip(" .,;:")
    return s


def strip_art(s):
    return re.sub(r"^(?:the|such|said|each|every|any|a|an)\s+", "", s)


def title_case(s):
    small = {"of", "the", "and", "in", "on", "for", "to", "a"}
    return " ".join(w if (i and w in small) else (w[:1].upper() + w[1:]) for i, w in enumerate(s.split()))


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
