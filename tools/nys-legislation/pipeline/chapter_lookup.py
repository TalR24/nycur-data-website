"""Look up the chapter an act points to ("same date and in the same manner as a chapter of the laws of 2022 ... as
proposed in legislative bills numbers S. 1997-A and A. 286-A", or "chapter 815 of the laws of 2022") through the Open
Legislation API, and return its signing date and effective date. Lookups are cached in data/chapter_index.json.
Resolver signature used by effective_date.parse_effective: resolver(bills=[("S", 1997), ("A", 286)], chapter=None, year=2022)."""
import json, os, re
import openleg

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "..", "data", "chapter_index.json")
CHAP_RE = re.compile(r"SIGNED\s+CHAP(?:TER)?\s*\.?\s*(\d+)", re.I)
_idx = None


def _load():
    global _idx
    if _idx is None:
        _idx = json.load(open(INDEX)) if os.path.exists(INDEX) else {}
    return _idx


def _save():
    json.dump(_idx, open(INDEX, "w"), indent=1, sort_keys=True)


def session_for(year):
    return year if year % 2 else year - 1


def _from_bill(session, base):
    """Signed bill -> {chapter, year, signed_date, effective_date, rule, bill} or None (not signed / not found)."""
    import text_markup
    from effective_date import parse_effective
    d = openleg.get("/api/3/bills/%d/%s" % (session, base), {"fullTextFormat": ["HTML", "PLAIN"]})
    if not d:
        return None
    r = d["result"]
    chap = signed = None
    for a in (r.get("actions") or {}).get("items") or []:
        m = CHAP_RE.search(a.get("text") or "")
        if m:
            chap, signed = int(m.group(1)), a["date"]
    if chap is None:
        return None
    a = (r.get("amendments") or {}).get("items", {}).get(r.get("activeVersion") or "") or {}
    h, p = a.get("fullTextHtml"), a.get("fullText")
    txt = text_markup.from_html(h) if h else text_markup.from_plain_old(p or "")
    e = parse_effective(txt, signed, resolver=_hop)        # M40: follows a chain of references, 3 hops at most
    return {"bill": "%d-%s" % (session, base), "chapter": chap, "year": int(signed[:4]), "signed_date": signed,
            "effective_date": e["effective_date"], "rule": e["rule"], "raw_clause": e["raw_clause"],
            "expires_date": e.get("expires_date"), "section_dates": [x for x in e.get("section_dates") or [] if x.get("expires_date")]}


TEXT_MARKED = os.path.join(HERE, "cache", "text_marked")
DATA_DIR = os.path.join(HERE, "..", "data")


def _local_bill(session, base):
    """M9 (Oct 11 2026): a bill the act names ('as proposed in legislative bills numbers S.459 and A.5251') is looked up first in the
    signed index data/signed/{session}.json, with its effective date parsed from the cached marked text (one hop) or read from
    data/effective_dates/{session}.json. Returns the chapter_lookup record shape, or None when the bill is not in the index."""
    from effective_date import parse_effective
    p = os.path.join(DATA_DIR, "signed", "%d.json" % session)
    if not os.path.exists(p):
        return None
    hit = next((l for l in json.load(open(p)) if re.sub(r"[A-Za-z]$", "", l["print_no"]) == base), None)
    if not hit:
        return None
    tp = os.path.join(TEXT_MARKED, hit["key"] + ".txt")
    ep = os.path.join(DATA_DIR, "effective_dates", "%d.json" % session)
    if os.path.exists(tp):
        e = parse_effective(open(tp).read(), hit["signed_date"], resolver=_hop)
    elif os.path.exists(ep) and hit["key"] in json.load(open(ep)):
        e = json.load(open(ep))[hit["key"]]
    else:
        return None
    return {"bill": hit["key"], "chapter": hit["chapter_number"], "year": hit["chapter_year"], "signed_date": hit["signed_date"],
            "effective_date": e["effective_date"], "rule": e["rule"], "raw_clause": e["raw_clause"],
            "expires_date": e.get("expires_date"), "section_dates": [x for x in e.get("section_dates") or [] if x.get("expires_date")]}


_depth = 0
STALE = ("same_as_chapter_unresolved", "after_chapter_unresolved")


def _hop(**kw):
    """Resolver for a referenced chapter that itself points at another chapter (M40, Oct 15 2026): at most 3 hops."""
    global _depth
    if _depth >= 3:
        return None
    _depth += 1
    try:
        return resolve(**kw)
    finally:
        _depth -= 1


