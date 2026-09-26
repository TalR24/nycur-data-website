"""Tests for the opportunities radar monitor. Offline only, no network.

Run with:
  python3 -m unittest discover -s opportunity_monitor -p "test_monitor.py" -v
"""

import sys
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import monitor  # noqa: E402

TODAY = date(2026, 10, 3)  # a Saturday, day 3 <= 7 (first-Saturday window)


def make_item(**over):
    item = {
        "id": "test-item",
        "name": "Test Opportunity",
        "url": "https://example.org/test",
        "category": "conference",
        "projects": ["nycuriosity"],
        "payoffs": ["speaking", "credential"],
        "format": "remote",
        "fit": 2,
        "effort": "medium",
        "deadline": None,
        "deadline_kind": "rolling",
        "expected_month": None,
        "status": "watch",
        "verified": None,
        "source": "test",
        "added": date(2026, 9, 1),
        "notes": "Some notes.",
    }
    item.update(over)
    return item


class FilterTests(unittest.TestCase):
    def test_full_time_leave_excluded_regardless_of_status(self):
        items = [
            make_item(id="a", format="full_time_leave", status="watch"),
            make_item(id="b", format="full_time_leave", status="new"),
            make_item(id="c", format="remote", status="watch"),
        ]
        out = monitor.filter_items(items)
        self.assertEqual([i["id"] for i in out], ["c"])

    def test_skip_done_won_declined_excluded(self):
        items = [make_item(id=s, status=s) for s in
                 ["skip", "done", "won", "declined", "watch"]]
        out = monitor.filter_items(items)
        self.assertEqual([i["id"] for i in out], ["watch"])


class ScoringTests(unittest.TestCase):
    def test_scoring_formula(self):
        # fit 3, 2 payoffs, no deadline (no urgency bonus), medium effort
        item = make_item(fit=3, payoffs=["speaking", "credential"], effort="medium",
                          deadline=None)
        self.assertEqual(monitor.score_item(item, TODAY), 3 + 2 + 0 - 0)

    def test_urgency_bonus_within_21_days(self):
        item = make_item(fit=1, payoffs=[], effort="medium",
                          deadline=TODAY + monitor.timedelta(days=10))
        self.assertEqual(monitor.score_item(item, TODAY), 1 + 0 + 2 - 0)

    def test_urgency_bonus_within_45_days(self):
        item = make_item(fit=1, payoffs=[], effort="medium",
                          deadline=TODAY + monitor.timedelta(days=40))
        self.assertEqual(monitor.score_item(item, TODAY), 1 + 0 + 1 - 0)

    def test_no_urgency_bonus_past_45_days(self):
        item = make_item(fit=1, payoffs=[], effort="medium",
                          deadline=TODAY + monitor.timedelta(days=90))
        self.assertEqual(monitor.score_item(item, TODAY), 1)

    def test_high_effort_penalty(self):
        item = make_item(fit=1, payoffs=[], effort="high", deadline=None)
        self.assertEqual(monitor.score_item(item, TODAY), 1 - 1)


