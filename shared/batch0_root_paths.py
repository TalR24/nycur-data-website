#!/usr/bin/env python3
"""Phase 3 batch 0 (Nov 19 2026): replace depth-counting path hops with a
marker-found repo root, so tool folders can move without breaking pipelines.

Every hop that climbed out of its own tool folder (`HERE.parent.parent.parent`,
`parents[3]`, os.path.dirname x3 ...) becomes SITE_ROOT / "<repo-relative path>".
SITE_ROOT is the nearest ancestor holding CNAME (the GitHub Pages marker at the
repo root, present in every Actions checkout). Repo-relative paths are written
as one string so the folder-move rewrite can update them like any other path.

One-off migration script; kept for the record. Run from the repo root.
"""
import pathlib, sys

ROOT_LINE = ('SITE_ROOT = next(p for p in Path(__file__).resolve().parents '
             'if (p / "CNAME").is_file())  # repo root by marker, safe across folder moves\n')

LIT = 'civic_reference/legislation_implementation_tracker'
CNL = 'civic_reference/nyc_council_legislation_trackers'
FIS = 'civic_reference/nyc_council_fiscal_impacts_tracker'
GOV = 'civic_reference/nyc-gov-bodies-explorer'

# file -> (anchor line after which SITE_ROOT is defined, [(old, new), ...])
EDITS = {
 'cb-tools/member-tracker/pipeline/build_static_boards.py': ('HERE = Path(__file__).resolve().parent.parent\n', [
   ('str(HERE.parent.parent / "seo")', 'str(SITE_ROOT / "seo")')]),
 'cb-tools/member-tracker/pipeline/send_cb_alerts.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('str(HERE.parents[2] / "shared")', 'str(SITE_ROOT / "shared")')]),
 f'{LIT}/pipeline/build_report_filings.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('str(HERE.parent.parent.parent / "pipeline")', 'str(SITE_ROOT / "pipeline")')]),
 f'{LIT}/pipeline/build_static_snapshots.py': ('HERE = Path(__file__).resolve().parent.parent          # legislation_implementation_tracker/\n', [
   ('str(HERE.parent.parent / "seo")', 'str(SITE_ROOT / "seo")'),
   ('relative_to(HERE.parent.parent)', 'relative_to(SITE_ROOT)')]),
 f'{LIT}/pipeline/email_quality_summary.py': ('TRACKER = Path(__file__).resolve().parent.parent\n', [
   ('str(Path(__file__).resolve().parents[3] / "shared")', 'str(SITE_ROOT / "shared")'),
   ('str(Path(__file__).resolve().parents[3] / "seo")', 'str(SITE_ROOT / "seo")')]),
 f'{LIT}/pipeline/extract_obligations.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('str(HERE.parent.parent.parent / "pipeline")', 'str(SITE_ROOT / "pipeline")'),
   ('HERE.parent.parent.parent / "pipeline" / "max_refresh.json"', 'SITE_ROOT / "pipeline" / "max_refresh.json"')]),
 f'{LIT}/pipeline/label_kinds.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('str(HERE.parent.parent.parent / "pipeline")', 'str(SITE_ROOT / "pipeline")')]),
 f'{LIT}/pipeline/monthly_quality_report.py': ('TRACKER = HERE.parent\n', [
   ('REPO = TRACKER.parent.parent', 'REPO = SITE_ROOT')]),
 f'{LIT}/pipeline/reconcile_protected.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('HERE.parent.parent / "nyc_council_legislation_trackers" / "quality"', f'SITE_ROOT / "{CNL}/quality"')]),
 f'{LIT}/pipeline/tests/test_crosswalk_copies.py': (None, [
   ('REPO = Path(__file__).resolve().parents[4]',
    'REPO = next(p for p in Path(__file__).resolve().parents if (p / "CNAME").is_file())')]),
 f'{CNL}/pipeline/build_agency_profiles.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('HERE.parent.parent / "legislation_implementation_tracker" / "data"', f'SITE_ROOT / "{LIT}/data"'),
   ('HERE.parent.parent / "nyc_council_fiscal_impacts_tracker" / "data"', f'SITE_ROOT / "{FIS}/data"'),
   ('HERE.parent.parent / "nyc-gov-bodies-explorer" / "index.html"', f'SITE_ROOT / "{GOV}/index.html"'),
   ('str(HERE.parent.parent.parent / "pipeline")', 'str(SITE_ROOT / "pipeline")')]),
 f'{CNL}/pipeline/build_ask_index.py': (None, [
   ('DATA_WEBSITE_ROOT = COUNCIL_TRACKERS_DIR.parent.parent',
    'DATA_WEBSITE_ROOT = next(p for p in PIPELINE_DIR.parents if (p / "CNAME").is_file())  # marker, safe across moves'),
   ('DATA_WEBSITE_ROOT / "civic_reference" / "legislation_implementation_tracker" / "data"', f'DATA_WEBSITE_ROOT / "{LIT}/data"'),
   ('DATA_WEBSITE_ROOT / "civic_reference" / "nyc_council_fiscal_impacts_tracker" / "data"', f'DATA_WEBSITE_ROOT / "{FIS}/data"')]),
 f'{CNL}/pipeline/send_alerts.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('str(HERE.parent.parent.parent / "pipeline")', 'str(SITE_ROOT / "pipeline")'),
   ('str(HERE.parents[2] / "shared")', 'str(SITE_ROOT / "shared")')]),
 f'{CNL}/quality/sample.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('REPO = HERE.parent.parent.parent  # data_website/', 'REPO = SITE_ROOT  # data_website/')]),
 f'{CNL}/quality/score_gold.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('REPO = HERE.parent.parent.parent', 'REPO = SITE_ROOT')]),
 f'{CNL}/quality/sweep_candidates.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('python3 ../../legislation_implementation_tracker/pipeline/verify_obligations.py',
    f'python3 {LIT}/pipeline/verify_obligations.py (from the repo root)'),
   ('LIT = HERE.parent.parent / "legislation_implementation_tracker"', f'LIT = SITE_ROOT / "{LIT}"')]),
 'civic_reference/nys_legislation_trackers/pipeline/agency_resolve_nys.py': (None, [
   ('(Path(__file__).resolve().parent.parent.parent / "legislation_implementation_tracker" / "data" / "agency_crosswalk.json")',
    f'(next(p for p in Path(__file__).resolve().parents if (p / "CNAME").is_file()) / "{LIT}/data/agency_crosswalk.json")')]),
 'civic_reference/nys_legislation_trackers/pipeline/api_long_windows.py': ('HERE = Path(os.path.abspath(__file__)).parent\n', [
   ('str(HERE.parent.parent.parent / "pipeline")', 'str(SITE_ROOT / "pipeline")')]),
 'civic_reference/nys_legislation_trackers/pipeline/build_site_snapshots.py': (None, [
   ('REPO = HERE.parent.parent ', 'REPO = next(p for p in HERE.parents if (p / "CNAME").is_file())')]),
 'civic_reference/nys_legislation_trackers/pipeline/extract_duties.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('COUNCIL = HERE.parent.parent / "legislation_implementation_tracker"', f'COUNCIL = SITE_ROOT / "{LIT}"')]),
 'civic_reference/nys_legislation_trackers/pipeline/validate_duties.py': ('HERE = Path(__file__).resolve().parent\n', [
   ('COUNCIL = HERE.parent.parent / "legislation_implementation_tracker" / "pipeline"', f'COUNCIL = SITE_ROOT / "{LIT}/pipeline"')]),
 'cb-tools/block-party/update_stats.py': (None, [
   ('SITE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))',
    'SITE = str(next(p for p in __import__("pathlib").Path(__file__).resolve().parents if (p / "CNAME").is_file()))'),
   ('os.path.join(SITE, "cb-tools", "block-party", "data", "stats.json")', 'os.path.join(SITE, "cb-tools/block-party/data/stats.json")')]),
 'civic_reference/nys_legislation_trackers/quality/gold_lib.py': (None, [
   ('os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "legislation_implementation_tracker", "data", "agency_crosswalk.json")',
    f'os.path.join(str(next(p for p in __import__("pathlib").Path(__file__).resolve().parents if (p / "CNAME").is_file())), "{LIT}/data/agency_crosswalk.json")')]),
}


def main():
    root = pathlib.Path.cwd()
    assert (root / 'CNAME').is_file(), 'run from the repo root'
    for rel, (anchor, pairs) in EDITS.items():
        p = root / rel
        t = p.read_text()
        for old, new in pairs:
            assert t.count(old) >= 1, f'{rel}: missing {old!r}'
            t = t.replace(old, new)
        if anchor:
            assert t.count(anchor) == 1, f'{rel}: anchor {anchor!r} x{t.count(anchor)}'
            t = t.replace(anchor, anchor + ROOT_LINE)
        p.write_text(t)
        print('ok', rel)


if __name__ == '__main__':
    main()
