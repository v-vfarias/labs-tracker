import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from labs_tracker.services.sync import sync
from test_models_tasks import FakeDb


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.repo_id = "owner/repo"
        self.history = [{"stage": "Resolved", "note": "Keep this history"}]
        self.db = FakeDb([], [
            {"issueId": "owner/repo#1", "repoId": self.repo_id, "kind": "Issue",
             "state": "Open", "status": "Closed", "handlingHistory": self.history},
            {"issueId": "owner/repo#2", "repoId": self.repo_id, "kind": "Issue",
             "state": "Open", "handlingHistory": self.history},
            {"issueId": "owner/repo#3", "repoId": self.repo_id, "kind": "Issue",
             "state": "Open", "handlingHistory": []},
            {"issueId": "owner/other#4", "repoId": "owner/other", "kind": "Issue",
             "state": "Open", "handlingHistory": self.history},
            {"issueId": "owner/repo#5", "repoId": self.repo_id, "kind": "Issue",
             "state": "Closed", "handlingHistory": self.history},
        ])
        self.repo = Mock(full_name=self.repo_id, archived=False, pushed_at=None)
        self.repo.name = "repo"
        self.repo.get_issues.side_effect = lambda **kwargs: (
            [SimpleNamespace(number=2, title="Still open", state="open", pull_request=None)]
            if kwargs["state"] == "open" else []
        )
        self.repo.get_issue.side_effect = lambda number: SimpleNamespace(
            number=number, title=f"Refreshed {number}", state="closed", pull_request=None,
        )
        self.github = Mock()
        self.github.get_repo.return_value = self.repo
        self.settings = SimpleNamespace(github_token="test", tracked_repos=[self.repo_id])
        for target, value in (
            ("get_database", self.db), ("get_github", self.github), ("ensure_indexes", None),
        ):
            patcher = patch(f"labs_tracker.services.sync.{target}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_refreshes_retained_issues_and_preserves_manual_fields(self):
        for _ in range(2):
            result = sync(self.settings)
            self.assertEqual(result, {"success": True, "repoCount": 1, "issueCount": 3})
            self.assertEqual(self.db.issues.count_documents(
                {"repoId": self.repo_id, "state": "Open"}), 1)
        saved = self.db.issues.find_one({"issueId": "owner/repo#1"})
        self.assertEqual(saved["state"], "Closed")
        self.assertEqual(saved["status"], "Closed")
        self.assertEqual(saved["handlingHistory"], self.history)
        self.assertEqual(saved["title"], "Refreshed 1")
        self.assertEqual(self.db.issues.find_one({"issueId": "owner/repo#5"})["title"], "Refreshed 5")
        self.assertIsNone(self.db.issues.find_one({"issueId": "owner/repo#3"}))
        self.assertIsNotNone(self.db.issues.find_one({"issueId": "owner/other#4"}))
        self.assertEqual([call.kwargs["number"] for call in self.repo.get_issue.call_args_list],
                         [1, 5, 1, 5])

    def test_retained_refresh_failure_is_reported_without_pruning(self):
        self.repo.get_issue.side_effect = RuntimeError("GitHub lookup failed")
        with self.assertRaisesRegex(RuntimeError, "GitHub lookup failed"):
            sync(self.settings)
        self.assertIsNotNone(self.db.issues.find_one({"issueId": "owner/repo#3"}))
        saved = self.db.issues.find_one({"issueId": "owner/repo#1"})
        self.assertEqual(saved["state"], "Open")
        self.assertEqual(saved["handlingHistory"], self.history)

    def test_refreshes_retained_issues_when_pruning_is_disabled(self):
        sync(self.settings, prune=False)
        self.assertEqual(self.db.issues.find_one({"issueId": "owner/repo#1"})["state"], "Closed")
        self.assertIsNotNone(self.db.issues.find_one({"issueId": "owner/repo#3"}))

    def test_skips_pull_requests_returned_by_retained_lookup(self):
        self.repo.get_issue.side_effect = None
        self.repo.get_issue.return_value = SimpleNamespace(number=1, pull_request=object())
        result = sync(self.settings)
        self.assertEqual(result["issueCount"], 1)
        self.assertEqual(self.db.issues.find_one({"issueId": "owner/repo#1"})["state"], "Open")


if __name__ == "__main__":
    unittest.main()
