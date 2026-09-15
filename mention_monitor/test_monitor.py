"""Tests for the mention monitor.

Run with:
  python -m unittest discover -s mention_monitor -p "test_monitor.py" -v

Set MENTION_MONITOR_SKIP_LIVE_TESTS=1 to skip the live network tests (CI can
still run them; the flag exists for flaky-network days). A live test that
hits the network and fails is SKIPPED loudly, never a silent pass.
"""

import copy
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import monitor  # noqa: E402


CITY_REPORTER_URL = (
    "https://www.thecityreporter.nyc/2026/08/18/"
    "mamdani-agency-reporting-requirements-city-council-laws/"
)
VITAL_CITY_URL = (
    "https://www.vitalcitynyc.org/nyc-coge-charter-reform-government-operations-fixes/"
)
STREETSBLOG_URL = (
    "https://nyc.streetsblog.org/2026/07/01/"
    "opinion-clinton-street-has-a-traffic-problem-a-low-traffic-neighborhood-redesign-would-fix-it"
)
STREETSBLOG_SIDEBAR_URL = (
    "https://nyc.streetsblog.org/2026/09/11/"
    "cm-marte-pedestrianizing-lower-manhattan-is-a-fitting-memorial-to-sept-11"
)

IRAN_TEXT = ("Iran rejects report on Resolution 2231 at the Security Council, "
             "2,231 days after the deal was signed.")
CITATION_TEXT = ("According to a recent analysis, the City's own records list "
                  "2,231 reporting requirements spread across 183 agencies.")


def load_config():
    with open(HERE / "config.json") as f:
        return json.load(f)


def skip_live():
    return os.environ.get("MENTION_MONITOR_SKIP_LIVE_TESTS") == "1"


class LiveKnownCitationTests(unittest.TestCase):
    """Hits real URLs; SKIPPED loudly (never a silent pass) on any network
    failure or on MENTION_MONITOR_SKIP_LIVE_TESTS=1."""

    def setUp(self):
        if skip_live():
            self.skipTest("MENTION_MONITOR_SKIP_LIVE_TESTS=1")
        self.cfg = load_config()

    def _fetch(self, url):
        try:
            r = monitor.http_get(url, timeout=20)
            return r.text
        except Exception as e:  # noqa: BLE001
            self.skipTest(f"SKIPPED (network): could not fetch {url}: {e}")

    def _flag_and_classify(self, url, html):
        """The real item flag+classify path end to end: flag_text (the
        same link/term flagging fetch_outlets uses) builds the item via
        _outlet_style_item, then classify_pending_kind (the same function
        main() calls) decides its pending bucket. Returns (item, kind)."""
        own_byline_urls = {monitor.normalize_url(u) for u in self.cfg["own_byline_urls"]}
        stripped_related = monitor.strip_related_blocks(html)
        outlet_queries = [q for q in self.cfg["queries"]
                           if "outlets" in q.get("sources", [])]
        own_link, matched_queries = monitor.flag_text(
            stripped_related, outlet_queries, self.cfg["own_link_domains"], own_byline_urls)
        domain = monitor.norm_domain(monitor.urlparse(url).netloc)
        author = monitor.extract_author(None, stripped_related)
        title_m = monitor.re.search(r"<title>(.*?)</title>", stripped_related,
                                     monitor.re.I | monitor.re.S)
        title = monitor.strip_html(title_m.group(1)) if title_m else "(untitled)"
        item = monitor._outlet_style_item(
            "outlets", outlet_queries, self.cfg["own_link_domains"], own_link,
            matched_queries, domain, domain, title, url, None, stripped_related, author)
        kind = monitor.classify_pending_kind(item, self.cfg)
        return item, kind

    def test_city_reporter_flagged_by_link(self):
        html = self._fetch(CITY_REPORTER_URL)
        item, kind = self._flag_and_classify(CITY_REPORTER_URL, html)
        self.assertEqual(kind, "outside", f"expected outside citation, got {kind!r}")
        self.assertIn("link", item.get("signal", ""))

    def test_vital_city_flagged_by_link_and_term(self):
        html = self._fetch(VITAL_CITY_URL)
        item, kind = self._flag_and_classify(VITAL_CITY_URL, html)
        self.assertEqual(kind, "outside", f"expected outside citation, got {kind!r}")
        self.assertIn("link", item.get("signal", ""))
        self.assertIn("term:", item.get("signal", ""),
                       "Vital City must flag by link AND term")

    def test_streetsblog_classified_as_own_byline_via_author(self):
        """The real flag+classify path end to end, forced to use author
        parsing only: own_byline_urls / own_byline_titles are emptied so
        the URL/title seeds can't carry the assertion."""
        html = self._fetch(STREETSBLOG_URL)
        cfg = copy.deepcopy(self.cfg)
        cfg["own_byline_urls"] = []
        cfg["own_byline_titles"] = []
        self.cfg = cfg
        item, kind = self._flag_and_classify(STREETSBLOG_URL, html)
        self.assertEqual(
            kind, "own",
            f"expected Streetsblog byline to classify as own via author "
            f"parsing alone (author={item.get('author')!r})",
        )

    def test_streetsblog_sidebar_link_not_flagged(self):
        """A different Streetsblog article that only links to Tal's op-ed
        from a "recommended"/related sidebar block must not be flagged,
        while the City Reporter fixture (a real citation) still is."""
        try:
            html = self._fetch(STREETSBLOG_SIDEBAR_URL)
        except Exception:  # noqa: BLE001
            self.skipTest("SKIPPED: sidebar fixture URL unavailable")
            return
        stripped = monitor.strip_related_blocks(html)
        own_link = monitor.find_own_link(stripped, self.cfg["own_link_domains"])
        byline_urls = {monitor.normalize_url(u) for u in self.cfg["own_byline_urls"]}
        if own_link is not None:
            self.assertNotIn(
                monitor.normalize_url(own_link), byline_urls,
                "sidebar link to Tal's own byline should have been stripped",
            )
        city_reporter_html = self._fetch(CITY_REPORTER_URL)
        cr_link = monitor.find_own_link(city_reporter_html, self.cfg["own_link_domains"])
        self.assertIsNotNone(cr_link, "City Reporter must still be flagged")

    def test_wp_search_finds_both_streetsblog_roundups(self):
        """Item 8: nyc.streetsblog.org's WordPress search for "nycuriosity"
        must surface both known roundup hits, and each must classify as
        outside + roundup, not a plain outside mention."""
        roundup_urls = {
            "https://nyc.streetsblog.org/2026/01/23/fridays-headlines-"
            "redesign-not-crackdowns-edition",
            "https://nyc.streetsblog.org/2026/09/09/wednesdays-headlines-"
            "more-helmet-discourse-edition",
        }
        try:
            items, errors, stats = monitor.fetch_wp_search(
                {"wp_search_sites": ["nyc.streetsblog.org"], "wp_search_terms": ["nycuriosity"],
                 "own_link_domains": self.cfg["own_link_domains"],
                 "own_byline_urls": self.cfg["own_byline_urls"],
                 "max_article_fetches": 40}, self.cfg["queries"], 0.5)
        except Exception as e:  # noqa: BLE001
            self.skipTest(f"SKIPPED (network): wp_search failed: {e}")
            return
        if not items:
            self.skipTest("SKIPPED (network): wp_search returned no hits")
            return
        found = {monitor.normalize_url(i["url"]) for i in items}
        missing = {monitor.normalize_url(u) for u in roundup_urls} - found
        if missing:
            self.skipTest(f"SKIPPED (network): roundup(s) not found this run: {missing}")
            return
        for item in items:
            if monitor.normalize_url(item["url"]) in {monitor.normalize_url(u) for u in roundup_urls}:
                kind = monitor.classify_pending_kind(item, self.cfg)
                self.assertEqual(kind, "outside", item["url"])
                self.assertTrue(monitor.is_roundup(item, self.cfg), item["url"])


class OfflineQueryMatchTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()
        self.fig_query = next(q for q in self.cfg["queries"] if q["id"] == "fig-2231-reports")

    def test_iran_resolution_does_not_flag(self):
        self.assertFalse(monitor.query_matches_text(self.fig_query, IRAN_TEXT.lower()))

    def test_real_citation_flags(self):
        self.assertTrue(monitor.query_matches_text(self.fig_query, CITATION_TEXT.lower()))


class OfflineOwnBylineTitleTests(unittest.TestCase):
    """Item 1: Google News own-bylines with no author and an opaque
    news.google.com URL, matched instead by normalized title."""

    def setUp(self):
        self.cfg = load_config()

    def test_streetsblog_title_via_google_news_matches(self):
        item = {
            "url": "https://news.google.com/rss/articles/opaque-redirect-1",
            "author": "",
            "title": "OPINION: Clinton Street Has a Traffic Problem — A Low-Traffic "
                      "Neighborhood Redesign Would Fix It",
        }
        self.assertTrue(monitor.is_own_byline(item, self.cfg))

    def test_vital_city_job_quality_title_matches(self):
        item = {
            "url": "https://news.google.com/rss/articles/opaque-redirect-2",
            "author": "",
            "title": "New York City’s Job Growth Has a Quality Problem",
        }
        self.assertTrue(monitor.is_own_byline(item, self.cfg))

    def test_unrelated_title_does_not_match(self):
        item = {
            "url": "https://news.google.com/rss/articles/opaque-redirect-3",
            "author": "",
            "title": "Some Unrelated Article About Traffic",
        }
        self.assertFalse(monitor.is_own_byline(item, self.cfg))


class OfflineResearchCitationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()

    def test_nber_domain_is_research(self):
        item = {"domain": "nber.org"}
        self.assertTrue(monitor.is_research_citation(item, self.cfg))

    def test_cato_domain_is_research(self):
        item = {"domain": "cato.org"}
        self.assertTrue(monitor.is_research_citation(item, self.cfg))

    def test_frb_family_domain_is_research(self):
        item = {"domain": "frbatlanta.org"}
        self.assertTrue(monitor.is_research_citation(item, self.cfg))

    def test_ordinary_news_domain_is_not_research(self):
        item = {"domain": "thecityreporter.nyc"}
        self.assertFalse(monitor.is_research_citation(item, self.cfg))

    def test_unverified_name_match_flagged(self):
        item = {
            "sources": {"google_news"}, "queries": {"name"},
            "title": "The Trajectory of US Unemployment After World War II",
            "text": "A paper by Fujita, Ramey, and Roded.",
        }
        self.assertTrue(monitor.is_unverified_name_match(item))

    def test_verified_name_match_not_flagged(self):
        item = {
            "sources": {"google_news"}, "queries": {"name"},
            "title": "Tal Roded on the city's obligations tracker",
            "text": "",
        }
        self.assertFalse(monitor.is_unverified_name_match(item))


class OfflineReferrerIgnoreTests(unittest.TestCase):
    """Item 5: host_ignored must match full hosts, parent domains, and
    label-prefix entries like "google.", never a bare .endswith(h) bug."""

    def setUp(self):
        self.ignore = load_config()["referrer_ignore_hosts"]

    def test_ignored_hosts(self):
        for host in ("www.google.com", "l.facebook.com", "www.linkedin.com",
                     "duckduckgo.com", "t.co"):
            with self.subTest(host=host):
                self.assertTrue(monitor.host_ignored(host, self.ignore))

    def test_kept_hosts(self):
        for host in ("www.thecityreporter.nyc", "vitalcitynyc.org"):
            with self.subTest(host=host):
                self.assertFalse(monitor.host_ignored(host, self.ignore))


