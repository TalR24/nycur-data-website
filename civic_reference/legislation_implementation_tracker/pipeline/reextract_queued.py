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
MAX_CHARS = 300_000  # only a sanity ceiling now; extract_law windows long laws


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


def _docx_text(blob: bytes) -> str:
    import zipfile
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _pdf_text(blob: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(blob), strict=False)
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)


def attachment_text(html: str) -> str | None:
    """Extract the enacted law text from a detail page's attachments.

    Selection matters: the first attachments are usually summaries, agendas,
    and transcripts. Prefer, in order: an attachment named "Local Law ...",
    then the bill text ("Int. No. ..."), then anything else. Formats: PDF
    (pypdf, lenient, per-page salvage) and docx (zip + XML strip).
    """
    pairs = re.findall(r'href="(View\.ashx\?M=F[^"]+)"[^>]*>([^<]+)<', html)
    if not pairs:
        return None

    def rank(name: str) -> int:
        n = name.lower().strip()
        if "local law" in n:
            return 0
        if n.startswith("int. no") and "summary" not in n:
            return 1
        if "summary" in n or "agenda" in n or "transcript" in n or "minutes" in n \
                or "testimony" in n or "report" in n:
            return 3
        return 2

    for url, name in sorted(pairs, key=lambda p: rank(p[1])):
        full = "https://legistar.council.nyc.gov/" + url.replace("&amp;", "&")
        for attempt in range(2):
            try:
                r = requests.get(full, headers={"User-Agent": UA}, timeout=600)
                r.raise_for_status()
                blob = r.content
                if blob.startswith(b"%PDF"):
                    if b"%%EOF" not in blob[-2048:]:
                        print(f"  truncated download of {name!r}, retrying")
                        continue
                    text = _pdf_text(blob)
                elif blob.startswith(b"PK"):
                    text = _docx_text(blob)
                else:
                    break  # unknown format; next attachment
                if len(text) > 500:
                    print(f"  law text from attachment {name!r} ({len(text)} chars)")
                    return text
                break
            except Exception as e:
                print(f"  attachment {name!r} attempt {attempt + 1} failed: {e}")
    return None


EXCLUSIONS_PATH = HERE / "reextract_exclusions.json"


def load_exclusions() -> dict:
    """Matters whose extraction was corrected by hand and must not be redone.

    This file existed from the start but only build_full_reextract_queue.py
    ever read it, so anything added to the queue afterwards bypassed the
    protection entirely. An adversarial review caught it in Aug 2026 with 16
    hand-audited laws sitting in the queue, one monthly run away from being
    overwritten. The consumer, not just the producer, has to enforce it.
    """
    if not EXCLUSIONS_PATH.exists():
        return {}
    return json.loads(EXCLUSIONS_PATH.read_text()).get("matters", {})


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
    exclusions = load_exclusions()
    failed: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for mid, reason in todo.items():
        if mid in exclusions:
            skipped[mid] = f"{reason} [protected: {exclusions[mid]}]"
            print(f"{mid}: SKIPPED, hand-corrected ({exclusions[mid]})")
            continue
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
            # No head+tail truncation any more: extract_law splits a long law at
            # its own section boundaries and extracts each window, so the middle
            # is no longer dropped. Left as a guard only for texts so large that
            # windowing them would be pathological.
            if len(text) > MAX_CHARS * 40:
                text = text[:MAX_CHARS * 40]
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

    # Protected matters are dropped rather than retried: they will be skipped
    # every run, and leaving them in makes the queue look like unfinished work.
    queue["matters"] = {**failed, **deferred}
    QUEUE.write_text(json.dumps(queue, indent=2) + "\n")
    print(f"done: {len(todo) - len(failed)} re-extracted, {len(failed)} failed, "
          f"{len(deferred)} deferred to next run, "
          f"{len(skipped)} skipped as hand-corrected")


if __name__ == "__main__":
    main()
