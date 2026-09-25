#!/usr/bin/env python3
"""
Pilot a different extraction model on a handful of laws, without touching the
committed data (Tal approved a Sonnet 5 pilot on 15 laws, Sep 25 2026).

For each matter it fetches the enacted text exactly as reextract_queued.py does
(Legistar page, PDF attachment fallback, new-matter {{...}} markers kept) and
writes cache/text/<id>.txt plus cache/extracted/<id>.json from the chosen
model. The workflow then runs `extract_obligations.py --incremental`, which
assembles a full dataset preferring these caches for the pilot laws and the
committed obligations.json for everything else, and uploads the result as an
artifact. Nothing is committed.

Usage (Actions, claude_backfill.yml task pilot_obligations):
    python3 pipeline/pilot_extract.py --model claude-sonnet-5 --matters 7872578 6029061 ...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import extract_obligations as eo  # noqa: E402
from fetch_enacted_laws import parse_detail_page  # noqa: E402
from reextract_queued import (  # noqa: E402
    MAX_CHARS, attachment_text, fetch_page, sanitize,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--matters", nargs="+", required=True)
    args = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")
    import anthropic
    client = anthropic.Anthropic()

    matters = [m for part in args.matters for m in part.replace(",", " ").split()]
    laws = {l["matter_id"]: l for l in json.loads(eo.LAWS_JSON.read_text())["laws"]}
    cw = json.loads(eo.CROSSWALK_JSON.read_text())
    lookup = cw["lookup"]
    agencies_by_canon = {a["canonical"]: a for a in cw["agencies"]}
    eo.TEXT_CACHE.mkdir(parents=True, exist_ok=True)
    eo.EXTRACT_CACHE.mkdir(parents=True, exist_ok=True)

    failed = []
    for mid in matters:
        law = laws.get(mid)
        if not law:
            failed.append(f"{mid}: not in laws.json")
            continue
        try:
            html = fetch_page(law["legistar_url"])
            rec = parse_detail_page(html, mid, law.get("legistar_guid", ""))
            text = rec.get("_text") or ""
            if len(text) < 500 or "ATTACHMENT" in text.upper()[:400]:
                pdf_text = attachment_text(html)
                if pdf_text and len(pdf_text) > len(text):
                    text = pdf_text
            if len(text) < 500:
                failed.append(f"{mid}: no usable text")
                continue
            text = sanitize(text)[:MAX_CHARS * 40]
            (eo.TEXT_CACHE / f"{mid}.txt").write_text(text)
            res = eo.extract_law(client, args.model, law, text, lookup, agencies_by_canon)
            res["pilot_model"] = args.model
            (eo.EXTRACT_CACHE / f"{mid}.json").write_text(json.dumps(res, indent=1))
            print(f"{mid}: {len(res['obligations'])} records ({args.model})")
            time.sleep(0.5)
        except Exception as e:  # keep going; report at the end
            failed.append(f"{mid}: {e}")
    print(f"done: {len(matters) - len(failed)} extracted, {len(failed)} failed")
    for f in failed:
        print("  FAILED", f)
    return 1 if len(failed) == len(matters) else 0


if __name__ == "__main__":
    sys.exit(main())
