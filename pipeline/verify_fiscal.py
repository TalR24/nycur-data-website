#!/usr/bin/env python3
"""BILLING: the default path calls the Anthropic API (Opus, billed per token,
not covered by Claude Max). Prefer --emit-packets / --ingest, judged by Claude
Code subagents on the Max plan; the API path needs Tal's approval first.


Independent LLM verification of every record in fiscal_impacts.json against
the statement actually used, judged by the fiscal rules in
civic_reference/nyc_council_legislation_trackers/quality/criteria.md.

Runs in GitHub Actions (ANTHROPIC_API_KEY). Mirrors the SDK usage of
extract_fiscal_data() in fetch_fiscal_impacts.py: model "claude-opus-5",
messages.create with output_config json_schema so the response is
guaranteed-parseable JSON, the same retry/backoff shape.

Resumable: each matter's verdict is cached in pipeline/cache/fiscal_verify/
(gitignored) and skipped on a rerun unless --force.

Usage:
    python3 pipeline/verify_fiscal.py --dry-run
    python3 pipeline/verify_fiscal.py --matters 12345 67890
    python3 pipeline/verify_fiscal.py --matters 12345,67890
    python3 pipeline/verify_fiscal.py --limit 20
    python3 pipeline/verify_fiscal.py                      # every record
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from fetch_fiscal_impacts import (  # noqa: E402
    create_session, get_fiscal_attachment, download_docx, extract_docx_text,
)
from claude_batch import cached_content, Usage, message_text  # noqa: E402

USAGE = Usage()  # caching only here (verify_fiscal.py is not in batch mode's scope)

FISCAL_DATA = REPO / "civic_reference" / "nyc_council_fiscal_impacts_tracker" / "data" / "fiscal_impacts.json"
OVERRIDES_PATH = HERE / "fiscal_overrides.json"
CRITERIA = REPO / "civic_reference" / "nyc_council_legislation_trackers" / "quality" / "criteria.md"
CACHE_DIR = HERE / "cache" / "fiscal_verify"
OUT_DIR = REPO / "civic_reference" / "nyc_council_legislation_trackers" / "quality"

VERIFY_MODEL = "claude-opus-5"
TEXT_CAP = 150_000
CONCURRENCY = 4
MAX_TOKENS = 16000  # adaptive thinking counts toward this budget
MIN_LEGISTAR_INTERVAL = 1.0  # seconds between Legistar requests, shared across every worker
ERROR_EXIT_THRESHOLD = 0.10


class _RateLimiter:
    """Shared across the whole worker pool: no two threads hit Legistar less
    than MIN_LEGISTAR_INTERVAL apart, however many workers are running."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._min_interval - (now - self._last)
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


LEGISTAR_LIMITER = _RateLimiter(MIN_LEGISTAR_INTERVAL)