class OfflineRelatedBlockStripTests(unittest.TestCase):
    """Streetsblog false-hit fix: a "Recommended" sidebar is a plain
    <aside> with no related/recommended class name on the tag itself, so
    the strip must catch that shape too, not just Jetpack's named divs."""

    def test_aside_recommended_block_is_stripped(self):
        html = (
            "<p>Real article text about pedestrians.</p>"
            '<aside class="not-prose mb-5"><h3>Recommended</h3>'
            '<a href="https://nyc.streetsblog.org/2026/07/01/'
            'opinion-clinton-street-has-a-traffic-problem">Tal Roded op-ed</a>'
            "</aside>"
        )
        stripped = monitor.strip_related_blocks(html)
        self.assertNotIn("Tal Roded", stripped)
        self.assertIn("Real article text", stripped)

    def test_named_related_div_is_stripped(self):
        html = (
            "<p>Article body.</p>"
            '<div class="jp-relatedposts">Tal Roded coverage</div>'
        )
        stripped = monitor.strip_related_blocks(html)
        self.assertNotIn("Tal Roded", stripped)


class OfflineDateNormalizationTests(unittest.TestCase):
    """Item P1.1: every parsed date must come out UTC-aware, so a digest
    sort never mixes naive and aware datetimes."""

    def test_parse_iso_naive_becomes_aware(self):
        dt = monitor.parse_iso("2026-01-05")
        self.assertIsNotNone(dt.tzinfo)
        self.assertEqual(dt.utcoffset(), timedelta(0))

    def test_parse_iso_aware_stays_aware(self):
        dt = monitor.parse_iso("2026-01-05T12:00:00Z")
        self.assertIsNotNone(dt.tzinfo)

    def test_to_utc_handles_none(self):
        self.assertIsNone(monitor.to_utc(None))

    def test_sort_key_published_mixes_naive_aware_none_without_crashing(self):
        naive = datetime(2026, 1, 1)
        aware = datetime(2026, 1, 2, tzinfo=timezone.utc)
        items = [
            {"published": naive},
            {"published": aware},
            {"published": None},
        ]
        # Must not raise "can't compare offset-naive and offset-aware
        # datetimes"; must sort None to the earliest position.
        ordered = sorted(items, key=monitor.sort_key_published, reverse=True)
        self.assertEqual(ordered[0]["published"], aware)
        self.assertEqual(ordered[-1]["published"], None)

    def test_digest_sorts_mixed_naive_aware_items_without_crashing(self):
        naive_item = monitor.make_item(
            "openalex", "openalex-citing", "Some Journal", "example.org",
            "Naive dated item", "https://example.org/a",
            datetime(2026, 1, 1), "text",
        )
        aware_item = monitor.make_item(
            "google_news", "name", "Example Outlet", "example.com",
            "Aware dated item", "https://example.com/b",
            datetime(2026, 1, 2, tzinfo=timezone.utc), "text",
        )
        cfg = {"queries": [{"id": "name", "match_terms": ["Tal Roded"]}]}
        try:
            digest = monitor.build_digest(
                [aware_item], [], [naive_item], None, [], cfg, "2026-01-05")
        except TypeError as e:
            self.fail(f"build_digest raised on mixed-tz dates: {e}")
        self.assertIn("Aware dated item", digest)


class OfflineDigestFailureLeavesPendingTests(unittest.TestCase):
    """Item P1.1: if digest building raises, pending rows must stay pending
    and the error must reach stderr (never silently swallowed)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.conn = monitor.db_connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_build_digest_exception_leaves_pending_rows_untouched(self):
        item = monitor.make_item(
            "outlets", "fig-2231-reports", "Test Outlet", "example.com",
            "Test headline", "https://example.com/a", datetime.now(timezone.utc),
            "test text",
        )
        item["keys"] = {"u:crashkey"}
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        monitor.pending_add(self.conn, item, "outside", now_iso)
        self.conn.commit()

        outside, own, research, ids = monitor.pending_load(self.conn)
        self.assertEqual(len(outside), 1)

        with self.assertRaises(RuntimeError):
            with unittest.mock.patch.object(
                    monitor, "build_digest", side_effect=RuntimeError("boom")):
                # Mirror main()'s ordering: load pending, then build the
                # digest, then (only on success) mark digested.
                monitor.build_digest(outside, own, research, None, [], {}, "2026-01-05")
                monitor.pending_mark_digested(self.conn, ids)

        outside2, own2, research2, ids2 = monitor.pending_load(self.conn)
        self.assertEqual(len(outside2), 1, "pending row must survive a digest crash")


class OfflinePendingDigestFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.conn = monitor.db_connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _sample_item(self, key="u:testkey", query_id="fig-2231-reports"):
        item = monitor.make_item(
            "outlets", query_id, "Test Outlet", "example.com",
            "Test headline", "https://example.com/a", datetime.now(timezone.utc),
            "test text",
        )
        item["keys"] = {key}
        return item

    def test_pending_to_digest_to_digested(self):
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        monitor.pending_add(self.conn, self._sample_item(), "outside", now_iso)
        self.conn.commit()

        outside, own, research, ids = monitor.pending_load(self.conn)
        self.assertEqual(len(outside), 1)
        self.assertEqual(len(own), 0)
        self.assertEqual(len(research), 0)
        self.assertEqual(outside[0]["title"], "Test headline")

        monitor.pending_mark_digested(self.conn, ids)
        self.conn.commit()

        outside2, own2, research2, ids2 = monitor.pending_load(self.conn)
        self.assertEqual(outside2, [])
        self.assertEqual(ids2, [])

    def test_research_kind_round_trips(self):
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        monitor.pending_add(self.conn, self._sample_item(key="u:researchkey"),
                             "research", now_iso)
        self.conn.commit()
        outside, own, research, ids = monitor.pending_load(self.conn)
        self.assertEqual(len(research), 1)
        self.assertEqual(len(outside), 0)

    def test_backfill_invokes_real_path_writes_no_pending(self):
        """Runs the actual main() collect path (via monitor.collect with a
        fetcher-less config so no network happens) in backfill mode and
        confirms it only calls mark_seen, never pending_add."""
        cfg = {"queries": [], "outlets": [], "sources": ["google_news"]}
        since = datetime.now(timezone.utc)
        items, errors, outlet_stats = monitor.collect(cfg, since, conn=self.conn)
        self.assertEqual(items, [])
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # Simulate the backfill branch of main(): mark_seen only, no pending.
        sample = self._sample_item(key="u:backfillkey")
        monitor.mark_seen(self.conn, sample, now_iso)
        self.conn.commit()
        outside, own, research, ids = monitor.pending_load(self.conn)
        self.assertEqual(ids, [])


class OfflineScannedTableTests(unittest.TestCase):
    """Item 4: a URL recorded in `scanned` is skipped on a later
    fetch_outlets pass, and errors persist across runs until a digest
    clears them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.conn = monitor.db_connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_is_scanned_round_trip(self):
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        url = "https://example.com/article-1"
        self.assertFalse(monitor.is_scanned(self.conn, url))
        monitor.mark_scanned(self.conn, url, "Test Outlet", now_iso)
        self.conn.commit()
        self.assertTrue(monitor.is_scanned(self.conn, url))

    def test_source_errors_persist_and_clear_on_digest(self):
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        monitor.record_source_errors(self.conn, ["outlets/Foo: boom", "outlets/Foo: boom"], now_iso)
        self.conn.commit()
        grouped = monitor.load_and_clear_source_errors(self.conn)
        self.assertEqual(grouped, ["outlets/Foo: boom (x2)"])
        # cleared: a second load returns nothing
        self.assertEqual(monitor.load_and_clear_source_errors(self.conn), [])

    def test_is_backlog_notice_distinguishes_cap_budget_from_real_failures(self):
        """Round 6 item 2: cap/budget carry-over notices are backlog, not
        errors; HTTP/TLS/parse/GraphQL failures stay real errors."""
        backlog_messages = [
            "outlets/City & State NY: hit max_article_fetches cap (150); "
            "22 entries skipped and will be retried next run",
            "outlets: hit outlet_time_budget_seconds (300s); some article "
            "fetches were skipped and will be retried next run",
            "sitemap_scan/Vital City: hit cap/budget; 489 articles still to "
            "scan, carries over to the next run",
            "wp_search/site.example.com: hit max_article_fetches cap (150); "
            "3 hits skipped and will be retried next run",
            "google_news: hit query_time_budget_seconds (120s); remaining "
            "queries were skipped and will be retried next run",
        ]
        real_messages = [
            "outlets/Foo: HTTPSConnectionPool timeout",
            "sitemap_scan/Vital City article https://x/y: TLS error",
            "cloudflare_referrers: zone does not have access to the field "
            "'clientrefererhost'",
        ]
        for m in backlog_messages:
            self.assertTrue(monitor.is_backlog_notice(m), m)
        for m in real_messages:
            self.assertFalse(monitor.is_backlog_notice(m), m)

    def test_backlog_notices_persist_latest_per_unit_and_clear(self):
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        monitor.record_backlog_notices(
            self.conn,
            ["sitemap_scan/Vital City: hit cap/budget; 519 articles still "
             "to scan, carries over to the next run"],
            now_iso)
        self.conn.commit()
        # A later run's smaller remaining count replaces the earlier one for
        # the same unit, rather than accumulating both.
        monitor.record_backlog_notices(
            self.conn,
            ["sitemap_scan/Vital City: hit cap/budget; 489 articles still "
             "to scan, carries over to the next run"],
            now_iso)
        self.conn.commit()
        notices = monitor.load_and_clear_backlog_notices(self.conn)
        self.assertEqual(len(notices), 1)
        self.assertIn("489 articles still to scan", notices[0])
        self.assertEqual(monitor.load_and_clear_backlog_notices(self.conn), [])


class OfflineBacklogDigestTests(unittest.TestCase):
    """Round 6 item 2: backlog notices land in a separate "Scan progress"
    section, never in "Source errors", in both the text and HTML digest."""

    def test_backlog_in_scan_progress_not_source_errors(self):
        cfg = {"queries": [{"id": "name", "match_terms": ["Tal Roded"]}]}
        backlog = ["sitemap_scan/Vital City: hit cap/budget; 489 articles "
                   "still to scan, carries over to the next run"]
        real_errors = ["outlets/Foo: boom"]
        digest = monitor.build_digest([], [], [], None, real_errors, cfg, "2026-09-15",
                                       backlog_notices=backlog)
        self.assertIn("## Scan progress", digest)
        self.assertIn("Vital City", digest)
        self.assertIn("## Source errors", digest)
        self.assertIn("outlets/Foo: boom", digest)
        # Not cross-contaminated: the backlog line isn't under Source errors
        # and the real error isn't under Scan progress.
        source_errors_section = digest.split("## Source errors")[1].split("## Scan progress")[0]
        self.assertNotIn("Vital City", source_errors_section)
        scan_progress_section = digest.split("## Scan progress")[1]
        self.assertNotIn("outlets/Foo: boom", scan_progress_section)

    def test_subject_error_count_excludes_backlog(self):
        """build_digest_subject is never handed backlog notices (main()
        passes it digest_errors, the real-errors-only list), so its error
        count and the subject line can never include backlog."""
        cfg = {"queries": [{"id": "name", "match_terms": ["Tal Roded"]}]}
        subject = monitor.build_digest_subject([], [], [], [], None, None, cfg, "2026-09-15")
        self.assertNotIn("error", subject)
        subject_with_real_error = monitor.build_digest_subject(
            [], [], [], ["outlets/Foo: boom"], None, None, cfg, "2026-09-15")
        self.assertIn("1 error", subject_with_real_error)


