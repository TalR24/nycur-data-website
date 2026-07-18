#!/usr/bin/env python3
"""
Canonical NYC agency naming for the Fiscal Impacts Tracker.

Wraps pipeline/agency_crosswalk.json, built from NYC Open Data t3jq-9nkf
(NYC Agencies and Governance Organizations) by the data website's
civic_reference/legislation_implementation_tracker/pipeline/build_agency_crosswalk.py
(that script is the single source of truth; regenerate there and copy the JSON
here when the dataset updates).

Usage:
    from agency_canon import canonicalize
    canon, full = canonicalize("Dept of Transportation")   # ("DOT", "New York City Department of Transportation")
    canon, full = canonicalize("Unknown Body")             # (None, None) -> keep original
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_CW_PATH = Path(__file__).resolve().parent / "agency_crosswalk.json"
_cw = json.loads(_CW_PATH.read_text())
_LOOKUP: dict[str, str] = _cw["lookup"]
_BY_CANON: dict[str, dict] = {a["canonical"]: a for a in _cw["agencies"]}

_PREFIX = re.compile(r"^(the\s+)?(new\s+york\s+city\s+|nyc\s+|city\s+)?", re.I)


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = s.replace("&", "and")
    s = re.sub(r"[.,'’]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def canonicalize(name: str | None) -> tuple[str | None, str | None]:
    """Resolve a free-text agency name or abbreviation to
    (canonical_abbrev, full_name), or (None, None) if unknown."""
    if not name:
        return None, None
    candidates = [name]
    stripped = _PREFIX.sub("", name).strip()
    if stripped and stripped != name:
        candidates.append(stripped)
    m = re.match(r"(?:the\s+)?commissioner\s+of\s+(.+)", name, re.I)
    if m:
        candidates.append(f"department of {m.group(1)}")
        candidates.append(m.group(1))
    for cand in candidates:
        canon = _LOOKUP.get(_norm(cand))
        if canon:
            return canon, _BY_CANON.get(canon, {}).get("full_name", canon)
    return None, None