class SectionTests(unittest.TestCase):
    def test_pursuing_section(self):
        items = [
            make_item(id="p1", status="pursue", deadline=date(2026, 10, 20),
                      deadline_kind="set"),
            make_item(id="p2", status="drafting", deadline=None),
            make_item(id="w1", status="watch", deadline=None),
        ]
        sections, _ = monitor.build_sections(items, TODAY, [])
        self.assertEqual({i["id"] for i in sections["pursuing"]}, {"p1", "p2"})

    def test_closing45_excludes_pursuing(self):
        items = [
            make_item(id="c1", status="watch", deadline=date(2026, 10, 20),
                      deadline_kind="set"),
            make_item(id="c2", status="pursue", deadline=date(2026, 10, 15),
                      deadline_kind="set"),
            make_item(id="c3", status="watch", deadline=date(2026, 12, 1),
                      deadline_kind="set"),  # past 45 days
            make_item(id="c4", status="watch", deadline=date(2026, 9, 1),
                      deadline_kind="set"),  # already past
        ]
        sections, _ = monitor.build_sections(items, TODAY, [])
        self.assertEqual({i["id"] for i in sections["closing45"]}, {"c1"})

    def test_new_this_week_status_new_or_recently_added(self):
        items = [
            make_item(id="n1", status="new", added=date(2026, 1, 1)),
            make_item(id="n2", status="watch", added=date(2026, 9, 28)),  # 5 days ago
            make_item(id="n3", status="watch", added=date(2026, 9, 1)),   # too old
        ]
        sections, _ = monitor.build_sections(items, TODAY, [])
        self.assertEqual({i["id"] for i in sections["new_week"]}, {"n1", "n2"})

    def test_windows_opening_soon_this_or_next_month(self):
        # TODAY is October 2026: this month=10, next=11
        items = [
            make_item(id="w1", deadline_kind="expected", expected_month=10),
            make_item(id="w2", deadline_kind="expected", expected_month=11),
            make_item(id="w3", deadline_kind="expected", expected_month=1),
            make_item(id="w4", deadline_kind="rolling", expected_month=10),
        ]
        sections, _ = monitor.build_sections(items, TODAY, [])
        self.assertEqual({i["id"] for i in sections["windows"]}, {"w1", "w2"})

    def test_windows_wraps_december_to_january(self):
        dec_today = date(2026, 12, 15)
        items = [
            make_item(id="w1", deadline_kind="expected", expected_month=12),
            make_item(id="w2", deadline_kind="expected", expected_month=1),
            make_item(id="w3", deadline_kind="expected", expected_month=6),
        ]
        sections, _ = monitor.build_sections(items, dec_today, [])
        self.assertEqual({i["id"] for i in sections["windows"]}, {"w1", "w2"})

    def test_rolling_and_open_only_first_week_of_month(self):
        items = [
            make_item(id="r1", deadline_kind="rolling"),
            make_item(id="r2", deadline_kind="open"),
            make_item(id="s1", deadline_kind="set", deadline=date(2026, 12, 1)),
        ]
        first_week = date(2026, 10, 3)
        sections, _ = monitor.build_sections(items, first_week, [])
        self.assertEqual({i["id"] for i in sections["rolling_open"]}, {"r1", "r2"})

        later = date(2026, 10, 15)
        sections2, _ = monitor.build_sections(items, later, [])
        self.assertEqual(sections2["rolling_open"], [])

    def test_past_deadline_section(self):
        items = [
            make_item(id="d1", status="watch", deadline=date(2026, 9, 1),
                      deadline_kind="set"),
            make_item(id="d2", status="pursue", deadline=date(2026, 9, 1),
                      deadline_kind="set"),
            make_item(id="d3", status="submitted", deadline=date(2026, 9, 1),
                      deadline_kind="set"),
        ]
        sections, _ = monitor.build_sections(items, TODAY, [])
        self.assertEqual({i["id"] for i in sections["past_deadline"]}, {"d1"})


class PageChangeTests(unittest.TestCase):
    def test_baseline_first_fetch_not_reported_as_change(self):
        items = [make_item(id="x1", url="https://example.org/x1")]

        def fake_fetch(url):
            return (["Applications due October 1"], "live", 200, None)

        changes, failures, state = monitor.check_pages(items, {}, TODAY, False, fake_fetch)
        self.assertEqual(changes, [])
        self.assertEqual(failures, [])
        self.assertIn("x1", state)
        self.assertEqual(state["x1"]["lines"], ["Applications due October 1"])

    def test_changed_lines_reported_on_second_run(self):
        items = [make_item(id="x1", url="https://example.org/x1")]
        prior_state = {}

        def fetch_v1(url):
            return (["Applications due October 1"], "live", 200, None)

        _, _, state = monitor.check_pages(items, prior_state, TODAY, False, fetch_v1)

        def fetch_v2(url):
            return (["Applications due October 1", "Deadline extended to November 15"],
                     "live", 200, None)

        changes, failures, state2 = monitor.check_pages(items, state, TODAY, False, fetch_v2)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["id"], "x1")
        self.assertIn("Deadline extended to November 15", changes[0]["new_lines"])
        self.assertEqual(failures, [])

    def test_unchanged_hash_reports_no_change(self):
        items = [make_item(id="x1", url="https://example.org/x1")]

        def fake_fetch(url):
            return (["Applications due October 1"], "live", 200, None)

        _, _, state = monitor.check_pages(items, {}, TODAY, False, fake_fetch)
        changes, failures, state2 = monitor.check_pages(items, state, TODAY, False, fake_fetch)
        self.assertEqual(changes, [])

    def test_fetch_failure_collected_not_fatal(self):
        items = [make_item(id="x1", name="Blocked Site", url="https://example.org/x1")]

        def failing_fetch(url):
            return (None, "live", 403, "HTTP 403")

        changes, failures, state = monitor.check_pages(items, {}, TODAY, False, failing_fetch)
        self.assertEqual(changes, [])
        self.assertEqual(len(failures), 1)
        self.assertIn("Blocked Site", failures[0])

    def test_no_fetch_skips_entirely(self):
        items = [make_item(id="x1")]
        changes, failures, state = monitor.check_pages(items, {"seed": 1}, TODAY, True)
        self.assertEqual(changes, [])
        self.assertEqual(failures, [])
        self.assertEqual(state, {"seed": 1})

    def test_changed_section_appears_in_build_sections(self):
        items = [make_item(id="x1", status="watch", deadline=None)]
        page_changes = [{"id": "x1", "name": "Test Opportunity",
                          "url": "https://example.org/x1", "new_lines": ["New line"]}]
        sections, by_id_changed = monitor.build_sections(items, TODAY, page_changes)
        self.assertEqual({i["id"] for i in sections["changed"]}, {"x1"})
        self.assertEqual(by_id_changed["x1"]["new_lines"], ["New line"])


