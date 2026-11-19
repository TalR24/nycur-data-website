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
    """Line-end hyphens become '- ' here; fix_hyphens() decides join or keep once the whole text is assembled."""
    return re.sub(r"([A-Za-z0-9])-[ \t]*\n[ \t]*(?=[A-Za-z0-9])", r"\1- ", s)


TENS_W = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
UNITS_W = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "first", "second", "third", "fourth",
           "fifth", "sixth", "seventh", "eighth", "ninth"}
VOWEL_KEEP = {"re", "pre", "co", "de", "un", "in", "anti", "multi", "semi", "inter", "intra", "non", "sub", "pro", "post", "mid"}
ALWAYS_KEEP = {"non", "self", "ex", "vice", "cross", "half", "quasi", "all", "well", "full", "part", "high", "low", "long", "short",
               "state", "city", "county", "town", "year", "day", "month", "per", "cost", "third", "first", "second"}
HYPH_STATS = {"rejoined": 0, "kept": 0}


def fix_hyphens(body):
    """Resolve 'left- right' (a line-end hyphen) in either era.
    Keep the hyphen when: the hyphenated form appears mid-line elsewhere in the same text; the left part is a tens word and
    the right a units word (seventy-three); the left part is an always-hyphenated prefix (non, self, ...); or the left part is
    a vowel-sensitive prefix (re, pre, co, ...) and the right starts with a vowel (re-enact). Otherwise join (proc- ess ->
    process). 'pre- and post-' style pairs (right part and/or/to) and digit pairs are left alone or hyphenated."""
    seen = {m.group(0).lower() for m in re.finditer(r"\b[A-Za-z]+-[A-Za-z]+\b", body)}
    def rep(m):
        left, right = m.group(1), m.group(2)
        l, r = left.lower(), right.lower()
        if r in ("and", "or", "to"):
            return m.group(0)
        if r in ("of", "in", "on", "by") and body[m.end():m.end() + 1] == "-":   # out- of-pocket
            HYPH_STATS["kept"] += 1
            return left + "-" + right
        if (l + "-" + r) in seen or (l in TENS_W and r in UNITS_W) or l in ALWAYS_KEEP or (l in VOWEL_KEEP and r[0] in "aeiou"):
            HYPH_STATS["kept"] += 1
            return left + "-" + right
        HYPH_STATS["rejoined"] += 1
        return left + right
    body = re.sub(r"(?<![\w])([A-Za-z]{2,})- ([a-z]+)(?!\w)", rep, body)
    return re.sub(r"(\d)- (\d)", r"\1-\2", body)


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
    return trim_after_effective(fix_hyphens(body))


RULE_STATS = {"digits_after_deleted": 0, "bridged_tokens": 0, "status_or_citation_unbraced": 0, "case_restored_from_law": 0,
              "appended_text_stripped": 0}
STATUS_WORDS = {"REPEALED", "REPEALED.", "REPEALED;", "REPEALED,"}
CITATION = re.compile(r"^[SA]\.?\s?\d+(?:-[A-Za-z]+)?[.,;]?$")
SENT_END = re.compile(r"[.:;]$")


def _is_upper_tok(t):
    if t in STATUS_WORDS:
        RULE_STATS["status_or_citation_unbraced"] += 1
        return False
    core = re.sub(r"[^A-Za-z]", "", t)
    return len(core) >= 2 and core.isupper() or (len(core) == 1 and core.isupper() and t.startswith("("))


def _vocab(raw):
    """lower -> Capitalised form, from words the law itself prints capitalised mid-sentence (names, places)."""
    v = {}
    for m in re.finditer(r"(?<![.:;]\s)(?<!^)\b([A-Z][a-z]{2,})\b", re.sub(r"\s+", " ", raw)):
        v.setdefault(m.group(1).lower(), m.group(1))
    for w in ("new", "york", "state", "the", "of", "and", "an", "act"):
        v.pop(w, None)
    for mth in ("January", "February", "March", "April", "June", "July", "August", "September", "October", "November", "December"):
        v.setdefault(mth.lower(), mth)
    return v


def _fmt_run(toks, cap_first, vocab):
    out, cap = [], cap_first
    for k, t in enumerate(toks):
        w = t.lower()
        core = re.sub(r"^\W+|\W+$", "", w)
        if core in vocab and not cap:
            w = w.replace(core, vocab[core]); RULE_STATS["case_restored_from_law"] += 1
        if cap:
            w = re.sub(r"[a-z]", lambda m: m.group(0).upper(), w, count=1)
            cap = False
        if SENT_END.search(t) or (re.fullmatch(r"\(\w\)", t) and k == 0 and cap_first):
            cap = True
        out.append(w)
    return " ".join(out)


