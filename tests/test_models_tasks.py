import unittest
from datetime import datetime, timedelta, timezone

from labs_tracker.models import default_manual_fields
from labs_tracker.tasks import generate_tasks


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None):
        return list(self.docs)


class FakeDb:
    def __init__(self, repos, items):
        self.repos = FakeCollection(repos)
        self.items = FakeCollection(items)


class ModelTaskTests(unittest.TestCase):
    def test_default_manual_fields_preserve_unknown_classification(self):
        fields = default_manual_fields("open")
        self.assertEqual(fields["typeOfIssue"], "Unknown")
        self.assertEqual(fields["resolution"], "Unknown")
        self.assertEqual(fields["status"], "Open")
        self.assertEqual(fields["testResult"], "Not tested")
        self.assertIsNone(fields["lastTested"])

    def test_generate_tasks_includes_pr_validation_and_repo_retest(self):
        now = datetime.now(timezone.utc)
        db = FakeDb(
            repos=[{"id": "owner/repo", "name": "repo", "lastUpdated": now, "lastTested": None}],
            items=[
                {
                    "id": "owner/repo#1",
                    "repoId": "owner/repo",
                    "number": 1,
                    "title": "Fix lab",
                    "kind": "pr",
                    "url": "https://example.test/pr/1",
                    "state": "open",
                    "draft": False,
                    "createdAt": now - timedelta(days=20),
                    "updatedAt": now,
                    "typeOfIssue": "Unknown",
                    "resolution": "Unknown",
                    "testResult": "Not tested",
                    "lastTested": None,
                }
            ],
        )

        reasons = [task["reason"] for task in generate_tasks(db)]

        self.assertIn("Open PR needs maintainer validation", reasons)
        self.assertIn("Aging contribution: PR open over 14 days and untested", reasons)
        self.assertIn("Repo changed after last test; retest after repo changes", reasons)


if __name__ == "__main__":
    unittest.main()
