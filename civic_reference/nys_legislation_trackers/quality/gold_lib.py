"""Shared helpers for the gold regression set: quote matching and Wilson intervals."""
import json
import math
import os
import re

SCORED_FIELDS = ["agency", "agency_unit", "kind", "deadline_kind", "deadline_date", "extends_existing"]


def words(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def jaccard(a, b):
    wa, wb = set(words(a)), set(words(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def quote_score(a, b):
    """1.0 when one normalised quote contains the other, else word Jaccard."""
    na, nb = " ".join(words(a)), " ".join(words(b))
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0
    return jaccard(a, b)


def quotes_match(a, b, threshold=0.5):
    return quote_score(a, b) >= threshold


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


# ---- agency normalisation (auditor free text vs crosswalk codes) ----
_XWALK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "agency_crosswalk_nys.json")
# normalised auditor phrasing -> canonical name; keys and values go through _plain
_ALIASES = {
    "education department": "SED",
    "department of parks and recreation": "DPR",
    "department of parks recreation": "DPR",
    "public bodies state and local": "State and local bodies",
    "retirement board of the new york state teachers retirement system": "Teachers' Retirement System Board",
    "new york state teachers retirement system": "Teachers' Retirement System Board",
    "teachers retirement system of the state of new york": "Teachers' Retirement System Board",
    "office of the state comptroller": "State Comptroller",
}
_index = None


def _plain(s):
    """Strip parentheticals, lower-case, drop punctuation."""
    s = re.sub(r"\([^)]*\)", " ", s or "")
    return " ".join(re.findall(r"[a-z0-9]+", s.lower().replace("'", "")))


def _build_index():
    global _index
    if _index is None:
        _index = {}
        with open(_XWALK) as f:
            x = json.load(f)
        for a in x["agencies"]:
            c = a["canonical"]
            for n in [c, a.get("full_name"), a.get("display_name")] + list(a.get("variants") or []):
                if n:
                    _index.setdefault(_plain(n), c)
        for k, c in x.get("lookup", {}).items():
            _index.setdefault(_plain(k), c)
        for k, c in _ALIASES.items():
            _index[_plain(k)] = c
        for c in set(_ALIASES.values()):
            _index.setdefault(_plain(c), c)
    return _index


def agency_code(s):
    """Canonical key for an agency string, or None when it is not a known agency/alias."""
    if not s:
        return None
    c = _build_index().get(_plain(s))
    return _plain(c) if c else None


def agency_equal(stored, expected, stored_full=None):
    """True when stored matches expected through normalisation (unknown expected: word Jaccard >= 0.6)."""
    if not stored and not expected:
        return True
    if not stored or not expected:
        return False
    ek = agency_code(expected)
    if ek:
        return ek in {agency_code(stored), agency_code(stored_full)}
    cand = [stored, stored_full]
    return _plain(stored) == _plain(expected) or any(c and jaccard(_plain(c), _plain(expected)) >= 0.6 for c in cand)


def is_act_clause(quote):
    return " ".join(words(quote))[:30].startswith("this act shall take effect")
