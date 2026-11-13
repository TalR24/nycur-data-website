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
    'nyc_council_legislation_trackers': '/civic_reference/nyc_council_fiscal_impacts_tracker/agency-fiscal-impact/',
    'cb-tools': '/cb-tools/member-tracker/',
    'state_capacity_ecosystem': 'https://statecapacityecosystem.com/ecosystem/',
    'nys_legislation_trackers': '/civic_reference/nys_legislation_trackers/duties/',
}

# Cards on the tool hubs (Obligations, Powers, Fiscal overview, /cb-tools/): file name -> target page.
# A target with nothing visual (methodology) gets no file and the card shows a flat palette block.
LT = '/civic_reference/legislation_implementation_tracker/'
FT = '/civic_reference/nyc_council_fiscal_impacts_tracker/'
TOOL_CARDS = {
    'tool--obligations-table': LT + 'obligations-table/',
    'tool--agency-workload': LT + 'agency-workload/',
    'tool--deadline-timeline': LT + 'deadline-timeline/',
    'tool--law': LT + 'law/',
    'tool--powers-table': LT + 'powers-table/',
    'tool--agency-powers': LT + 'powers/agency-powers/',
    'tool--methodology': LT + 'methodology/',
    'tool--fiscal-bill-table': FT,
    'tool--agency-fiscal-impact': FT + 'agency-fiscal-impact/',
    'tool--sponsor-fiscal-impact': FT + 'sponsor-fiscal-impact/',
    'tool--intro-year-impact': FT + 'intro-year-impact/',
    'tool--cost-revenue-breakdown': FT + 'cost-revenue-breakdown/',
    'tool--fiscal-methodology': FT + 'methodology/',
    'tool--cb-member-guide': '/civic_reference/cb_member_guide/',
    'tool--roberts-rules-helper': '/cb-tools/roberts-rules-helper/',
    'tool--meeting-review': '/cb-tools/meeting-review/',
    # the tool page is only a 'moved to Block Party' notice; show the resolutions-by-board chart instead (Nov 11 2026)
    'tool--block-party': '/nycuriosity_substack_posts/block_party_updates_2026/by-board/',
    'tool--board-scorecard': '/cb-tools/board-scorecard/',
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
    im = im.convert('RGB')
    if im.size != (W, H):
        im = im.resize((W, H), Image.LANCZOS)
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


PAD = 14                       # page-ground padding around the plot, in stored pixels
GROUND = (250, 246, 241)       # --b-cream, the page ground (assets/brand.css)

# Per-item overrides when the automatic rule is still unreadable. Keyed by target URL.
#   sel:   CSS selector of the element to show (default: the chart's plot area)
#   rows:  table only, height in CSS px of the slice shown (default 380)
#   width: table only, width in CSS px of the slice shown (default 760)
#   top:   True = show the top 2:1 slice at full width (bars stay whole, only rows below are cut); for plots
#          so tall that the whole plot would be a thumbnail-sized sliver
#   clip:  (x, y, w, h) in CSS px relative to the element, replaces the whole-element rule
P = POSTS
OVERRIDES = {
    P + 'robust_opposition/council-margins-2025/': {'top': True},
    P + 'state_capacity_ai/public-service-delivery/': {'top': True},
    P + 'block_party_updates_2026/by-board/': {'top': True},
    P + 'cso_reports_2026/nyc-tax-rates/': {'top': True},
    P + 'west_4th_st_station/station-timeline/': {'top': True},
    # pages that draw with divs or a map rather than svg/canvas/table: take the viewport below the header
    'https://statecapacityecosystem.com/ecosystem/': {},
    # Nov 11 2026: these two showed the nav pills and page title; capture the tool itself
    '/civic_reference/legislation_implementation_tracker/deadline-timeline/': {'sel': '#content', 'top': True},
    '/civic_reference/legislation_implementation_tracker/law/': {'sel': '#lawList', 'top': True},
}


MAX_ASPECT = 3.0  # wider than this and a chart shrank to a thin strip in the 2:1 card (Nov 11 2026)


def fit(im, box=None):
    """Scale im to fit inside the padded 2:1 frame, centred on the page ground. A very wide, short chart is
    first trimmed from the right to MAX_ASPECT (category labels and axes sit on the left) so it fills the card at a readable size; nothing else is cropped."""
    iw, ih = im.size
    if iw / ih > MAX_ASPECT:
        keep = int(ih * MAX_ASPECT)
        left = 0
        im = im.crop((left, 0, left + keep, ih))
        iw = keep
    aw, ah = W - 2 * PAD, H - 2 * PAD
    sc = min(aw / iw, ah / ih, 1.0 if iw >= aw else 1.5)
    nw, nh = max(1, int(iw * sc)), max(1, int(ih * sc))
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new('RGB', (W, H), GROUND)
    canvas.paste(im, ((W - nw) // 2, (H - nh) // 2))
    return canvas


def capture(page, base, url):
    """Return a W x H PIL image: the whole plot area (no title) scaled to fit, or the first rows of a
    table at readable size; None for a text page with nothing visual."""
    page.goto(url if url.startswith('http') else base + url, wait_until='load', timeout=40000)
    page.wait_for_timeout(2500)
    ov = OVERRIDES.get(url)
    if ov is None and not has_visual(page):
        return None
    ov = ov or {}
    if False:
        return None
    sels = [ov['sel']] if 'sel' in ov else ['.chart-card .c-plot', '.chart-card', '#chart-box', 'main table', '#map', '.leaflet-container']
    box, is_table = None, False
    for sel in sels:
        el = page.query_selector(sel)
        if el:
            el.scroll_into_view_if_needed()
            b = el.bounding_box()
            if b and b['width'] > 300 and b['height'] > 120:
                box = b
                is_table = el.evaluate("e => (e.tagName === 'TABLE' || !!e.querySelector('table')) && !e.querySelector('svg, canvas')")
                break
    if box is None:  # a tool page: the viewport below the header
        hh = page.evaluate("() => { const h=document.querySelector('header'); return h ? h.getBoundingClientRect().bottom : 0; }")
        box = {'x': 0, 'y': hh, 'width': 1100, 'height': 550}
    sy = page.evaluate('window.scrollY')
    x, y, w, h = box['x'], box['y'] + sy, box['width'], box['height']
    if 'clip' in ov:
        cx, cy, cw, ch = ov['clip']
        x, y, w, h = x + cx, y + cy, cw, ch
    elif ov.get('top'):
        h = min(h, w / 2)
    elif is_table:  # first rows at readable size: a slice about 2:1, not the whole table shrunk
        w = min(w, ov.get('width', 760))
        h = min(h, ov.get('rows', 380))
    png = page.screenshot(clip={'x': x, 'y': y, 'width': w, 'height': min(h, 1600)}, full_page=True)
    return fit(Image.open(BytesIO(png)).convert('RGB'))


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
    for name, u in TOOL_CARDS.items():
        jobs.append((name + '.jpg', u, 'tools'))
    cache = {}
    total = 0
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context(viewport={'width': 1100, 'height': 900}, device_scale_factor=2)
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