# Mirrors FISCAL_SCHEMA's _obj() in fetch_fiscal_impacts.py: every object is
# additionalProperties: false with every property required, and any value
# whose type could vary (tracker_value/right_value: a number, a list, a bool
# in the tracker) is asked for as its string representation rather than an
# open union, since the API rejects too many nullable/union types (fetch_
# fiscal_impacts.py comment, Sep 24 2026).
_STR = {"type": "string"}
_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _obj(props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_OBJ_ERROR = _obj({
    "field": _STR, "tracker_value": _NULLABLE_STR, "right_value": _NULLABLE_STR, "evidence": _STR,
})
VERIFY_SCHEMA = _obj({
    "verdict": {"type": "string", "enum": ["correct", "wrong"]},
    "errors": {"type": "array", "items": _OBJ_ERROR},
})

TRACKER_FIELDS = [
    "total_revenue", "total_expenditure", "total_capital", "net_fiscal_impact", "totals_basis",
    "time_limited_program", "outlasts_statement", "program_end_fy", "sunset_quote",
    "costs_already_in_financial_plan", "agencies_abbrev", "fiscal_table_columns",
]

# House rules the Opus verifier kept re-raising against correct records (Sep
# 27 2026 adjudication of its first 60 "wrong" verdicts: 34 CONFIRMED, 82
# REJECTED; the revenue-loss rule alone caused 50 of the 82 rejections).
# Stated verbatim in the prompt so the verifier stops re-litigating them.
HOUSE_RULES = """HOUSE RULES (do not re-raise these as errors; they are settled tracker conventions):
- A revenue loss is stored as a positive expenditure (the cost of the reduction), not as negative
  revenue. Judge total_revenue and total_expenditure together against net_fiscal_impact, not the
  sign of total_revenue alone.
- Fiscal years are stored as two digits: 30 means FY2030, not 1930 or year 30.
- A program that ends on July 1 or July 2 closes out the prior fiscal year (the FY that had just
  run its course), not the FY that technically begins on July 1.
- Only the statement's own repeal/expiration/sunset sentence makes a program time-limited. A
  multi-year spending schedule, a stated cost horizon ("over ten years"), or a one-year study does
  NOT make the program itself time-limited unless the statement separately says the program ends.
- An agency named only as consulted, reviewing, or using its own existing resources (no new cost
  or line item) is not listed in agencies_abbrev.
"""


def load_override(record: dict) -> dict | None:
    """The record's pinned override, if any, tied to the same attachment_id
    (a newer statement voids it, same rule as apply_overrides() in
    fetch_fiscal_impacts.py)."""
    if not OVERRIDES_PATH.exists():
        return None
    overrides = json.loads(OVERRIDES_PATH.read_text())
    entry = overrides.get(str(record.get("matter_id")))
    if not entry or str(record.get("attachment_id")) != str(entry.get("attachment_id")):
        return None
    return entry


# Prompt caching (Tal, Sep 28 2026): everything identical across every
# record (the intro, FISCAL RULES, HOUSE_RULES, and the judging instructions,
# which used to close the prompt AFTER the per-record data) is now one fixed
# block that ends the same instructions but BEFORE the per-record data, so it
# can be a stable cached prefix. Same wording throughout, just moved; "above"
# became "below" since the fields it refers to now follow instead of precede.
def build_prompt_fixed(rules: str) -> str:
    return f"""You are auditing one row of the NYC Council Fiscal Impacts tracker against the fiscal
impact statement it was extracted from.

FISCAL RULES (from the tracker's own audit criteria):
---
{rules}
---

{HOUSE_RULES}
Judge the record against the rules and the statement only. Return verdict "correct" if every
tracker field below follows the rules from this statement; otherwise "wrong" with one entry per
incorrect field: the field name, the tracker's current value, the right value per the rules, and
the statement text or citation that shows it. Write tracker_value and right_value as plain text
exactly as they should appear (e.g. "1800000", "true", "[\\"DOF\\", \\"DOB\\"]", or "null" for
absent), not as JSON types.
"""


def build_prompt_variable(statement_text: str, record: dict) -> str:
    tracker_view = {k: record.get(k) for k in TRACKER_FIELDS}
    override = load_override(record)
    override_block = ""
    if override:
        override_block = f"""
PINNED HUMAN AUDIT (same statement, attachment_id {record.get('attachment_id')}):
{json.dumps(override, indent=1, ensure_ascii=False)}
These values were verified by a human audit; contradict them only if the statement plainly shows
them wrong, and quote it.
"""
    return f"""{override_block}
STATEMENT TEXT:
---
{statement_text[:TEXT_CAP]}
---

TRACKER RECORD (the fields the rules govern):
{json.dumps(tracker_view, indent=1, ensure_ascii=False)}
"""


def build_prompt(statement_text: str, record: dict, rules: str) -> str:
    """Kept for reference/back-compat: the single-string prompt, unsplit."""
    return build_prompt_fixed(rules) + build_prompt_variable(statement_text, record)


def load_records(matters: set[str] | None, limit: int | None) -> list[dict]:
    data = json.loads(FISCAL_DATA.read_text())
    records = data.get("records", [])
    if matters:
        records = [r for r in records if str(r.get("matter_id")) in matters]
    if limit:
        records = records[:limit]
    return records


def cache_path(matter_id: str) -> Path:
    return CACHE_DIR / f"{matter_id}.json"


def fetch_statement(session, record: dict) -> tuple[str, dict]:
    """Fetch the statement actually used for this record. Returns (text, note).
    Every Legistar request goes through LEGISTAR_LIMITER, shared across the
    whole worker pool, so pacing holds however many workers run at once."""
    matter_id = str(record["matter_id"])
    guid = record.get("legistar_guid", "")
    note: dict = {}
    # historical records (fetch_fiscal_impacts_historical.py) carry the
    # statement's direct legistar1 .docx URL and no Legistar page (Sep 27 2026:
    # all 21 errors of the first full run)
    direct = str(record.get("attachment_id") or "")
    if direct.lower().startswith("http") and direct.lower().endswith(".docx"):
        from fetch_fiscal_impacts_historical import download_docx_url
        LEGISTAR_LIMITER.wait()
        path = download_docx_url(session, direct)
        if not path:
            return "", {"fetch_error": "direct docx download failed"}
        return extract_docx_text(path), {"source": "direct_docx"}
    LEGISTAR_LIMITER.wait()
    att_id, att_guid = get_fiscal_attachment(session, matter_id, guid)
    if not att_id:
        return "", {"fetch_error": "no attachment found on the current Legistar page"}
    if record.get("attachment_id") and str(att_id) != str(record["attachment_id"]):
        note["attachment_id_changed"] = {"stored": record["attachment_id"], "current": att_id}
    LEGISTAR_LIMITER.wait()
    path = download_docx(session, att_id, att_guid)
    if not path:
        return "", {"fetch_error": "download failed"}
    text = extract_docx_text(path)
    return text, note


def _cache_success(cp: Path, result: dict) -> None:
    """Only a successful verdict is cached: an error result is never written,
    so a resume always retries it rather than replaying the failure."""
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(result, indent=1, ensure_ascii=False))


