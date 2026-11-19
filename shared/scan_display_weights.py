#!/usr/bin/env python3
"""List every element rendered in Playfair Display heavier than 500 (brand
skill §9c rule 2: Playfair at 400 to 500), measured from computed styles.

    python3 shared/scan_display_weights.py [page ...]

Pages default to every live page in sitemap.xml. Pages load from disk through
Playwright (no server). Prints one line per page with the offending selectors
and a total; exit 1 if any. Written Nov 19 2026 after a rule-based sweep missed
headings whose face comes from site.js and whose weight comes from the page.
"""
import mimetypes, pathlib, re, sys
from playwright.sync_api import sync_playwright

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / 'CNAME').is_file())
HOST = 'http://ds.local/'
JS = """() => {
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!el.firstChild || !el.textContent.trim()) continue;
    const cs = getComputedStyle(el);
    if (!/Playfair/i.test(cs.fontFamily) || parseInt(cs.fontWeight, 10) <= 500) continue;
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    // only elements whose own text is drawn (not containers that inherit)
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    const cls = el.classList.length ? '.' + [...el.classList].join('.') : '';
    out.push(el.tagName.toLowerCase() + cls + ' ' + cs.fontWeight);
  }
  return [...new Set(out)];
}"""


def serve(route):
    rel = route.request.url.split('ds.local/', 1)[1].split('?')[0].split('#')[0]
    p = ROOT / rel
    if p.is_dir() or rel.endswith('/') or rel == '':
        p = p / 'index.html'
    if not p.exists():
        return route.fulfill(status=404, body='')
    route.fulfill(status=200, body=p.read_bytes(), content_type=mimetypes.guess_type(str(p))[0] or 'text/plain')


def pages():
    if len(sys.argv) > 1:
        return sys.argv[1:]
    xml = (ROOT / 'sitemap.xml').read_text()
    return [u.replace('https://data.nycuriosity.com/', '') for u in re.findall(r'<loc>([^<]+)</loc>', xml)]


def main():
    total = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        pg = b.new_page(viewport={'width': 1280, 'height': 900})
        # Playwright tries the most recently added route first: the catch-all goes in first
        pg.route('**/*', lambda r: r.continue_() if r.request.url.startswith('https://fonts.') else r.abort())
        pg.route(HOST + '**', serve)
        for path in pages():
            try:
                pg.goto(HOST + path, wait_until='load', timeout=20000)
                pg.wait_for_timeout(600)
                hits = pg.evaluate(JS)
            except Exception as e:  # noqa: BLE001
                print(f'ERROR {path}: {str(e)[:80]}')
                continue
            if hits:
                total += len(hits)
                print(f'{path or "/"}: ' + ', '.join(hits[:8]))
        b.close()
    print(f'TOTAL {total} heavy Playfair elements')
    sys.exit(1 if total else 0)


if __name__ == '__main__':
    main()
