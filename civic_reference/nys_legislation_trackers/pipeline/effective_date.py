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
    p = hit[-1]
    p = re.split(r"\s*Fiscal\s+NOTE", p, flags=re.I)[0]
    return p.strip()


def _single(clause, signed):
    """(effective_date, rule, retroactive_to) for the first 'shall take effect' statement of the clause."""
    c = re.sub(r"^\s*(?:§|Section|S)\s*\d+\.\s*", "", clause)
    sent = re.split(r";|\.\s+(?=[A-Z])", c)[0]
    low = sent.lower()
    if re.search(r"same date and in the same manner|same date and same manner|same manner and on the same date", low):
        return None, "same_as_chapter", None
    m = re.search(r"take effect (?:on )?(?:the )?first of (" + MONTH_RE + r") next succeeding", low)
    if m:
        return next_succeeding(MONTHS[m.group(1)], 1, signed), "first_of_month_next_succeeding", None
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?(" + ORD_WORD + r"|\d+(?:st|nd|rd|th)?) day (?:next )?(?:after|following)", low)
    if m:
        n = words_to_int(m.group(1)) if not m.group(1)[0].isdigit() else int(re.sub(r"\D", "", m.group(1)))
        if n is not None:
            return signed + timedelta(days=n), "nth_day_after_law", None
    m = re.search(r"(?:take|takes) effect (?:on )?(?:the )?(" + NUM_WORDS + r"|\d+)\s+(day|days|month|months)\s+(?:next\s+)?(?:after|following)", low)
    if m and m.group(1).strip():
        n = words_to_int(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))
        if n is not None:
            if m.group(2).startswith("month"):
                return add_months(signed, n), "n_months_after_law", None
            return signed + timedelta(days=n), "n_days_after_law", None
    m = re.search(r"(?:take|takes) effect (?:on )?(" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})", low)
    if m:
        return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))), "fixed_date", None
    m = re.search(r"take effect immediately", low)
    if m:
        retro = re.search(r"in full force and effect on and after (" + MONTH_RE + r")\s+(\d{1,2}),?\s+(\d{4})", c.lower())
        r = date(int(retro.group(3)), MONTHS[retro.group(1)], int(retro.group(2))) if retro else None
        return signed, "immediately", r
    return None, "unparsed", None


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


def parse_effective(text, signed_date):
    """text: the full act text (marked or plain) or just the clause. signed_date: ISO string of the governor's signature."""
    signed = _d(signed_date)
    clause = final_clause(text) or re.sub(r"\s+", " ", text or "").strip()
    eff, rule, retro = _single(clause, signed)
    expires = _expiry(clause, eff, signed)
    others = []
    for m in re.finditer(r";\s*provided(?:,? however,?| further,?)?,?\s+that\s+(.*?)(?=;\s*provided|$)", clause, re.I):
        part = m.group(1)
        if re.search(r"shall take effect|takes effect", part, re.I):
            sect = re.search(r"((?:sections?|paragraph|subdivision)[^,]*?(?:of this act|made by section [\w\s-]+ of this act))", part, re.I)
            e2, r2, _ = _single("This act " + part[part.lower().find("shall take effect"):], signed) if "shall take effect" in part.lower() else (None, "unparsed", None)
            others.append({"applies_to": (sect.group(1) if sect else part[:80]).strip(), "effective_date": e2.isoformat() if e2 else None, "rule": r2})
    return {"effective_date": eff.isoformat() if eff else None, "rule": rule,
            "expires_date": expires.isoformat() if expires else None,
            "retroactive_to": retro.isoformat() if retro else None,
            "other_dates": others, "raw_clause": clause}