class SubjectTests(unittest.TestCase):
    def test_quiet_week(self):
        sections = {k: [] for k, _ in monitor.SECTION_TITLES}
        self.assertEqual(monitor.build_subject(sections), "Opportunities radar: quiet week")

    def test_counts_in_subject(self):
        sections = {k: [] for k, _ in monitor.SECTION_TITLES}
        sections["closing45"] = [make_item(id="c1"), make_item(id="c2")]
        sections["new_week"] = [make_item(id="n1")]
        self.assertEqual(monitor.build_subject(sections),
                         "Opportunities radar: 2 closing soon, 1 new")


class CopyRuleTests(unittest.TestCase):
    def test_no_em_dash_or_double_hyphen_in_digest(self):
        items = [
            make_item(id="a", status="pursue", deadline=date(2026, 10, 20),
                      deadline_kind="set", notes="Draft due, then submit."),
            make_item(id="b", status="new", deadline=None,
                      deadline_kind="expected", expected_month=11,
                      notes="Watch this one closely."),
        ]
        sections, by_id_changed = monitor.build_sections(items, TODAY, [])
        text = monitor.build_digest_text(sections, by_id_changed, TODAY, None, [])
        html = monitor.build_digest_html(sections, by_id_changed, TODAY, None, [])
        for blob in (text, html):
            self.assertNotIn("—", blob)
            self.assertNotIn("--", blob)


class DateNormalizationTests(unittest.TestCase):
    def test_quoted_string_dates_parsed(self):
        items = [make_item(id="a", deadline="2026-11-01", added="2026-09-20",
                            verified="2026-09-25")]
        warnings = monitor.normalize_item_dates(items)
        self.assertEqual(warnings, [])
        self.assertEqual(items[0]["deadline"], date(2026, 11, 1))
        self.assertEqual(items[0]["added"], date(2026, 9, 20))
        self.assertEqual(items[0]["verified"], date(2026, 9, 25))

    def test_datetime_string_truncated_to_date(self):
        items = [make_item(id="a", deadline="2026-11-01T14:30:00Z")]
        warnings = monitor.normalize_item_dates(items)
        self.assertEqual(warnings, [])
        self.assertEqual(items[0]["deadline"], date(2026, 11, 1))

    def test_datetime_object_dropped_to_date(self):
        import datetime as dt
        items = [make_item(id="a", deadline=dt.datetime(2026, 11, 1, 9, 0, 0))]
        warnings = monitor.normalize_item_dates(items)
        self.assertEqual(warnings, [])
        self.assertEqual(items[0]["deadline"], date(2026, 11, 1))

    def test_date_object_passes_through(self):
        items = [make_item(id="a", deadline=date(2026, 11, 1))]
        warnings = monitor.normalize_item_dates(items)
        self.assertEqual(warnings, [])
        self.assertEqual(items[0]["deadline"], date(2026, 11, 1))

    def test_unparseable_string_becomes_none_with_warning(self):
        items = [make_item(id="a", name="Bad Date Item", deadline="not-a-date")]
        warnings = monitor.normalize_item_dates(items)
        self.assertEqual(items[0]["deadline"], None)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Bad Date Item", warnings[0])
        self.assertIn("deadline", warnings[0])

    def test_none_stays_none_no_warning(self):
        items = [make_item(id="a", deadline=None)]
        warnings = monitor.normalize_item_dates(items)
        self.assertEqual(warnings, [])
        self.assertIsNone(items[0]["deadline"])