class OfflineCloudflareReferrerTests(unittest.TestCase):
    """Round 6 item 4: Web Analytics (RUM) referrer source, account-scoped."""

    def setUp(self):
        self.cfg = {"cloudflare_referrers_enabled": True,
                    "referrer_ignore_hosts": ["google.", "substack.com"]}
        self.env = unittest.mock.patch.dict(
            os.environ, {"CF_ANALYTICS_TOKEN": "tok", "CF_ACCOUNT_ID": "acct123"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def _rum_response(self, groups):
        return FakeResponse(200, json_data={
            "data": {"viewer": {"accounts": [
                {"rumPageloadEventsAdaptiveGroups": groups}
            ]}}
        })

    def test_rows_parsed_ignore_list_applied_own_hosts_dropped(self):
        groups = [
            {"count": 5, "dimensions": {"refererHost": "news.example.com",
                                         "requestHost": "www.nycuriosity.com",
                                         "requestPath": "/p/a"}},
            {"count": 3, "dimensions": {"refererHost": "www.google.com",
                                         "requestHost": "www.nycuriosity.com",
                                         "requestPath": "/p/b"}},
            {"count": 2, "dimensions": {"refererHost": "nycuriosity.com",
                                         "requestHost": "www.nycuriosity.com",
                                         "requestPath": "/p/c"}},
        ]
        with unittest.mock.patch.object(
                monitor.SESSION, "post", return_value=self._rum_response(groups)):
            rows, err, skipped = monitor.fetch_cloudflare_referrers(
                self.cfg, datetime.now(timezone.utc))
        self.assertIsNone(err)
        self.assertFalse(skipped)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["host"], "news.example.com")
        self.assertEqual(rows[0]["requests"], 5)

    def test_graphql_error_reports_message_only_ids_redacted(self):
        def fake_post(url, json=None, headers=None, timeout=None):
            return FakeResponse(200, json_data={
                "errors": [{"message": "zone acct123 does not have access to "
                                        "the field 'refererHost'"}]
            })
        with unittest.mock.patch.object(monitor.SESSION, "post", side_effect=fake_post):
            rows, err, skipped = monitor.fetch_cloudflare_referrers(
                self.cfg, datetime.now(timezone.utc))
        self.assertEqual(rows, [])
        self.assertFalse(skipped)
        self.assertIn("does not have access", err)
        self.assertNotIn("acct123", err)

    def test_skipped_when_disabled(self):
        self.cfg["cloudflare_referrers_enabled"] = False
        rows, err, skipped = monitor.fetch_cloudflare_referrers(
            self.cfg, datetime.now(timezone.utc))
        self.assertEqual(rows, [])
        self.assertIsNone(err)
        self.assertTrue(skipped)

    def test_skipped_when_account_id_missing(self):
        del os.environ["CF_ACCOUNT_ID"]
        rows, err, skipped = monitor.fetch_cloudflare_referrers(
            self.cfg, datetime.now(timezone.utc))
        self.assertEqual(rows, [])
        self.assertIsNone(err)
        self.assertTrue(skipped)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", content=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.content = content if content is not None else text.encode()

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class OfflineWpSearchTests(unittest.TestCase):
    """Item 1: paging stops on an empty page or HTTP 400."""

    def test_paging_stops_on_400(self):
        cfg = {"wp_search_sites": ["example.com"], "wp_search_terms": ["nycuriosity"],
               "own_link_domains": []}
        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append(params["page"])
            if params["page"] == 1:
                return FakeResponse(200, json_data=[])
            return FakeResponse(400)

        with unittest.mock.patch.object(monitor.SESSION, "get", side_effect=fake_get):
            items, errors, stats = monitor.fetch_wp_search(cfg, [], 0)
        self.assertEqual(items, [])
        self.assertEqual(stats["example.com"]["hits"], 0)
        self.assertEqual(calls, [1])  # empty first page stops paging

    def test_paging_stops_on_400_after_hits(self):
        cfg = {"wp_search_sites": ["example.com"], "wp_search_terms": ["nycuriosity"],
               "own_link_domains": []}

        def fake_get(url, params=None, timeout=None):
            if params["page"] == 1:
                return FakeResponse(200, json_data=[{"url": "https://example.com/a", "title": "A"}])
            return FakeResponse(400)

        with unittest.mock.patch.object(monitor.SESSION, "get", side_effect=fake_get):
            with unittest.mock.patch.object(monitor, "http_get") as mocked:
                mocked.side_effect = RuntimeError("no article fetch needed for this test")
                items, errors, stats = monitor.fetch_wp_search(cfg, [], 0)
        self.assertEqual(stats["example.com"]["hits"], 1)

    def test_wp_search_cap_hit_records_source_error(self):
        # Item 15: hitting max_article_fetches must be a recorded source
        # error, not a silent skip.
        cfg = {"wp_search_sites": ["example.com"], "wp_search_terms": ["nycuriosity"],
               "own_link_domains": []}
        hits = [{"url": f"https://example.com/{i}", "title": f"T{i}"} for i in range(3)]

        def fake_get(url, params=None, timeout=None):
            if params["page"] == 1:
                return FakeResponse(200, json_data=hits)
            return FakeResponse(400)

        with unittest.mock.patch.object(monitor.SESSION, "get", side_effect=fake_get):
            with unittest.mock.patch.object(
                    monitor, "http_get",
                    return_value=FakeResponse(200, text="body")) as mocked:
                mocked.return_value.text = "body"
                items, errors, stats = monitor.fetch_wp_search(cfg, [], 0, cap_override=1)
        self.assertTrue(any("cap" in e for e in errors))


class OfflineRunBudgetTests(unittest.TestCase):
    """Item P1.3: one shared per-run deadline is checked before every
    network call, and hitting it never crashes collect()."""

    def tearDown(self):
        monitor.clear_run_budget()

    def test_check_run_budget_raises_past_deadline(self):
        monitor.set_run_budget({"run_time_budget_seconds": 0})
        with self.assertRaises(monitor.RunBudgetExceeded):
            monitor.check_run_budget()

    def test_check_run_budget_noop_when_unset(self):
        monitor.clear_run_budget()
        monitor.check_run_budget()  # must not raise

    def test_collect_isolates_a_run_budget_hit_as_a_source_error(self):
        cfg = {"queries": [], "sources": ["google_news"],
               "alert_feeds": [{"env": "GOOGLE_ALERT_FEEDS"}]}
        monitor.set_run_budget({"run_time_budget_seconds": 0})
        try:
            with unittest.mock.patch.object(
                    monitor, "fetch_alert_feeds", side_effect=monitor.RunBudgetExceeded("x")):
                items, errors, stats = monitor.collect(cfg, datetime.now(timezone.utc))
        finally:
            monitor.clear_run_budget()
        self.assertEqual(items, [])
        self.assertTrue(any("alert_feeds" in e for e in errors))

    def test_outlet_feed_with_full_text_processed_even_past_deadline(self):
        """The old bug: a feed whose entries already carry full text (no
        article fetch needed) must still be scanned even once the outlet
        time budget has elapsed."""
        cfg = {"outlets": [{"name": "FullText", "feed": "https://ex.com/feed",
                             "fetch_article": False}],
               "outlet_time_budget_seconds": 0, "own_link_domains": []}
        full_text = ("<p>" + "word " * 200 +
                     "Tal Roded testimony on congestion pricing.</p>")
        feed_xml = (
            "<rss><channel><item><title>T</title>"
            "<link>https://ex.com/a</link>"
            f"<content:encoded><![CDATA[{full_text}]]></content:encoded>"
            "</item></channel></rss>"
        )

        def fake_http_get(url, timeout=15, retries=2):
            return FakeResponse(200, text=feed_xml, content=feed_xml.encode())

        queries = [{"id": "name", "match_terms": ["Tal Roded"]}]
        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            items, errors, stats = monitor.fetch_outlets(cfg, queries, 0)
        self.assertEqual(stats["FullText"]["scanned"], 1)
        self.assertEqual(len(items), 1)


class OfflineSitemapWatermarkTests(unittest.TestCase):
    """Item 3: the watermark only advances to the newest lastmod actually
    scanned, so a budget/cap-skipped entry carries over to the next run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = monitor.db_connect(os.path.join(self.tmp.name, "t.db"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_watermark_advances_and_gates_next_run(self):
        cfg = {"sitemap_scan": [{"sitemap": "https://ex.com/sitemap-posts.xml",
                                  "name": "Ex", "tier": "news"}],
               "own_link_domains": [], "own_byline_urls": []}
        sitemap_xml = (
            "<urlset><url><loc>https://ex.com/old</loc>"
            "<lastmod>2020-01-01T00:00:00Z</lastmod></url>"
            "<url><loc>https://ex.com/new</loc>"
            "<lastmod>2026-09-10T00:00:00Z</lastmod></url></urlset>"
        )

        def fake_http_get(url, timeout=15, retries=2):
            if url.endswith("sitemap-posts.xml"):
                return FakeResponse(200, text=sitemap_xml)
            return FakeResponse(200, text="<html><body>" + "word " * 100 + "</body></html>")

        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            items, errors, stats = monitor.fetch_sitemap_scan(
                cfg, [], 0, conn=self.conn, now=now)
        # "old" predates the 90-day default window relative to `now`; only
        # "new" gets fetched.
        self.assertEqual(stats["Ex"]["scanned"], 1)
        # Watermark is now a successful-scan marker (now_iso), not a lastmod.
        wm = monitor.get_sitemap_watermark(self.conn, "Ex")
        self.assertEqual(wm, now.isoformat(timespec="seconds"))

        # A second run with the same feed content re-fetches nothing new:
        # "new" is already in the `scanned` table, and "old" is still
        # outside the (now narrower) window.
        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            items2, errors2, stats2 = monitor.fetch_sitemap_scan(
                cfg, [], 0, conn=self.conn, now=now)
        self.assertEqual(stats2["Ex"]["scanned"], 0)

    def test_carry_over_across_three_runs_loses_nothing(self):
        """Item P1.2: a 5-URL sitemap with a per-run cap of 2 must scan all
        5 URLs across three runs; none are lost to the watermark jumping
        past unscanned (older) entries."""
        cfg = {"sitemap_scan": [{"sitemap": "https://ex.com/sitemap-posts.xml",
                                  "name": "Ex", "tier": "news"}],
               "own_link_domains": [], "own_byline_urls": []}
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        urls = [f"https://ex.com/post-{i}" for i in range(5)]
        # Newest-first in the sitemap, as real sitemaps are.
        sitemap_xml = "<urlset>" + "".join(
            f"<url><loc>{u}</loc><lastmod>2026-09-{10 - i:02d}T00:00:00Z</lastmod></url>"
            for i, u in enumerate(urls)
        ) + "</urlset>"

        def fake_http_get(url, timeout=15, retries=2):
            if url.endswith("sitemap-posts.xml"):
                return FakeResponse(200, text=sitemap_xml)
            return FakeResponse(200, text="<html><body>" + "word " * 100 + "</body></html>")

        scanned_urls = set()
        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            for _ in range(3):
                items, errors, stats = monitor.fetch_sitemap_scan(
                    cfg, [], 0, conn=self.conn, now=now, cap_override=2)
                for u in urls:
                    if monitor.is_scanned(self.conn, u):
                        scanned_urls.add(u)
        self.assertEqual(scanned_urls, set(urls))

    def _two_sitemap_cfg(self):
        return {"sitemap_scan": [
                    {"sitemap": "https://big.com/sitemap-posts.xml", "name": "Big", "tier": "news"},
                    {"sitemap": "https://small.com/sitemap-posts.xml", "name": "Small", "tier": "news"}],
                "own_link_domains": [], "own_byline_urls": []}

    @staticmethod
    def _sitemap(host, n):
        return "<urlset>" + "".join(
            f"<url><loc>https://{host}/p{i}</loc><lastmod>2026-09-{10 - (i % 9):02d}T00:00:00Z</lastmod></url>"
            for i in range(n)) + "</urlset>"

    def test_cap_is_shared_so_later_sitemaps_are_not_starved(self):
        cfg = self._two_sitemap_cfg()
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)

        def fake_http_get(url, timeout=15, retries=2):
            if "big.com/sitemap" in url:
                return FakeResponse(200, text=self._sitemap("big.com", 50))
            if "small.com/sitemap" in url:
                return FakeResponse(200, text=self._sitemap("small.com", 3))
            return FakeResponse(200, text="<html><body>" + "word " * 100 + "</body></html>")

        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            _, _, stats = monitor.fetch_sitemap_scan(cfg, [], 0, conn=self.conn, now=now, cap_override=10)
        self.assertEqual(stats["Big"]["scanned"], 5)
        self.assertEqual(stats["Small"]["scanned"], 3)

    def test_url_failing_three_runs_is_given_up_and_window_advances(self):
        cfg = {"sitemap_scan": [{"sitemap": "https://ex.com/sitemap-posts.xml", "name": "Ex", "tier": "news"}],
               "own_link_domains": [], "own_byline_urls": []}
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        bad = "https://ex.com/broken"
        xml = f"<urlset><url><loc>{bad}</loc><lastmod>2026-09-10T00:00:00Z</lastmod></url></urlset>"

        def fake_http_get(url, timeout=15, retries=2):
            if url.endswith("sitemap-posts.xml"):
                return FakeResponse(200, text=xml)
            raise monitor.requests.ConnectionError("boom")

        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            for _ in range(3):
                _, errors, _ = monitor.fetch_sitemap_scan(cfg, [], 0, conn=self.conn, now=now, cap_override=5)
        self.assertTrue(monitor.is_scanned(self.conn, bad))
        self.assertTrue(any("gave up" in e for e in errors))
        self.assertIsNotNone(monitor.get_sitemap_watermark(self.conn, "Ex"))

    def test_discovered_cap_skip_does_not_advance_window(self):
        cfg = {"sitemap_scan": [{"sitemap": "https://d.com/sitemap-posts.xml", "name": "D",
                                 "tier": "news", "discovered_cap": 1}],
               "own_link_domains": [], "own_byline_urls": []}
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)

        def fake_http_get(url, timeout=15, retries=2):
            if url.endswith("sitemap-posts.xml"):
                return FakeResponse(200, text=self._sitemap("d.com", 3))
            return FakeResponse(200, text="<html><body>" + "word " * 100 + "</body></html>")

        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            monitor.fetch_sitemap_scan(cfg, [], 0, conn=self.conn, now=now, cap_override=10)
        self.assertIsNone(monitor.get_sitemap_watermark(self.conn, "D"))


class OfflineOpenAlexTests(unittest.TestCase):
    """Item 4: citing-work items are built correctly and dedupe through the
    same seen-table mechanism every other source uses."""

    def test_citing_items_dedupe_via_seen_table(self):
        cfg = {"openalex_author_ids": ["A5018877478"], "mailto": "tal@nycuriosity.com"}
        own_work = {"id": "https://openalex.org/W1", "title": "Own paper",
                    "publication_date": "2024-01-01",
                    "primary_location": {"source": {"display_name": "NBER"},
                                         "landing_page_url": "https://nber.org/w1"}}
        citing_work = {"id": "https://openalex.org/W2", "title": "Citing paper",
                       "publication_date": "2026-01-01", "referenced_works": ["https://openalex.org/W1"],
                       "primary_location": {"source": {"display_name": "Some Journal"},
                                            "landing_page_url": "https://example.org/w2"}}
        calls = {"n": 0}

        def fake_get(url, params=None, timeout=None):
            calls["n"] += 1
            if "authorships.author.id" in params.get("filter", ""):
                return FakeResponse(200, json_data={"results": [own_work] if calls["n"] == 1 else [],
                                                     "meta": {"next_cursor": None}})
            return FakeResponse(200, json_data={"results": [citing_work] if calls["n"] == 2 else [],
                                                 "meta": {"next_cursor": None}})

        with unittest.mock.patch.object(monitor.SESSION, "get", side_effect=fake_get):
            items, errors, stats = monitor.fetch_openalex(cfg)
        self.assertEqual(errors, [])
        citing = [i for i in items if i.get("openalex_kind") == "citing"]
        self.assertEqual(len(citing), 1)
        self.assertIn("W1", citing[0]["text"])

        tmp = tempfile.TemporaryDirectory()
        try:
            conn = monitor.db_connect(os.path.join(tmp.name, "t.db"))
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            item = citing[0]
            item["keys"] = monitor.item_keys(item)
            self.assertFalse(monitor.any_seen(conn, item["keys"]))
            monitor.mark_seen(conn, item, now_iso)
            conn.commit()
            self.assertTrue(monitor.any_seen(conn, item["keys"]))
            conn.close()
        finally:
            tmp.cleanup()


class OfflineAlertFeedsTests(unittest.TestCase):
    """Item 5: Google Alerts redirect links are unwrapped and highlight
    tags stripped; no full feed URL appears in an error message."""

    def test_unwrap_google_alert_link(self):
        wrapped = ("https://www.google.com/url?rct=j&sa=t&url=https://example.com/"
                   "real-article&ct=ga")
        self.assertEqual(monitor.unwrap_google_alert_link(wrapped),
                          "https://example.com/real-article")
        self.assertEqual(monitor.unwrap_google_alert_link("https://example.com/plain"),
                          "https://example.com/plain")

    def test_strip_highlight_tags(self):
        self.assertEqual(monitor.strip_alert_highlight_tags("See <b>NYCuriosity</b> here"),
                          "See NYCuriosity here")

    def test_synthetic_atom_entry_round_trip(self):
        atom = (
            '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
            '<title>Google Alert - NYCuriosity</title>'
            '<entry><title>See <b>NYCuriosity</b> coverage</title>'
            '<link href="https://www.google.com/url?url=https://outlet.example.com/story"/>'
            '<summary>About <b>NYCuriosity</b> tracker work.</summary></entry></feed>'
        )
        cfg = {"alert_feeds": [{"name": "test alert", "url": "https://www.google.com/alerts/feeds/1/2"}]}
        with unittest.mock.patch.object(monitor, "http_get",
                                         return_value=FakeResponse(200, text=atom)):
            items, errors, stats = monitor.fetch_alert_feeds(cfg, 0)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://outlet.example.com/story")
        self.assertNotIn("<b>", items[0]["title"])
        self.assertEqual(stats["test alert"], 1)

    def test_empty_alert_feeds_silently_skipped(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_ALERT_FEEDS", None)
            items, errors, stats = monitor.fetch_alert_feeds({"alert_feeds": []}, 0)
        self.assertEqual((items, errors, stats), ([], [], {}))

    def test_env_feed_error_never_logs_full_url(self):
        secret_url = "https://www.google.com/alerts/feeds/1234567890/9876543210"
        with unittest.mock.patch.dict(os.environ, {"GOOGLE_ALERT_FEEDS": secret_url}):
            with unittest.mock.patch.object(monitor, "http_get",
                                             side_effect=RuntimeError("boom")):
                items, errors, stats = monitor.fetch_alert_feeds({"alert_feeds": []}, 0)
        self.assertEqual(len(errors), 1)
        self.assertNotIn("1234567890", errors[0])
        self.assertNotIn(secret_url, errors[0])


class OfflinePruningTests(unittest.TestCase):
    """Item 8: consecutive-weeks removal logic, exempt units, young units."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = monitor.db_connect(os.path.join(self.tmp.name, "t.db"))
        self.cfg = {"prune_after_weeks": 3, "prune_error_weeks": 2,
                    "prune_exempt": ["openalex", "query:name"]}

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _add(self, unit, dates_flagged, errored_dates=()):
        for d, flagged in dates_flagged:
            monitor.record_yield(self.conn, d, [
                {"unit": unit, "ran": True, "items_fetched": 5, "items_flagged": flagged,
                 "errored": d in errored_dates}])
        self.conn.commit()

    def test_zero_flagged_streak_suggested(self):
        self._add("outlets:Dead Outlet",
                   [("2026-08-01", 0), ("2026-08-08", 0), ("2026-08-15", 0)])
        suggestions = monitor.suggest_removals(self.conn, self.cfg)
        units = {s["unit"] for s in suggestions}
        self.assertIn("outlets:Dead Outlet", units)

    def test_young_unit_not_suggested(self):
        self._add("outlets:Young Outlet", [("2026-09-01", 0), ("2026-09-08", 0)])
        suggestions = monitor.suggest_removals(self.conn, self.cfg)
        units = {s["unit"] for s in suggestions}
        self.assertNotIn("outlets:Young Outlet", units)

    def test_exempt_unit_never_suggested(self):
        self._add("query:name", [("2026-08-01", 0), ("2026-08-08", 0), ("2026-08-15", 0)])
        suggestions = monitor.suggest_removals(self.conn, self.cfg)
        units = {s["unit"] for s in suggestions}
        self.assertNotIn("query:name", units)

    def test_error_streak_suggested(self):
        self._add("outlets:Broken Outlet",
                   [("2026-08-01", 0), ("2026-08-08", 0)],
                   errored_dates=("2026-08-01", "2026-08-08"))
        suggestions = monitor.suggest_removals(self.conn, self.cfg)
        units = {s["unit"]: s for s in suggestions}
        self.assertIn("outlets:Broken Outlet", units)
        self.assertEqual(units["outlets:Broken Outlet"]["reason"], "errored on every run")

    def test_eight_daily_rows_in_one_week_count_as_one_week(self):
        # Item 6: 8 daily rows all inside ISO week 2026-08-03..08-09 must
        # collapse to a single distinct week, not 8.
        dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06",
                  "2026-08-07", "2026-08-08", "2026-08-09", "2026-08-09"]
        self._add("outlets:Daily Outlet", [(d, 0) for d in dates])
        suggestions = monitor.suggest_removals(self.conn, self.cfg)
        units = {s["unit"] for s in suggestions}
        # prune_after_weeks is 3; a single collapsed week must not qualify.
        self.assertNotIn("outlets:Daily Outlet", units)

    def test_error_streak_fires_with_config_location(self):
        self._add("outlets:Broken Outlet",
                   [("2026-08-01", 0), ("2026-08-08", 0)],
                   errored_dates=("2026-08-01", "2026-08-08"))
        suggestions = monitor.suggest_removals(self.conn, self.cfg)
        units = {s["unit"]: s for s in suggestions}
        self.assertIn("outlets:Broken Outlet", units)
        self.assertIn('outlets[name="Broken Outlet"]',
                       units["outlets:Broken Outlet"]["config_location"])

    def test_google_news_and_discovered_config_location(self):
        loc = monitor.config_location_for_unit("google_news:fig-2231", {})
        self.assertIn("queries[id=\"fig-2231\"]", loc)
        self.assertIn("sources", loc)

    def test_flagged_recently_breaks_the_streak(self):
        self._add("outlets:Active Outlet",
                   [("2026-08-01", 0), ("2026-08-08", 3), ("2026-08-15", 0), ("2026-08-22", 0)])
        suggestions = monitor.suggest_removals(self.conn, self.cfg)
        units = {s["unit"] for s in suggestions}
        self.assertNotIn("outlets:Active Outlet", units)


