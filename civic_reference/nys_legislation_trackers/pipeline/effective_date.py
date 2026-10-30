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
    # M9 (Oct 11 2026): "a chapter of the laws of 2015, amending chapter 672 of the laws of 1993 ..., as proposed in legislative bills numbers
    # S.459 and A.5251, takes effect": the bills name the referenced chapter; the chapter number in the middle is the law it amends
    y = YEAR_REF.search(clause)
    pm = re.search(r"as proposed in legislative bills? numbers?([^;]*?)(?:,? takes? effect|;|$)", clause, re.I)
    if y and pm:
        bills = [(b.group(1).upper(), int(b.group(2))) for b in BILL_REF.finditer(pm.group(1))]
        if bills:
            return {"bills": bills, "chapter": None, "year": int(y.group(1))}
    m = CHAP_REF.search(clause)
    if m:
        return {"chapter": int(m.group(1)), "year": int(m.group(2)), "bills": []}
    return None


def _single(clause, signed, ref=None):
    """(effective_date, rule, reference_info) for the first 'shall take effect' statement of the clause."""
    c = re.sub(r"^\s*(?:§|Section|S)\s*\d+\.\s*", "", clause)
    sent = re.split(r";|:\s+(?=provided)|\.\s+(?=[A-Z])", c)[0]      # E3: "take effect July 1, 2014: provided, however, ... same date as such chapter" is a proviso, not the main rule
    low = sent.lower()
    if re.search(r"same date and in the same manner|same date and same manner|same manner and on the same date", low):
        # the referenced chapter could not be found (not signed yet, or outside the
        # sessions the API serves): leave the date open rather than crash the run
        if not ref or not ref.get("effective_date"):
            return None, "same_as_chapter_unresolved", ref
        return _d(ref["effective_date"]), "same_as_chapter", ref
    # T3 (Oct 18 2026): "the first day of the first month next succeeding the one hundred twentieth day after it shall have become a law" is the signing date
    # plus N days, then the first day of the month after that
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?first(?: day)? of the (?:first )?month (?:next )?(?:succeeding|following)(?: the)? (" + ORD_WORD + r"|\d+(?:st|nd|rd|th)?) day (?:next )?(?:after|following)", low)
    if m:
        n = words_to_int(m.group(1)) if not m.group(1)[0].isdigit() else int(re.sub(r"\D", "", m.group(1)))
        if n is not None:
            d = signed + timedelta(days=n)
            return add_months(date(d.year, d.month, 1), 1), "first_of_month_after_nth_day", None
    # B15 (Oct 30 2026): "on the same date as the reversion of ... as provided in section 10 of chapter 413 of the laws of 2003": the referenced
    # chapter's expiry date when the lookup knows it; pre-2009 chapters are not in the API, so the reference is kept and the date left open
    if re.search(r"take effect (?:on )?the same date as the reversion of", low):
        if ref and ref.get("expires_date"):
            return _d(ref["expires_date"]), "same_as_reversion", ref
        return None, "same_as_reversion_unresolved", ref
    # B15: a day of a named month. "the first of January, 2020" / "the first day of June 2021" is a fixed date; "the first day of January next
    # (succeeding)", "January first next succeeding" and "the fifteenth of December next succeeding the date on which it shall have become a law" are
    # the first such date after signing; "the first of the month next succeeding the date on which ..." is the first of the following month
    if not re.search(r"following the (?:\w+ )?(?:first|\w+th|\w+) of ", low):         # "first of January following the first of September next succeeding ..." is a compound date
        pass
    else:
        return None, "unparsed", None
    # "the first day of the eighteenth month after it shall have become a law": the first of the month N months after the signing month
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?first day of the (" + ORD_WORD + r"|\d+(?:st|nd|rd|th)?) month (?:next )?(?:after|following) (?:the date on which )?(?:it|this act) shall have become a law", low)
    if m:
        n = words_to_int(m.group(1)) if not m.group(1)[0].isdigit() else int(re.sub(r"\D", "", m.group(1)))
        if n:
            return add_months(date(signed.year, signed.month, 1), n), "first_of_nth_month_after_law", None
    DAYX = r"(" + ORD_WORD + r"|\d{1,2}(?:st|nd|rd|th)?)"
    def _day(g):
        return words_to_int(g) if not g[0].isdigit() else int(re.sub(r"\D", "", g))
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?" + DAYX + r"(?: day)? of (" + MONTH_RE + r"),?\s+(\d{4})", low)
    if m and _day(m.group(1)):
        return date(int(m.group(3)), MONTHS[m.group(2)], _day(m.group(1))), "fixed_date", None
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?" + DAYX + r"(?: day)? of (" + MONTH_RE + r")(?: (?:next|following|after)\b|(?=\s+(?:and|following)?\s*$))", low)
    if not m:
        m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?(" + MONTH_RE + r") " + DAYX + r"(?:\s+next|\s+following)\b", low)
        if m:
            m = (m.group(2), m.group(1))
        else:
            m = None
    else:
        m = (m.group(1), m.group(2))
    if m and _day(m[0]) and not re.search(r"take effect (?:on )?(?:the )?first of (" + MONTH_RE + r") next succeeding", low):     # that one keeps its original rule name
        return next_succeeding(MONTHS[m[1]], _day(m[0]), signed), "day_of_month_next_succeeding", None
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?" + DAYX + r"(?: day)? of the (?:calendar )?month (?:next )?(?:succeeding|following) the date on which it shall have become a law", low)
    if m and _day(m.group(1)):
        return add_months(date(signed.year, signed.month, 1), 1).replace(day=_day(m.group(1))), "day_of_month_next_succeeding", None
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
    # M14 (Oct 12 2026): also "after the date on which it shall have become a law" / "after the date it shall ..."
    # M1 (Oct 10 2026): "one year / two years after it shall have become a law" is the signing date plus the offset
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?(" + NUM_WORDS + r"|\d+)\s+(years?)\s+(?:next\s+)?(?:after|following)\s+(?:the\s+date\s+(?:on\s+which\s+)?)?(?:it|this act)\s+shall\s+have\s+become\s+(?:a\s+)?law", low)
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


