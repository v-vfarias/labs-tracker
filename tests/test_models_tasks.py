import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from labs_tracker.models import default_issue_manual_fields
from labs_tracker.sync import simplify_collections
from labs_tracker.tasks import generate_tasks


class FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query=None):
        return list(self.docs)

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def count_documents(self, query=None):
        return len(self.docs)

    def delete_many(self, query=None):
        self.docs = []

    def insert_many(self, docs):
        self.docs = list(docs)

    def drop(self):
        self.docs = []


class FakeDb:
    def __init__(self, repos, issues, items=None, sync_runs=None):
        self.repos = FakeCollection(repos)
        self.issues = FakeCollection(issues)
        self.items = FakeCollection(items or [])
        self.syncRuns = FakeCollection(sync_runs or [])

    def list_collection_names(self):
        names = ["repos", "issues"]
        if self.items.docs:
            names.append("items")
        if self.syncRuns.docs:
            names.append("syncRuns")
        return names


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

    def test_simplify_collections_normalizes_legacy_items(self):
        db = FakeDb(
            repos=[
                {
                    "_id": "legacy",
                    "id": "owner/repo",
                    "name": "repo",
                    "devs": ["alice"],
                    "products": ["P1"],
                    "status": "Live",
                    "lastUpdated": datetime(2026, 1, 1, tzinfo=timezone.utc),
                    "lastTested": None,
                    "github": {"id": 1},
                }
            ],
            issues=[],
            items=[
                {
                    "_id": "legacy-item",
                    "id": "owner/repo#7",
                    "repoId": "owner/repo",
                    "kind": "pr",
                    "title": "Legacy title",
                    "state": "open",
                    "typeOfIssue": "Unknown",
                    "resolution": "Invalid resolution",
                    "status": "In review",
                    "testResult": "Not tested",
                    "lastTested": None,
                }
            ],
            sync_runs=[{"startedAt": datetime.now(timezone.utc)}],
        )

        with patch("labs_tracker.sync.get_database", return_value=db), patch("labs_tracker.sync.ensure_indexes"):
            result = simplify_collections(settings=object(), confirm=True)

        self.assertEqual(result["repos"], 1)
        self.assertEqual(result["issues"], 1)
        self.assertEqual(db.items.docs, [])
        self.assertEqual(db.syncRuns.docs, [])

        issue = db.issues.docs[0]
        self.assertEqual(issue["issueId"], "owner/repo#7")
        self.assertEqual(issue["kind"], "PR")
        self.assertEqual(issue["state"], "Open")
        self.assertEqual(issue["resolution"], "Unknown")
        self.assertEqual(
            sorted(issue.keys()),
            sorted(["_id", "issueId", "repoId", "kind", "title", "state", "typeOfIssue", "resolution", "status", "lastTested"]),
        )

    def test_simplify_requires_confirm_flag(self):
        with self.assertRaises(RuntimeError):
            simplify_collections(settings=object(), confirm=False)


if __name__ == "__main__":
    unittest.main()