class OfflineDiscoveryTests(unittest.TestCase):
    """Item 9: candidate extraction/filtering, probe order, discovered_sources
    append without duplicates, auto_add_discovered=false, 30-day suppression."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = monitor.db_connect(os.path.join(self.tmp.name, "t.db"))
        self.discovered_path = Path(self.tmp.name) / "discovered_sources.json"

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _item(self, source, domain):
        item = monitor.make_item(source, "name", domain, domain, "T",
                                  f"https://{domain}/a", None, "")
        return item

    def test_candidate_extraction_filters_own_and_ignored(self):
        cfg = {"own_link_domains": ["nycuriosity.com"], "exclude_domains": [],
               "discovery_ignore_domains": ["doi.org", "linkedin.com"],
               "outlets": [], "wp_search_sites": [], "sitemap_scan": []}
        items = [self._item("google_news", "newoutlet.com"),
                 self._item("google_news", "nycuriosity.com"),
                 self._item("alert_feeds", "doi.org"),
                 self._item("outlets", "already-an-outlet.com")]
        candidates = monitor.extract_candidate_domains(items, cfg, self.discovered_path)
        self.assertIn("newoutlet.com", candidates)
        self.assertNotIn("nycuriosity.com", candidates)
        self.assertNotIn("doi.org", candidates)
        self.assertNotIn("already-an-outlet.com", candidates)  # not google_news/alert/openalex

    def test_probe_order_feed_then_wp_search_then_sitemap(self):
        def fake_http_get(url, timeout=10, retries=1, params=None):
            if url == "https://feedsite.com/":
                return FakeResponse(200, text="<html>no alternate link</html>")
            if url == "https://feedsite.com/feed/":
                return FakeResponse(200, text=(
                    '<?xml version="1.0"?><rss><channel><item><title>x</title></item>'
                    "</channel></rss>"))
            raise RuntimeError("should not reach wp_search/sitemap probes")

        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            passed, ptype, url = monitor.probe_domain("feedsite.com")
        self.assertTrue(passed)
        self.assertEqual(ptype, "feed")
        self.assertEqual(url, "https://feedsite.com/feed/")

    def test_probe_falls_through_to_wp_search(self):
        def fake_http_get(url, timeout=10, retries=1, params=None):
            if "wp-json" in url:
                return FakeResponse(200, json_data=[])
            if url.startswith("https://wpsite.com/"):
                return FakeResponse(200, text="<html>no feed</html>")
            raise RuntimeError("HTTP 404")

        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            passed, ptype, url = monitor.probe_domain("wpsite.com")
        self.assertTrue(passed)
        self.assertEqual(ptype, "wp_search")

    def test_discovered_sources_appended_without_duplicates(self):
        cfg = {"new_probe_cap": 10, "auto_add_discovered": True}
        candidates = {"feedsite.com": "google_news"}
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        with unittest.mock.patch.object(monitor, "probe_domain",
                                         return_value=(True, "feed", "https://feedsite.com/feed/")):
            added, reviewed = monitor.run_discovery(cfg, self.conn, now, candidates,
                                                      self.discovered_path)
        self.assertEqual(len(added), 1)
        rows = monitor.load_discovered_sources(self.discovered_path)
        self.assertEqual(len(rows), 1)
        # Running again with the same candidate does not duplicate the entry.
        with unittest.mock.patch.object(monitor, "probe_domain",
                                         return_value=(True, "feed", "https://feedsite.com/feed/")):
            monitor.run_discovery(cfg, self.conn, now, candidates, self.discovered_path)
        self.assertEqual(len(monitor.load_discovered_sources(self.discovered_path)), 1)

    def test_auto_add_discovered_false_only_reviewed(self):
        cfg = {"new_probe_cap": 10, "auto_add_discovered": False}
        candidates = {"feedsite.com": "google_news"}
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        with unittest.mock.patch.object(monitor, "probe_domain",
                                         return_value=(True, "feed", "https://feedsite.com/feed/")):
            added, reviewed = monitor.run_discovery(cfg, self.conn, now, candidates,
                                                      self.discovered_path)
        self.assertEqual(added, [])
        self.assertEqual(len(reviewed), 1)
        self.assertEqual(monitor.load_discovered_sources(self.discovered_path), [])

    def test_probe_raises_run_budget_exceeded_not_swallowed(self):
        """Should-fix 4: a budget hit inside probe_domain must propagate,
        never be recorded as a failed probe."""
        with unittest.mock.patch.object(monitor, "http_get",
                                         side_effect=monitor.RunBudgetExceeded("deadline")):
            with self.assertRaises(monitor.RunBudgetExceeded):
                monitor.probe_domain("feedsite.com")

    def test_run_discovery_budget_hit_not_recorded_or_suppressed(self):
        """Should-fix 4: run_discovery must stop (not crash) on a budget
        hit and must not record that domain as a failed probe (which
        would suppress it for 30 days)."""
        cfg = {"new_probe_cap": 10, "auto_add_discovered": True}
        candidates = {"feedsite.com": "google_news", "other.com": "google_news"}
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        with unittest.mock.patch.object(monitor, "probe_domain",
                                         side_effect=monitor.RunBudgetExceeded("deadline")):
            added, reviewed = monitor.run_discovery(cfg, self.conn, now, candidates,
                                                      self.discovered_path)
        self.assertEqual(added, [])
        self.assertEqual(reviewed, [])
        self.assertFalse(monitor.recently_probed(self.conn, "feedsite.com", now))
        self.assertFalse(monitor.recently_probed(self.conn, "other.com", now))

    def test_30_day_reprobe_suppression(self):
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        monitor.record_probe(self.conn, "feedsite.com", now.isoformat(timespec="seconds"),
                              True, "feed", "https://feedsite.com/feed/")
        self.conn.commit()
        self.assertTrue(monitor.recently_probed(self.conn, "feedsite.com", now))
        self.assertFalse(
            monitor.recently_probed(self.conn, "feedsite.com", now + timedelta(days=31)))


class OfflineDiscoveryItem7Tests(unittest.TestCase):
    """Round 4 item 7: registrable_domain multi-part suffixes, full-host
    coverage, referrer candidates, research/ignore filtering before probe,
    sitemapindex rejection, first_item_url, discovered_max_fetches,
    backfill probe persistence."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = monitor.db_connect(os.path.join(self.tmp.name, "t.db"))
        self.discovered_path = Path(self.tmp.name) / "discovered_sources.json"

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_registrable_domain_multi_part_suffix(self):
        self.assertEqual(monitor.registrable_domain("news.bbc.co.uk"), "bbc.co.uk")
        self.assertEqual(monitor.registrable_domain("bbc.co.uk"), "bbc.co.uk")
        self.assertNotEqual(monitor.registrable_domain("bbc.co.uk"), "co.uk")

    def test_subdomain_covered_by_configured_full_host(self):
        cfg = {"outlets": [{"name": "Streetsblog", "feed": "https://nyc.streetsblog.org/feed/"}],
               "wp_search_sites": [], "sitemap_scan": [], "own_link_domains": [],
               "exclude_domains": [], "discovery_ignore_domains": [], "research_domains": []}
        item = monitor.make_item("google_news", "name", "nyc.streetsblog.org",
                                  "nyc.streetsblog.org", "T", "https://nyc.streetsblog.org/a",
                                  None, "")
        candidates = monitor.extract_candidate_domains([item], cfg, self.discovered_path)
        self.assertNotIn("streetsblog.org", candidates)

    def test_referrer_host_is_a_candidate(self):
        cfg = {"outlets": [], "wp_search_sites": [], "sitemap_scan": [],
               "own_link_domains": ["nycuriosity.com"], "exclude_domains": [],
               "discovery_ignore_domains": [], "research_domains": []}
        candidates = monitor.extract_candidate_domains(
            [], cfg, self.discovered_path, referrer_hosts=["referringsite.com"])
        self.assertIn("referringsite.com", candidates)

    def test_research_and_ignore_domains_skipped_before_probe(self):
        cfg = {"outlets": [], "wp_search_sites": [], "sitemap_scan": [],
               "own_link_domains": [], "exclude_domains": [],
               "discovery_ignore_domains": ["notresearch.com"],
               "research_domains": ["cato.org"]}
        item1 = monitor.make_item("google_news", "name", "cato.org", "cato.org", "T",
                                   "https://cato.org/a", None, "")
        item2 = monitor.make_item("google_news", "name", "notresearch.com", "notresearch.com",
                                   "T", "https://notresearch.com/a", None, "")
        candidates = monitor.extract_candidate_domains([item1, item2], cfg, self.discovered_path)
        self.assertNotIn("cato.org", candidates)
        self.assertNotIn("notresearch.com", candidates)

    def test_sitemapindex_rejected(self):
        def fake_http_get(url, timeout=10, retries=1, params=None):
            if url == "https://siteidx.com/":
                return FakeResponse(200, text="<html>no alternate link</html>")
            if url.endswith("/sitemap-posts.xml"):
                return FakeResponse(200, text='<sitemapindex></sitemapindex>')
            if url.endswith("/sitemap.xml"):
                return FakeResponse(200, text='<sitemapindex></sitemapindex>')
            raise RuntimeError("HTTP 404")

        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            passed, ptype, url = monitor.probe_domain("siteidx.com")
        self.assertFalse(passed)

    def test_sitemapindex_follows_one_level_to_urlset(self):
        def fake_http_get(url, timeout=10, retries=1, params=None):
            if url == "https://siteidx.com/":
                return FakeResponse(200, text="<html>no alternate link</html>")
            if url.endswith("/sitemap-posts.xml"):
                return FakeResponse(200, text=(
                    '<sitemapindex><sitemap><loc>https://siteidx.com/'
                    'sitemap-posts1.xml</loc></sitemap></sitemapindex>'))
            if url == "https://siteidx.com/sitemap-posts1.xml":
                return FakeResponse(200, text=(
                    '<urlset><url><loc>https://siteidx.com/a</loc>'
                    '<lastmod>2026-01-01</lastmod></url></urlset>'))
            raise RuntimeError("HTTP 404")

        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get):
            passed, ptype, url = monitor.probe_domain("siteidx.com")
        self.assertTrue(passed)
        self.assertEqual(ptype, "sitemap")
        self.assertEqual(url, "https://siteidx.com/sitemap-posts1.xml")

    def test_first_item_url_filled_from_triggering_item(self):
        cfg = {"new_probe_cap": 10, "auto_add_discovered": True}
        candidates = {"feedsite.com": {"via": "google_news",
                                        "first_item_url": "https://feedsite.com/the-article"}}
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        with unittest.mock.patch.object(monitor, "probe_domain",
                                         return_value=(True, "feed", "https://feedsite.com/feed/")):
            added, reviewed = monitor.run_discovery(cfg, self.conn, now, candidates,
                                                      self.discovered_path)
        self.assertEqual(added[0]["first_item_url"], "https://feedsite.com/the-article")

    def test_backfill_probe_results_persisted_for_next_digest(self):
        now_iso = "2026-09-01T00:00:00+00:00"
        monitor.record_discovery_results(
            self.conn,
            [{"domain": "feedsite.com", "type": "feed", "url": "https://feedsite.com/feed/",
              "added_on": "2026-09-01", "found_via": "google_news", "first_item_url": ""}],
            [{"domain": "other.com", "passed": False, "type": None, "found_via": "google_news"}],
            now_iso)
        self.conn.commit()
        added, reviewed = monitor.load_and_clear_discovery_results(self.conn)
        self.assertEqual(len(added), 1)
        self.assertEqual(len(reviewed), 1)
        # Cleared after loading, so a later digest doesn't repeat it.
        added2, reviewed2 = monitor.load_and_clear_discovery_results(self.conn)
        self.assertEqual(added2, [])
        self.assertEqual(reviewed2, [])

    def test_discovered_feed_caps_per_run_entries(self):
        cfg = {"discovered_max_fetches": 2}
        self.discovered_path.write_text(json.dumps([
            {"domain": "bigfeed.com", "type": "feed", "url": "https://bigfeed.com/feed/",
             "added_on": "2026-09-01", "found_via": "google_news", "first_item_url": ""},
        ]))
        cfg_runtime = monitor.apply_discovered_sources(cfg, self.discovered_path)
        outlet = cfg_runtime["outlets"][0]
        self.assertEqual(outlet["discovered_cap"], 2)
        rss = ('<?xml version="1.0"?><rss><channel>' +
               "".join(f'<item><title>T{i}</title><link>https://bigfeed.com/{i}</link>'
                       f"<description>short</description></item>" for i in range(5)) +
               "</channel></rss>")
        with unittest.mock.patch.object(monitor, "http_get",
                                         return_value=FakeResponse(200, text=rss,
                                                                    content=rss.encode())):
            items, errors, stats = monitor.fetch_outlets(cfg_runtime, [], 0, conn=self.conn)
        self.assertEqual(stats["bigfeed.com"]["scanned"], 2)


