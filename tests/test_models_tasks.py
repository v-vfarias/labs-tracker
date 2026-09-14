import unittest
from datetime import datetime, timezone

from labs_tracker.models import default_issue_manual_fields
from labs_tracker.tasks import generate_tasks


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None):
        return list(self.docs)


class FakeDb:
    def __init__(self, repos, issues):
        self.repos = FakeCollection(repos)
        self.issues = FakeCollection(issues)


class ModelTaskTests(unittest.TestCase):
    def test_default_manual_fields_preserve_unknown_classification(self):
        fields = default_issue_manual_fields("open")
        self.assertEqual(fields["typeOfIssue"], "Unknown")
        self.assertEqual(fields["resolution"], "Unknown")
        self.assertEqual(fields["status"], "Open")
        self.assertIsNone(fields["lastTested"])

    def test_generate_tasks_matches_simplified_rules(self):
        now = datetime.now(timezone.utc)
        db = FakeDb(
            repos=[{"id": "owner/repo", "name": "repo", "lastUpdated": now, "lastTested": None}],
            issues=[
                {
                    "issueId": "owner/repo#1",
                    "repoId": "owner/repo",
                    "kind": "Issue",
                    "title": "Issue to classify",
                    "state": "Open",
                    "typeOfIssue": "Unknown",
                    "resolution": "Unknown",
                    "status": "Open",
                    "lastTested": None,
                },
                {
                    "issueId": "owner/repo#2",
                    "repoId": "owner/repo",
                    "kind": "PR",
                    "title": "PR to validate",
                    "state": "Open",
                    "typeOfIssue": "UI drift",
                    "resolution": "Unknown",
                    "status": "In review",
                    "lastTested": None,
                },
                {
                    "issueId": "owner/repo#3",
                    "repoId": "owner/repo",
                    "kind": "Issue",
                    "title": "Closed item",
                    "state": "Closed",
                    "typeOfIssue": "UI drift",
                    "resolution": "Not applicable",
                    "status": "Closed",
                    "lastTested": None,
                },
            ],
        )

        reasons = [task["reason"] for task in generate_tasks(db)]

        self.assertIn("Open issue/PR with unknown type: classify", reasons)
        self.assertIn("Open issue missing lastTested: test whether it reproduces", reasons)
        self.assertIn("Open PR missing lastTested: validate PR for maintainers", reasons)
        self.assertIn("Closed item missing lastTested: record validation", reasons)
        self.assertIn("Repo changed after last tested (or never tested): retest repo/lab", reasons)


if __name__ == "__main__":
    unittest.main()