RETRO = re.compile(r"(?:shall be |is |are )?deemed to have been in full force(?: and effect)? on and after (" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})", re.I)
COND = re.compile(r"if (?:this act|it) shall (not )?have become (?:a )?law (on or before|after) (" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})", re.I)


def _retro(clause, signed):
    """[(applies_to or None, ISO date)] for 'deemed to have been in full force [and effect] on and after D' statements that
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
    # M10 (Oct 11 2026): "...; further provided that this act shall expire and be deemed repealed December 31, 2012" (a proviso after the
    # effective date; only a statement about the act as a whole counts, a named section's sunset does not)
    m = re.search(r"(?<!of )\bthis act shall (?:expire|be deemed to expire)(?: and be deemed repealed)?(?: on)?\s+(" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})", low)
    if m:
        return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    return _act_expiry(clause, effective)


def _signed_expiry(clause, signed):
    """W2 (Oct 20 2026): 'shall expire five years after having become a law' / 'after it shall have become a law' is the signing date plus N."""
    low = clause.lower()
    m = re.search(r"\bthis act shall (?:take effect[^;]*?\s+and\s+shall\s+)?(?:expire|be deemed to expire)(?:\s+and\s+be\s+deemed\s+repealed)?\s+(" + NUM_WORDS + r"|\d+)\s+(years?|months?)\s+after\s+(?:having\s+become\s+a\s+law|(?:it|this\s+act)\s+shall\s+have\s+become\s+a\s+law)", low)
    if not (m and signed and m.group(1).strip()):
        return None
    n = words_to_int(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))
    if n is None:
        return None
    return add_months(signed, 12 * n if m.group(2).startswith("year") else n)


EXP_VERB = r"(?:shall|will)\s+(?:expire|be\s+deemed\s+(?:to\s+)?(?:expire|repealed))(?:\s+and\s+(?:shall\s+)?be\s+deemed\s+(?:to\s+)?(?:repealed|expire))?"
SECT_SUBJ = re.compile(r"(?:sections?|subdivisions?|paragraphs?|subparagraphs?|articles?|parts?|amendments?\s+made\s+by|provisions?)\b[^;]*?\bof\s+this\s+act\b[^;]*$", re.I)


def _act_expiry(clause, effective):
    """M25 (Oct 13 2026): the general act-level sunset. 'This act shall take effect immediately and shall expire and be deemed repealed
    December 31, 2012' / 'shall expire on <date>' / 'shall be deemed repealed on and after <date>' / 'shall expire and be deemed repealed
    three years after such effective date'. Only when the subject is the act itself; a clause that names a section or 'the amendments made
    by section N' is handled as a section expiry (M21)."""
    low = clause.lower()
    for m in re.finditer(EXP_VERB + r"(?:\s+(?:on|upon))?(?:\s+and\s+after|\s+or\s+after)?\s+(?:(" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})|(" + NUM_WORDS + r"|\d+)\s+(years?|months?|days?)\s+(?:after|from)\s+(?:such\s+effective\s+date|such\s+date|the\s+effective\s+date|the\s+date\s+(?:on\s+which\s+)?this\s+act\s+(?:shall\s+have\s+)?(?:takes?|taken)\s+effect|this\s+act\s+(?:shall\s+have\s+)?taken\s+effect))", low):
        seg_start = max(low.rfind(";", 0, m.start()), low.rfind(". ", 0, m.start())) + 1
        prefix = low[seg_start:m.start()]
        if "this act" not in prefix or SECT_SUBJ.search(prefix):
            continue
        if m.group(1):
            return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
        if effective and m.group(4).strip():
            n = words_to_int(m.group(4)) if not m.group(4).isdigit() else int(m.group(4))
            if n is not None:
                u = m.group(5)
                return add_months(effective, 12 * n) if u.startswith("year") else (
                    add_months(effective, n) if u.startswith("month") else effective + timedelta(days=n))
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