def from_plain_old(t):
    """Plain text (2009-2016) -> marked text via the uppercase convention (new matter is printed in capitals)."""
    vocab = _vocab(t)
    lines = [ln for ln in t.split("\n") if not PAGE_HDR.match(ln) and not FOOTER_LINE.match(ln)
             and not re.match(r"^\s*(S|A)\.\s*\d+(--[A-Z])?\s+\d+\s*$", ln)]
    txt = "\n".join(lines)
    m = re.search(r"(?is)DO\s+ENACT\s+AS\s+FOLLOWS:\s*\n", txt)
    txt = txt[m.end():] if m else txt
    f = re.search(r"(?m)^\s*FISCAL\s+NOTE", txt)          # appended fiscal notes are not part of the act
    if f:
        txt = txt[:f.start()]; RULE_STATS["appended_text_stripped"] += 1
    paras = _paragraphs(txt.split("\n"), lambda ln: re.match(r"^ {2}\S", ln) is not None)
    out = []
    for p in paras:
        p = re.sub(r"^S\s+(\d)", r"§ \1", p)
        toks = [x.lower() if re.fullmatch(r"\d[\w-]*[A-Z][\w-]*\.?", x) else x for x in p.split(" ") if x != ""]
        up = [_is_upper_tok(x) for x in toks]
        cite = [bool(CITATION.match(x)) for x in toks]
        mark = list(up)
        for i, x in enumerate(toks):
            if cite[i]:
                mark[i] = False
                continue
            single = bool(re.fullmatch(r"[A-Z]\.?", x)) and x not in ("§",)
            small = bool(re.fullmatch(r"[\d.,;:()\-]+", x))
            if not up[i] and (single or small):         # a lone initial, class letter, "A" or number inside or at the start of a run
                left = i > 0 and up[i - 1]
                right = i + 1 < len(toks) and up[i + 1]
                if (left and right and i < len(toks) - 1) or (i == 0 and single and right):
                    mark[i] = True; RULE_STATS["bridged_tokens"] += 1
        for i, x in enumerate(toks):                     # digits that directly follow a [deleted] span are the new matter
            if i and re.search(r"\][.,;:)]*$", toks[i - 1]) and re.fullmatch(r"\d[\d,]*[.,;:)]*", x) and not mark[i]:
                mark[i] = True; RULE_STATS["digits_after_deleted"] += 1
        MONTH_TOK = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}
        for i, x in enumerate(toks):                     # "{{July}} 23, 2013": digits that continue a braced month or number join the run
            if i and not mark[i] and mark[i - 1] and re.fullmatch(r"\d{1,4},?", x):
                prev = re.sub(r"\W", "", toks[i - 1]).lower()
                if prev in MONTH_TOK or (re.fullmatch(r"\d{1,2}", prev) and toks[i - 1].endswith(",")) or re.fullmatch(r"\d{1,2},", toks[i - 1]):
                    mark[i] = True; RULE_STATS["digits_continue_run"] = RULE_STATS.get("digits_continue_run", 0) + 1
        res, i = [], 0
        while i < len(toks):
            if mark[i]:
                j = i
                while j < len(toks) and mark[j]:
                    j += 1
                run = toks[i:j]
                tail = ""
                mt = re.search(r"([.,;:)]+)$", run[-1])
                if mt and re.fullmatch(r"\d[\d,]*[.,;:)]*", run[-1]):   # keep punctuation after a bare number outside the braces
                    tail = mt.group(1); run[-1] = run[-1][:-len(tail)]
                cap_first = i == 0 or bool(SENT_END.search(toks[i - 1])) or toks[i - 1] == "§"
                res.append("{{" + _fmt_run(run, cap_first, vocab) + "}}" + tail)
                i = j
            else:
                res.append(toks[i]); i += 1
        out.append(" ".join(res))
    return trim_after_effective(fix_hyphens("\n\n".join(out)))


def trim_after_effective(body):
    """Drop anything after the act's final effective-date section that is not another numbered section (appended notes)."""
    paras = body.split("\n\n")
    last = max((i for i, p in enumerate(paras) if re.search(r"\b(?:shall take effect|takes? effect)\b", p)), default=None)
    if last is None:
        return body
    keep = paras[:last + 1]
    for p in paras[last + 1:]:
        if re.match(r"^\s*(§|Section)\s*\d", p):
            keep.append(p)
        else:
            RULE_STATS["appended_text_stripped"] += 1
    return "\n\n".join(keep)


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
    HYPH_STATS.update(rejoined=0, kept=0)
    for k in list(RULE_STATS): RULE_STATS[k] = 0
    for b in bills:
        key = "%s-%s" % (b["session"], b["base_print_no"])
        txt, src = convert(key, HERE)
        open(os.path.join(HERE, "cache", "text_marked", key + ".txt"), "w").write(txt)
        stats[src][0] += 1
        stats[src][1] += 1 if "{{" in txt else 0
    print("converted", len(bills), {k: "%d laws, %d with markers" % tuple(v) for k, v in stats.items()}, "hyphens", HYPH_STATS, "rules", RULE_STATS)


if __name__ == "__main__":
    main()
