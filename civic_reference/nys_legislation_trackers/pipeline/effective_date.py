"""Effective and expiry dates of a NYS act, parsed from its effective-date section against the signing date.

parse_effective(text, signed_date) -> {"effective_date": ISO|None, "rule": str, "expires_date": ISO|None,
                                       "retroactive_to": ISO|None, "other_dates": [...], "raw_clause": str}
The clause is the last paragraph of the act that says the act "shall take effect" (or "takes effect"). A date is
returned only when the clause fixes it; "same date and same manner as chapter X" stays None (rule same_as_chapter)
until the other chapter's date is known.
"""
import re
from datetime import date, timedelta

UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
         "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
ORD = {"first": "one", "second": "two", "third": "three", "fourth": "four", "fifth": "five", "sixth": "six",
       "seventh": "seven", "eighth": "eight", "ninth": "nine", "tenth": "ten", "eleventh": "eleven",
       "twelfth": "twelve", "thirteenth": "thirteen", "fourteenth": "fourteen", "fifteenth": "fifteen",
       "sixteenth": "sixteen", "seventeenth": "seventeen", "eighteenth": "eighteen", "nineteenth": "nineteen",
       "twentieth": "twenty", "thirtieth": "thirty", "fortieth": "forty", "fiftieth": "fifty", "sixtieth": "sixty",
       "seventieth": "seventy", "eightieth": "eighty", "ninetieth": "ninety"}
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"])}
MONTH_RE = "|".join(MONTHS)
NUM_WORDS = r"(?:(?:one|two|three|four|five|six|seven|eight|nine)\s+hundred\s+)?(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[\s-]*)?(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)?"
ORD_WORD = r"(?:(?:one|two|three|four|five|six|seven|eight|nine)\s+hundred\s+)?(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[\s-]*)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth)|(?:(?:one|two|three|four|five|six|seven|eight|nine)\s+hundred\s+)?(?:twentieth|thirtieth|fortieth|fiftieth|sixtieth|seventieth|eightieth|ninetieth)|(?:one|two|three|four|five|six|seven|eight|nine)\s+hundredth"


def words_to_int(s):
    """'one hundred eightieth' -> 180, 'sixty' -> 60, 'ninetyfirst' style hyphenless joins too; None if unparseable."""
    s = s.lower().replace("-", " ").strip()
    s = re.sub(r"\b(" + "|".join(TENS) + r")(" + "|".join(list(UNITS) + list(ORD)) + r")\b", r"\1 \2", s)
    total, seen = 0, False
    toks = s.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "hundredth":
            total = max(total, 1) * 100 if total == 0 else total * 100
            seen = True
        elif t == "hundred":
            total = max(total, 1) * 100
            seen = True
        else:
            t = ORD.get(t, t)
            if t in UNITS:
                total += UNITS[t]; seen = True
            elif t in TENS:
                total += TENS[t]; seen = True
            elif t.isdigit():
                total += int(t); seen = True
            elif t == "and":
                pass
            else:
                return None
        i += 1
    return total if seen else None


def _d(s):
    return date.fromisoformat(s) if isinstance(s, str) else s


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue


def next_succeeding(month, day, signed):
    """'the first of January next succeeding the date on which it shall have become a law': first such date after signing."""
    cand = date(signed.year, month, day)
    return cand if cand > signed else date(signed.year + 1, month, day)


