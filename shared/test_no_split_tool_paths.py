#!/usr/bin/env python3
"""Standing check (Phase 3, Nov 19 2026): tool folders are named by ONE
repo-relative string from a marker-found root, never built from segments
("civic_reference" / "nyc_council_..."), never reached as a sibling
(BASE.parent / "legislation_implementation_tracker"), and never by counting
parent folders past the tool. Split paths are invisible to the folder-move
rewrite (shared/move_folders.py) and silently point at the old place after a
move; on Nov 19 2026 the fiscal pipeline would have rebuilt the old folder.

Premium paths are exempt: the premium repo keeps the old folder names, so a
line that builds a path under a premium checkout (prem /, PREMIUM_*) is fine.
Exit 0 = clean. Run: python3 shared/test_no_split_tool_paths.py
"""
import pathlib, re, subprocess, sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / 'CNAME').is_file())
TOOL_NAMES = ('legislation_implementation_tracker', 'nyc_council_fiscal_impacts_tracker',
              'nyc_council_legislation_trackers', 'nys_legislation_trackers', 'member-tracker',
              'cb_member_guide', 'block_party_maps', 'nyc-gov-bodies-explorer')
SPLIT = re.compile(r'["\'](civic_reference|cb-tools|tools|posts)["\']\s*(/|,)\s*["\']')
SIBLING = re.compile(r'\.parent\s*/\s*["\'](' + '|'.join(map(re.escape, TOOL_NAMES)) + r')["\']')
DEEP_HOP = re.compile(r'parent\.parent\.parent|parents\[[3-9]\]')
EXEMPT_LINE = re.compile(r'prem\b|PREMIUM|premium', re.I)
SKIP = ('/cache/', 'state_capacity_ecosystem/', 'shared/batch0_root_paths.py', 'shared/move_folders.py',
        'shared/test_no_split_tool_paths.py')

files = subprocess.run(['git', 'ls-files', '*.py'], cwd=ROOT, capture_output=True, text=True).stdout.split()
bad = []
for rel in files:
    if any(s in rel for s in SKIP):
        continue
    for i, line in enumerate((ROOT / rel).read_text(errors='ignore').split('\n'), 1):
        code = line.split('#', 1)[0]
        if EXEMPT_LINE.search(line) or 'path-ok' in line:
            continue
        if SPLIT.search(code) or SIBLING.search(code) or (DEEP_HOP.search(code) and '/tests/' not in rel):
            bad.append(f'{rel}:{i}: {line.strip()[:140]}')
for b in bad:
    print('SPLIT PATH', b)
print(f'{len(files)} python files scanned, {len(bad)} split tool paths')
sys.exit(1 if bad else 0)
