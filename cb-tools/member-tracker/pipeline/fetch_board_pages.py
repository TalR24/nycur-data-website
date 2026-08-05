"""Discover and cache each community board's roster/committee pages.

For every board in cache/cau_boards.json:
  1. fetch the board's website homepage (CAU URL, falling back to the
     nyc.gov CMS pattern), following meta-refresh redirects
  2. collect nav links whose text or href suggests members / committees /
     leadership, plus the standard nyc.gov CMS page paths
  3. fetch up to MAX_PAGES candidates per board and cache the HTML

Writes cache/pages/<boro_cd>/*.html and cache/pages_index.json
(per-page url, file, sha256 — the extraction step re-runs only on hash
changes). nyc.gov 403s non-browser user agents, so requests go out with a
Chrome UA. One request every DELAY seconds; total run is ~10 minutes.

Run from the member-tracker folder: python3 pipeline/fetch_board_pages.py
"""
from __future__ import annotations

import hashlib
import html.parser
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path(__file__).resolve().parent / "cache"
PAGES = CACHE / "pages"
DELAY = 0.7
MAX_PAGES = 8
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

LINK_RE = re.compile(
    r"member|committee|leadership|officer|about|who we are|meet the board|"
    r"board list|roster|task force|executive",
    re.I,
)
SKIP_RE = re.compile(
    r"\.(pdf|jpg|jpeg|png|gif|doc|docx|xls|xlsx|zip)($|\?)|mailto:|tel:|"
    r"facebook|twitter|instagram|youtube|linkedin|#",
    re.I,
)

NYC_GOV_SLUGS = {
    1: "manhattancb", 2: "bronxcb", 3: "brooklyncb", 4: "queenscb", 5: "statenislandcb",
}
CMS_PATHS = [
    "about/members.page",
    "about/board-members.page",
    "committees/committees.page",
    "about/about.page",
]


class LinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []  # (href, text)
        self._href: str | None = None
        self._text: list[str] = []
        self.meta_refresh: str | None = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a" and d.get("href"):
            self._href, self._text = d["href"], []
        if tag == "meta" and d.get("http-equiv", "").lower() == "refresh":
            m = re.search(r"url=(.+)", d.get("content", ""), re.I)
            if m:
                self.meta_refresh = m.group(1).strip("'\" ")

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None


def get(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(4_000_000)
        time.sleep(DELAY)
        return body.decode("utf-8", errors="replace")
    except Exception as e:  # incl. socket.timeout, which py3.9 keeps separate from TimeoutError
        time.sleep(DELAY)
        print(f"    fetch failed {url}: {e}")
        return None


def resolve_home(board: dict) -> tuple[str, str] | None:
    """Return (final_url, html) for the board homepage, following meta-refresh."""
    candidates = []
    if board.get("website"):
        candidates.append(board["website"])
    slug = NYC_GOV_SLUGS[board["boro_cd"] // 100] + str(board["board_number"])
    fallback = f"https://www.nyc.gov/site/{slug}/index.page"
    if fallback not in candidates:
        candidates.append(fallback)

    for url in candidates:
        for _ in range(3):  # follow up to 2 meta-refreshes
            body = get(url)
            if body is None:
                break
            p = LinkParser()
            try:
                p.feed(body)
            except Exception:
                pass
            if p.meta_refresh:
                url = urllib.parse.urljoin(url, p.meta_refresh)
                continue
            return url, body
    return None


def candidate_urls(home_url: str, body: str) -> list[str]:
    p = LinkParser()
    try:
        p.feed(body)
    except Exception:
        pass
    seen, out = set(), []
    for href, text in p.links:
        if SKIP_RE.search(href):
            continue
        if not (LINK_RE.search(text) or LINK_RE.search(href)):
            continue
        absu = urllib.parse.urljoin(home_url, href)
        if urllib.parse.urlparse(absu).netloc != urllib.parse.urlparse(home_url).netloc:
            continue
        if absu not in seen:
            seen.add(absu)
            out.append(absu)
    # standard CMS paths, cheap to try even when not linked from the homepage
    if ".nyc.gov/site/" in home_url:
        base = home_url.rsplit("/", 1)[0] + "/"
        for path in CMS_PATHS:
            absu = urllib.parse.urljoin(base, path)
            if absu not in seen:
                seen.add(absu)
                out.append(absu)
    return out[:MAX_PAGES]


def main() -> None:
    boards = json.loads((CACHE / "cau_boards.json").read_text())
    PAGES.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}

    for board in boards:
        cd = board["boro_cd"]
        print(f"[{cd}] {board['borough']} CB {board['board_number']}")
        home = resolve_home(board)
        entry = {"home": None, "pages": []}
        index[str(cd)] = entry
        if home is None:
            print("    no homepage reachable")
            continue
        home_url, home_body = home
        entry["home"] = home_url
        bdir = PAGES / str(cd)
        bdir.mkdir(parents=True, exist_ok=True)

        pages = [(home_url, home_body)]
        for url in candidate_urls(home_url, home_body):
            body = get(url)
            if body is not None and len(body) > 500:
                pages.append((url, body))

        for i, (url, body) in enumerate(pages):
            slug = re.sub(r"[^a-z0-9]+", "-", url.split("//", 1)[-1].lower())[-80:]
            fname = f"{i:02d}_{slug}.html"
            (bdir / fname).write_text(body)
            entry["pages"].append(
                {
                    "url": url,
                    "file": f"{cd}/{fname}",
                    "sha256": hashlib.sha256(body.encode()).hexdigest()[:16],
                }
            )
        print(f"    cached {len(pages)} pages")

    (CACHE / "pages_index.json").write_text(json.dumps(index, indent=1))
    total = sum(len(e["pages"]) for e in index.values())
    empty = [cd for cd, e in index.items() if not e["pages"]]
    print(f"\ndone: {total} pages across {len(index)} boards; unreachable: {empty or 'none'}")


if __name__ == "__main__":
    main()
