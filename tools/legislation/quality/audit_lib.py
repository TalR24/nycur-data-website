"""
Shared helpers for parsing past audit packets and prose verdicts into the
structured "Results format" documented in criteria.md. Used by
seed_gold_from_past.py (one-off backfill of Q/gold_*.json from the audit4 /
spot_audit / ab2_audit material) and importable from ingest.py / score_gold.py.
"""
from __future__ import annotations

import re


def _norm_key_text(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())[:200]


def gold_key_obl(g: dict) -> tuple:
    """Dedup key for a gold_obligations.json entry, shared by ingest.py and
    seed_gold_from_past.py so a re-seed or a re-ingest of the same finding
    lands on the same key. A "missed" entry has no tracker record to key by
    quote prefix reliably (the auditor's quote is often a paraphrase, or
    blank with the finding only in `note`); key those by matter + normalized
    missed text instead, so distinct misses in the same law don't collide on
    an empty/near-empty quote."""
    if g.get("verdict") == "missed":
        return (g["matter_id"], "missed", _norm_key_text(g.get("quote") or g.get("note")))
    return (g["matter_id"], _norm_key_text(g.get("quote")), g.get("verdict"))

# A packet record line looks like:
# - R1 kind=duty agency=DOB unit=None actor='the department' existing_code=False
RECORD_HEADER = re.compile(
    r"^-\s+([A-Z]\d+)\s+kind=(\S+)\s+agency=(\S+)(?:\s+unit=(\S+))?\s+actor=(.+?)\s+existing_code=(\S+)\s*$"
)


def parse_packet_records(packet_text: str) -> dict[str, dict]:
    """Returns label -> {kind, agency, unit, actor, existing_code, citation,
    deliverable, deadline_kind, deadline_text, deadline_date, recurrence, quote, summary}."""
    lines = packet_text.splitlines()
    out: dict[str, dict] = {}
    i = 0
    while i < len(lines):
        m = RECORD_HEADER.match(lines[i])
        if not m:
            i += 1
            continue
        label, kind, agency, unit, actor, existing_code = m.groups()
        rec = {
            "kind": kind, "agency": agency, "unit": None if unit in (None, "None") else unit,
            "actor": actor.strip("'\""), "existing_code": existing_code == "True",
        }
        j = i + 1
        while j < len(lines) and not RECORD_HEADER.match(lines[j]) and lines[j].strip():
            line = lines[j].strip()
            if line.startswith("summary:"):
                rec["summary"] = line[len("summary:"):].strip()
            elif line.startswith("citation:"):
                parts = line[len("citation:"):].split("|")
                rec["citation"] = parts[0].strip()
                if len(parts) > 1 and "deliverable:" in parts[1]:
                    rec["deliverable"] = parts[1].split("deliverable:")[1].strip()
            elif line.startswith("deadline:"):
                bits = [b.strip() for b in line[len("deadline:"):].split("|")]
                if len(bits) >= 4:
                    rec["deadline_kind"] = bits[0]
                    rec["deadline_text"] = None if bits[1] == "None" else bits[1]
                    rec["deadline_date"] = None if bits[2] == "None" else bits[2]
                    rec["recurrence"] = bits[3].replace("recurrence=", "")
            elif line.startswith("quote:"):
                rec["quote"] = line[len("quote:"):].strip()
            j += 1
        out[label] = rec
        i = j
    return out


CRITERION_RE = re.compile(r"\((\d(?:/\d)*)\)")


def parse_wrong_detail(text: str) -> tuple[str | None, list[str], str]:
    """'R3: (5) deadline_type none ...' -> (label, ['5'], note). Label may be
    None if the string has no leading R#/A#/B# token (rare free-text note)."""
    m = re.match(r"^([A-Z]\d+):\s*(.*)$", text.strip())
    if not m:
        return None, [], text.strip()
    label, rest = m.groups()
    crit_m = CRITERION_RE.search(rest)
    criteria = crit_m.group(1).split("/") if crit_m else []
    return label, criteria, rest.strip()


def field_for_criterion(criteria: list[str]) -> str | None:
    """Best-effort map from a failed criterion number to the tracker field
    most likely to hold the auditor's stated right value; None when the
    criterion (1 quote, 2 real-duty, 6 new-matter) has no single field."""
    return {"3": "agency", "4": "kind", "5": "deadline_date"}.get(criteria[0]) if criteria else None