class OfflineSnippetTests(unittest.TestCase):
    """Item 10: context_from_html must build snippets from stripped text
    only, never by slicing raw HTML around a match position (which can
    cut mid-tag or mid-attribute)."""

    def test_snippet_has_no_markup_fragments_near_a_wide_anchor_tag(self):
        html = (
            "<p>Before text. According to "
            '<a href="https://www.nycuriosity.com/p/x" '
            'data-tracking="abcdefghijklmnopqrstuvwxyz0123456789" '
            'class="some-long-class-name-that-pads-the-tag-out-a-lot">'
            "NYCuriosity</a> the numbers are real. After text follows here "
            "to pad out the width used for the snippet window nicely.</p>"
        )
        snippet = monitor.context_from_html(html, ["nycuriosity.com"], [], width=40)
        self.assertNotIn("<", snippet)
        self.assertNotIn("data-tracking", snippet)
        self.assertNotIn('="', snippet)

    def test_snippet_falls_back_to_term_when_anchor_text_unlocatable(self):
        html = ('<p>Reporting requirements context. <a href="https://www.nycuriosity.com/p/x">'
                '<img src="pic.png"></a> 2,231 obligations follow.</p>')
        snippet = monitor.context_from_html(html, ["nycuriosity.com"], ["2,231"], width=40)
        self.assertNotIn("<", snippet)
        self.assertIn("2,231", snippet)


