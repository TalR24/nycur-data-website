#!/usr/bin/env python3
"""
Re-extract the laws listed in pipeline/reextract_queue.json.

Runs inside the monthly Action (which holds ANTHROPIC_API_KEY) between the
fetch and extract steps. For each queued matter it:

  1. fetches the Legistar detail page and pulls the enacted text; if the page
     text is an attachment placeholder (or too short), downloads the first
     PDF attachment and extracts its text with pypdf;
  2. writes cache/text/<matter_id>.txt;
  3. calls extract_law() directly and writes cache/extracted/<matter_id>.json
     WITHOUT touching data/obligations.json — the subsequent
     `extract_obligations.py --incremental` step assembles the full dataset,
     preferring these fresh caches for the queued laws and the committed
     obligations.json for everything else;
  4. rewrites the queue keeping only matters that failed, so retries are free.

Never add an audited/hand-corrected matter to the queue: re-extraction
regenerates the record from the model and discards manual cache corrections.
"""
from __future__ import annotations

import json
import io
import os
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from fetch_enacted_laws import parse_detail_page  # noqa: E402
import extract_obligations as eo  # noqa: E402

QUEUE = HERE / "reextract_queue.json"
TEXT_CACHE = HERE / "cache" / "text"
EXTRACT_CACHE = HERE / "cache" / "extracted"
MAX_CHARS = 300_000  # head+tail cap for attachment-scale laws (LL47 precedent)


def sanitize(text: str) -> str:
    """PDF-extracted text carries invalid unicode and control characters that
    can break the HTTP request body mid-send (the 'Stream has ended
    unexpectedly' failures). Keep printable text plus newlines/tabs only."""
    text = text.encode("utf-8", "ignore").decode("utf-8", "ignore")
    return "".join(c for c in text if c == "\n" or c == "\t" or ord(c) >= 32)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def fetch_page(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=90)
    r.raise_for_status()
    return r.text


def attachment_text(html: str) -> str | None:
    """Download PDF attachments from a detail page and extract text.

    Legistar's View.ashx sometimes truncates large downloads; pypdf then dies
    with "Stream has ended unexpectedly". Mitigations: verify the payload is a
    complete PDF (%PDF header, %%EOF near the end), retry the download once,
    parse in lenient mode (strict=False), and salvage per-page.
    """
    links = re.findall(r'href="(View\.ashx\?M=F[^"]+)"', html)
    if not links:
        return None
    from pypdf import PdfReader
    for link in links[:3]:
        url = "https://legistar.council.nyc.gov/" + link.replace("&amp;", "&")
        for attempt in range(3):
            try:
                r = requests.get(url, headers={"User-Agent": UA}, timeout=600)
                r.raise_for_status()
                blob = r.content
                if not blob.startswith(b"%PDF"):
                    break  # not a PDF (error page); try next link
                if b"%%EOF" not in blob[-2048:]:
                    print(f"  attachment download truncated ({len(blob)} bytes), retrying")
                    continue
                reader = PdfReader(io.BytesIO(blob), strict=False)
                pages = []
                for page in reader.pages:
                    try:
                        pages.append(page.extract_text() or "")
                    except Exception:
                        pages.append("")
                text = "\n".join(pages)
                if len(text) > 500:
                    return text
                break  # parsed but no text layer; try next link
            except Exception as e:
                print(f"  attachment attempt {attempt + 1} failed: {e}")
    return None


def main() -> None:
    if not QUEUE.exists():
        print("no queue file; nothing to do")
        return
    queue = json.loads(QUEUE.read_text())
    matters = queue.get("matters", {})
    if not matters:
        print("queue empty; nothing to do")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")
    import anthropic
    client = anthropic.Anthropic()

    laws = {l["matter_id"]: l
            for l in json.loads(eo.LAWS_JSON.read_text())["laws"]}
    cw = json.loads(eo.CROSSWALK_JSON.read_text())
    lookup = cw["lookup"]
    agencies_by_canon = {a["canonical"]: a for a in cw["agencies"]}
    TEXT_CACHE.mkdir(parents=True, exist_ok=True)
    EXTRACT_CACHE.mkdir(parents=True, exist_ok=True)

    limit = int(os.environ.get("REEXTRACT_LIMIT", "200"))
    todo = dict(list(matters.items())[:limit])
    deferred = {m: r for m, r in matters.items() if m not in todo}
    if deferred:
        print(f"processing {len(todo)} of {len(matters)} queued (REEXTRACT_LIMIT={limit})")
    failed: dict[str, str] = {}
    for mid, reason in todo.items():
        law = laws.get(mid)
        if not law:
            failed[mid] = reason + " [matter not in laws.json]"
            continue
        try:
            html = fetch_page(law["legistar_url"])
            guid = law.get("legistar_guid", "")
            rec = parse_detail_page(html, mid, guid)
            text = rec.get("_text") or ""
            truncated = False
            if len(text) < 500 or "ATTACHMENT" in text.upper()[:400]:
                pdf_text = attachment_text(html)
                if pdf_text and len(pdf_text) > len(text):
                    text = pdf_text
            if len(text) < 500:
                failed[mid] = reason + " [no usable text found]"
                continue
            text = sanitize(text)
            if len(text) > MAX_CHARS:
                text = text[:MAX_CHARS - 30_000] + "\n[...]\n" + text[-30_000:]
                truncated = True
            (TEXT_CACHE / f"{mid}.txt").write_text(text)
            print(f"{mid}: extracting ({len(text)} chars"
                  + (", truncated" if truncated else "") + ")")
            res = eo.extract_law(client, eo.DEFAULT_MODEL, law, text,
                                 lookup, agencies_by_canon)
            if truncated:
                res["truncated_extraction"] = True
            (EXTRACT_CACHE / f"{mid}.json").write_text(json.dumps(res, indent=1))
            print(f"{mid}: -> {len(res['obligations'])} obligations")
            time.sleep(0.5)
        except Exception as e:  # keep going; queue retains the failure
            failed[mid] = reason + f" [failed: {e}]"
            print(f"{mid}: FAILED {e}")

    queue["matters"] = {**failed, **deferred}
    QUEUE.write_text(json.dumps(queue, indent=2) + "\n")
    print(f"done: {len(todo) - len(failed)} re-extracted, {len(failed)} failed, "
          f"{len(deferred)} deferred to next run")


if __name__ == "__main__":
    main()
