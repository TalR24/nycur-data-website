#!/usr/bin/env python3
"""Every chart card must carry the large-type class: <figure class="chart-card c-lg">.

Why: a downloaded chart PNG is placed in a Substack column about 728px wide, so base-size
ticks, legends and value labels land near 7 to 9px in the post (Tal, Nov 2026). The c-lg
layer in assets/chart.css lifts all chart text except the title and deck.

Pages listed in seo/chart_type_legacy.txt predate the rule (published charts whose SVG
layouts were spaced for the smaller type). Never add a page to that list: convert it.
To convert a legacy page, add c-lg, check the exported PNG, and delete its line.

Run from the data_website folder:  python3 seo/check_chart_type.py
Exit code 1 if any page outside the legacy list has a .chart-card without c-lg.
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY = set(l.strip() for l in open(os.path.join(ROOT, 'seo', 'chart_type_legacy.txt')) if l.strip())
CARD = re.compile(r'class="([^"]*\bchart-card\b[^"]*)"')
SKIP_DIRS = {'.git', 'node_modules', '.claude'}

bad, stale = [], []
for d, dirs, files in os.walk(ROOT):
    dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
    for f in files:
        if not f.endswith('.html'):
            continue
        p = os.path.join(d, f)
        rel = os.path.relpath(p, ROOT)
        html = open(p, encoding='utf-8', errors='replace').read()
        cards = CARD.findall(html)
        if not cards:
            continue
        missing = [c for c in cards if 'c-lg' not in c.split()]
        if missing and rel not in LEGACY:
            bad.append(rel)
        if not missing and rel in LEGACY:
            stale.append(rel)
for rel in sorted(stale):
    print('NOTE  %s is converted; delete its line from seo/chart_type_legacy.txt' % rel)
for rel in sorted(bad):
    print('FAIL  %s: .chart-card without c-lg (use class="chart-card c-lg")' % rel)
print('%d page(s) fail, %d legacy page(s) exempt' % (len(bad), len(LEGACY)))
sys.exit(1 if bad else 0)