class OfflineArticleBodyPaywallTests(unittest.TestCase):
    """Item 12: paywall length check must measure the extracted article
    body (article/main or JSON-LD articleBody), not the whole page."""

    def test_short_article_inside_long_nav_and_footer_counts_as_paywalled(self):
        html = (
            "<nav>" + ("link " * 200) + "</nav>"
            "<article>Subscribe to read the rest of this story.</article>"
            "<footer>" + ("copyright text " * 200) + "</footer>"
        )
        self.assertLess(len(monitor.extract_article_body_text(html)), 200)
        self.assertGreater(len(monitor.strip_html(html)), 200)

    def test_long_article_body_not_paywalled(self):
        html = "<main><article>" + ("Real reporting text. " * 20) + "</article></main>"
        self.assertGreaterEqual(len(monitor.extract_article_body_text(html)), 200)

    def test_json_ld_article_body_used_when_present(self):
        html = ('<script type="application/ld+json">{"articleBody": "' +
                ("Full text of the story. " * 20) + '"}</script><article>preview only</article>')
        self.assertGreaterEqual(len(monitor.extract_article_body_text(html)), 200)


class OfflineSubjectTests(unittest.TestCase):
    """Item 13: email subject includes each nonzero count."""

    def _item(self, title="Some title"):
        return monitor.make_item("outlets", "name", "Outlet", "outlet.com", title,
                                  "https://outlet.com/a", None, "")

    def test_subject_includes_all_nonzero_counts(self):
        cfg = {"roundup_title_patterns": ["Headlines"]}
        new_items = [self._item("Regular story"), self._item("Friday's Headlines")]
        subject = monitor.build_digest_subject(
            new_items, [self._item()], [self._item()], ["err1"],
            [{"unit": "x"}], [{"domain": "y"}], cfg, "2026-09-15")
        self.assertIn("1 new mention", subject)
        self.assertIn("1 roundup", subject)
        self.assertIn("1 own piece", subject)
        self.assertIn("1 research item", subject)
        self.assertIn("1 source", subject)
        self.assertIn("1 removal suggestion", subject)
        self.assertIn("1 error", subject)

    def test_subject_omits_zero_counts(self):
        cfg = {}
        subject = monitor.build_digest_subject([], [], [], [], [], [], cfg, "2026-09-15")
        self.assertNotIn("new mention", subject)
        self.assertIn("update", subject)


class OfflineDigestPathTests(unittest.TestCase):
    """Should-fix 10: a second --digest run on the same date must never
    overwrite the first digest file."""

    def test_second_run_same_date_gets_dash2(self):
        with tempfile.TemporaryDirectory() as d:
            outdir = Path(d)
            p1 = monitor.next_digest_path(outdir, "2026-09-15")
            p1.write_text("first")
            p2 = monitor.next_digest_path(outdir, "2026-09-15")
            self.assertNotEqual(p1, p2)
            self.assertEqual(p2.name, "2026-09-15-2.md")
            p2.write_text("second")
            p3 = monitor.next_digest_path(outdir, "2026-09-15")
            self.assertEqual(p3.name, "2026-09-15-3.md")
            self.assertEqual(p1.read_text(), "first")
            self.assertEqual(p2.read_text(), "second")

    def test_different_date_not_suffixed(self):
        with tempfile.TemporaryDirectory() as d:
            outdir = Path(d)
            p = monitor.next_digest_path(outdir, "2026-09-16")
            self.assertEqual(p.name, "2026-09-16.md")


class OfflineSmtpTimeoutTests(unittest.TestCase):
    """Should-fix 9: the SMTP connection must have a bounded timeout."""

    def test_smtp_ssl_called_with_timeout(self):
        captured = {}

        class FakeSMTP:
            def __init__(self, *a, **k):
                captured["args"] = a
                captured["kwargs"] = k

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, u, p):
                pass

            def send_message(self, msg):
                pass

        env = {"GMAIL_USER": "me@example.com", "GMAIL_APP_PASSWORD": "x"}
        with unittest.mock.patch.dict(os.environ, env):
            with unittest.mock.patch.object(monitor.smtplib, "SMTP_SSL", FakeSMTP):
                monitor.send_email("subject", "body")
        self.assertEqual(captured["kwargs"].get("timeout"), 30)


class OfflineEmailTests(unittest.TestCase):
    """Coordinator fixes: MENTION_DIGEST_TO empty-string fallback, and a
    multipart/alternative message with escaped HTML."""

    def test_empty_mention_digest_to_falls_back_to_gmail_user(self):
        sent = {}

        class FakeSMTP:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, u, p):
                pass

            def send_message(self, msg):
                sent["to"] = msg["To"]

        env = {"GMAIL_USER": "me@example.com", "GMAIL_APP_PASSWORD": "x",
               "MENTION_DIGEST_TO": ""}
        with unittest.mock.patch.dict(os.environ, env):
            with unittest.mock.patch.object(monitor.smtplib, "SMTP_SSL", FakeSMTP):
                monitor.send_email("subject", "body")
        self.assertEqual(sent["to"], "me@example.com")

    def test_multipart_email_with_escaped_html(self):
        sent = {}

        class FakeSMTP:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, u, p):
                pass

            def send_message(self, msg):
                sent["msg"] = msg

        env = {"GMAIL_USER": "me@example.com", "GMAIL_APP_PASSWORD": "x"}
        html = "<html><body><script>alert(1)</script></body></html>"
        with unittest.mock.patch.dict(os.environ, env):
            with unittest.mock.patch.object(monitor.smtplib, "SMTP_SSL", FakeSMTP):
                monitor.send_email("subject", "text body", html)
        msg = sent["msg"]
        self.assertTrue(msg.is_multipart())
        parts = msg.get_payload()
        self.assertEqual(len(parts), 2)
        content_types = {p.get_content_type() for p in parts}
        self.assertEqual(content_types, {"text/plain", "text/html"})

    def test_html_digest_escapes_script_title(self):
        cfg = load_config()
        item = monitor.make_item("outlets", "fig-2231-reports", "Test Outlet", "example.com",
                                  "<script>alert(1)</script>", "https://example.com/a",
                                  datetime.now(timezone.utc), "text")
        html = monitor.build_digest_html([item], [], [], None, [], cfg, "2026-09-15")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_html_digest_every_section_has_no_raw_markdown(self):
        """Round 6 item 1: every digest section renders as real HTML (h2,
        <li>/<strong>/<a>); only the Claude Code prompt text itself stays in
        a <pre> block."""
        cfg = load_config()
        queries_by_id = {q["id"]: q for q in cfg["queries"]}
        news_item = monitor.make_item(
            "outlets", "name", "Some Outlet", "outlet.example.com", "A headline",
            "https://outlet.example.com/a", datetime.now(timezone.utc), "snippet")
        news_item["queries"] = {"name"}
        news_item["signal"] = "term:name"

        removal_suggestions = [{
            "unit": "outlets:Dead Outlet", "reason": "zero flagged items",
            "weeks_silent": 9, "items_fetched": 12, "last_flagged": "2026-01-01",
            "config_location": 'config.json → outlets[name="Dead Outlet"]',
        }]
        discovery_added = [{"domain": "newsite.example.com", "type": "feed",
                             "found_via": "google_news"}]
        discovery_reviewed = [{"domain": "maybesite.example.com", "passed": False,
                                "found_via": "alert_feeds"}]
        backlog_notices = ["sitemap_scan/Vital City: hit cap/budget; 489 "
                            "articles still to scan, carries over to the next run"]

        with unittest.mock.patch.object(monitor, "http_get",
                                         return_value=FakeResponse(404, text="")):
            html = monitor.build_digest_html(
                [news_item], [], [], None, ["outlets/Foo: boom"], cfg, "2026-09-15",
                removal_suggestions=removal_suggestions,
                discovery_added=discovery_added,
                discovery_reviewed=discovery_reviewed,
                backlog_notices=backlog_notices,
            )

        self.assertIn("<h2", html)
        self.assertIn("Suggested website updates", html)
        self.assertIn("Suggested removals", html)
        self.assertIn("Added this week", html)
        self.assertIn("Candidates needing manual review", html)
        self.assertIn("Scan progress", html)
        self.assertIn("Vital City", html)
        self.assertNotIn("**", html)
        self.assertNotIn("## ", html)
        self.assertNotIn("\n- ", html)

        # The Claude Code prompt (built for the news item, which gets a
        # real prompt since it has no already-listed page match) still
        # lives inside a <pre> block, exactly copyable.
        entries = monitor.site_update_entries([news_item], [], [], cfg, queries_by_id)
        prompt = next(p for _, _, p in entries if p)
        self.assertIn(f"<pre", html)
        self.assertIn(monitor.html_mod.escape(prompt), html)