def _carry_over(year, chapter):
    """E3 (Oct 16 2026): bills passed in year Y and signed in January Y+1 keep Y's numbering ('chapter 557 of the laws of 2013' was signed
    2014-01-10, so the signed index files it under chapter_year 2014). A chapter number above every one signed in Y is such a carry-over."""
    p = os.path.join(DATA_DIR, "signed", "%d.json" % session_for(year))
    if not os.path.exists(p):
        return False
    nums = [l["chapter_number"] for l in json.load(open(p)) if l["chapter_year"] == year]
    return bool(nums) and chapter > max(nums)


def _local_chapter(year, chapter):
    """M40: a chapter the signed index already holds (data/signed/{session}.json, chapter number and year), with its effective date parsed
    from the cached marked text. No API call. Returns the chapter_lookup record shape, or None. E3: also the January carry-over chapters."""
    from effective_date import parse_effective
    p = os.path.join(DATA_DIR, "signed", "%d.json" % session_for(year))
    if not os.path.exists(p):
        return None
    signed = json.load(open(p))
    hit = next((l for l in signed if l["chapter_number"] == chapter and l["chapter_year"] == year), None)
    if not hit and _carry_over(year, chapter):
        hit = next((l for l in signed if l["chapter_number"] == chapter and l["chapter_year"] == year + 1), None)
    tp = os.path.join(TEXT_MARKED, hit["key"] + ".txt") if hit else None
    if not hit or not os.path.exists(tp):
        return None
    e = parse_effective(open(tp).read(), hit["signed_date"], resolver=_hop)
    return {"bill": hit["key"], "chapter": chapter, "year": year, "signed_date": hit["signed_date"],
            "effective_date": e["effective_date"], "rule": e["rule"], "raw_clause": e["raw_clause"],
            "expires_date": e.get("expires_date"), "section_dates": [x for x in e.get("section_dates") or [] if x.get("expires_date")]}


def _tried(year, chapter):
    """What was tried for a chapter that stayed unresolved (E3, Oct 16 2026); recorded on the law's reference."""
    if year < 2009:
        return ("signed index (sessions 2009 on) has no chapter %d of %d; Open Legislation API serves sessions 2009 onward: bills/%d listing and "
                "search 'SIGNED CHAP.%d' returned 0 items, /api/3/laws/chapter/%d returned 404" % (chapter, year, session_for(year), chapter, chapter))
    return ("signed index session %d: no chapter %d of %d (carry-over %d checked); API bills/%d search 'SIGNED CHAP.%d' matched no bill signed as that chapter"
            % (session_for(year), chapter, year, year + 1, session_for(year), chapter))


def _with_expiry(rec, year, chapter):
    """E2 (Oct 16 2026): a chapter record cached before expiry was tracked gets expires_date / section_dates from the local signed index
    (in memory only, no API call, nothing written back to chapter_index.json)."""
    if rec and "expires_date" not in rec:
        loc = _local_chapter(year, chapter)
        if loc:
            return {**rec, "expires_date": loc["expires_date"], "section_dates": loc["section_dates"]}
    return rec


def resolve(bills=None, chapter=None, year=None):
    idx = _load()
    if bills and year:
        for ch, num in bills:
            rec = _local_bill(session_for(year), "%s%d" % (ch, num))
            if rec:
                return rec
    if chapter and year:
        key = "chap:%d-%d" % (year, chapter)
        if idx.get(key) and idx[key].get("rule") in STALE:         # M40: an entry that stopped at a second hop is retried locally
            rec = _local_chapter(year, chapter)
            if rec and rec["effective_date"]:
                idx[key] = rec
                _save()
        if key not in idx or (idx[key] is None and _local_chapter(year, chapter)):
            found = _local_chapter(year, chapter)           # E3: the signed index first (incl. carry-over chapters), then the API
            if found is None and year >= 2009:
                for sess in {session_for(year)}:
                    d = openleg.get("/api/3/bills/%d/search" % sess, {"term": '"SIGNED CHAP.%d"' % chapter, "limit": 10, "view": "no_fulltext"})
                    for it in ((d or {}).get("result") or {}).get("items") or []:
                        base = it["result"]["basePrintNo"]
                        rec = _from_bill(sess, base)
                        if rec and rec["chapter"] == chapter and (rec["year"] == year or (rec["year"] == year + 1 and _carry_over(year, chapter))):
                            found = {**rec, "year": year}
                            break
            idx[key] = found
            _save()
        return _with_expiry(idx[key], year, chapter) or {"unresolved": True, "bills": [], "chapter": chapter, "year": year, "tried": _tried(year, chapter)}
    for ch, num in (bills or []):
        key = "bill:%d-%s%d" % (session_for(year), ch, num)
        if key not in idx:
            idx[key] = _from_bill(session_for(year), "%s%d" % (ch, num))
            _save()
        if idx[key]:
            return idx[key]
    return None