AMENDS_EFFECT = re.compile(r"(?is)\bsection\s+\d+\s+of\s+chapter\s+(\d+)\s+of\s+the\s+laws\s+of\s+(\d{4})\b[^§]{0,400}?is\s+amended\s+to\s+read\s+as\s+follows:\s*\n+\s*(?:§\s*\d+\.\s*)?(This act shall take effect[^\n]*)")


def _amended_fixed_reference(text, ref, signed=None):
    """M40 (Oct 15 2026). The act that points at chapter X may itself rewrite chapter X's effective-date section with a new calendar date
    ('Section 7 of chapter 550 of the laws of 2014 ... is amended to read as follows: This act shall take effect January 1, [2015 ...] {{2016}}').
    Rule D1: the amended date applies only when the amending chapter was signed on or before the original effective date; signed later, the
    original stands and the amendment is recorded on the reference (amended_clause_ignored, amended_fixed_date). Returns the reference."""
    for m in AMENDS_EFFECT.finditer(text or ""):
        if int(m.group(1)) != ref.get("chapter") or int(m.group(2)) != ref.get("year"):
            continue
        sent = re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", " ", m.group(3)).replace("{{", "").replace("}}", "")).strip()
        eff, rule, _ = _single(sent, date.today(), None)
        if eff and rule == "fixed_date" and eff.isoformat() != ref.get("effective_date"):
            if signed is not None and ref.get("effective_date") and signed > _d(ref["effective_date"]):
                return {**ref, "amended_clause_ignored": True, "amended_fixed_date": eff.isoformat()}
            return {**ref, "effective_date": eff.isoformat(), "original_effective_date": ref.get("effective_date"), "amended_fixed_date_applied": True}
    return ref


# E1 (Oct 16 2026): omnibus acts of Parts. Each Part ends with its own "This act shall take effect ..." section and the act closes with
# a general clause ("the applicable effective date of Parts A through C shall be as set forth in the last section of such Parts").
# Part headings are "{{Part}} B" inline at the end of the previous Part's last paragraph (marked text) or a bare "PART B" / "Part B" line.
PART_MARK = re.compile(r"\{\{Part\}\}[ \t]+([A-Z]{1,2}\d?)\b|^[ \t]*(?:PART|Part)[ \t]+([A-Z]{1,2}\d?)[ \t]*$", re.M)
OWN_CLAUSE = re.compile(r"^(?:(?:§|Section)\s*\d+\.\s*)?This act shall take effect", re.I)
PAGE_HDR = re.compile(r"(?:\s+[SA]\.\s*\d+(?:-[A-Za-z])?\s+\d+){1,2}(?:\s+[SA]\.\s*\d+(?:-[A-Za-z])?)?\s*$")


