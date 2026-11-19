#!/usr/bin/env python3
"""Move site folders to new URLs and rewrite every reference (Phase 3, Nov 2026).

    python3 shared/move_folders.py <batch> [--dry-run]

For each (old, new) pair of the batch, in order:
  1. git mv old -> new (a folder or a single file).
  2. Rewrite every reference to `old` in tracked text files: absolute URLs
     (/old/..., data.nycuriosity.com/old/...), repo-relative paths in scripts and
     workflows ("old/..."), and root-relative links. Matches are left alone when
     they point at the PREMIUM site, which keeps the old folder names: a match
     preceded by premium.nycuriosity.com/ or file= (the /members/?file= paywall
     links), and, in .py/.yml/.sh files, any line that mentions premium. Every
     skipped line is printed for review.
  3. Write a redirect stub at the old path of every moved public .html page
     (one hop, query and hash preserved, canonical to the new URL, noindex).
Then run shared/check_local_links.py and compare against the pre-move baseline.

Stubs are never written inside pipeline/, data/, cache/, quality/ or tests/
folders, which hold no public pages.
"""
import html, pathlib, re, subprocess, sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / 'CNAME').is_file())
SITE = 'https://data.nycuriosity.com'
TEXT_EXT = {'.html', '.js', '.css', '.json', '.py', '.sh', '.yml', '.yaml', '.md', '.txt', '.xml', '.webmanifest'}
NO_STUB_PARTS = {'pipeline', 'data', 'cache', 'quality', 'tests', 'quality_reports'}
SKIP_FILES = ('/cache/', 'state_capacity_ecosystem/', 'shared/move_folders.py', 'shared/batch0_root_paths.py')

CR = 'civic_reference'
POSTS = sorted(p.name for p in (ROOT / 'nycuriosity_substack_posts').iterdir() if p.is_dir()) \
    if (ROOT / 'nycuriosity_substack_posts').is_dir() else []

BATCHES = {
    'posts': [(f'nycuriosity_substack_posts/{s}', f'posts/{s.replace("_", "-")}') for s in POSTS],
    'cb': [
        ('cb-tools/index.html', 'tools/community-boards/index.html'),
        ('cb-tools/cb-filter.css', 'tools/community-boards/cb-filter.css'),
        ('cb-tools/cb-filter.js', 'tools/community-boards/cb-filter.js'),
        ('cb-tools/cb-switch.js', 'tools/community-boards/cb-switch.js'),
        *[(f'cb-tools/{d}', f'tools/community-boards/{d}') for d in (
            'block-party', 'block_party_july2026', 'board-scorecard', 'explorer', 'harvard-rcn-2026',
            'meeting-review', 'resolutions-per-year', 'roberts-rules-helper', 'school-of-data-2026',
            'sogt-2026', 'top-agencies', 'top-topics')],
        (f'{CR}/cb_member_guide', 'tools/community-boards/member-guide'),
        (f'{CR}/block_party_maps', 'tools/community-boards/block-party-maps'),
        (f'{CR}/nyc-gov-bodies-explorer', 'tools/gov-bodies'),
    ],
    'fiscal': [(f'{CR}/nyc_council_fiscal_impacts_tracker', 'tools/legislation/fiscal')],
    'council': [(f'{CR}/nyc_council_legislation_trackers', 'tools/legislation')],
    'implementation': [(f'{CR}/legislation_implementation_tracker', 'tools/legislation/implementation')],
    'nys': [(f'{CR}/nys_legislation_trackers', 'tools/nys-legislation')],
    'member-tracker': [('cb-tools/member-tracker', 'tools/community-boards/member-tracker')],
}

BOUNDARY_AFTER = r'(?=[/"\'\s?#)\]`,;<>]|$)'


def git(*a, check=True):
    return subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True, check=check).stdout


def tracked_text_files():
    out = []
    for rel in git('ls-files').splitlines():
        if any(s in rel for s in SKIP_FILES):
            continue
        p = ROOT / rel
        if p.suffix.lower() in TEXT_EXT and p.is_file():
            out.append(p)
    return out