def final_clause(text):
    """The paragraph that carries the effective-date sentence (the last one in the act), trimmed of fiscal notes."""
    t = (text or "").replace("{{", "").replace("}}", "")
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    hit = [p for p in paras if re.search(r"\b(shall take effect|takes effect|take effect)\b", p, re.I)]
    if not hit:
        return ""
    # Oct 9 2026 (F1): an act that reads "This act shall take effect <date> provided, however, that: (a) ..." lists provisos in later
    # paragraphs that also say "shall take effect"; the act's own sentence is the one that starts with "This act shall take effect"
    own = [i for i, p in enumerate(paras) if re.match(r"^(?:(?:§|Section)\s*\d+\.\s*)?This act shall take effect", p, re.I)]
    if own:
        i = own[-1]
        p = paras[i]
        if re.search(r":\s*$", p):          # the provisos that follow belong to the same clause
            j = i + 1
            while j < len(paras) and not re.match(r"^(?:§|Section)\s*\d+\.", paras[j]) and not re.match(r"^Fiscal\s+NOTE", paras[j], re.I):
                p += " " + paras[j]; j += 1
    else:
        p = hit[-1]
    p = re.split(r"\s*Fiscal\s+NOTE", p, flags=re.I)[0]
    return p.strip()


BILL_REF = re.compile(r"\b([SA])\.?\s?(\d+)(?:-[A-Za-z])?", re.I)
CHAP_REF = re.compile(r"chapter\s+(\d+)\s+of\s+the\s+laws\s+of\s+(\d{4})", re.I)
YEAR_REF = re.compile(r"laws\s+of\s+(\d{4})", re.I)


def find_reference(clause):
    """What 'same date and manner as a chapter ...' points at: {'bills': [(S,1997),(A,286)], 'chapter': n, 'year': y}."""
    m = CHAP_REF.search(clause)
    if m:
        return {"chapter": int(m.group(1)), "year": int(m.group(2)), "bills": []}
    y = YEAR_REF.search(clause)
    pm = re.search(r"as proposed in legislative bills? numbers?([^;]*?)(?:,? takes? effect|;|$)", clause, re.I)
    if y and pm:
        bills = [(b.group(1).upper(), int(b.group(2))) for b in BILL_REF.finditer(pm.group(1))]
        if bills:
            return {"bills": bills, "chapter": None, "year": int(y.group(1))}
    return None


def _single(clause, signed, ref=None):
    """(effective_date, rule, reference_info) for the first 'shall take effect' statement of the clause."""
    c = re.sub(r"^\s*(?:§|Section|S)\s*\d+\.\s*", "", clause)
    sent = re.split(r";|\.\s+(?=[A-Z])", c)[0]
    low = sent.lower()
    if re.search(r"same date and in the same manner|same date and same manner|same manner and on the same date", low):
        # the referenced chapter could not be found (not signed yet, or outside the
        # sessions the API serves): leave the date open rather than crash the run
        if not ref or not ref.get("effective_date"):
            return None, "same_as_chapter_unresolved", ref
        return _d(ref["effective_date"]), "same_as_chapter", ref
    m = re.search(r"take effect (?:on )?(?:the )?first of (" + MONTH_RE + r") next succeeding", low)
    if m:
        return next_succeeding(MONTHS[m.group(1)], 1, signed), "first_of_month_next_succeeding", None
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?(" + ORD_WORD + r"|\d+(?:st|nd|rd|th)?) day (?:next )?(?:after|following)(?: the (enactment|effective date) of such chapter)?", low)
    if m:
        n = words_to_int(m.group(1)) if not m.group(1)[0].isdigit() else int(re.sub(r"\D", "", m.group(1)))
        if n is not None:
            if "of such chapter" in m.group(0):
                if not ref or not ref.get("signed_date"):
                    return None, "after_chapter_unresolved", ref
                base = _d(ref["signed_date"] if m.group(2) == "enactment" else (ref["effective_date"] or ref["signed_date"]))
                return base + timedelta(days=n), "nth_day_after_chapter", ref
            return signed + timedelta(days=n), "nth_day_after_law", None
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?(" + NUM_WORDS + r"|\d+)\s+(day|days|month|months)\s+(?:next\s+)?(?:after|following)", low)
    if m and m.group(1).strip():
        n = words_to_int(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))
        if n is not None:
            if m.group(2).startswith("month"):
                return add_months(signed, n), "n_months_after_law", None
            return signed + timedelta(days=n), "n_days_after_law", None
    # M1 (Oct 10 2026): "one year / two years after it shall have become a law" is the signing date plus the offset
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?(" + NUM_WORDS + r"|\d+)\s+(years?)\s+(?:next\s+)?(?:after|following)\s+(?:it|this act)\s+shall\s+have\s+become\s+(?:a\s+)?law", low)
    if m and m.group(1).strip():
        n = words_to_int(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))
        if n is not None:
            return add_months(signed, 12 * n), "n_years_after_law", None
    m = re.search(r"(?:take|takes) effect (?:on )?(" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})", low)
    if m:
        return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))), "fixed_date", None
    if re.search(r"take effect immediately", low):
        return signed, "immediately", None
    return None, "unparsed", None