def _own_clauses(text):
    """[(start, end, clause_text)] for every paragraph that starts "[§ N.] This act shall take effect", provisos that follow a colon merged;
    start/end are character offsets in `text`."""
    paras = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\S(?:[^\n]|\n(?!\s*\n))*", text)]
    out = []
    for i, (a, b, p) in enumerate(paras):
        q = re.sub(r"\s+", " ", re.sub(r"\s*\{\{Part\}\}\s+[A-Z]{1,2}\d?\b.*$", "", p, flags=re.S).replace("{{", "").replace("}}", "")).strip()   # the next Part's heading rides on this paragraph
        if not OWN_CLAUSE.match(q):
            continue
        end, j = b, i + 1
        if re.search(r":\s*$", q):
            while j < len(paras):
                qq = re.sub(r"\s+", " ", paras[j][2]).strip()
                if re.match(r"^(?:§|Section)\s*\d+\.", qq) or re.match(r"^Fiscal\s+NOTE", qq, re.I):
                    break
                q += " " + qq; end = paras[j][1]; j += 1
        q = re.split(r"\s*Fiscal\s+NOTE", q, flags=re.I)[0]
        q = PAGE_HDR.sub("", q).strip()
        out.append((a, end, q))
    return out


def part_dates(text, signed_date, resolver=None):
    """E1. Section-date entries for each Part's own effective-date clause, scoped to that Part's character span in `text`:
    {applies_to, part, span_start, span_end, effective_date, rule, raw_clause[, expires_date]}. [] unless the text has two or more
    Part headings and two or more "This act shall take effect" clauses. The final act-level clause is not a Part entry (it stays the law's date)."""
    text = text or ""
    marks, seen = [], set()
    for m in PART_MARK.finditer(text):
        letter = m.group(1) or m.group(2)
        if letter not in seen:                 # a running page header repeats the letter: the first one opens the Part
            seen.add(letter)
            marks.append((m.start(), letter))
    clauses = _own_clauses(text)
    if len(marks) < 2 or len(clauses) < 2:
        return []
    act = clauses[-1]
    last_start = marks[-1][0]
    act_level = bool(re.search(r"\bparts?\b", act[2], re.I)) or sum(1 for c in clauses if c[0] >= last_start) >= 2
    out = []
    for i, (pos, letter) in enumerate(marks):
        nxt = marks[i + 1][0] if i + 1 < len(marks) else None
        end = nxt if nxt is not None else (act[0] if act_level and act[0] >= pos else len(text))
        inside = [c for c in clauses if pos <= c[0] < (nxt if nxt is not None else len(text)) and not (nxt is None and act_level and c is act)]
        if not inside:
            continue
        c = inside[-1]
        e = parse_effective(c[2], signed_date, resolver=resolver, _parts=False)
        entry = {"applies_to": "Part %s of this act" % letter, "part": letter, "span_start": pos, "span_end": end,
                 "effective_date": e["effective_date"], "rule": e["rule"], "raw_clause": c[2]}
        if e["expires_date"]:
            entry["expires_date"] = e["expires_date"]
        if e.get("expires_rule"):
            entry["expires_rule"] = e["expires_rule"]
            if e.get("expires_reference"):
                entry["expires_reference"] = e["expires_reference"]
        out.append(entry)
    return out


# E2 (Oct 16 2026): the repeal is bound to a section's own sunset, not a date of this act
_UNIT = r"(?:section|subdivision|paragraph|subparagraph|clause|article|title|part|subsection|item|act|provision|chapter|undesignated\s+paragraph)s?"
SECTION_BOUND = [
    re.compile(r"(?:expire|repeal|deemed\s+(?:to\s+)?(?:expire|repeal(?:ed)?))(?:\s+and\s+(?:be\s+)?deemed\s+(?:to\s+)?repeal(?:ed)?)?\s+(?:on\s+)?the\s+same\s+date\s+as\s+such\s+" + _UNIT, re.I),
    re.compile(r"\bof\s+such\s+" + _UNIT + r"\b[^;]{0,140}?\band\s+shall\s+(?:be\s+)?(?:deemed\s+(?:to\s+)?(?:be\s+)?(?:expired?|repeal(?:ed)?)|expire|repeal)(?:\s+and\s+(?:be\s+)?deemed\s+(?:to\s+be\s+)?repealed)?\s+therewith", re.I),
    re.compile(r"\bshall\s+not\s+affect\s+the\s+(?:expiration|repeal)(?:\s+(?:and|or)\s+(?:expiration|repeal))?\s+of\s+the\s+amendments\s+thereto\b[^;]{0,300}?\band\s+shall\s+(?:expire|repeal)(?:\s+and\s+(?:be\s+)?deemed\s+(?:to\s+be\s+)?repeal(?:ed)?)?\s+therewith", re.I),
]
NAMED_CHAPTER_SECTION = re.compile(r"\bsections?\s+([\w.-]+)\s+of\s+chapter\s+(\d+)\s+of\s+the\s+laws\s+of\s+(\d{4})", re.I)


