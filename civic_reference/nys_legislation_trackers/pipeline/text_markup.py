"""Convert NYS bill text to the Council cache convention: {{new matter}}, [deleted matter] kept, flowing paragraphs.

Two sources, because the Open Legislation API only serves HTML (underline tags) for bills of the 2017-2018 session
onward:
  * HTML (2017+): new matter is <u>...</u>, deleted matter is <s>...</s> inside [brackets].
  * Plain text (2009-2016): new matter is printed in UPPERCASE, deleted matter in [brackets]. Uppercase runs
    are wrapped in {{ }} and lower-cased (first letter of each sentence kept capital), so quotes read normally.
Usage: python3 text_markup.py   (writes cache/text_marked/<session>-<print>.txt for every signed pilot bill)
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OPEN, CLOSE = "\x01", "\x02"
ENACT = re.compile(r"The\s+People\s+of\s+the\s+State\s+of\s+New\s+York,\s+represented\s+in\s+Senate\s+and\s+Assem-?\s*bly,\s+do\s+enact\s+as\s+follows:", re.I)
PAGE_HDR = re.compile(r"^\s*(?:[SA]\.\s*\d+(?:--[A-Z])?\s+\d+|\d+\s+[SA]\.\s*\d+(?:--[A-Z])?|\d+(?:--[A-Z])?\s+\d+\s+[A-Z]{3}\d+-\d+-\d)\s*$")
FOOTER_LINE = re.compile(r"^\s*(EXPLANATION--|\[\s*(?:<b><s>)?\s*(?:</s></b>)?\s*\]\s+is old law|matter in brackets|LBD\d+-\d+-\d)", re.I)
LINE_NO = re.compile(r"^\s*(\d{1,2})(\s{2,})(.*)$")
NO_JOIN_PREFIX = {"non", "self", "ex", "semi", "anti", "vice", "cross", "half", "quasi", "all", "co", "pre", "re", "multi"}


def _dehyphenate(s):
    """Join words broken across a line or span edge: 'elec- tric' -> 'electric'; keep digit and compound hyphens."""
    def rep(m):
        a, b = m.group(1), m.group(2)
        if a.isdigit() or b[0].isdigit():
            return a + "-" + b
        if a.lower() in NO_JOIN_PREFIX:
            return a + "-" + b
        return a + b
    return re.sub(r"([A-Za-z0-9]+)-\n([A-Za-z0-9][^\s]*)", rep, s)


def _paragraphs(lines, indent_fn):
    """Reflow physical lines to paragraphs; indent_fn(line) says whether a line starts a paragraph."""
    paras, cur = [], []
    for ln in lines:
        if not ln.strip():
            continue
        if indent_fn(ln) and cur:
            paras.append(cur)
            cur = []
        cur.append(ln.strip())
    if cur:
        paras.append(cur)
    out = []
    for p in paras:
        out.append(re.sub(r"[ \t]+", " ", _dehyphenate("\n".join(p)).replace("\n", " ")).strip())
    return out


def from_html(h):
    """HTML (2017+) -> marked text."""
    h = re.sub(r"(?is)<style.*?</style>", "", h)
    h = re.sub(r"(?i)</?(pre|font[^>]*|b|i|p[^>]*)>", "", h)
    h = re.sub(r"(?i)</?s>", "", h)
    h = re.sub(r"(?i)<u>", OPEN, h)
    h = re.sub(r"(?i)</u>", CLOSE, h)
    h = h.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&nbsp;", " ")
    lines, started = [], False
    for ln in h.split("\n"):
        if PAGE_HDR.match(ln) or FOOTER_LINE.match(ln):
            continue
        m = LINE_NO.match(ln)
        if m:
            started = True
            lines.append(("P " if len(m.group(2)) >= 4 else "C ") + m.group(3))
        elif started and ln.strip() and not re.match(r"^\s*(S\.|A\.)\s*\d+", ln):
            lines.append("C " + ln.strip())
    pl, cur = [], []
    for l in lines:
        if l.startswith("P ") and cur:
            pl.append(cur); cur = []
        cur.append(l[2:].strip())
    if cur:
        pl.append(cur)
    paras = [re.sub(r"[ \t]+", " ", _dehyphenate("\n".join(p)).replace("\n", " ")).strip() for p in pl]
    body = "\n\n".join(paras)
    body = re.sub(CLOSE + r"[ \t]*" + OPEN, " ", body)             # merge adjacent underlined spans (same paragraph)
    body = re.sub(OPEN + r"[ \t]+", " " + OPEN, body)
    body = re.sub(r"[ \t]+" + CLOSE, CLOSE + " ", body)
    body = body.replace(OPEN, "{{").replace(CLOSE, "}}")
    return body


def _cap_sentences(s):
    s = s.lower()
    return re.sub(r"(^|[.;:]\s+|\(\w\)\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)


def _is_upper_tok(t):
    core = re.sub(r"[^A-Za-z]", "", t)
    return len(core) >= 2 and core.isupper() or (len(core) == 1 and core.isupper() and t.startswith("("))


def from_plain_old(t):
    """Plain text (2009-2016) -> marked text via the uppercase convention."""
    lines = [ln for ln in t.split("\n") if not PAGE_HDR.match(ln) and not FOOTER_LINE.match(ln)
             and not re.match(r"^\s*(S|A)\.\s*\d+(--[A-Z])?\s+\d+\s*$", ln)]
    # body starts at the enacting clause
    txt = "\n".join(lines)
    m = re.search(r"(?is)DO\s+ENACT\s+AS\s+FOLLOWS:\s*\n", txt)
    txt = txt[m.end():] if m else txt
    paras = _paragraphs(txt.split("\n"), lambda ln: re.match(r"^ {2}\S", ln) is not None)
    out = []
    for p in paras:
        p = re.sub(r"^S\s+(\d)", r"§ \1", p)
        toks = [x.lower() if re.fullmatch(r"\d[\w-]*[A-Z][\w-]*\.?", x) else x for x in p.split(" ")]   # "1662-E." -> "1662-e."
        up = [_is_upper_tok(x) for x in toks]
        mark = list(up)
        for i, x in enumerate(toks):          # a bare "A"/"I", a number or a lone symbol inside an uppercase run is part of it
            if not up[i] and (x in ("A", "I") or re.fullmatch(r"[\d.,;:()\-]+", x)):
                if 0 < i < len(toks) - 1 and up[i - 1] and up[i + 1]:
                    mark[i] = True
        res, i = [], 0
        while i < len(toks):
            if mark[i]:
                j = i
                while j < len(toks) and mark[j]:
                    j += 1
                res.append("{{" + _cap_sentences(" ".join(toks[i:j])) + "}}")
                i = j
            else:
                res.append(toks[i]); i += 1
        out.append(" ".join(res))
    return "\n\n".join(out)


def convert(key, base):
    """Returns (marked_text, source) for bill key; prefers HTML, falls back to plain text."""
    hp = os.path.join(base, "cache", "html", key + ".html")
    pp = os.path.join(base, "cache", "text", key + ".txt")
    if os.path.exists(hp):
        return from_html(open(hp).read()), "html"
    return from_plain_old(open(pp).read()), "uppercase"


def main():
    bills = [b for b in json.load(open(os.path.join(HERE, "..", "data", "bills.json"))) if b.get("chapter")]
    os.makedirs(os.path.join(HERE, "cache", "text_marked"), exist_ok=True)
    stats = {"html": [0, 0], "uppercase": [0, 0]}
    for b in bills:
        key = "%s-%s" % (b["session"], b["base_print_no"])
        txt, src = convert(key, HERE)
        open(os.path.join(HERE, "cache", "text_marked", key + ".txt"), "w").write(txt)
        stats[src][0] += 1
        stats[src][1] += 1 if "{{" in txt else 0
    print("converted", len(bills), {k: "%d laws, %d with markers" % tuple(v) for k, v in stats.items()})


if __name__ == "__main__":
    main()