RETRO = re.compile(r"(?:shall be |is |are )?deemed to have been in full force and effect on and after (" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})", re.I)
COND = re.compile(r"if (?:this act|it) shall (not )?have become (?:a )?law (on or before|after) (" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})", re.I)


def _retro(clause, signed):
    """[(applies_to or None, ISO date)] for 'deemed to have been in full force and effect on and after D' statements that
    apply: a proviso conditioned on a date the act beat at signing ('if not law on or before March 27') does not."""
    out = []
    for m in RETRO.finditer(clause):
        d = date(int(m.group(4)), MONTHS[m.group(2).lower()], int(m.group(3))) if False else date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        before = clause[max(0, m.start() - 220):m.start()]
        cs = list(COND.finditer(before))
        if cs:
            c = cs[-1]
            cd = date(int(c.group(5)), MONTHS[c.group(3).lower()], int(c.group(4)))
            holds = signed > cd          # "not law on or before D" and "law after D" both hold only if signed after D
            if not holds:
                continue
        sect = re.search(r"(sections?\s+[a-z0-9 -]+?)\s+of this act\s+(?:shall be|is|are)\s*$", before.strip(), re.I) or \
            re.search(r"(sections?\s+[a-z0-9 -]+?)\s+of this act[^;]{0,40}$", before, re.I)
        out.append((sect.group(1).strip() if sect else None, d))
    return out


def _expiry(clause, effective, signed):
    low = clause.lower()
    m = re.search(r"expire(?:s)?(?: and be deemed repealed)?[^;.]{0,40}?(" + NUM_WORDS + r"|\d+)\s+(years?|months?|days?)\s+after (?:such date|the effective date|this act shall have taken effect)", low)
    if m and m.group(1).strip() and effective:
        n = words_to_int(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))
        u = m.group(2)
        if n is not None:
            return add_months(effective, 12 * n) if u.startswith("year") else (
                add_months(effective, n) if u.startswith("month") else effective + timedelta(days=n))
    m = re.search(r"expire(?:s)?(?: on)? (" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})", low)
    if m:
        return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    return None


def _amended_reference(text, ref, signed):
    """D1. The act may also amend the referenced chapter's own effective-date section ('Section 2 of a chapter of the laws of
    2021 ... is amended to read as follows: This act shall take effect on the [sixtieth] {{one hundred eightieth}} day ...').
    Signed BEFORE the chapter's original effective date, the amended date applies; signed on or after it, the original stands
    (the chapter was already in effect)."""
    m = re.search(r"(?is)\bof a chapter of the laws of \d{4}[^§]{0,400}?is amended to read as follows:.{0,200}?take effect on the (?:\[[^\]]*\]\s*)?\{\{([^}]+)\}\}\s+day after", text or "")
    if not m:
        return ref
    n = words_to_int(m.group(1).replace("day", "").strip())
    if not n:
        return ref
    original = _d(ref["effective_date"])
    if signed >= original:
        return {**ref, "amended_clause_ignored": True}
    amended = _d(ref["signed_date"]) + timedelta(days=n)
    return {**ref, "effective_date": amended.isoformat(), "original_effective_date": ref["effective_date"], "amended_clause_applied": True}


