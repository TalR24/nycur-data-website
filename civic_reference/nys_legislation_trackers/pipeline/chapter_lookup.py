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
    e = parse_effective(txt, signed, resolver=None)        # one hop only: a chain of references stays unresolved
    return {"bill": "%d-%s" % (session, base), "chapter": chap, "year": int(signed[:4]), "signed_date": signed,
            "effective_date": e["effective_date"], "rule": e["rule"], "raw_clause": e["raw_clause"]}


def resolve(bills=None, chapter=None, year=None):
    idx = _load()
    if chapter and year:
        key = "chap:%d-%d" % (year, chapter)
        if key not in idx:
            found = None
            for sess in {session_for(year), session_for(year) - 0}:
                d = openleg.get("/api/3/bills/%d/search" % sess, {"term": '"SIGNED CHAP.%d"' % chapter, "limit": 10, "view": "no_fulltext"})
                for it in ((d or {}).get("result") or {}).get("items") or []:
                    base = it["result"]["basePrintNo"]
                    rec = _from_bill(sess, base)
                    if rec and rec["chapter"] == chapter and rec["year"] == year:
                        found = rec
                        break
            idx[key] = found
            _save()
        return idx[key]
    for ch, num in (bills or []):
        key = "bill:%d-%s%d" % (session_for(year), ch, num)
        if key not in idx:
            idx[key] = _from_bill(session_for(year), "%s%d" % (ch, num))
            _save()
        if idx[key]:
            return idx[key]
    return None