def verify_one(client, session, record: dict, rules: str, force: bool) -> dict:
    matter_id = str(record["matter_id"])
    cp = cache_path(matter_id)
    if cp.exists() and not force:
        return json.loads(cp.read_text())

    text, note = fetch_statement(session, record)
    if not text:
        return {"matter_id": matter_id, "error": note.get("fetch_error", "no text"), **note}

    truncated = len(text) > TEXT_CAP
    if truncated:
        note["truncated"] = True
    fixed = build_prompt_fixed(rules)
    variable = build_prompt_variable(text, record)
    for attempt in range(3):
        try:
            msg = client.messages.create(
                model=VERIFY_MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": cached_content(fixed, variable)}],
                output_config={"format": {"type": "json_schema", "schema": VERIFY_SCHEMA}},
            )
            USAGE.add(msg)
            if msg.stop_reason == "max_tokens":
                raise json.JSONDecodeError("output truncated at max_tokens", "", 0)
            verdict = json.loads(message_text(msg))
            result = {"matter_id": matter_id, "verdict": verdict["verdict"], "errors": verdict["errors"], **note}
            _cache_success(cp, result)
            return result
        except json.JSONDecodeError as e:
            log.warning(f"  {matter_id}: JSON decode error (attempt {attempt+1}): {e}")
            if attempt == 2:
                return {"matter_id": matter_id, "error": str(e), **note}
        except Exception as e:  # noqa: BLE001  (rate limit, API error, etc.)
            wait = 30 * (attempt + 1)
            log.warning(f"  {matter_id}: API error (attempt {attempt+1}): {e} — waiting {wait}s")
            time.sleep(wait)
    return {"matter_id": matter_id, "error": "failed after 3 attempts", **note}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matters", nargs="+", default=None,
                     help="matter ids, space- and/or comma-separated (e.g. --matters 111 222,333)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fetch-in-dry-run", action="store_true", help="with --dry-run, still fetch statements to size the real token estimate")
    ap.add_argument("--force", action="store_true", help="ignore the resumable cache and re-verify")
    # Max-plan path (Tal, Sep 27 2026): no API billing. --emit-packets writes one
    # prompt per bill for Claude Code subagents; each writes DIR/results/<id>.json
    # ({verdict, errors}); --ingest DIR folds them into the day's report.
    ap.add_argument("--emit-packets", metavar="DIR", default=None)
    ap.add_argument("--ingest", metavar="DIR", default=None)
    args = ap.parse_args()

    matters = None
    if args.matters:
        matters = {m for token in args.matters for m in token.split(",") if m}
    records = load_records(matters, args.limit)
    rules = CRITERIA.read_text() if CRITERIA.exists() else ""

    if args.emit_packets:
        d = Path(args.emit_packets); (d / "results").mkdir(parents=True, exist_ok=True)
        session = create_session(); n = 0
        for r in records:
            text, note = fetch_statement(session, r)
            if not text:
                print(f"  {r['matter_id']}: no statement ({note})"); continue
            (d / f"{r['matter_id']}.txt").write_text(
                build_prompt(text, r, rules) + "\n\nANSWER FORMAT: write ONLY a JSON object matching this "
                f"schema to results/{r['matter_id']}.json:\n" + json.dumps(VERIFY_SCHEMA))
            n += 1
        print(f"wrote {n} packets to {d}")
        return 0
    if args.ingest:
        d = Path(args.ingest); results = {}
        for f in sorted((d / "results").glob("*.json")):
            v = json.loads(f.read_text())
            results[f.stem] = {"matter_id": f.stem, "verdict": v.get("verdict"), "errors": v.get("errors", []),
                               "judge": "subagent"}
        out_path = OUT_DIR / f"fiscal_verification_{date.today().isoformat()}.json"
        prior = json.loads(out_path.read_text()).get("results", {}) if out_path.exists() else {}
        merged = {**prior, **results}
        checked = [r for r in merged.values() if "verdict" in r and r["verdict"]]
        out_path.write_text(json.dumps({
            "generated": date.today().isoformat(), "checked": len(checked),
            "correct": sum(r["verdict"] == "correct" for r in checked),
            "wrong": sum(r["verdict"] == "wrong" for r in checked),
            "errored": len(merged) - len(checked), "results": merged}, indent=1, ensure_ascii=False))
        print(f"ingested {len(results)} subagent verdicts into {out_path}")
        return 0

    if args.dry_run:
        session = create_session() if args.fetch_in_dry_run else None
        total_chars = 0
        for r in records:
            mid = str(r["matter_id"])
            if session is not None:
                text, _ = fetch_statement(session, r)
                time.sleep(0.5)
            else:
                text = " " * 8000  # rough statement-length placeholder for the estimate
            chars = len(text) + len(rules) + len(json.dumps(r))
            total_chars += chars
            print(f"  would call: matter {mid} (~{chars/3.5:,.0f} input tokens)")
        print(f"\n{len(records)} calls, ~{total_chars/3.5:,.0f} total input tokens (chars/3.5 estimate)")
        return 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY environment variable is not set.")
        return 1
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    session = create_session()

    results: dict[str, dict] = {}
    # Prompt caching: a parallel request cannot read a cache entry until the
    # first response naming it has begun, so the first record is verified
    # alone (writing the cache), then the rest fan out across the pool.
    remaining = records
    if records:
        first, remaining = records[0], records[1:]
        res = verify_one(client, session, first, rules, args.force)
        results[res["matter_id"]] = res

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {pool.submit(verify_one, client, session, r, rules, args.force): r for r in remaining}
        for fut in as_completed(futures):
            r = futures[fut]
            try:
                res = fut.result()
            except Exception as e:  # noqa: BLE001
                res = {"matter_id": str(r["matter_id"]), "error": str(e)}
            results[res["matter_id"]] = res

    # a same-day rerun (--matters for the ones that errored) merges into the
    # day's report instead of replacing it
    out_path = OUT_DIR / f"fiscal_verification_{date.today().isoformat()}.json"
    if out_path.exists():
        prior = json.loads(out_path.read_text()).get("results", {})
        results = {**prior, **{k: v for k, v in results.items()
                               if "verdict" in v or k not in prior}}
    checked = sum(1 for r in results.values() if "verdict" in r)
    correct = sum(1 for r in results.values() if r.get("verdict") == "correct")
    wrong = sum(1 for r in results.values() if r.get("verdict") == "wrong")
    by_field: dict[str, int] = {}
    for r in results.values():
        for e in r.get("errors", []):
            by_field[e.get("field", "?")] = by_field.get(e.get("field", "?"), 0) + 1
    errored = len(results) - checked

    out_path.write_text(json.dumps({
        "generated": date.today().isoformat(), "checked": checked, "correct": correct,
        "wrong": wrong, "errored": errored, "errors_by_field": by_field, "results": results,
    }, indent=1, ensure_ascii=False))

    print(f"checked={checked} correct={correct} wrong={wrong} errored={errored} by_field={by_field}")
    print(f"wrote {out_path}")
    log.info(USAGE.line())
    if records and errored / len(records) > ERROR_EXIT_THRESHOLD:
        log.error(f"{errored}/{len(records)} matters errored (> {ERROR_EXIT_THRESHOLD:.0%}) — failing the run")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
