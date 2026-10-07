import unittest
import asyncio
import os
from email.message import Message
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from pymongo import MongoClient

from labs_tracker.domain.release_checks import Article, compare_articles
from labs_tracker.config import ReleaseCheckSettings, Settings
from labs_tracker.integrations.release_agent import MockReleaseAnalyzer
from labs_tracker.integrations.github import load_lab_context
from labs_tracker.domain.release_checks import PILOT_REPO
from labs_tracker.db import ensure_indexes
from labs_tracker.services.release_checks import CheckBusyError, check_release_notes, get_release_check, mark_reviewed
from labs_tracker.integrations.release_notes import (
    ARCHIVE_URL, FEED_URL, IncompleteCheck, SafeRedirectHandler,
    discover_articles, extract_article, fetch_document, parse_feed,
)


ARTICLE_URL = "https://devblogs.microsoft.com/foundry/whats-new-test/"
ARTICLE_HTML = b'''<h1>What's new in Microsoft Foundry</h1>
<meta property="article:published_time" content="2026-09-01T00:00:00Z">
<nav>Changing navigation</nav><div class="entry-content"><h2>SDK</h2>
<p>Version 2.0 <a href="https://example.com/docs">Docs</a></p>
<pre>if ready:\n    run()</pre><script>noise</script></div>'''


class ExtractionTests(unittest.TestCase):
    def test_normalization_preserves_code_and_links_but_ignores_chrome(self):
        original = extract_article(ARTICLE_HTML, ARTICLE_URL)
        changed = extract_article(ARTICLE_HTML.replace(b"Changing navigation", b"new menu").replace(b"noise", b"other JS"), ARTICLE_URL)
        self.assertEqual(original.content_hash, changed.content_hash)
        self.assertIn("    run()", original.content)
        self.assertIn("https://example.com/docs", original.content)
        self.assertNotEqual(original.content_hash, extract_article(ARTICLE_HTML.replace(b"2.0", b"3.0"), ARTICLE_URL).content_hash)

    def test_missing_body_rejected(self):
        with self.assertRaises(IncompleteCheck):
            extract_article(ARTICLE_HTML.replace(b'entry-content', b'unknown'), ARTICLE_URL)

    def test_unsafe_redirect_rejected_before_request(self):
        with self.assertRaises(ValueError):
            SafeRedirectHandler().redirect_request(Mock(), None, 302, "", {}, "https://localhost/private")

    def test_download_overflow_rejected(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = ARTICLE_URL
        response.getcode.return_value = 200
        response.headers = Message()
        response.headers["Content-Type"] = "text/html"
        response.read.return_value = b"12345"
        with self.assertRaises(IncompleteCheck):
            fetch_document(ARTICLE_URL, limit=4, opener=Mock(return_value=response))
        response.read.assert_called_once_with(5)

    def test_discovery_keeps_watched_articles(self):
        newer = ARTICLE_URL.replace("test", "new")
        feed = f"<rss><channel><title>Foundry</title><item><link>{newer}</link></item><item><link>{ARTICLE_URL}</link></item></channel></rss>".encode()
        archive = f'<h2><a href="{newer}">New</a></h2><h2><a href="{ARTICLE_URL}">Seed</a></h2>'.encode()
        documents = {FEED_URL: feed, ARCHIVE_URL: archive, ARTICLE_URL: ARTICLE_HTML, newer: ARTICLE_HTML}
        result = discover_articles(ARTICLE_URL, [], fetcher=lambda url, **kwargs: (documents[url], url), now=datetime(2026, 10, 7, tzinfo=timezone.utc))
        self.assertEqual({article.url for article in result}, {ARTICLE_URL, newer})
        documents[ARCHIVE_URL] = f'<h2><a href="{newer}">New</a></h2>'.encode()
        with self.assertRaises(IncompleteCheck):
            discover_articles(ARTICLE_URL, [], fetcher=lambda url, **kwargs: (documents[url], url))

    def test_feed_rejects_entities(self):
        with self.assertRaises(Exception):
            parse_feed(b'<!DOCTYPE rss [<!ENTITY test SYSTEM "file:///secret">]><rss><channel><title>&test;</title></channel></rss>')


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.article = Article("post-1", "https://devblogs.microsoft.com/foundry/example/", "Foundry update", datetime(2026, 9, 1, tzinfo=timezone.utc), "SDK 2.0", "raw")

    def test_first_unchanged_and_edited(self):
        first = compare_articles(None, [self.article])
        self.assertEqual(first["status"], "First check")
        self.assertEqual(compare_articles(first["hashes"], [self.article])["status"], "No changes")
        edited = replace(self.article, content="SDK 3.0")
        result = compare_articles(first["hashes"], [edited])
        self.assertEqual(result["status"], "Updated")
        self.assertEqual(result["edited"], ["post-1"])

    def test_raw_html_hash_is_not_semantic_content(self):
        self.assertEqual(self.article.content_hash, replace(self.article, raw_hash="chrome-changed").content_hash)

    def test_new_article_and_missing_coverage(self):
        previous = compare_articles(None, [self.article])["hashes"]
        newer = replace(self.article, article_id="post-2")
        self.assertEqual(compare_articles(previous, [self.article, newer])["new"], ["post-2"])
        with self.assertRaises(ValueError):
            compare_articles(previous, [newer])
        with self.assertRaises(ValueError):
            compare_articles(None, [])


class MockAnalyzerTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_does_not_invent_impact(self):
        result = await MockReleaseAnalyzer().analyze([], {"files": [], "commit": "test-sha"}, {"new": ["article"], "edited": []})
        self.assertEqual(result["impact"], "Not assessed")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["backend"], "mock")

    def test_settings_remain_backwards_compatible(self):
        self.assertFalse(Settings("uri", "db", None, []).release_check.enabled)
        self.assertEqual(ReleaseCheckSettings().backend, "mock")

    def test_github_scope_rejected_before_network(self):
        with self.assertRaises(ValueError):
            load_lab_context("owner/other", None, "main", ("Instructions/*.md",))