def section_bound_expiry(clause, resolver=None):
    """-> None, or {"expires_rule": "with_referenced_section", "expires_date": ISO|None, "reference": {...}|None}. The date is filled only
    when the clause names 'section N of chapter M of the laws of YYYY' and resolver(chapter=M, year=YYYY) returns that chapter's own
    expiry (record key expires_date, or a section_expiry entry for section N in its section_dates)."""
    hit = None
    for rx in SECTION_BOUND:
        m = rx.search(clause or "")
        if m and (hit is None or m.start() < hit.start()):
            hit = m
    if not hit:
        return None
    out = {"expires_rule": "with_referenced_section", "expires_date": None, "reference": None}
    named = list(NAMED_CHAPTER_SECTION.finditer(clause[max(0, hit.start() - 400):hit.end()]))
    if named and resolver:
        sec, ch, yr = named[-1].group(1), int(named[-1].group(2)), int(named[-1].group(3))
        rec = None
        try:
            rec = resolver(bills=[], chapter=ch, year=yr)
        except Exception:
            rec = None
        out["reference"] = {"section": sec, "chapter": ch, "year": yr}
        if rec:
            exp = rec.get("expires_date")
            for x in rec.get("section_dates") or []:
                if x.get("rule") in ("section_expiry", "section_expiry_whole_act") and x.get("expires_date"):
                    mm = re.match(r"\s*sections?\s+(.*?)\s+of this act", x.get("applies_to") or "", re.I)
                    if mm and sec.lower() in [w.strip().lower() for w in re.split(r",|\band\b", mm.group(1))]:
                        exp = x["expires_date"]
            out["expires_date"] = exp
    return out