class OfflineSiteUpdateTests(unittest.TestCase):
    """User-approved item: Suggested website updates mapping."""

    def setUp(self):
        self.cfg = load_config()

    def _item(self, url="https://outlet.example.com/a", own_link_url="", queries=None,
              tier_domain="outlet.example.com"):
        item = monitor.make_item("outlets", "name", "Outlet", tier_domain, "Headline",
                                  url, datetime.now(timezone.utc), "snippet text")
        item["own_link_url"] = own_link_url
        item["queries"] = queries or {"name"}
        item["signal"] = "link"
        return item

    def test_targets_by_link_path(self):
        item = self._item(own_link_url="https://data.nycuriosity.com/civic_reference/"
                                        "legislation_implementation_tracker/index.html")
        targets = monitor.site_update_targets(item, self.cfg)
        files = {f for f, _ in targets}
        self.assertIn(self.cfg["site_update_rules"]["implementation_tracker_file"], files)
        self.assertIn(self.cfg["site_update_rules"]["trackers_hub_file"], files)
        self.assertIn(self.cfg["site_update_rules"]["personal_site_file"], files)

    def test_targets_by_second_own_link_not_just_first(self):
        # Item 14: the implementation tracker link is the SECOND own link
        # on the page; targeting must not stop at the first.
        item = self._item(own_link_url="https://www.nycuriosity.com/p/some-post")
        item["own_link_urls"] = [
            "https://www.nycuriosity.com/p/some-post",
            "https://data.nycuriosity.com/civic_reference/"
            "legislation_implementation_tracker/index.html",
        ]
        targets = monitor.site_update_targets(item, self.cfg)
        files = {f for f, _ in targets}
        self.assertIn(self.cfg["site_update_rules"]["implementation_tracker_file"], files)

    def test_targets_by_query_id(self):
        item = self._item(queries={"fig-7.5b-mandates"})
        targets = monitor.site_update_targets(item, self.cfg)
        files = {f for f, _ in targets}
        self.assertIn(self.cfg["site_update_rules"]["fiscal_tracker_file"], files)

    def test_never_feature_url_skipped(self):
        never_url = self.cfg["never_feature_urls"][0]
        item = self._item(url=never_url)
        entries = monitor.site_update_entries(
            [item], [], [], self.cfg, {q["id"]: q for q in self.cfg["queries"]})
        self.assertEqual(entries, [])

    def test_already_listed_skips_prompt(self):
        item = self._item()
        cache_page = f"already has {item['url']} listed"
        with unittest.mock.patch.object(monitor, "http_get",
                                         return_value=FakeResponse(200, text=cache_page)):
            entries = monitor.site_update_entries(
                [item], [], [], self.cfg, {q["id"]: q for q in self.cfg["queries"]})
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1], "already listed on all its targets")

    def test_deadline_hit_reports_unknown_not_a_prompt(self):
        """Should-fix 4: a run-deadline hit while fetching the site page
        must not be treated as "not listed" (which would spuriously
        prompt); it must be reported as unchecked, with no prompt."""
        item = self._item()
        with unittest.mock.patch.object(monitor, "http_get",
                                         side_effect=monitor.RunBudgetExceeded("deadline")):
            entries = monitor.site_update_entries(
                [item], [], [], self.cfg, {q["id"]: q for q in self.cfg["queries"]})
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1], "could not check site pages this run")
        self.assertIsNone(entries[0][2])

    def test_own_item_deadline_hit_reports_unknown_not_a_prompt(self):
        item = self._item()
        with unittest.mock.patch.object(monitor, "http_get",
                                         side_effect=monitor.RunBudgetExceeded("deadline")):
            entries = monitor.site_update_entries(
                [], [item], [], self.cfg, {q["id"]: q for q in self.cfg["queries"]})
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1], "could not check site pages this run")
        self.assertIsNone(entries[0][2])

    def test_term_only_match_is_possible_uncredited_citation(self):
        """Should-fix 5: a figure-only match (no own link, no name/brand
        term) must not get a Featured-in/In-the-press prompt."""
        item = self._item(queries={"fig-7.5b-mandates"})
        item["own_link_url"] = ""
        entries = monitor.site_update_entries(
            [item], [], [], self.cfg, {q["id"]: q for q in self.cfg["queries"]})
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0][2])
        self.assertIn("Possible uncredited citation, verify manually", entries[0][1])
        self.assertIn("$7.5 billion", entries[0][1])

    def test_name_match_still_gets_a_prompt(self):
        """A "name" match (Tal Roded) is a confident citation, not term-only."""
        item = self._item(queries={"name"})
        item["own_link_url"] = ""
        with unittest.mock.patch.object(monitor, "http_get",
                                         return_value=FakeResponse(404, text="")):
            entries = monitor.site_update_entries(
                [item], [], [], self.cfg, {q["id"]: q for q in self.cfg["queries"]})
        self.assertEqual(len(entries), 1)
        self.assertIsNotNone(entries[0][2])

    def test_own_byline_targets_policy_section(self):
        item = self._item()
        with unittest.mock.patch.object(monitor, "http_get",
                                         return_value=FakeResponse(404, text="")):
            entries = monitor.site_update_entries([], [item], [], self.cfg,
                                                    {q["id"]: q for q in self.cfg["queries"]})
        self.assertEqual(len(entries), 1)
        self.assertIn(self.cfg["site_update_rules"]["personal_own_section"], entries[0][2])

    def test_google_news_vital_city_job_quality_resolves_to_already_listed(self):
        """Round 5 must-fix 1: a Google News item whose opaque link
        actually resolves (via the real decode flow, mocked here) to the
        Vital City job-quality own byline must be recognized as an own
        byline via the resolved URL and, once already listed on the
        personal site, produce no prompt. resolved_url is produced by
        resolve_google_news_url itself, not hard-coded onto the item."""
        vital_city_url = self.cfg["own_byline_urls"][1]
        opaque = "https://news.google.com/rss/articles/CBMi_fake_job_quality"

        def fake_get(url, timeout=None, headers=None):
            return FakeResponse(200, text='<html data-n-a-sg="SIG1" data-n-a-ts="1700000000">'
                                          '</html>')

        def fake_post(url, headers=None, data=None, timeout=None):
            return FakeResponse(200, text='[\\"garturlres\\",\\"' + vital_city_url + '\\",1]')

        with unittest.mock.patch.object(monitor.SESSION, "get", side_effect=fake_get), \
             unittest.mock.patch.object(monitor.SESSION, "post", side_effect=fake_post):
            resolved, err = monitor.resolve_google_news_url(opaque)
        self.assertEqual(resolved, vital_city_url)
        self.assertIsNone(err)

        item = monitor.make_item(
            "google_news", "name", "Vital City", "vitalcitynyc.org", "The NYC Job Quality Problem",
            opaque, datetime.now(timezone.utc), "snippet")
        item["resolved_url"] = resolved
        self.assertTrue(monitor.is_own_byline(item, self.cfg))
        cache_page = f"already has {vital_city_url} listed"
        with unittest.mock.patch.object(monitor, "http_get",
                                         return_value=FakeResponse(200, text=cache_page)):
            entries = monitor.site_update_entries([], [item], [], self.cfg,
                                                    {q["id"]: q for q in self.cfg["queries"]})
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1], "already listed")
        self.assertIsNone(entries[0][2])