@unittest.skipUnless(os.getenv("LABS_TRACKER_RUN_MONGO_TESTS") == "1", "Opt-in local MongoDB integration tests")
class ReleasePersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=2000, tz_aware=True)
        self.addCleanup(self.client.close)
        self.db = self.client[f"labs_tracker_test_{uuid4().hex}"]
        self.addCleanup(self.client.drop_database, self.db.name)
        ensure_indexes(self.db)
        self.db.repos.insert_one({"id": PILOT_REPO})
        self.db.productSources.insert_one({"_id": "Foundry", "url": ARTICLE_URL})
        self.settings = Settings("unused", self.db.name, None, [PILOT_REPO], ReleaseCheckSettings(enabled=True))
        self.article = extract_article(ARTICLE_HTML, ARTICLE_URL)
        self.discover = Mock(return_value=[self.article])
        self.context = Mock(return_value={"hash": "context-1", "commit": "sha-1", "files": []})
        self.analyzer = MockReleaseAnalyzer()
        self.analyzer.analyze = AsyncMock(wraps=self.analyzer.analyze)

    async def check(self):
        return await check_release_notes(self.db, PILOT_REPO, self.settings, analyzer=self.analyzer, discover=self.discover, context_loader=self.context)

    async def test_first_unchanged_changed_context_and_snapshots(self):
        self.assertEqual((await self.check())["status"], "First check")
        self.assertEqual((await self.check())["status"], "No changes")
        self.assertEqual(self.analyzer.analyze.await_count, 1)
        self.context.return_value["hash"] = "context-2"
        self.assertEqual((await self.check())["status"], "No changes")
        self.assertEqual(self.analyzer.analyze.await_count, 2)
        self.analyzer.version = "mock-new-version"
        self.assertEqual((await self.check())["status"], "No changes")
        self.assertEqual(self.analyzer.analyze.await_count, 3)
        self.discover.return_value = [replace(self.article, content="Version 3.0")]
        self.assertEqual((await self.check())["status"], "Updated")
        self.assertEqual(self.db.releaseSnapshots.count_documents({}), 2)
        self.assertEqual(get_release_check(self.db, PILOT_REPO)["reviewStatus"], "Not assessed")

    async def test_failed_analysis_retries_without_advancing_baseline(self):
        await self.check()
        self.discover.return_value = [replace(self.article, content="Version 3.0")]
        self.analyzer.analyze.side_effect = RuntimeError("offline")
        self.assertEqual((await self.check())["status"], "Failed")
        self.assertEqual(get_release_check(self.db, PILOT_REPO)["lastSuccessfulCheck"]["status"], "First check")
        self.analyzer.analyze.side_effect = None
        self.assertEqual((await self.check())["status"], "Updated")

    async def test_unchanged_preserves_findings_and_review_requires_note_and_version(self):
        await self.check()
        self.db.repoReleaseChecks.update_one({"repoId": PILOT_REPO}, {"$set": {"findings": [{"id": "finding-1", "summary": "Existing finding"}], "reviewStatus": "Needs revision"}})
        await self.check()
        state = get_release_check(self.db, PILOT_REPO)
        self.assertEqual(state["reviewStatus"], "Needs revision")
        with self.assertRaises(ValueError):
            mark_reviewed(self.db, PILOT_REPO, ["finding-1"], "", state["version"])
        with self.assertRaises(CheckBusyError):
            mark_reviewed(self.db, PILOT_REPO, ["finding-1"], "Reviewed", state["version"] - 1)
        reviewed = mark_reviewed(self.db, PILOT_REPO, ["finding-1"], "Checked the affected instructions", state["version"])
        self.assertEqual(reviewed["reviewStatus"], "Reviewed")
        self.assertEqual(reviewed["findings"], [])

    async def test_duplicate_run_and_cancellation_release_lock(self):
        entered = asyncio.Event()
        async def blocking(*args):
            entered.set()
            await asyncio.Event().wait()
        self.analyzer.analyze.side_effect = blocking
        task = asyncio.create_task(self.check())
        await asyncio.wait_for(entered.wait(), 5)
        try:
            with self.assertRaises(CheckBusyError):
                await self.check()
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        state = get_release_check(self.db, PILOT_REPO)
        self.assertNotIn("leaseToken", state)
        self.assertEqual(state["lastAttempt"]["status"], "Cancelled")

    async def test_source_edit_during_run_rejects_publication(self):
        original = self.analyzer.analyze
        async def edit_source(*args):
            self.db.productSources.update_one({"_id": "Foundry"}, {"$set": {"url": ARTICLE_URL.replace("test", "other")}})
            return await original(*args)
        self.analyzer.analyze = edit_source
        self.assertEqual((await self.check())["status"], "Failed")
        self.assertNotIn("lastSuccessfulCheck", get_release_check(self.db, PILOT_REPO))

    async def test_stale_worker_cannot_publish_or_unlock_newer_worker(self):
        original = self.analyzer.analyze
        async def supersede(*args):
            self.db.repoReleaseChecks.update_one({"repoId": PILOT_REPO}, {"$set": {"leaseToken": "newer"}, "$inc": {"version": 1}})
            return await original(*args)
        self.analyzer.analyze = supersede
        self.assertEqual((await self.check())["status"], "Failed")
        state = get_release_check(self.db, PILOT_REPO)
        self.assertEqual(state["leaseToken"], "newer")
        self.assertNotIn("lastSuccessfulCheck", state)