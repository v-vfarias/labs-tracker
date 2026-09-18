import os
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from labs_tracker.config import Settings
from labs_tracker.db import ensure_indexes
from labs_tracker.integrations import release_sources
from labs_tracker.services.reports import build_issue_report
from labs_tracker.services.sync import sync
from labs_tracker.services.tracking import (
    DuplicateRecordError, IssueEdit, IssueFilters, RepoEdit, TrackingValidationError,
    delete_repo, get_issue, get_repo, list_issues, product_source_statuses,
    save_issue, save_repo,
)
from test_release_sources import FakeResponse


@unittest.skipUnless(os.getenv("LABS_TRACKER_RUN_MONGO_TESTS") == "1", "Opt-in local MongoDB integration tests")
class MongoIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=2000, tz_aware=True)
        self.addCleanup(self.client.close)
        self.client.admin.command("ping")
        self.database_name = f"labs_tracker_test_{uuid4().hex}"
        self.db = self.client[self.database_name]
        self.addCleanup(self.client.drop_database, self.database_name)
        ensure_indexes(self.db)
        self.repo = RepoEdit(repo_id="owner/repo", name="Test lab", products=["Foundry"])
        self.issue = IssueEdit(issue_id="owner/repo#1", repo_id="owner/repo", title="Test issue")

    def test_indexes_and_typed_repo_round_trip(self):
        save_repo(self.db, replace(self.repo, last_tested="2026-09-18"))
        saved = get_repo(self.db, "owner/repo")
        self.assertEqual(saved["_id"], "owner/repo")
        self.assertEqual(saved["lastTested"], datetime(2026, 9, 18, tzinfo=timezone.utc))
        with self.assertRaises(DuplicateRecordError):
            save_repo(self.db, self.repo)
        with self.assertRaises(DuplicateKeyError):
            self.db.repos.insert_one({"id": "owner/repo"})
        save_repo(self.db, replace(self.repo, existing_id="owner/repo", name="Ignored", involved_devs=["Owner"]))
        saved = get_repo(self.db, "owner/repo")
        self.assertEqual(saved["name"], "Test lab")
        self.assertEqual(saved["involvedDevs"], ["Owner"])

    def test_issue_history_validation_filters_and_report(self):
        save_repo(self.db, self.repo)
        save_issue(self.db, self.issue)
        original = get_issue(self.db, self.issue.issue_id)
        edit = replace(self.issue, existing_id=self.issue.issue_id, handling_stage="Investigating")
        with self.assertRaises(TrackingValidationError):
            save_issue(self.db, edit)
        self.assertEqual(get_issue(self.db, self.issue.issue_id), original)
        edit = replace(edit, progress_note="Reproduced locally", external_response="Evidence")
        save_issue(self.db, edit)
        saved = get_issue(self.db, self.issue.issue_id)
        self.assertEqual(len(saved["handlingHistory"]), len(original["handlingHistory"]) + 1)
        self.assertEqual(saved["handlingHistory"][-1]["evidence"]["externalResponse"], "Evidence")
        save_issue(self.db, replace(edit, progress_note=""))
        self.assertEqual(get_issue(self.db, self.issue.issue_id)["handlingHistory"], saved["handlingHistory"])
        self.assertEqual(len(list_issues(self.db, IssueFilters(missing_classification=True))), 1)
        report = build_issue_report(self.db)
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["longestRunning"][0]["handlingStage"], "Investigating")

    def test_source_overrides_are_shared_and_validation_precedes_writes(self):
        url = "https://github.blog/changelog/"
        save_repo(self.db, replace(self.repo, source_urls={"Foundry": url}))
        self.assertEqual(self.db.productSources.find_one({"_id": "Foundry"})["url"], url)
        save_repo(self.db, replace(self.repo, repo_id="owner/other"))
        self.assertEqual(product_source_statuses(self.db, ["Foundry"])[0]["source"]["url"], url)
        with self.assertRaises(TrackingValidationError):
            save_repo(self.db, replace(self.repo, repo_id="owner/invalid", source_urls={"Foundry": "https://example.com/"}))
        self.assertIsNone(get_repo(self.db, "owner/invalid"))
        self.assertEqual(self.db.productSources.count_documents({}), 1)

    def test_repo_delete_cascades_only_to_its_issues(self):
        save_repo(self.db, self.repo)
        save_issue(self.db, self.issue)
        save_repo(self.db, replace(self.repo, repo_id="owner/other"))
        save_issue(self.db, replace(self.issue, issue_id="owner/other#1", repo_id="owner/other"))
        delete_repo(self.db, "owner/repo")
        self.assertIsNone(get_repo(self.db, "owner/repo"))
        self.assertIsNone(get_issue(self.db, "owner/repo#1"))
        self.assertIsNotNone(get_repo(self.db, "owner/other"))
        self.assertIsNotNone(get_issue(self.db, "owner/other#1"))

    def test_sync_upserts_preserve_manual_fields_and_history_while_pruning(self):
        save_repo(self.db, replace(self.repo, involved_devs=["Owner"]))
        save_issue(self.db, replace(self.issue, type_of_issue="UI drift", external_response="Keep evidence"))
        save_issue(self.db, replace(self.issue, issue_id="owner/repo#90"))
        self.db.issues.insert_many([
            {"issueId": "owner/repo#91", "repoId": "owner/repo", "kind": "Issue", "handlingHistory": []},
            {"issueId": "owner/repo#92", "repoId": "owner/repo", "kind": "Issue"},
        ])
        history = get_issue(self.db, self.issue.issue_id)["handlingHistory"]
        github_issue = SimpleNamespace(number=1, title="Updated title", state="open", pull_request=None)
        github_pr = SimpleNamespace(number=2, pull_request=object())
        github_closed = SimpleNamespace(number=3, title="Closed issue", state="closed", pull_request=None)
        repo = SimpleNamespace(full_name="owner/repo", name="Updated lab", archived=False,
                               pushed_at=datetime(2026, 9, 18, tzinfo=timezone.utc))
        repo.get_issues = Mock(side_effect=lambda **kwargs: [github_issue, github_pr] if kwargs["state"] == "open" else [github_closed])
        github = Mock()
        github.get_repo.return_value = repo
        settings = Settings("mongodb://127.0.0.1:27017", self.database_name, "test-only", ["owner/repo"])
        with patch("labs_tracker.services.sync.get_database", return_value=self.db), \
                patch("labs_tracker.services.sync.get_github", return_value=github):
            for _ in range(2):
                self.assertEqual(sync(settings), {"success": True, "repoCount": 1, "issueCount": 2})
        saved = get_issue(self.db, self.issue.issue_id)
        self.assertEqual(saved["title"], "Updated title")
        self.assertEqual(saved["typeOfIssue"], "UI drift")
        self.assertEqual(saved["externalResponse"], "Keep evidence")
        self.assertEqual(saved["handlingHistory"], history)
        self.assertEqual(get_repo(self.db, "owner/repo")["involvedDevs"], ["Owner"])
        self.assertIsNotNone(get_issue(self.db, "owner/repo#90"))
        for issue_id in ("owner/repo#2", "owner/repo#91", "owner/repo#92"):
            self.assertIsNone(get_issue(self.db, issue_id))
        self.assertEqual(get_issue(self.db, "owner/repo#3")["state"], "Closed")
        self.assertEqual(self.db.issues.count_documents({}), 3)

    def test_source_validation_persists_evidence_and_invalidates_changed_url(self):
        now = datetime(2026, 9, 18, tzinfo=timezone.utc)
        source = release_sources.PRODUCT_SOURCES["Foundry"]
        opener = Mock(return_value=FakeResponse("<title>What's new in Microsoft Foundry</title><main>September 2026</main>", source["url"]))
        with patch.dict(release_sources.PRODUCT_SOURCES, {"Foundry": source}, clear=True):
            for _ in range(2):
                results = release_sources.validate_all_sources(self.db, opener=opener, now=now)
        self.assertEqual(results[0]["status"], "Validated")
        self.assertEqual(self.db.sourceValidations.count_documents({}), 1)
        saved = self.db.sourceValidations.find_one({"product": "Foundry"})
        self.assertEqual(saved["checkedAt"], now)
        self.assertEqual(len(saved["contentHash"]), 64)
        self.assertEqual(product_source_statuses(self.db, ["Foundry"])[0]["validation"]["status"], "Validated")
        release_sources.save_source_urls(self.db, {"Foundry": "https://github.blog/changelog/"})
        self.assertEqual(product_source_statuses(self.db, ["Foundry"])[0]["validation"], {})