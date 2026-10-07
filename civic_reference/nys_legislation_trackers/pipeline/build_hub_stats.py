#!/usr/bin/env python3
"""Write data/hub_stats.json: per-session bill and signed-law counts for the hub pills,
so the hub does not download the nine 6-8 MB bill files. No model calls."""
import json, os, glob

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')

sessions = []
for p in sorted(glob.glob(os.path.join(DATA, 'bills', '*.json'))):
    d = json.load(open(p))
    c = {k: i for i, k in enumerate(d['cols'])}
    rows = d['rows']
    sessions.append({
        'session': d['session'],
        'bills': len(rows),
        'signed': sum(1 for r in rows if r[c['signed']]),
        'vetoed': sum(1 for r in rows if r[c['vetoed']]),
    })
out = {'generated': max(json.load(open(p)).get('generated', '') for p in glob.glob(os.path.join(DATA, 'bills', '*.json'))),
       'sessions': sessions}
json.dump(out, open(os.path.join(DATA, 'hub_stats.json'), 'w'), separators=(',', ':'))
print(sum(s['bills'] for s in sessions), sum(s['signed'] for s in sessions), len(sessions))
