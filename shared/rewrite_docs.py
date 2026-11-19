#!/usr/bin/env python3
"""Rewrite old data-site paths and URLs in docs outside the site repo (skills,
memory, CLAUDE.md, routine instruction files, helper scripts) after the
Phase 3 URL restructure (Nov 19 2026).

    python3 shared/rewrite_docs.py [--dry-run] FILE...

Applies every batch of shared/move_folders.py at once. Lines that mention
premium or a /members/?file= value are left alone and printed: the premium
repo keeps the old folder names, so those lines need a human read.
"""
import pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.argv, _args = [sys.argv[0]], sys.argv[1:]
import move_folders as m  # noqa: E402

PAIRS = []
for b in ('posts', 'cb', 'council', 'fiscal', 'implementation', 'nys', 'member-tracker'):
    PAIRS += m.BATCHES[b]
# longest first, so civic_reference/nyc_council_legislation_trackers is not cut by a shorter key
PAIRS.sort(key=lambda p: -len(p[0]))
EXTRA = [('nycuriosity_substack_posts/', 'posts/'), ('cb-tools/', 'tools/community-boards/')]
RX = [(re.compile(r'(?<![\w.-])' + re.escape(o) + m.BOUNDARY_AFTER), n) for o, n in PAIRS]
# docs often name a tool folder without its parent (legislation_implementation_tracker/pipeline/...)
BARE = [('nyc_council_legislation_trackers/', 'tools/legislation/'),
        ('legislation_implementation_tracker/', 'tools/legislation/implementation/'),
        ('nyc_council_fiscal_impacts_tracker/', 'tools/legislation/fiscal/'),
        ('nys_legislation_trackers/', 'tools/nys-legislation/')]
EXTRA_BARE = [(re.compile(r'(?<![\w/.-])' + re.escape(o)), n) for o, n in BARE]
RX += [(re.compile(r'(?<![\w.-])' + re.escape(o)), n) for o, n in EXTRA]
GUARD = re.compile(r'premium|file=|PREMIUM', re.I)


def main():
    dry = '--dry-run' in _args
    changed = skipped = 0
    for f in [a for a in _args if a != '--dry-run']:
        p = pathlib.Path(f)
        lines = p.read_text().split('\n')
        out = []
        for i, line in enumerate(lines, 1):
            new = line
            if any(o in line for o, _ in PAIRS + EXTRA + BARE):
                for rx, n in RX + EXTRA_BARE:
                    def sub(mm, n=n, src=new):
                        before = src[max(0, mm.start() - 45):mm.start()]
                        if re.search(r'premium[\w.-]*[/ `]*$|nycur-data-premium/[\w/.-]*$|file=/?$', before, re.I):
                            return mm.group(0)
                        return n
                    new = rx.sub(sub, new)
                if GUARD.search(line):
                    skipped += 1
                    print(f'REVIEW {f}:{i}:\n   - {line.strip()[:200]}\n   + {new.strip()[:200]}')
            out.append(new)
        if out != lines:
            changed += 1
            if not dry:
                p.write_text('\n'.join(out))
    print(f'{changed} files rewritten, {skipped} premium/file= lines to review')


if __name__ == '__main__':
    main()
