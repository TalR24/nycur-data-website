"""Model-assisted duty / power / neither labels for existing obligation records.

New laws get `kind_model` inside the extraction call (provision_kind). This
script backfills it for records extracted before that field existed:

  python3 pipeline/label_kinds.py --build-input   # local: needs cache/text; writes kind_label_input.json
  python3 pipeline/label_kinds.py                 # CI or local with ANTHROPIC_API_KEY; writes kind_labels.json
  python3 pipeline/label_kinds.py --apply         # local: kind_model into cache/extracted, then rebuild

The model sees the same definitions the blind reviewers used (KIND_DEFINITIONS)
and the full provision the quote comes from, and answers through a schema enum.
Resumable: records already in kind_labels.json are skipped.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from extract_obligations import (DEFAULT_MODEL, EXTRACT_CACHE, KIND_DEFINITIONS, KINDS,  # noqa: E402
                                 TEXT_CACHE, _clause, provision_context)

INPUT = HERE / "kind_label_input.json"
LABELS = HERE / "kind_labels.json"
SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": KINDS},
        "decisive_words": {"type": "string"},
    },
    "required": ["kind", "decisive_words"],
    "additionalProperties": False,
}
PROMPT = """You are sorting provisions of New York City local laws for a public tracker. Label the provision below as duty, power, or neither, using these definitions:

{definitions}

LEAD-IN (for a list item; may be empty):
{lead}

PROVISION (the clause the quoted text sits in):
{clause}

LATER TEXT THE QUOTE RUNS INTO (may be empty):
{more}

QUOTED TEXT ON THE RECORD:
{quote}

Answer with the label and the few words of the law that decide it."""


def build_input() -> None:
    items = []
    for f in sorted(EXTRACT_CACHE.glob("*.json")):
        rec = json.loads(f.read_text())
        tf = TEXT_CACHE / f"{rec['matter_id']}.txt"
        text = tf.read_text() if tf.exists() else None
        for o in rec.get("obligations", []):
            ctx = provision_context(o.get("quote", ""), text) if text else None
            if ctx:
                lead, sentence, offset, more = ctx
                clause = _clause(sentence, offset)
            else:
                lead, clause, more = "", o.get("quote", ""), []
            items.append({"id": o["obligation_id"], "lead": lead[:600], "clause": clause[:1500],
                          "more": " | ".join(more)[:1200], "quote": (o.get("quote") or "")[:800]})
    INPUT.write_text(json.dumps(items, separators=(",", ":")))
    print(f"wrote {INPUT}: {len(items)} records")


def label(limit: int | None, workers: int) -> int:
    import anthropic
    client = anthropic.Anthropic(max_retries=6)
    items = json.loads(INPUT.read_text())
    done = json.loads(LABELS.read_text()) if LABELS.exists() else {}
    todo = [i for i in items if i["id"] not in done][: limit or None]
    print(f"{len(items)} records, {len(done)} already labelled, {len(todo)} to label", flush=True)
    lock = threading.Lock()
    failures = []

    def one(item):
        prompt = PROMPT.format(definitions=KIND_DEFINITIONS, lead=item["lead"] or "(none)",
                               clause=item["clause"], more=item["more"] or "(none)", quote=item["quote"])
        msg = client.messages.create(
            model=DEFAULT_MODEL, max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
        if msg.stop_reason not in ("end_turn", "stop_sequence"):
            raise RuntimeError(f"stop_reason={msg.stop_reason}")
        out = json.loads(next(b.text for b in msg.content if b.type == "text"))
        return item["id"], out["kind"]

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, i): i["id"] for i in todo}
        for n, fut in enumerate(cf.as_completed(futs), 1):
            try:
                oid, kind = fut.result()
                with lock:
                    done[oid] = kind
            except Exception as e:  # noqa: BLE001  one failure never stops the batch
                failures.append((futs[fut], str(e)[:120]))
            if n % 250 == 0:
                with lock:
                    LABELS.write_text(json.dumps(done, sort_keys=True, indent=0))
                print(f"  {n}/{len(todo)} ({time.time() - t0:.0f}s), {len(failures)} failed", flush=True)
    LABELS.write_text(json.dumps(done, sort_keys=True, indent=0))
    print(f"labelled {len(done)} of {len(items)}; {len(failures)} failed this run", flush=True)
    for f in failures[:10]:
        print("  FAILED", f)
    # a run that labels nothing is broken (bad key, schema rejected): fail loudly
    return 1 if todo and len(failures) == len(todo) else 0


def apply() -> None:
    labels = json.loads(LABELS.read_text())
    n = 0
    for f in sorted(EXTRACT_CACHE.glob("*.json")):
        rec = json.loads(f.read_text())
        changed = False
        for o in rec.get("obligations", []):
            k = labels.get(o["obligation_id"])
            if k in KINDS and o.get("kind_model") != k:
                o["kind_model"] = k
                changed = True
                n += 1
        if changed:
            f.write_text(json.dumps(rec, indent=1))
    print(f"kind_model written on {n} cached records")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-input", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("LABEL_WORKERS", "6")))
    args = ap.parse_args()
    if args.build_input:
        build_input()
        return 0
    if args.apply:
        apply()
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")
    return label(args.limit, args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
