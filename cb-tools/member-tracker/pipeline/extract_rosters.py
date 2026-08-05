#!/usr/bin/env python3
"""
Extract member rosters, officers, and committees from cached board pages.

For each board in cache/pages_index.json, concatenates the cached pages
(HTML stripped to text) and asks Claude for the structured roster per
extracted/ROSTER_SCHEMA.md. Skips boards whose page hashes are unchanged
since the last extraction (stored as "page_hashes" in each output file), so
the monthly Action only bills for boards whose sites changed — the same
cost-guard idea as the Block Party content-hash skip.

Guard: every extracted person name must appear verbatim in the source text
(whitespace-collapsed, case-insensitive). Names that fail are dropped with
a warning; a board whose whole result fails validation keeps its previous
extraction.

Env: ANTHROPIC_API_KEY (Action secret; already used by the implementation
tracker's extraction step).

Usage (from the member-tracker folder):
    python3 pipeline/extract_rosters.py [--only 103] [--force] [--model ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
OUT_DIR = HERE / "extracted" / "rosters"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_CHARS = 250_000  # 90k truncated boards with many committee pages (104, 208)

PROMPT = """You are extracting a NYC community board's roster from its website pages.

Return ONLY a JSON object with this exact shape (no markdown fences, no prose):
{
  "officers": [{"role": "Chair", "name": "..."}],
  "members": [{"name": "...", "roles": []}],
  "committees": [{"name": "...", "chair": null, "members": []}],
  "as_of": null,
  "notes": ""
}

Rules:
- Every name must be copied VERBATIM from the text below. Never infer,
  complete, or normalize a name.
- "members" = appointed voting board members only. Exclude staff (district
  manager, community coordinators/associates) and elected officials. Exclude
  committee "public members" from the top-level members list.
- "officers" = leadership roles the pages state (Chair, First Vice Chair,
  Secretary, Treasurer, ...). Officers also stay in "members" if a full
  roster is listed.
- "committees": every standing committee/task force named. "chair" only if
  the pages name that committee's chair. "members" only if the pages list
  that committee's membership (otherwise []).
- In each member's "roles", record roles the pages state for that person
  (e.g. "Chair", "Land Use Committee Chair"). Plain membership = [].
- "as_of": a "last updated" date printed on a page (YYYY-MM-DD), else null.
- "notes": one short sentence on gaps (e.g. "no member roster published").
- If the pages contain no roster at all, return empty lists and say so in
  notes.

PAGES:
"""


def strip_html(html: str) -> str:
    html = re.sub(r"<(script|style|noscript)[\s\S]*?</\1>", " ", html, flags=re.I)
    html = re.sub(r"<!--[\s\S]*?-->", " ", html)
    html = re.sub(r"<[^>]+>", "\n", html)
    html = html.replace("&amp;", "&").replace("&nbsp;", " ")
    html = re.sub(r"&#?\w+;", " ", html)
    return re.sub(r"[ \t]+", " ", html)


def page_text(entry: dict) -> str:
    chunks = []
    for p in entry["pages"]:
        f = CACHE / "pages" / p["file"]
        if not f.exists():
            continue
        text = strip_html(f.read_text(errors="replace"))
        text = re.sub(r"\n{3,}", "\n\n", text)
        chunks.append(f"=== PAGE: {p['url']} ===\n{text}")
    blob = "\n\n".join(chunks)
    return blob[:MAX_CHARS]


def name_in_text(name: str, squashed: str) -> bool:
    n = re.sub(r"\s+", " ", name).strip().lower()
    return bool(n) and n in squashed


def validate(result: dict, text: str) -> dict:
    squashed = re.sub(r"\s+", " ", text).lower()
    dropped = []

    def keep(name):
        ok = name_in_text(name, squashed)
        if not ok:
            dropped.append(name)
        return ok

    result["officers"] = [o for o in result.get("officers", []) if keep(o.get("name", ""))]
    result["members"] = [m for m in result.get("members", []) if keep(m.get("name", ""))]
    committees = []
    for c in result.get("committees", []):
        if c.get("chair") and not name_in_text(c["chair"], squashed):
            dropped.append(c["chair"])
            c["chair"] = None
        c["members"] = [n for n in (c.get("members") or []) if name_in_text(n, squashed)]
        committees.append(c)
    result["committees"] = committees
    if dropped:
        print(f"    dropped {len(dropped)} name(s) not found verbatim: {dropped[:5]}")
    return result


def call_claude(client, model: str, text: str) -> dict:
    resp = client.messages.create(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": PROMPT + text}],
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.M).strip()
    return json.loads(raw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="single boro_cd")
    ap.add_argument("--force", action="store_true", help="ignore hash skip")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    index = json.loads((CACHE / "pages_index.json").read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    import anthropic
    client = anthropic.Anthropic()

    done = skipped = failed = 0
    for cd, entry in sorted(index.items()):
        if args.only and int(cd) != args.only:
            continue
        if not entry["pages"]:
            continue
        hashes = sorted(p["sha256"] for p in entry["pages"])
        out_path = OUT_DIR / f"{cd}.json"
        prev = json.loads(out_path.read_text()) if out_path.exists() else None
        if prev and prev.get("page_hashes") == hashes and not args.force:
            skipped += 1
            continue

        print(f"[{cd}] extracting from {len(entry['pages'])} pages")
        text = page_text(entry)
        try:
            result = call_claude(client, args.model, text)
            result = validate(result, text)
        except Exception as e:
            print(f"    extraction failed ({e}); keeping previous result")
            failed += 1
            continue
        result = {
            "cd": int(cd),
            "sources": [p["url"] for p in entry["pages"]],
            "page_hashes": hashes,
            **{k: result.get(k) for k in ("as_of", "officers", "members", "committees", "notes")},
        }
        out_path.write_text(json.dumps(result, indent=1, ensure_ascii=False))
        done += 1

    print(f"extracted {done}, skipped {skipped} unchanged, failed {failed}")
    if failed and not done:
        sys.exit(1)


if __name__ == "__main__":
    main()
