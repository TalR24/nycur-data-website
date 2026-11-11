#!/usr/bin/env python3
"""Generate the card thumbnails in assets/thumbs/ (Playwright + Pillow, no new libraries).

Every card on the homepage and on each post hub shows a real miniature of the chart or
tool it links to, never an abstract icon. This script renders each target at a fixed
1100px viewport, crops the chart area to 2:1, and writes a JPEG of at most 60 KB.

Files (the HTML uses exactly this naming, see card_thumb_name):
  assets/thumbs/<hub>.jpg             lead chart of a post hub, or the tool page for a tool card
  assets/thumbs/<hub>--<chart>.jpg    every other chart card inside a hub
A card whose target has no chart to show gets no file; the HTML then renders a flat
palette block instead.

Run from the data_website folder:  python3 seo/make_thumbs.py [--only hub-slug]
Starts and stops its own local http.server. Re-run after a chart changes.
"""
import functools, http.server, os, re, socketserver, sys, threading
from io import BytesIO

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'assets', 'thumbs')
W, H = 640, 320          # stored size, 2:1
MAX_BYTES = 60 * 1024
POSTS = '/nycuriosity_substack_posts/'

# Homepage tool cards: slug -> page whose top is the best miniature of the tool.
TOOLS = {
    'nyc_council_legislation_trackers': '/civic_reference/nyc_council_fiscal_impacts_tracker/overview/',
    'cb-tools': '/cb-tools/member-tracker/',
}


def hubs():
    """Post hub slugs in homepage order."""
    s = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    seen = []
    for m in re.finditer(r'<a class="card"[^>]*href="' + POSTS + r'([^/"]+)/"', s):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def hub_charts(slug):
    p = os.path.join(ROOT, POSTS.strip('/'), slug, 'index.html')
    s = open(p, encoding='utf-8').read()
    out = []
    for m in re.finditer(r'<a\s+(?:class="hub-card"\s+href="([^"]+)"|href="([^"]+)"\s+class="hub-card")', s):
        href = m.group(1) or m.group(2)
        if href.startswith('http'):
            continue
        url = href if href.startswith('/') else os.path.normpath(os.path.join(POSTS, slug, href)) + '/'
        if not url.startswith('/'):
            url = '/' + url
        if not url.endswith('/') and '.' not in os.path.basename(url):
            url += '/'
        out.append(url)
    return out


def card_thumb_name(slug, chart_url, lead):
    if lead:
        return slug + '.jpg'
    return slug + '--' + chart_url.rstrip('/').split('/')[-1] + '.jpg'


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    class Q(handler.func):
        def log_message(self, *a):
            pass
    srv = socketserver.ThreadingTCPServer(('127.0.0.1', 0), functools.partial(Q, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def save_jpeg(im, path):
    im = im.convert('RGB').resize((W, H), Image.LANCZOS)
    for q in (82, 74, 66, 58, 50, 42, 34):
        buf = BytesIO()
        im.save(buf, 'JPEG', quality=q, optimize=True, progressive=True)
        if buf.tell() <= MAX_BYTES:
            break
    open(path, 'wb').write(buf.getvalue())
    return buf.tell()


def has_visual(page):
    return page.evaluate("""() => !!document.querySelector(
      '.chart-card .c-plot, .chart-card canvas, .chart-card svg, .chart-card table, .chart-card .c-bars, canvas, #map, table, .leaflet-container, iframe')""")


def capture(page, base, url):
    """Return a PIL image (cropped to 2:1) of the page's lead visual, or None for a text page."""
    page.goto(base + url, wait_until='load', timeout=40000)
    page.wait_for_timeout(2500)
    if not has_visual(page):
        return None
    box = None
    for sel in ('.chart-card .c-plot', '.chart-card', '#chart-box', 'main table', '#map', '.leaflet-container'):
        el = page.query_selector(sel)
        if el:
            el.scroll_into_view_if_needed()
            b = el.bounding_box()
            if b and b['width'] > 300 and b['height'] > 120:
                box = b
                break
    if box is None:  # a tool page: the viewport below the header
        hh = page.evaluate("() => { const h=document.querySelector('header'); return h ? h.getBoundingClientRect().bottom : 0; }")
        box = {'x': 0, 'y': hh, 'width': 1100, 'height': 550}
    w = min(box['width'], 1100)
    h = min(box['height'], w / 2)
    clip = {'x': box['x'], 'y': box['y'] + page.evaluate('window.scrollY'), 'width': w, 'height': h}
    png = page.screenshot(clip=clip, full_page=True)
    im = Image.open(BytesIO(png)).convert('RGB')
    canvas = Image.new('RGB', (int(w), int(w / 2)), (255, 255, 255))
    canvas.paste(im, (0, 0))
    return canvas


def main():
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    os.makedirs(OUT, exist_ok=True)
    srv = serve()
    base = 'http://127.0.0.1:%d' % srv.server_address[1]
    jobs = []  # (file, url)
    for slug in hubs():
        charts = hub_charts(slug)
        for i, u in enumerate(charts):
            jobs.append((card_thumb_name(slug, u, i == 0), u, slug))
    for slug, u in TOOLS.items():
        jobs.append((slug + '.jpg', u, slug))
    cache = {}
    total = 0
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context(viewport={'width': 1100, 'height': 900})
            page = ctx.new_page()
            for fname, url, slug in jobs:
                if only and slug not in only.split(','):
                    continue
                dest = os.path.join(OUT, fname)
                if os.path.exists(dest):
                    os.remove(dest)
                try:
                    if url not in cache:
                        cache[url] = capture(page, base, url)
                    im = cache[url]
                except Exception as ex:
                    print('FAIL', url, str(ex)[:80])
                    continue
                if im is None:
                    print('flat  ', fname, url)
                    continue
                n = save_jpeg(im, dest)
                total += n
                print('%6d  %s  <- %s' % (n, fname, url))
            b.close()
    finally:
        srv.shutdown()
        srv.server_close()
    print('total bytes', total)


if __name__ == '__main__':
    main()