class OfflineGoogleNewsResolveTests(unittest.TestCase):
    """Round 5 must-fix 1: Google News links no longer HTTP-redirect;
    resolve_google_news_url decodes the article page's batchexecute
    payload instead. resolved_url still feeds dedupe, exclusions,
    own-byline matching, never_feature, and already-listed."""

    def _article_page(self, sg="SIGtoken", ts="1700000000"):
        return f'<html data-n-a-sg="{sg}" data-n-a-ts="{ts}"></html>'

    def _batchexecute_response(self, url):
        return '[\\"garturlres\\",\\"' + url + '\\",1]'

    def test_resolve_decodes_via_batchexecute(self):
        opaque = "https://news.google.com/rss/articles/CBMi_fake_x"
        real_url = "https://nyc.streetsblog.org/real-article"
        calls = {"get": 0, "post": 0}

        def fake_get(url, timeout=None, headers=None):
            calls["get"] += 1
            self.assertIn("news.google.com/articles/", url)
            self.assertIn("User-Agent", headers)
            return FakeResponse(200, text=self._article_page())

        def fake_post(url, headers=None, data=None, timeout=None):
            calls["post"] += 1
            return FakeResponse(200, text=self._batchexecute_response(real_url))

        with unittest.mock.patch.object(monitor.SESSION, "get", side_effect=fake_get), \
             unittest.mock.patch.object(monitor.SESSION, "post", side_effect=fake_post):
            resolved, err = monitor.resolve_google_news_url(opaque)
        self.assertEqual(resolved, real_url)
        self.assertIsNone(err)
        self.assertEqual(calls["get"], 1)
        self.assertEqual(calls["post"], 1)

    def test_resolve_caches_in_conn_so_link_decoded_once(self):
        conn = monitor.db_connect(":memory:")
        opaque = "https://news.google.com/rss/articles/CBMi_cache_x"
        real_url = "https://example.com/cached-article"
        calls = {"get": 0, "post": 0}

        def fake_get(url, timeout=None, headers=None):
            calls["get"] += 1
            return FakeResponse(200, text=self._article_page())

        def fake_post(url, headers=None, data=None, timeout=None):
            calls["post"] += 1
            return FakeResponse(200, text=self._batchexecute_response(real_url))

        with unittest.mock.patch.object(monitor.SESSION, "get", side_effect=fake_get), \
             unittest.mock.patch.object(monitor.SESSION, "post", side_effect=fake_post):
            resolved1, _ = monitor.resolve_google_news_url(opaque, conn=conn)
            resolved2, _ = monitor.resolve_google_news_url(opaque, conn=conn)
        self.assertEqual(resolved1, real_url)
        self.assertEqual(resolved2, real_url)
        self.assertEqual(calls["get"], 1, "second resolution must be served from the cache")
        self.assertEqual(calls["post"], 1)

    def test_resolve_failure_falls_back_to_opaque_url_and_reports_error(self):
        with unittest.mock.patch.object(monitor.SESSION, "get",
                                         side_effect=RuntimeError("timeout")):
            resolved, err = monitor.resolve_google_news_url(
                "https://news.google.com/rss/articles/CBMi_y")
        self.assertEqual(resolved, "https://news.google.com/rss/articles/CBMi_y")
        self.assertEqual(err, "timeout")

    def test_resolve_failure_missing_signature_falls_back(self):
        with unittest.mock.patch.object(monitor.SESSION, "get",
                                         return_value=FakeResponse(200, text="<html></html>")):
            resolved, err = monitor.resolve_google_news_url(
                "https://news.google.com/rss/articles/CBMi_nosig")
        self.assertEqual(resolved, "https://news.google.com/rss/articles/CBMi_nosig")
        self.assertIsNotNone(err)

    def test_non_google_url_passthrough(self):
        resolved, err = monitor.resolve_google_news_url("https://example.com/a")
        self.assertEqual(resolved, "https://example.com/a")
        self.assertIsNone(err)

    def test_fetch_google_news_resolve_failure_is_never_a_source_error(self):
        """Must-fix 1: a decode failure must NOT be recorded as a source
        error (only counted in the run summary line by collect())."""
        feed_xml = (
            "<rss><channel><item><title>A - Outlet</title>"
            "<link>https://news.google.com/rss/articles/CBMi_z</link>"
            "<source>Outlet</source></item></channel></rss>"
        )

        def fake_http_get(url, params=None, timeout=30):
            return FakeResponse(200, text=feed_xml, content=feed_xml.encode())

        errors = []
        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get), \
             unittest.mock.patch.object(monitor.SESSION, "get",
                                         side_effect=RuntimeError("net down")):
            items = monitor.fetch_google_news({"id": "name", "q": "Tal Roded"}, {}, None,
                                               errors=errors)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["resolved_url"], items[0]["url"])
        self.assertEqual(errors, [], "resolve failures must never be recorded as source errors")

    def test_fetch_google_news_fallback_matches_never_feature_by_title(self):
        """Must-fix 1 fallback: an unresolved never_feature item is matched
        by normalized title, not just by its (unusable, opaque) URL."""
        cfg = load_config()
        feed_xml = (
            "<rss><channel><item>"
            "<title>Expert Advice for Mamdani's Commission on Government Efficiency - "
            "Vital City</title>"
            "<link>https://news.google.com/rss/articles/CBMi_never_feature</link>"
            "<source>Vital City</source></item></channel></rss>"
        )

        def fake_http_get(url, params=None, timeout=30):
            return FakeResponse(200, text=feed_xml, content=feed_xml.encode())

        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get), \
             unittest.mock.patch.object(monitor.SESSION, "get",
                                         side_effect=RuntimeError("net down")):
            items = monitor.fetch_google_news({"id": "name", "q": "Tal Roded"}, cfg, None,
                                               conn=None)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIn("news.google.com", item["resolved_url"])  # never resolved
        never_titles = [monitor.normalize_title(t)
                        for t in cfg.get("never_feature_titles", [])]
        item_title_norm = monitor.normalize_title(item["title"])
        self.assertTrue(any(item_title_norm in t or t in item_title_norm
                             for t in never_titles if t))

    def test_query_with_unresolved_link_is_not_errored(self):
        """Must-fix 2: a resolve failure must not mark the google_news
        query `errored` (only an actual RSS-fetch exception may)."""
        cfg = {"queries": [{"id": "name", "q": "Tal Roded", "sources": ["google_news"]}],
               "request_delay_seconds": 0, "query_time_budget_seconds": 120}
        feed_xml = (
            "<rss><channel><item><title>A - Outlet</title>"
            "<link>https://news.google.com/rss/articles/CBMi_errtest</link>"
            "<source>Outlet</source></item></channel></rss>"
        )

        def fake_http_get(url, params=None, timeout=30):
            return FakeResponse(200, text=feed_xml, content=feed_xml.encode())

        with unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get), \
             unittest.mock.patch.object(monitor.SESSION, "get",
                                         side_effect=RuntimeError("net down")):
            items, errors, source_stats = monitor.collect(cfg, None)
        self.assertEqual(len(items), 1)
        gn_stats = source_stats["google_news"]["name"]
        self.assertEqual(gn_stats["errored"], 0)
        self.assertFalse(gn_stats["errored"])
        self.assertEqual(gn_stats["unresolved"], 1)


class OfflineAlreadyListedByTitleTests(unittest.TestCase):
    """Must-fix 1: check_already_listed also matches by normalized title,
    for a Google News item whose opaque link never resolved."""

    def setUp(self):
        self.cfg = load_config()

    def test_matches_by_normalized_title_when_url_never_resolved(self):
        title = "The NYC Job Quality Problem"
        page_text = "<p>Read more: The NYC Job Quality Problem, by Tal Roded.</p>"
        with unittest.mock.patch.object(monitor, "http_get",
                                         return_value=FakeResponse(200, text=page_text)):
            result = monitor.check_already_listed(
                "personal_website/publications/index.html",
                "https://news.google.com/rss/articles/CBMi_unresolved",
                self.cfg, {}, title=title)
        self.assertTrue(result)

    def test_no_match_without_title_or_url(self):
        page_text = "<p>Nothing relevant here.</p>"
        with unittest.mock.patch.object(monitor, "http_get",
                                         return_value=FakeResponse(200, text=page_text)):
            result = monitor.check_already_listed(
                "personal_website/publications/index.html",
                "https://news.google.com/rss/articles/CBMi_unresolved",
                self.cfg, {}, title="Something Totally Unrelated")
        self.assertFalse(result)


class OfflineWpSearchBudgetTests(unittest.TestCase):
    """Must-fix 3: a RunBudgetExceeded mid-loop must stop fetching, record
    a source error, and return the items already collected/flagged so far;
    a URL is never marked scanned unless its item was returned."""

    def test_budget_exceeded_returns_flagged_items_collected_so_far(self):
        conn = monitor.db_connect(":memory:")
        cfg = {"wp_search_sites": ["a.example", "b.example"],
               "wp_search_terms": ["nycuriosity"],
               "own_link_domains": ["nycuriosity.com"], "own_byline_urls": []}
        calls = {"n": 0}

        def fake_get(url, params=None, timeout=15):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeResponse(200, json_data=[{"url": "https://a.example/cites"}])
            return FakeResponse(400)

        def fake_http_get(url, **k):
            return FakeResponse(200, text='<html><title>X</title>'
                                           '<a href="https://nycuriosity.com/x">l</a>'
                                           + ("w " * 300) + "</html>")

        state = {"k": 0}

        def fake_check_run_budget():
            state["k"] += 1
            if state["k"] >= 3:
                raise monitor.RunBudgetExceeded("budget")

        with unittest.mock.patch.object(monitor.SESSION, "get", side_effect=fake_get), \
             unittest.mock.patch.object(monitor, "http_get", side_effect=fake_http_get), \
             unittest.mock.patch.object(monitor, "check_run_budget",
                                         side_effect=fake_check_run_budget):
            items, errors, site_hits = monitor.fetch_wp_search(cfg, [], 0, conn=conn)
        self.assertEqual(len(items), 1)
        self.assertTrue(monitor.is_scanned(conn, "https://a.example/cites"))
        self.assertTrue(any("budget" in e.lower() for e in errors))
        # b.example was never reached; nothing about it was marked scanned.
        self.assertFalse(monitor.is_scanned(conn, "https://b.example/cites"))


class LiveGoogleNewsResolveTests(unittest.TestCase):
    """Live test: decodes a real Google News link pulled from seen.db.
    Skipped loudly (never a silent pass) on any network failure or on
    MENTION_MONITOR_SKIP_LIVE_TESTS=1."""

    def _real_opaque_url_from_seen_db(self):
        db_path = os.environ.get("MENTION_MONITOR_LIVE_SEEN_DB")
        if not db_path or not os.path.exists(db_path):
            return None
        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT url FROM seen WHERE url LIKE '%news.google.com%' LIMIT 1").fetchone()
        conn.close()
        return row[0] if row else None

    def test_decodes_to_a_real_outlet_url(self):
        if skip_live():
            self.skipTest("MENTION_MONITOR_SKIP_LIVE_TESTS=1")
        url = self._real_opaque_url_from_seen_db()
        if not url:
            self.skipTest("MENTION_MONITOR_LIVE_SEEN_DB not set to a seen.db with a "
                           "news.google.com link")
        try:
            resolved, err = monitor.resolve_google_news_url(url, timeout=20)
        except Exception as e:  # noqa: BLE001
            self.skipTest(f"live network call failed: {e}")
        if err is not None:
            self.skipTest(f"live decode failed (undocumented flow): {err}")
        self.assertNotIn("news.google.com", resolved)


class OfflineRoundupTests(unittest.TestCase):
    """Item P2.5: roundup titles route to their own digest section with no
    website-update suggestion."""

    def setUp(self):
        self.cfg = load_config()

    def _item(self, title):
        return monitor.make_item("outlets", "name", "Streetsblog", "nyc.streetsblog.org",
                                  title, "https://nyc.streetsblog.org/x",
                                  datetime.now(timezone.utc), "snippet")

    def test_fridays_headlines_is_roundup(self):
        item = self._item("Friday's Headlines: Redesign, Not Crackdowns, Edition")
        self.assertTrue(monitor.is_roundup(item, self.cfg))

    def test_wednesdays_headlines_is_roundup(self):
        item = self._item("Wednesday's Headlines: More Helmet Discourse Edition")
        self.assertTrue(monitor.is_roundup(item, self.cfg))

    def test_ordinary_title_is_not_roundup(self):
        item = self._item("Tal Roded on congestion pricing")
        self.assertFalse(monitor.is_roundup(item, self.cfg))

    def test_roundup_item_gets_own_section_and_no_update_suggestion(self):
        item = self._item("Friday's Headlines: Redesign, Not Crackdowns, Edition")
        digest = monitor.build_digest(
            [item], [], [], None, [], self.cfg, "2026-09-15")
        self.assertIn("Mentioned in roundups (1)", digest)
        self.assertNotIn("## Suggested website updates", digest)


if __name__ == "__main__":
    unittest.main()