def parse_effective(text, signed_date, resolver=None):
    """text: the full act text (marked or plain) or just the clause. signed_date: ISO string of the governor's signature.
    resolver(bills=..., chapter=..., year=...) -> {signed_date, effective_date, chapter, ...} resolves 'same as chapter X'."""
    signed = _d(signed_date)
    clause = final_clause(text)
    if not clause:                       # no section says it: take the last section of the text (an empty act clause)
        paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", (text or "")) if p.strip()]
        clause = paras[-1] if paras else ""
    refinfo = None
    if re.search(r"same date and|same manner|chapter\s+\d+\s+of the laws", clause, re.I):
        r = find_reference(clause)
        if r and resolver:
            refinfo = resolver(bills=r["bills"], chapter=r["chapter"], year=r["year"])
        if refinfo is None and r:
            refinfo = {"unresolved": True, **{k: r[k] for k in ("bills", "chapter", "year")}}
        if refinfo and refinfo.get("unresolved"):
            refinfo = {"effective_date": None, "signed_date": None, **refinfo}
    if refinfo and refinfo.get("effective_date") and refinfo.get("signed_date"):
        refinfo = _amended_reference(text, refinfo, signed)
    eff, rule, ref_used = _single(clause, signed, refinfo)
    retros = _retro(clause, signed)
    expires = _expiry(clause, eff, signed)
    sections = []
    for m in re.finditer(r";\s*provided(?:,? however,?| further,?)?,?\s+(?:that\s+)?(.*?)(?=;\s*provided|$)", clause, re.I):
        part = m.group(1)
        if not re.search(r"shall take effect|takes effect", part, re.I):
            continue
        sect = re.search(r"^(.*?)\s+(?:shall take effect|takes effect)", part, re.I)
        if re.match(r"\s*(?:that\s+)?(?:if|effective)\b|this act\b", part, re.I):   # a condition on the act itself, not a section
            continue
        sub = "This act " + part[part.lower().find("shall take effect"):]
        e2, r2, _ = _single(sub, signed, refinfo)
        sections.append({"applies_to": re.sub(r"^that\s+", "", (sect.group(1) if sect else part[:80]).strip()), "effective_date": e2.isoformat() if e2 else None, "rule": r2})
    for m in re.finditer(r"(sections?\s+[\w,\s-]+?\s+of this act)\s+shall take effect\s+(?:on|upon)\s+the\s+(?:expiration|repeal|termination)\s+of\s+([^;.]*)", clause, re.I):
        # keyed to another law's expiration (Oct 8 2026, audit B): the date is open until that law expires, never the act's own date
        sections.append({"applies_to": re.sub(r"\s+", " ", m.group(1)).strip(), "effective_date": None, "rule": "on_expiration_of_other_law", "open_date": True,
                         "depends_on": re.sub(r"\s+", " ", m.group(2)).strip()})
    for ap, d in retros:
        if ap:
            sections.append({"applies_to": ap, "effective_date": None, "rule": "retroactive", "retroactive_to": d.isoformat()})
    # top level only for a statement about the act as a whole (main clause, or a proviso conditioned on the act's own signing
    # date); one that names a section ("section 191 ... deemed in full force") stays in section_dates
    retro = min({d for ap, d in retros if not ap}, default=None)
    out = {"effective_date": eff.isoformat() if eff else None, "rule": rule,
           "expires_date": expires.isoformat() if expires else None,
           "retroactive_to": retro.isoformat() if retro else None,
           "other_dates": [x for x in sections if x["rule"] != "retroactive"], "section_dates": sections, "raw_clause": clause}
    if ref_used:
        out["reference"] = {k: ref_used.get(k) for k in ("bill", "chapter", "year", "signed_date", "effective_date", "rule") if k in ref_used}
    return out
