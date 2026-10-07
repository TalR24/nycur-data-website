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
import argparse, json, os, re, sys
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
    p = _sub(p, '- Do not invent obligations', '- When the only new matter extends an existing duty or power (a new expiry date, a changed amount or limit, an added place or district), still record it and set extends_existing true; otherwise false.\n- Do not invent obligations')
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
def signed_laws():
    out = []
    for b in json.load(open(DATA / "bills.json")):
        if not b.get("chapter"):
            continue
        key = "%s-%s" % (b["session"], b["base_print_no"])
        out.append({"matter_id": key, "key": key, "session": b["session"], "print_no": b["base_print_no"],
                    "chapter_number": b["chapter"]["number"], "chapter_year": b["chapter"]["year"],
                    "signed_date": b["chapter"]["signed_date"], "enactment_date": b["chapter"]["signed_date"],
                    "title": b["title"], "act_clause": b.get("act_clause"), "law_section": b.get("law_section"),
                    "sponsor": (b.get("sponsor") or {}).get("full_name"), "openleg_url": b.get("openleg_url"),
                    "law_number_display": "Chapter %d of %d" % (b["chapter"]["number"], b["chapter"]["year"])})
    return out


def load_todo(emit=False):
    todo, deferred = [], []
    for law in signed_laws():
        text = (TEXT_MARKED / (law["key"] + ".txt")).read_text()
        if len(text) > MAX_CHARS:
            deferred.append({"key": law["key"], "chapter": law["chapter_number"], "year": law["chapter_year"], "chars": len(text), "title": law["title"]})
        else:
            todo.append((law, text))
    return todo, deferred


def effective_table(laws):
    tab = {}
    for law in laws:
        text = (TEXT_MARKED / (law["key"] + ".txt")).read_text()
        tab[law["key"]] = parse_effective(text, law["signed_date"])
    return tab


def prepare(law, raw):
    """Replace the model's effective clause with the deterministic parse (the model still answers the schema field)."""
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


def _title(s):
    small = {"of", "the", "and", "in", "on", "for"}
    return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(s.split()))


def attach_jurisdiction(o):
    """Set jurisdiction / org_type / agency_group, and rescue unmatched local and NYC actors. Mutates the record."""
    if o.get("agency_matched") and o["agency"] in BY_CANON:
        a = BY_CANON[o["agency"]]
        o["jurisdiction"], o["agency_org_type"] = a["jurisdiction"], a["org_type"]
        o["agency_group"] = o["agency"] if a["org_type"] == "local government group" else None
        return
    names = [x for x in (o.get("actor_raw"), o.get("agency")) if x]
    for n in names:
        n2 = re.sub(r"^(?:the |such |said )", "", re.sub(r"\([^)]*\)", "", n.strip()), flags=re.I).strip()
        m = re.search(r"(?:^|\bof the |\bof )(town|village|city|county)\s+of\s+(?!the\b)(.+?)$", n2, re.I)
        if m and not NYC_MARKERS.search(n2):
            kind = m.group(1).lower()
            o.update(agency=_title("%s of %s" % (kind, m.group(2))), agency_full=_title("%s of %s" % (kind, m.group(2))), agency_matched=True,
                     jurisdiction="local", agency_org_type="local government", agency_group=LOCAL_GROUPS[kind])
            return
        m = re.match(r"^(.+?)\s+county$", n2, re.I)
        if m and len(n2.split()) <= 4 and not re.match(r"(?i)^(each|any|every|a|such|that|the same)\b", m.group(1)):
            o.update(agency=_title(n2), agency_full=_title(n2), agency_matched=True, jurisdiction="local", agency_org_type="local government", agency_group="Counties")
            return
        if re.search(r"(?i)\bschool district$", n2) and len(n2.split()) <= 6 and not re.match(r"(?i)^(each|any|every|a|such|the)\b", n2):
            o.update(agency=_title(n2), agency_full=_title(n2), agency_matched=True, jurisdiction="local", agency_org_type="local government", agency_group="School districts")
            return
    for n in names:
        if NYC_MARKERS.search(n):
            canon, full = eo.match_agency(n, NYC_LOOKUP, NYC_BY)
            if canon:
                o.update(agency=canon, agency_full=full, agency_matched=True, jurisdiction="nyc", agency_org_type=NYC_BY[canon].get("org_type"), agency_group=None)
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


