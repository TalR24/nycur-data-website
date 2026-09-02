#!/usr/bin/env python3
"""Move each Block Party map's inline DB literal into a sibling data file.

The pages embed a single `const DB={...}` holding every place and resolution —
up to 65MB, which is 99.7% of the file. Every code or brand edit therefore
rewrites a multi-megabyte blob into git history.

This extracts DB to data/<slug>.js, which assigns window.DB, and loads it with
a plain <script src> immediately before the app script. That keeps the app code
top-level and synchronous: no IIFE, no async. That matters because the pages
call 73 functions from dynamically-written onclick attributes and four of them
(goHome, toggleFacet, votePin, welcome) are NOT on window, so wrapping the
script in a closure would silently break them.

Run this after every map refresh. make_demo.py in the resolution_engine repo
still emits the inline form, so a fresh artifact copied over these pages will
re-inline the payload and undo the split:

    cd civic_reference/block_party_maps
    python3 tools/split_map_data.py *.html --apply

It is idempotent — already-split pages are skipped.
"""
import re, sys, pathlib, json

def find_db(s):
    """Locate the DB object literal. Must be string-aware: resolution text in
    these files contains braces, so a naive brace counter closes the object
    early and silently truncates the payload."""
    m = re.search(r'const\s+DB\s*=\s*', s)
    if not m: return None
    start = s.index('{', m.end() - 1)
    d = 0; i = start; instr = False; esc = False
    while i < len(s):
        c = s[i]
        if instr:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': instr = False
        else:
            if c == '"': instr = True
            elif c == '{': d += 1
            elif c == '}':
                d -= 1
                if d == 0: break
        i += 1
    return m.start(), start, i + 1

def main():
    apply = '--apply' in sys.argv
    files = [pathlib.Path(a) for a in sys.argv[1:] if a.endswith('.html')]
    data_dir = pathlib.Path('data'); 
    if apply: data_dir.mkdir(exist_ok=True)
    for f in files:
        s = f.read_text(errors='ignore')
        loc = find_db(s)
        if not loc:
            print(f'  {f.name}: no inline DB, skipped'); continue
        decl_start, obj_start, obj_end = loc
        if 'data/' + f.stem + '.js' in s:
            print(f'  {f.name}: already split, skipped'); continue
        payload = s[obj_start:obj_end]
        json.loads(payload)                       # fail loudly rather than ship a broken page
        # replace `const DB={...}` with a reference to the external assignment
        new = s[:decl_start] + 'const DB=window.DB' + s[obj_end:]
        # load the data file immediately before the app script that uses it
        tag = f'<script src="data/{f.stem}.js"></script>\n<script>'
        idx = new.rfind('<script>', 0, new.find('const DB=window.DB'))
        new = new[:idx] + tag + new[idx + len('<script>'):]
        before, after = len(s), len(new)
        print(f'  {f.name}: {before/1048576:6.2f} MB -> {after/1024:7.1f} KB '
              f'+ data/{f.stem}.js {len(payload)/1048576:.2f} MB')
        if apply:
            (data_dir / f'{f.stem}.js').write_text('window.DB=' + payload + ';\n')
            f.write_text(new)

main()