def rewrite(pairs, dry):
    skipped, changed = [], 0
    pats = [(re.compile(r'(?<![\w.-])' + re.escape(o) + BOUNDARY_AFTER), o, n) for o, n in pairs]
    for p in tracked_text_files():
        try:
            t = p.read_text()
        except UnicodeDecodeError:
            continue
        if not any(o in t for _, o, _ in pats):
            continue
        script_like = p.suffix in ('.py', '.yml', '.yaml', '.sh')
        lines = t.split('\n')
        for i, line in enumerate(lines):
            if not any(o in line for _, o, _ in pats):
                continue
            if script_like and 'premium' in line.lower():
                skipped.append(f'{p.relative_to(ROOT)}:{i + 1}: {line.strip()[:150]}')
                continue
            for rx, o, n in pats:
                def sub(m, n=n):
                    before = line[max(0, m.start() - 40):m.start()]
                    if 'premium.nycuriosity.com/' in before or re.search(r'file=/?$', before):
                        skipped.append(f'{p.relative_to(ROOT)}:{i + 1}: [premium/file=] {m.group(0)}')
                        return m.group(0)
                    return n
                line = rx.sub(sub, line)
            lines[i] = line
        new = '\n'.join(lines)
        if new != t:
            changed += 1
            if not dry:
                p.write_text(new)
    return changed, skipped


def page_meta(text):
    def grab(rx):
        m = re.search(rx, text, re.S | re.I)
        return html.unescape(m.group(1).strip()) if m else ''
    title = grab(r'<title>(.*?)</title>') or 'NYCuriosity Data'
    desc = grab(r'<meta\s+name="description"\s+content="(.*?)"')
    return title, desc


def url_of(rel):
    rel = rel.replace('\\', '/')
    if rel.endswith('index.html'):
        return '/' + rel[: -len('index.html')]
    return '/' + rel


STUB = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <meta name="robots" content="noindex">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="canonical" href="{site}{new}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{site}{new}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:image" content="{site}/website_logo.png">
  <meta http-equiv="refresh" content="0; url={new}">
  <script>
    // Moved in the Nov 2026 URL restructure; keep any query string and hash
    location.replace('{new}' + location.search + location.hash);
  </script>
  <link rel="stylesheet" href="/assets/brand.css">
  <style>body {{ font-family: var(--b-sans); padding: 60px 24px; max-width: 600px; margin: 0 auto; color: var(--b-ink-2); line-height: 1.6; }} a {{ color: var(--b-tangerine-deep); }}</style>
</head>
<body>
  <p>This page moved to <a href="{new}">{site_host}{new}</a>.</p>
</body>
</html>
'''


def make_stubs(moved_pages, dry):
    n = 0
    for old_rel, new_rel in moved_pages:
        if set(pathlib.PurePosixPath(old_rel).parts[:-1]) & NO_STUB_PARTS:
            continue
        text = (ROOT / new_rel).read_text(errors='ignore')
        target = url_of(new_rel)
        m = re.search(r'http-equiv="refresh"\s+content="0;\s*url=([^"]+)"', text)
        if m:  # the moved page is itself a stub: point straight at its final target (one hop)
            target = m.group(1).replace(SITE, '')
        title, desc = page_meta(text)
        stub = STUB.format(title=html.escape(title, quote=True), desc=html.escape(desc or title, quote=True),
                           site=SITE, site_host='data.nycuriosity.com', new=target)
        if not dry:
            dest = ROOT / old_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(stub)
        n += 1
    return n


def main():
    batch = sys.argv[1]
    dry = '--dry-run' in sys.argv
    pairs = BATCHES[batch]
    for o, n in pairs:
        assert (ROOT / o).exists(), f'missing {o}'
        assert not (ROOT / n).exists(), f'target exists {n}'
    moved_pages = []
    for o, n in pairs:
        files = git('ls-files', o).splitlines()
        moved_pages += [(f, n + f[len(o):]) for f in files if f.endswith('.html')]
        if not dry:
            (ROOT / n).parent.mkdir(parents=True, exist_ok=True)
            git('mv', o, n)
    print(f'{len(pairs)} moves, {len(moved_pages)} html files moved')
    changed, skipped = rewrite(pairs, dry)
    print(f'{changed} files rewritten')
    if not dry:
        print(f'{make_stubs(moved_pages, dry)} stubs written')
    print(f'{len(skipped)} premium/file= references left on the old path (review):')
    for s in skipped:
        print('   ', s)


if __name__ == '__main__':
    main()