# ── Ingest ──────────────────────────────────────────────────────────────────────────────────────────────────────
def write_cache(mid, res):
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    if mid in EXT_MODEL:
        res["extends_model"] = EXT_MODEL[mid]
    (EXTRACTED / (mid + ".json")).write_text(json.dumps(res, indent=1, ensure_ascii=False))


def build_records(laws):
    by_key = {l["key"]: l for l in laws}
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
            attach_jurisdiction(o)
            o["extends_existing"] = bool(res.get("extends_model", {}).get(o["obligation_id"])) or extends_by_text(o.get("quote") or "", text)
            if kind == "power":
                o["deadline_kind"], o["deadline_date"] = "none", None
            if o.get("deadline_kind") in (None, "none") and o.get("deadline_date") and o["deadline_date"] == res.get("effective_date"):
                o["deadline_date"] = None
            rec = {**o, "kind": kind, "chapter": law["chapter_number"], "chapter_year": law["chapter_year"],
                   "session": law["session"], "print_no": law["print_no"], "law_number_display": law["law_number_display"],
                   "law_title": law["title"], "prime_sponsor": law["sponsor"], "enactment_date": law["enactment_date"],
                   "effective_date": eff["effective_date"], "effective_rule": eff["rule"], "law_expires_date": eff["expires_date"],
                   "openleg_url": law["openleg_url"], "extraction_model": res.get("model")}
            (law_p if kind == "power" else law_d).append(rec)
        eo.merge_split_list_duplicates(law_d)
        eo.merge_split_list_duplicates(law_p)
        duties += law_d
        powers += law_p
    return duties, powers, excluded


def main():
    global EFFECTIVE
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-packets", metavar="DIR")
    ap.add_argument("--ingest", metavar="DIR")
    a = ap.parse_args()
    laws = signed_laws()
    EFFECTIVE = effective_table(laws)
    json.dump(EFFECTIVE, open(DATA / "effective_dates.json", "w"), indent=1)
    todo, deferred = load_todo()
    json.dump({"rule": "signed laws whose marked text exceeds %d characters (budget bills, recodifications) wait for a later phase" % MAX_CHARS,
               "laws": deferred}, open(DATA / "deferred_long.json", "w"), indent=1)
    if a.emit_packets:
        d = Path(a.emit_packets)
        (d / "results").mkdir(parents=True, exist_ok=True)
        eo.emit_packets(d, todo, fixed_prompt=FIXED_PROMPT, render=render_variable_prompt, schema=SCHEMA)
        sizes = sorted(os.path.getsize(d / (l["key"] + ".txt")) for l, _ in todo)
        print("packets %d (signed laws %d, deferred long %d); bytes min %d median %d max %d" % (len(todo), len(laws), len(deferred), sizes[0], sizes[len(sizes) // 2], sizes[-1]))
        return
    if a.ingest:
        d = Path(a.ingest)
        done, left = eo.ingest_packets(d, todo, LOOKUP, BY_CANON, "max-subagent", writer=write_cache, prepare=prepare, schema=SCHEMA)
        duties, powers, excluded = build_records(laws)
        json.dump({"generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "obligations": duties}, open(DATA / "duties.json", "w"), indent=1, ensure_ascii=False)
        json.dump({"generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "powers": powers}, open(DATA / "powers.json", "w"), indent=1, ensure_ascii=False)
        print("ingested %d laws, %d left (missing or invalid result); duties %d, powers %d, excluded (private or neither) %d" % (len(done), len(left), len(duties), len(powers), excluded))


if __name__ == "__main__":
    main()
