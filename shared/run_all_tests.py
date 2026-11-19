#!/usr/bin/env python3
"""Run every standalone test script in the repo, the way the workflows do
(`python3 <file>`, exit code 0 = pass), and print a pass/fail table.

Written for the Phase 3 folder moves (Nov 19 2026) so each batch can prove
nothing broke. Tests that need a local cache the checkout lacks print SKIP and
exit 0 on their own. Run from the repo root: python3 shared/run_all_tests.py
"""
import subprocess, sys, pathlib, time

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / 'CNAME').is_file())
tests = sorted(p for p in ROOT.rglob('test_*.py')
               if '/cache/' not in str(p) and 'node_modules' not in str(p)
               and 'state_capacity_ecosystem' not in str(p))
fails = []
t0 = time.time()
for p in tests:
    r = subprocess.run([sys.executable, str(p)], cwd=ROOT, capture_output=True, text=True, timeout=900)
    rel = p.relative_to(ROOT)
    if r.returncode != 0:
        fails.append(rel)
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        print(f'FAIL {rel}\n     ' + '\n     '.join(tail))
print(f'{len(tests)} test files, {len(tests) - len(fails)} passed, {len(fails)} failed, {time.time() - t0:.0f}s')
sys.exit(1 if fails else 0)
