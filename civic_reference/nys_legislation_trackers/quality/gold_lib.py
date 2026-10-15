"""Shared helpers for the gold regression set: quote matching and Wilson intervals."""
import math
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
