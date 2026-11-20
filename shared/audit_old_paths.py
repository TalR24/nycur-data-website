#!/usr/bin/env python3
"""Find every reference to a pre-Phase-3 data-site path anywhere on this Mac's
work folders, and sort each hit (Nov 19 2026 restructure audit).

    python3 shared/audit_old_paths.py [--out FILE]

Roots: ~/nycur (all repos and local folders), ~/.claude (CLAUDE.md, rules,
hooks, settings, skills incl. synced, agents, commands, memory), ~/bin, ~/code.
Each hit is classed:
  premium     the premium repo's own paths (it keeps the old folder names), a
              premium.nycuriosity.com URL, a /members/?file= value or a line that
              builds a premium path
  stub        a redirect stub on the data site (expected)
  history     archives that record what was true then (sent mail, SEO reports,
              briefs, inbox, digests, transcripts, local backups, git internals)
  doc-note    a line that names the old path as history ("moved from", "old URL")
  ACTION      everything else: should point at the new path
"""
import os, pathlib, re, sys

HOME = pathlib.Path.home()
ROOTS = [HOME / 'nycur', HOME / '.claude', HOME / 'bin', HOME / 'code']
OLD = re.compile(r'(?<![\w-])(civic_reference/(?:nyc_council_legislation_trackers|legislation_implementation_tracker|'
                 r'nyc_council_fiscal_impacts_tracker|nys_legislation_trackers|cb_member_guide|block_party_maps|'
                 r'nyc-gov-bodies-explorer)|cb-tools/|nycuriosity_substack_posts/)')
TEXT = {'.md', '.py', '.js', '.json', '.html', '.yml', '.yaml', '.sh', '.txt', '.toml', '.css', '.csv', '.mjs',
        '.ts', '.tsx', '.jsx', '.ini', '.cfg', '.xml', '.jsonc', ''}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', 'cache', '.venv', 'venv', 'out', 'public', 'projects_archive',
             'jobs', 'plugins', 'debug', 'paste-cache', 'image-cache', 'session-env', 'ide'}  # ~/.claude scratch and caches
HISTORY = ('seo_reports/', 'ops_digest/sent', 'ops_digest/pending', 'planning/sent', 'planning/inbox', 'planning/briefs',
           'mention_monitor_state/', 'opportunities/state', 'local_folders_backup/', '/archive/', 'handoffs/',
           'nycur_session_archive', '/.claude/projects/', 'quality_reports/', '/quality/nightly/', 'shell-snapshots',
           'file-history', 'todos/', 'statsig', '/logs/', 'copy_reports/', 'papercuts.md', 'changes.md',
           'site_redesign_phase3_action_inventory.md', 'site_redesign_plan_2026.md', 'broken_links_report')
OWN_TOOLS = ('shared/move_folders.py', 'shared/batch0_root_paths.py', 'shared/rewrite_docs.py',
             'shared/audit_old_paths.py', 'shared/test_no_split_tool_paths.py', 'shared/check_local_links.py',
             'test_monitor.py', 'mention_monitor/config.json', 'prune_overrides.py')
PREMIUM_LINE = re.compile(r'premium|PREMIUM|file=|/tmp/premium|prem\s*/|path-ok|alert_subscriptions|alerts_state|cb_alert|nys_bill_follows|nys_bill_alerts_state', re.I)
NOTE_LINE = re.compile(r'moved|old (url|path|folder)|pre-?move|redirect|stub|before the|Nov 19 2026|was at|formerly|legacy', re.I)
MEMORY = HOME / '.claude/projects/-Users-troded-nycur/memory'


def classify(path, line):
    s = str(path)
    if MEMORY.as_posix() in s:
        pass  # memory is live guidance, judged by line below
    elif any(h in s for h in HISTORY):
        return 'history'
    if '/nycur-data-premium/' in s and '/claude_context/' not in s:
        return 'premium'
    if any(s.endswith(t) for t in OWN_TOOLS):
        return 'doc-note'
    if '/data_website/' in s and s.endswith('.html'):
        try:
            head = path.read_text(errors='ignore')[:2500]
        except OSError:
            head = ''
        if 'http-equiv="refresh"' in head:
            return 'stub'
    if PREMIUM_LINE.search(line):
        return 'premium'
    if NOTE_LINE.search(line):
        return 'doc-note'
    return 'ACTION'


def walk():
    for root in ROOTS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.Trash')]
            if '/.claude/projects/' in dirpath and '/memory' not in dirpath:
                dirnames[:] = []
                continue
            for f in filenames:
                p = pathlib.Path(dirpath) / f
                if p.suffix.lower() not in TEXT or p.name.endswith('.jsonl'):
                    continue
                try:
                    if p.stat().st_size > 3_000_000:
                        continue
                    text = p.read_text(errors='ignore')
                except OSError:
                    continue
                if not OLD.search(text):
                    continue
                for i, line in enumerate(text.split('\n'), 1):
                    if OLD.search(line):
                        yield p, i, line


def main():
    out, counts = [], {}
    for p, i, line in walk():
        c = classify(p, line)
        counts[c] = counts.get(c, 0) + 1
        out.append(f'{c}\t{p}:{i}\t{line.strip()[:200]}')
    if '--out' in sys.argv:
        pathlib.Path(sys.argv[sys.argv.index('--out') + 1]).write_text('\n'.join(out) + '\n')
    for line in out:
        if line.startswith('ACTION'):
            print(line)
    print('COUNTS', counts)


if __name__ == '__main__':
    main()
