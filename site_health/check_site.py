#!/usr/bin/env python3
"""
Weekly site-health watchdog for data.nycuriosity.com.

Crawls every same-origin HTML page reachable from the homepage (capped), loads
each in headless Chromium, and flags the site's known failure modes:

  - HTTP status >= 400 on the page itself
  - any same-origin subresource (JSON/CSV/JS/img) responding >= 400
  - JavaScript page errors (uncaught exceptions, SyntaxError killing a script)
  - console.error output
  - blank chart SVGs: an <svg> at least 100px wide with no shape descendants
    after charts have had time to draw (the classic silent failure here)
  - visible "Loading" text still on screen after settle (stalled page)

Failed pages are retried once to absorb network flakes. If problems remain,
a plain-text report is emailed to ALERT_TO via Gmail SMTP (GMAIL_USER /
GMAIL_APP_PASSWORD env, same pattern as pipeline/send_alerts.py) and the
script exits 1 so the workflow run shows red. Healthy run: no email, exit 0.

Usage: python3 check_site.py [--dry-run]   (--dry-run: print report, never email)
"""

import os
import smtplib
import sys
from email.mime.text import MIMEText
from urllib.parse import urljoin, urldefrag, urlparse

from playwright.sync_api import sync_playwright

BASE = "https://data.nycuriosity.com"
ALERT_TO = "troded24@gmail.com"
MAX_PAGES = 150
SETTLE_MS = 3500  # charts draw via inline JS after load

SHAPE_SELECTOR = "path, rect, circle, ellipse, line, polyline, polygon, text, use, image"

BLANK_SVG_JS = """
() => {
  const bad = [];
  document.querySelectorAll('svg').forEach(svg => {
    const r = svg.getBoundingClientRect();
    if (r.width >= 100 && r.height >= 60 &&
        !svg.querySelector('%s')) {
      bad.push(svg.id || svg.getAttribute('class') || 'unnamed svg');
    }
  });
  return bad;
}
""" % SHAPE_SELECTOR

STUCK_LOADING_JS = """
() => {
  const hits = [];
  document.querySelectorAll('body *').forEach(el => {
    if (el.children.length === 0 && /^\\s*Loading/i.test(el.textContent || '') &&
        el.getBoundingClientRect().height > 0) {
      hits.push((el.textContent || '').trim().slice(0, 60));
    }
  });
  return hits.slice(0, 5);
}
"""


def same_origin(url):
    return urlparse(url).netloc == urlparse(BASE).netloc


def check_page(page, url):
    """Load one page, return list of problem strings (empty = healthy)."""
    problems = []
    console_errors = []
    page_errors = []
    bad_resources = []

    def on_console(msg):
        if msg.type == "error":
            console_errors.append(msg.text[:200])

    def on_pageerror(err):
        page_errors.append(str(err)[:200])

    def on_response(resp):
        if resp.status >= 400 and same_origin(resp.url):
            bad_resources.append(f"{resp.status} {resp.url}")

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)
    try:
        resp = page.goto(url, wait_until="load", timeout=45000)
        if resp is not None and resp.status >= 400:
            problems.append(f"page returned HTTP {resp.status}")
        page.wait_for_timeout(SETTLE_MS)

        for name in page.evaluate(BLANK_SVG_JS):
            problems.append(f"blank chart SVG: {name}")
        for text in page.evaluate(STUCK_LOADING_JS):
            problems.append(f'stuck on "{text}"')
    except Exception as e:
        problems.append(f"load failed: {str(e)[:200]}")
    finally:
        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_pageerror)
        page.remove_listener("response", on_response)

    for e in page_errors:
        problems.append(f"JS error: {e}")
    for e in console_errors:
        problems.append(f"console.error: {e}")
    for r in sorted(set(bad_resources)):
        problems.append(f"broken resource: {r}")
    return problems


def collect_links(page):
    hrefs = page.evaluate(
        "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))"
    )
    out = set()
    for h in hrefs:
        if not h or h.startswith(("mailto:", "javascript:", "#")):
            continue
        absu = urldefrag(urljoin(page.url, h)).url
        if same_origin(absu) and not absu.lower().endswith(
            (".csv", ".json", ".png", ".svg", ".pdf", ".zip", ".xlsx", ".pptx", ".ics")
        ):
            out.add(absu.rstrip("?"))
    return out


def crawl():
    results = {}  # url -> [problems]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        queue = [BASE + "/"]
        seen = set(queue)
        while queue and len(results) < MAX_PAGES:
            url = queue.pop(0)
            problems = check_page(page, url)
            if problems:  # retry once: absorb transient flakes
                problems = check_page(page, url)
            results[url] = problems
            if not problems or all(p.startswith(("console.error", "blank")) for p in problems):
                try:
                    for link in collect_links(page):
                        if link not in seen:
                            seen.add(link)
                            queue.append(link)
                except Exception:
                    pass
        browser.close()
    return results


def main():
    dry = "--dry-run" in sys.argv
    results = crawl()
    broken = {u: p for u, p in results.items() if p}

    print(f"Checked {len(results)} pages; {len(broken)} with problems.")
    for url, problems in sorted(broken.items()):
        print(f"\n{url}")
        for p in problems:
            print(f"  - {p}")

    if not broken:
        return 0

    lines = [
        f"Site-health check found problems on {len(broken)} of {len(results)} pages",
        f"at {BASE}.",
        "",
    ]
    for url, problems in sorted(broken.items()):
        lines.append(url)
        lines.extend(f"  - {p}" for p in problems)
        lines.append("")
    lines.append("Run details: GitHub Actions -> nycur-data-website -> Site Health.")
    body = "\n".join(lines)

    if dry:
        print("\n--dry-run: email suppressed.")
    else:
        msg = MIMEText(body)
        msg["Subject"] = f"data.nycuriosity.com health: {len(broken)} broken page(s)"
        msg["From"] = os.environ["GMAIL_USER"]
        msg["To"] = ALERT_TO
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
            s.send_message(msg)
        print(f"\nAlert emailed to {ALERT_TO}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