class FetchRecoveryTests(unittest.TestCase):
    def test_live_error_cleared_by_wayback_success(self):
        calls = []

        def fake_http_get(url, timeout=25):
            calls.append(url)
            if "web.archive.org" not in url:
                return None, None, "connection reset"
            return 200, "x" * 3000, None

        orig = monitor._http_get
        monitor._http_get = fake_http_get
        try:
            lines, via, code, err = monitor.default_fetch("https://example.org/p", 2026)
        finally:
            monitor._http_get = orig
        self.assertIsNone(err)
        self.assertEqual(via, "wayback")
        self.assertEqual(code, 200)

    def test_thin_live_body_with_failed_wayback_is_failure(self):
        def fake_http_get(url, timeout=25):
            if "web.archive.org" not in url:
                return 200, "too short", None
            return 404, "", None

        orig = monitor._http_get
        monitor._http_get = fake_http_get
        try:
            lines, via, code, err = monitor.default_fetch("https://example.org/p", 2026)
        finally:
            monitor._http_get = orig
        self.assertIsNone(lines)
        self.assertIsNotNone(err)

    def test_thin_body_keeps_previous_hash_in_check_pages(self):
        items = [make_item(id="x1", url="https://example.org/x1")]

        def good_fetch(url):
            return (["Applications due October 1"], "live", 200, None)

        _, _, state = monitor.check_pages(items, {}, TODAY, False, good_fetch)
        prior_entry = dict(state["x1"])

        def thin_fetch(url):
            return (None, "live", 200, "page too short")

        changes, failures, state2 = monitor.check_pages(items, state, TODAY, False, thin_fetch)
        self.assertEqual(changes, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(state2["x1"], prior_entry)

    def test_via_switch_stores_baseline_without_reporting_change(self):
        items = [make_item(id="x1", url="https://example.org/x1")]

        def live_fetch(url):
            return (["Applications due October 1"], "live", 200, None)

        _, _, state = monitor.check_pages(items, {}, TODAY, False, live_fetch)

        def wayback_fetch(url):
            return (["Deadline extended to November 15"], "wayback", 200, None)

        changes, failures, state2 = monitor.check_pages(items, state, TODAY, False, wayback_fetch)
        self.assertEqual(changes, [])
        self.assertEqual(state2["x1"]["via"], "wayback")
        self.assertEqual(state2["x1"]["lines"], ["Deadline extended to November 15"])


class MissingUrlTests(unittest.TestCase):
    def test_item_missing_url_and_check_url_skips_fetch(self):
        item = make_item(id="no-url", name="No URL Item")
        del item["url"]

        def should_not_be_called(url):
            raise AssertionError("fetch_fn should not be called for a url-less item")

        changes, failures, state = monitor.check_pages([item], {}, TODAY, False,
                                                         should_not_be_called)
        self.assertEqual(changes, [])
        self.assertEqual(len(failures), 1)
        self.assertIn("No URL Item", failures[0])
        self.assertEqual(state, {})


class ExpectedMonthValidationTests(unittest.TestCase):
    def test_out_of_range_month_treated_as_missing(self):
        item = make_item(id="a", deadline=None, deadline_kind="expected", expected_month=13)
        label, days = monitor._format_deadline(item, TODAY)
        self.assertEqual(label, "expected, month not set")

    def test_non_int_month_treated_as_missing(self):
        item = make_item(id="a", deadline=None, deadline_kind="expected", expected_month="soon")
        label, days = monitor._format_deadline(item, TODAY)
        self.assertEqual(label, "expected, month not set")

    def test_invalid_month_does_not_match_windows_section(self):
        items = [make_item(id="a", deadline_kind="expected", expected_month=13)]
        sections, _ = monitor.build_sections(items, TODAY, [])
        self.assertEqual(sections["windows"], [])


class PastDeadlineExclusionTests(unittest.TestCase):
    def test_drafting_and_submitted_excluded_alongside_pursue(self):
        items = [
            make_item(id="d1", status="watch", deadline=date(2026, 9, 1), deadline_kind="set"),
            make_item(id="d2", status="pursue", deadline=date(2026, 9, 1), deadline_kind="set"),
            make_item(id="d3", status="drafting", deadline=date(2026, 9, 1), deadline_kind="set"),
            make_item(id="d4", status="submitted", deadline=date(2026, 9, 1), deadline_kind="set"),
        ]
        sections, _ = monitor.build_sections(items, TODAY, [])
        self.assertEqual({i["id"] for i in sections["past_deadline"]}, {"d1"})


class UniqueTotalTests(unittest.TestCase):
    def test_header_counts_unique_ids_not_section_lengths(self):
        # Same item appears in both new_week and closing45.
        item = make_item(id="dual", status="new", deadline=date(2026, 10, 20),
                          deadline_kind="set", added=date(2026, 9, 30))
        items = [item]
        sections, by_id_changed = monitor.build_sections(items, TODAY, [])
        text = monitor.build_digest_text(sections, by_id_changed, TODAY, None, [])
        self.assertIn("1 item across", text)
        self.assertNotIn("2 items across", text)


class WatchingNoDateTests(unittest.TestCase):
    def test_expected_no_month_and_event_no_deadline_listed_on_first_saturday(self):
        items = [
            make_item(id="e1", deadline_kind="expected", expected_month=None, deadline=None),
            make_item(id="e2", deadline_kind="event", deadline=None),
            make_item(id="e3", deadline_kind="expected", expected_month=11, deadline=None),
        ]
        sections, _ = monitor.build_sections(items, TODAY, [])
        self.assertEqual({i["id"] for i in sections["watching_no_date"]}, {"e1", "e2"})

    def test_not_listed_outside_first_week(self):
        items = [make_item(id="e1", deadline_kind="expected", expected_month=None, deadline=None)]
        later = date(2026, 10, 15)
        sections, _ = monitor.build_sections(items, later, [])
        self.assertEqual(sections["watching_no_date"], [])

    def test_appears_under_subheading_in_text_digest(self):
        items = [make_item(id="e1", deadline_kind="expected", expected_month=None, deadline=None,
                            name="No Month Yet")]
        sections, by_id_changed = monitor.build_sections(items, TODAY, [])
        text = monitor.build_digest_text(sections, by_id_changed, TODAY, None, [])
        self.assertIn("Watching, no date yet", text)
        self.assertIn("No Month Yet", text)


class EmailFailureExitTests(unittest.TestCase):
    def test_main_returns_1_when_email_requested_but_credentials_missing(self):
        import os
        import tempfile
        import yaml as yaml_mod

        with tempfile.TemporaryDirectory() as tmp:
            watchlist_path = Path(tmp) / "watchlist.yaml"
            watchlist_path.write_text(yaml_mod.safe_dump({"items": []}))
            state_dir = Path(tmp) / "state"
            env_backup = {k: os.environ.pop(k, None) for k in
                          ("GMAIL_USER", "GMAIL_APP_PASSWORD")}
            try:
                rc = monitor.main([
                    "--watchlist", str(watchlist_path),
                    "--state-dir", str(state_dir),
                    "--today", "2026-10-03",
                    "--no-fetch", "--email",
                ])
            finally:
                for k, v in env_backup.items():
                    if v is not None:
                        os.environ[k] = v
            self.assertEqual(rc, 1)
            self.assertTrue((state_dir / "last_run.json").exists())


class LoadRobustnessTests(unittest.TestCase):
    def test_missing_id_and_string_fit_do_not_crash(self):
        items = [{"name": "No id", "fit": "2", "deadline": "2026-10-10"},
                 {"id": "b", "name": "Bad fit", "fit": "high"}]
        warnings = monitor.normalize_item_dates(items)
        self.assertEqual(items[0]["id"], "item-0")
        self.assertEqual(items[0]["fit"], 2)
        self.assertEqual(items[1]["fit"], 0)
        self.assertEqual(len(warnings), 2)
        monitor.build_sections(monitor.filter_items(items), date(2026, 10, 3), [])


if __name__ == "__main__":
    unittest.main()
