#!/usr/bin/env python3
"""Blind adjudication of protected-law re-extraction disagreements.

For every law reconcile_protected.py diff found a disagreement in, asks
claude-opus-5 ONE question per law: given the law's own definitions and the
text around each disputed quote, which of two unlabeled records (A/B for a
paired disagreement; a single yes/no judgment for a record only one side
has) is right, by the same criteria the Sep 27 2026 audits used. Writes
pipeline/reconcile_decisions.json, the input reconcile_protected.py apply
turns into record_overrides.json entries.

Resumable: each law's result is checkpointed to pipeline/cache/verify/
{matter_id}.json (gitignored, like the rest of cache/) before the next law is
attempted. An ERRORED law is never cached, so a resumed run retries it.

Text: reads pipeline/cache/text/{matter_id}.txt when present; in CI (cache/ is
gitignored and empty there) it fetches the law page and, if needed, its PDF
attachment the SAME way reextract_queued.py does (fetch_page +
parse_detail_page + attachment_text) rather than a new fetcher.

Usage:
    python3 pipeline/verify_obligations.py --dry-run
    ANTHROPIC_API_KEY=sk-ant-... python3 pipeline/verify_obligations.py
    python3 pipeline/verify_obligations.py --concurrency 4 --matters 1234 5678
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
TEXT_CACHE = HERE / "cache" / "text"
VERIFY_CACHE = HERE / "cache" / "verify"
DIFF_PATH = HERE / "reconcile_protected.json"
DECISIONS_PATH = HERE / "reconcile_decisions.json"

sys.path.insert(0, str(HERE))
import law_definitions  # noqa: E402
from extract_obligations import _nullable, LAWS_JSON  # noqa: E402
from sweep_restated_duties import split_markers, condense  # noqa: E402
from reconcile_protected import FIELDS_TO_DIFF  # noqa: E402

MODEL = "claude-opus-5"
CONTEXT_RADIUS = 2500  # +- chars of law text around the disputed quote
MAX_TOKENS = 16000      # adaptive-thinking output counts toward this cap

# Copied verbatim from the "Duties and powers" section of
# /Users/troded/.claude/jobs/bcbcad1f/tmp/audit4/criteria.md (Sep 27 2026),
# the same criteria the blind human/model audits used, so this adjudication
# is graded the same way the corpus already was.
CRITERIA = """A record is CORRECT if all hold:
(1) the quote appears in the law text (ignore {{ }} markers and whitespace);
(2) it is a real duty (the law requires a city agency or official to do something) or power (the law authorises one to act), not a private party's obligation or a construction clause;
(3) the agency is right, or honestly unresolved when the law names none; when a `unit` is shown, the unit is the office/body the law names and the agency is its parent or convening agency (offices inside a department count under the department; task forces/boards under the agency that convenes them; Mayor's Office only when the law has the mayor create or designate it; "Citywide (all agencies)" only for duties on every/each/all/any agency);
(4) kind duty/power is right;
(5) deadline and recurrence are right, or blank when the law states none (powers carry no deadline by design);
(6) it is new matter this law creates, or is flagged existing_code=True when the law only reprints it.
Otherwise WRONG: name the failed criterion. A duplicate of another record in the same law is WRONG. MISSED = a duty or power the law creates in new matter with no record."""

# `right_value` is a fixed object over FIELDS_TO_DIFF only (reconcile_protected
# diffs no other fields), every property present and nullable, matching the
# same additionalProperties:false / required-every-property / _nullable
# discipline OBLIGATIONS_SCHEMA follows (Sep 27 2026 rework).
_RIGHT_VALUE_SCHEMA = {
    "type": "object",
    "properties": {f: _nullable({"type": "string"}) for f in FIELDS_TO_DIFF},
    "required": list(FIELDS_TO_DIFF),
    "additionalProperties": False,
}
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    # paired item: which side is right. One-sided item: "A"
                    # means yes (the record is real, as shown), "B" means no.
                    "winner": {"type": "string", "enum": ["A", "B", "neither"]},
                    "right_value": _nullable(_RIGHT_VALUE_SCHEMA),
                    "evidence": {"type": "string"},
                },
                "required": ["item_id", "winner", "right_value", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def get_law_text(matter_id: str, law: dict | None) -> str:
    """Same text the extraction/re-extraction path uses: the cache first,
    then (CI, where cache/text is empty and gitignored) the same fetch
    reextract_queued.py uses for a missing law."""
    p = TEXT_CACHE / f"{matter_id}.txt"
    if p.exists():
        return p.read_text(errors="ignore")
    if not law or not law.get("legistar_url"):
        return ""
    from reextract_queued import fetch_page, attachment_text, sanitize
    from fetch_enacted_laws import parse_detail_page
    try:
        html = fetch_page(law["legistar_url"])
        rec = parse_detail_page(html, matter_id, law.get("legistar_guid", ""))
        text = rec.get("_text") or ""
        if len(text) < 500 or "ATTACHMENT" in text.upper()[:400]:
            pdf_text = attachment_text(html)
            if pdf_text and len(pdf_text) > len(text):
                text = pdf_text
        text = sanitize(text)
        TEXT_CACHE.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return text
    except Exception as e:  # noqa: BLE001
        print(f"  {matter_id}: could not fetch law text ({e})")
        return ""


def text_window(quote: str, text: str, radius: int = CONTEXT_RADIUS) -> str:
    """A real +-radius char slice of the RAW law text around the quote,
    located with the same split_markers/condense helpers reattribute_reprints
    already uses (no new locator): condense() maps a whitespace/marker-free
    haystack back to raw offsets, so the slice comes from the actual text
    rather than a normalized reconstruction."""
    if not text or not quote:
        return text[:radius * 2] if text else ""
    plain, _flags = split_markers(text)
    hay, idx = condense(plain)
    needle = "".join(c.lower() for c in quote if not c.isspace())
    at = hay.find(needle)
    if at < 0 or not idx:
        # punctuation and quote marks differ between quote and text often
        # enough (17 of 200, Sep 27 2026): match letters and digits only,
        # longest unambiguous prefix first, as provision_context does
        keep = [i for i, c in enumerate(plain) if c.isalnum()]
        hay2 = "".join(plain[i].lower() for i in keep)
        q2 = "".join(c.lower() for c in quote if c.isalnum())
        for n in (240, 120, 60, 30):
            if len(q2) >= n and hay2.count(q2[:n]) == 1:
                j = hay2.find(q2[:n])
                a, b = keep[j], keep[min(j + len(q2) - 1, len(keep) - 1)]
                return plain[max(0, a - radius):b + radius]
        return plain[:radius * 2]
    start_raw = idx[at]
    end_raw = idx[min(at + len(needle) - 1, len(idx) - 1)]
    return plain[max(0, start_raw - radius):end_raw + radius]


def build_law_items(matter_id: str, law_diff: dict) -> list[dict]:
    """One dict per disputed item for this law: a field disagreement on a
    paired record, a snapshot-only record (real duty the re-extraction
    dropped?), or a current-only record (a duty the re-extraction invented?).
    `record_kind` and any old/new wording live only in this local structure;
    none of it reaches the prompt (blinding, item 3)."""
    items = []
    for i, d in enumerate(law_diff.get("disagreements", [])):
        items.append({"item_id": f"i{i}", "record_kind": "disagreement",
                      "quote": d.get("current_quote") or d.get("quote", ""),
                      "agency": d.get("agency"), "fields": d.get("fields", {})})
    n = len(items)
    for i, s in enumerate(law_diff.get("snapshot_only", [])):
        items.append({"item_id": f"i{n + i}", "record_kind": "snapshot_only",
                      "quote": s.get("quote", ""), "agency": s.get("agency"),
                      "snapshot_fields": s})
    n = len(items)
    for i, c in enumerate(law_diff.get("current_only", [])):
        items.append({"item_id": f"i{n + i}", "record_kind": "current_only",
                      "quote": c.get("quote", ""), "agency": c.get("agency"),
                      "current_fields": c})
    return items


def build_prompt(matter_id: str, text: str, items: list[dict]) -> tuple[str, dict]:
    """Returns (prompt, label_key) where label_key maps item_id -> which side
    ("snapshot"|"current") the prompt called "A" (paired items) or asked the
    yes/no question about (one-sided items). Kept locally, never sent."""
    defs_block = law_definitions.defining_sentences(text) if text else ""
    label_key: dict[str, str] = {}
    rng = random.Random(matter_id)  # deterministic per law, resumable
    parts = [
        f"You are adjudicating disputed extraction records for NYC Local Law "
        f"matter {matter_id}. Criteria:\n{CRITERIA}\n",
    ]
    if defs_block:
        parts.append(f"DEFINITIONS AND ESTABLISHING SENTENCES IN THIS LAW:\n{defs_block}\n")
    for item in items:
        quote = item.get("quote", "")
        window = text_window(quote, text) if text else quote
        kind = item["record_kind"]
        if kind == "disagreement":
            a_is_snapshot = rng.random() < 0.5
            snap_view = {k: v["snapshot"] for k, v in item["fields"].items()}
            cur_view = {k: v["current"] for k, v in item["fields"].items()}
            a_val, b_val = (snap_view, cur_view) if a_is_snapshot else (cur_view, snap_view)
            label_key[item["item_id"]] = "snapshot" if a_is_snapshot else "current"
            parts.append(
                f"--- item {item['item_id']} ---\n"
                f"Law text window:\n{window}\n"
                f"Quote: {quote!r}\n"
                f"A: {json.dumps(a_val, ensure_ascii=False)}\n"
                f"B: {json.dumps(b_val, ensure_ascii=False)}\n"
                f"Which is right, A or B, or neither (state right_value)?\n")
        else:
            fields = item.get("snapshot_fields") or item.get("current_fields") or {}
            label_key[item["item_id"]] = "snapshot" if kind == "snapshot_only" else "current"
            parts.append(
                f"--- item {item['item_id']} ---\n"
                f"Law text window:\n{window}\n"
                f"Quote: {quote!r}\n"
                f"Proposed record: {json.dumps(fields, ensure_ascii=False)}\n"
                f"Is this a real duty or power the law creates, with these "
                f"field values? Answer 'A' for yes, 'B' for no. If the "
                f"fields need a correction rather than a flat yes, answer "
                f"'neither' and state right_value.\n")
    parts.append(
        "\nFor every item return item_id, winner (A, B, or neither), "
        "right_value (an object with exactly these fields: "
        + ", ".join(FIELDS_TO_DIFF) + " — null for any field you are not "
        "correcting; null when winner is not 'neither'), and evidence (a "
        "short quote from the law text window).")
    return "\n".join(parts), label_key


def estimate_tokens(prompt: str) -> int:
    return int(len(prompt) / 3.5)


def call_law(client, matter_id: str, text: str, items: list[dict],
            retries: int = 4) -> dict:
    prompt, label_key = build_prompt(matter_id, text, items)
    delay = 2.0
    last_err = None
    result = None
    for attempt in range(retries):
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
            ) as stream:
                msg = stream.get_final_message()
            result = json.loads(next(b.text for b in msg.content if b.type == "text"))
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(delay)
            delay *= 2
    if result is None:
        return {"matter_id": matter_id, "error": str(last_err), "items": []}

    by_id = {it["item_id"]: it for it in items}
    out_items = []
    for r in result.get("results", []):
        it = by_id.get(r.get("item_id"))
        if not it:
            continue
        label = label_key.get(r["item_id"])
        winner = r.get("winner")
        snapshot_label = "A" if label == "snapshot" else "B"
        out_items.append({
            "item_id": r["item_id"], "record_kind": it["record_kind"],
            "quote": it.get("quote", ""), "agency": it.get("agency"),
            "winner": winner, "snapshot_label": snapshot_label,
            "fields": it.get("fields"),                  # disagreement only
            "snapshot_fields": it.get("snapshot_fields"),
            "current_fields": it.get("current_fields"),
            "right_value": r.get("right_value"),
            "evidence": r.get("evidence", ""),
        })
    return {"matter_id": matter_id, "items": out_items}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--matters", nargs="+", default=None)
    args = ap.parse_args()

    if not DIFF_PATH.exists():
        sys.exit(f"{DIFF_PATH} missing; run reconcile_protected.py diff first")
    diffs = json.loads(DIFF_PATH.read_text())
    if args.matters:
        diffs = {m: d for m, d in diffs.items() if m in set(args.matters)}
    laws_by_id = {l["matter_id"]: l for l in json.loads(LAWS_JSON.read_text())["laws"]} \
        if LAWS_JSON.exists() else {}

    todo = {}
    for mid, law_diff in diffs.items():
        items = build_law_items(mid, law_diff)
        if items:
            todo[mid] = items

    if args.dry_run:
        total_tokens = 0
        for mid, items in todo.items():
            text = (TEXT_CACHE / f"{mid}.txt").read_text(errors="ignore") \
                if (TEXT_CACHE / f"{mid}.txt").exists() else ""
            prompt, _ = build_prompt(mid, text, items)
            total_tokens += estimate_tokens(prompt)
        print(f"--dry-run: {len(todo)} calls, ~{total_tokens:,} input tokens "
              f"(chars/3.5), 0 calls made")
        return

    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")
    import anthropic
    client = anthropic.Anthropic(max_retries=8)

    VERIFY_CACHE.mkdir(parents=True, exist_ok=True)
    decisions = json.loads(DECISIONS_PATH.read_text()) if DECISIONS_PATH.exists() else {}

    def process(mid: str) -> tuple[str, dict]:
        cache_file = VERIFY_CACHE / f"{mid}.json"
        if cache_file.exists():
            return mid, json.loads(cache_file.read_text())
        text = get_law_text(mid, laws_by_id.get(mid))
        result = call_law(client, mid, text, todo[mid])
        if not result.get("error"):
            # an errored law is never cached, so a resumed run retries it
            cache_file.write_text(json.dumps(result, indent=1))
        return mid, result

    errored = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(process, mid): mid for mid in todo}
        for fut in as_completed(futures):
            mid, result = fut.result()
            if result.get("error"):
                errored += 1
                print(f"{mid}: FAILED {result['error']}")
                continue
            decisions[mid] = {"items": result.get("items", [])}
            print(f"{mid}: {len(result.get('items', []))} items adjudicated")

    DECISIONS_PATH.write_text(json.dumps(decisions, indent=1))
    print(f"wrote {DECISIONS_PATH}: {len(decisions)} laws, {errored}/{len(todo)} errored")
    if todo and errored / len(todo) > 0.10:
        sys.exit(f"more than 10% of laws errored ({errored}/{len(todo)}); not treating this as a clean run")


if __name__ == "__main__":
    main()
