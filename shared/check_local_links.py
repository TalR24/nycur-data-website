#!/usr/bin/env python3
"""List every local link, asset and fetch on the site that points at nothing.

    python3 shared/check_local_links.py [--out FILE]

Scans every tracked .html (href, src, action, srcset, and string literals passed
to fetch()) plus site-wide .js/.json path strings that start with a known top
folder. A target counts as present when the repo has the file, or the folder has
an index.html. External URLs, data.nycuriosity.com URLs (checked as local paths),
anchors, mailto/tel/javascript/data URIs and template strings are handled or
skipped. Prints one 'source -> target' line per miss and a total; --out writes the
lines to a file so a pre-move baseline can be diffed against a post-move run.
Written for the Phase 3 URL restructure (Nov 2026).
"""
import pathlib, re, subprocess, sys, urllib.parse

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / 'CNAME').is_file())
SITE_PREFIXES = ('https://data.nycuriosity.com', 'http://data.nycuriosity.com', '//data.nycuriosity.com')
SKIP = ('/cache/', 'state_capacity_ecosystem/', 'node_modules/')
ATTR = re.compile(r'\b(?:href|src|action|data-src|data-cb-link)\s*=\s*"([^"]*)"|\b(?:href|src)\s*=\s*\'([^\']*)\'', re.I)
FETCH = re.compile(r'fetch\(\s*([\'"])([^\'"$`]+)\1')
JSPATH = re.compile(r'([\'"])(/(?:tools|posts|civic_reference|cb-tools|nycuriosity_substack_posts)/[^\'"\s$`]*)\1')

tracked = set(subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=ROOT,
                             capture_output=True, text=True).stdout.splitlines())
present = set(tracked)
for f in tracked:  # every folder that holds a tracked file exists
    parts = f.split('/')
    for i in range(1, len(parts)):
        present.add('/'.join(parts[:i]) + '/')


def exists(path):
    path = urllib.parse.unquote(path.split('#')[0].split('?')[0]).lstrip('/')
    if path == '' or path in present:
        return path == '' or not path.endswith('/') or (path + 'index.html') in present
    if path.endswith('/'):
        return (path + 'index.html') in present
    return (path + '/index.html') in present or path in present


def resolve(src_rel, target):
    target = target.strip()
    for pre in SITE_PREFIXES:
        if target.startswith(pre):
            target = target[len(pre):] or '/'
    if not target or target.startswith(('#', 'mailto:', 'tel:', 'javascript:', 'data:', 'http:', 'https:', '//', '{', '%7B')):
        return None
    if '${' in target or '{{' in target or "' +" in target or '+ ' in target:
        return None
    if target.startswith('/'):
        return target
    base = '/' + str(pathlib.PurePosixPath(src_rel).parent) + '/'
    return urllib.parse.urljoin(base if base != '/./' else '/', target)


def main():
    misses = []
    for rel in sorted(tracked):
        if any(s in rel for s in SKIP) or not (ROOT / rel).is_file():
            continue
        if rel.endswith('.html'):
            text = (ROOT / rel).read_text(errors='ignore')
            targets = [a or b for a, b in ATTR.findall(text)] + [m[1] for m in FETCH.findall(text)]
            if 'location.replace(' in text:  # stub targets
                targets += re.findall(r"location\.replace\('([^']+)'", text)
        elif rel.endswith(('.js', '.json')) and not rel.startswith(('.github', 'seo/')) and '/data/' not in rel:
            text = (ROOT / rel).read_text(errors='ignore')
            targets = [m[1] for m in JSPATH.findall(text)]
            targets += [m[1] for m in FETCH.findall(text) if m[1].startswith('/')]
        else:
            continue
        for t in targets:
            r = resolve(rel, t)
            if r and not exists(r):
                misses.append(f'{rel} -> {r}')
    misses = sorted(set(misses))
    if '--out' in sys.argv:
        pathlib.Path(sys.argv[sys.argv.index('--out') + 1]).write_text('\n'.join(misses) + '\n')
    for m in misses[:400]:
        print(m)
    print(f'TOTAL {len(misses)} missing local targets')


if __name__ == '__main__':
    main()