def parse_effective(text, signed_date, resolver=None, _parts=True):
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
        refinfo = _amended_fixed_reference(text, refinfo, signed)
    eff, rule, ref_used = _single(clause, signed, refinfo)
    if rule == "unparsed" and not re.search(r"take effect|takes effect", text or "", re.I):
        rule = "text_truncated"           # M19 (Oct 12 2026): the cached text ends before the act clause (budget schedules) or is empty
    retros = _retro(clause, signed)
    expires = _expiry(clause, eff, signed)
    if not expires:
        expires = _signed_expiry(clause, signed)
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
    # M20 (Oct 13 2026): "...provided, however, that: 1. ...; 2. sections three, four and five of this act shall take effect January 1, 2012;"
    # a numbered or lettered proviso names the sections and carries its own date
    seen = {(x["applies_to"], x["effective_date"]) for x in sections}
    for m in re.finditer(r"(?:^|[:;]|\b\d{1,2}\.|\([a-z]\))\s*(sections?\s+[\w,\s-]+?\s+of this act)\s+shall take effect\s+([^;]*)", clause, re.I):
        rest = re.sub(r"\s+", " ", m.group(2)).strip()
        if re.match(r"(?:on|upon)\s+the\s+(?:expiration|repeal|termination)", rest, re.I) or re.search(r"effective date|such date|such chapter", rest, re.I):
            continue                # keyed to another event: the on_expiration entry below, or a date this parser cannot fix
        e2, r2, _ = _single("This act shall take effect " + rest, signed, None)
        ap = re.sub(r"\s+", " ", m.group(1)).strip()
        if e2 and (ap, e2.isoformat()) not in seen:
            seen.add((ap, e2.isoformat()))
            sections.append({"applies_to": ap, "effective_date": e2.isoformat(), "rule": r2})
    # M21 (Oct 13 2026): "the amendments made by section one of this act shall expire and be deemed repealed April 1, 2015"
    sect_exp = []
    for m in re.finditer(r"(sections?\s+[\w,\s-]+?\s+of this act)\s+shall\s+(?:expire|be deemed to expire)(?:\s+and\s+be\s+deemed\s+repealed)?(?:\s+on)?\s+(" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})", clause, re.I):
        d = date(int(m.group(4)), MONTHS[m.group(2).lower()], int(m.group(3)))
        sect_exp.append({"applies_to": re.sub(r"\s+", " ", m.group(1)).strip(), "effective_date": None, "rule": "section_expiry", "expires_date": d.isoformat()})
    sections += sect_exp
    for m in re.finditer(r"(sections?\s+[\w,\s-]+?\s+of this act)\s+shall take effect\s+(?:on|upon)\s+the\s+(?:expiration|repeal|termination)\s+of\s+([^;.]*)", clause, re.I):
        # keyed to another law's expiration (Oct 8 2026, audit B): the date is open until that law expires, never the act's own date
        sections.append({"applies_to": re.sub(r"\s+", " ", m.group(1)).strip(), "effective_date": None, "rule": "on_expiration_of_other_law", "open_date": True,
                         "depends_on": re.sub(r"\s+", " ", m.group(2)).strip()})
    for ap, d in retros:
        if ap:
            sections.append({"applies_to": ap, "effective_date": None, "rule": "retroactive", "retroactive_to": d.isoformat()})
    # top level only for a statement about the act as a whole (main clause, or a proviso conditioned on the act's own signing
    # date); one that names a section ("section 191 ... deemed in full force") stays in section_dates
    if sect_exp and not expires:
        nums = {int(x) for x in re.findall(r"(?m)^(?:§|Section)\s*(\d+)\.", (text or "").replace("{{", ""))}
        subst = {n for n in nums if not re.search(r"(?m)^(?:§|Section)\s*%d\.[^\n]*shall take effect" % n, (text or ""))}
        from_text = set()
        for x in sect_exp:
            mm = re.match(r"\s*sections?\s+(.*?)\s+of this act", x["applies_to"], re.I)
            for part in re.split(r",|\band\b", mm.group(1) if mm else ""):
                n = words_to_int(part.strip()) if part.strip() else None
                if n:
                    from_text.add(n)
        if len(sect_exp) == 1 and subst and subst <= from_text:
            expires = date.fromisoformat(sect_exp[0]["expires_date"])
            sect_exp[0]["rule"] = "section_expiry_whole_act"
    retro = min({d for ap, d in retros if not ap}, default=None)
    out = {"effective_date": eff.isoformat() if eff else None, "rule": rule,
           "expires_date": expires.isoformat() if expires else None,
           "retroactive_to": retro.isoformat() if retro else None,
           "other_dates": [x for x in sections if x["rule"] != "retroactive"], "section_dates": sections, "raw_clause": clause}
    out["expires_rule"] = None
    if not out["expires_date"]:
        sb = section_bound_expiry(clause, resolver)
        if not sb and _parts:        # the proviso may sit in a lettered list before the closing clause: scan the act's tail for "made by section N of this act ..."
            tail = re.sub(r"\s+", " ", (text or "")[-6000:].replace("{{", "").replace("}}", ""))
            sb = section_bound_expiry(tail, resolver)
        if sb:
            out["expires_rule"], out["expires_date"] = sb["expires_rule"], sb["expires_date"]
            if sb["reference"]:
                out["expires_reference"] = sb["reference"]
    if _parts:
        out["section_dates"].extend(part_dates(text, signed_date, resolver))
    if ref_used and ref_used.get("amended_clause_ignored") and ref_used.get("amended_fixed_date"):
        note = {"applies_to": "the referenced chapter's effective-date section", "effective_date": ref_used["amended_fixed_date"], "rule": "amendment_after_original_effective_date",
                "note": "amended after the original effective date (D1): the original date stands"}
        out["other_dates"].append(note); out["section_dates"].append(note)
    if rule == "same_as_chapter_unresolved" and not ref_used and re.search(r"concurrent resolution", clause, re.I):
        # E3 (Oct 16 2026): a constitutional amendment has no chapter number; the lookups made are recorded instead of silence
        out["reference"] = {"tried": "concurrent resolution, no chapter: Open Legislation API search of the session's bills by its subject returned no resolution, "
                                     "and /api/3/resolutions/{session}/search returned 404; date left open"}
    if ref_used:
        out["reference"] = {k: ref_used.get(k) for k in ("bill", "chapter", "year", "signed_date", "effective_date", "rule", "tried") if k in ref_used}
    return out
