import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from labs_tracker.models import ISSUE_TYPE_ALIASES, ISSUE_TYPE_VALUES, OWNER_VALUES, PRODUCT_VALUES, RESOLUTION_ALIASES, RESOLUTION_VALUES, STATUS_VALUES, default_issue_manual_fields, default_repo_manual_fields
from labs_tracker.report import build_issue_report
from labs_tracker.sync import simplify_collections
from labs_tracker.tasks import generate_tasks


class FakeCursor(list):
    def sort(self, key, direction=1):
        return FakeCursor(sorted(self, key=lambda doc: doc.get(key) or ""))


class FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query=None, projection=None):
        return FakeCursor([doc for doc in self.docs if self._matches(doc, query or {})])

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def count_documents(self, query=None):
        return len([doc for doc in self.docs if self._matches(doc, query or {})])

    def _matches(self, doc, query):
        for key, expected in query.items():
            actual = doc.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$nin" in expected and actual in expected["$nin"]:
                    return False
            elif actual != expected:
                return False
        return True

    def delete_many(self, query=None):
        if not query:
            self.docs = []
            return
        for key, condition in query.items():
            if isinstance(condition, dict) and "$nin" in condition:
                allowed = condition["$nin"]
                self.docs = [doc for doc in self.docs if doc.get(key) in allowed]
                return
        self.docs = []

    def insert_many(self, docs):
        self.docs = list(docs)

    def update_one(self, query, update, upsert=False):
        key, value = next(iter(query.items()))
        for existing in self.docs:
            if existing.get(key) == value:
                existing.update(update.get("$set", {}))
                return
        if upsert:
            doc = dict(update.get("$setOnInsert", {}))
            doc.update(update.get("$set", {}))
            self.docs.append(doc)

    def replace_one(self, query, doc, upsert=False):
        key, value = next(iter(query.items()))
        for index, existing in enumerate(self.docs):
            if existing.get(key) == value:
                self.docs[index] = dict(doc)
                return
        if upsert:
            self.docs.append(dict(doc))

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
    def test_repo_metadata_options_include_tracked_owners_and_products(self):
        self.assertIn("Graeme Malcolm", OWNER_VALUES)
        self.assertIn("Juliane Padrao", OWNER_VALUES)
        self.assertIn("Foundry", PRODUCT_VALUES)
        self.assertIn("Foundry Toolkit for VS Code", PRODUCT_VALUES)
        self.assertIn("GitHub Actions", PRODUCT_VALUES)

    def test_issue_metadata_options_include_manual_review_observations(self):
        self.assertEqual(
            ISSUE_TYPE_VALUES,
            [
                "UI drift",
                "Skillable",
                "SDK/code issues",
                "Outdated versions",
                "User intent/setup mismatch",
                "Lab content clarity",
                "Product/service behavior",
                "Enhancement request",
                "Unknown",
            ],
        )
        self.assertEqual(ISSUE_TYPE_ALIASES["Support reproduction/setup"], "User intent/setup mismatch")
        self.assertEqual(ISSUE_TYPE_ALIASES["Modular suggestion"], "Enhancement request")
        self.assertEqual(ISSUE_TYPE_ALIASES["SDK/code update"], "SDK/code issues")
        self.assertEqual(
            RESOLUTION_VALUES,
            ["Fixed in lab", "Linked PR", "Replied/no lab change", "Reported externally", "Duplicate", "Cannot reproduce", "Not applicable", "Unknown"],
        )
        self.assertEqual(RESOLUTION_ALIASES["Updated code/sample"], "Fixed in lab")
        self.assertIn("Resolved locally", STATUS_VALUES)
        self.assertIn("Waiting owner review", STATUS_VALUES)
        self.assertIn("Temporary/out of scope", STATUS_VALUES)

    def test_default_manual_fields_preserve_unknown_classification(self):
        fields = default_issue_manual_fields("open")
        self.assertEqual(fields["typeOfIssue"], "Unknown")
        self.assertEqual(fields["resolution"], "Unknown")
        self.assertEqual(fields["status"], "Open")
        self.assertIsNone(fields["lastTested"])
        self.assertEqual(fields["closingPrUrl"], "")

    def test_default_repo_manual_fields_use_broad_foundry_bucket(self):
        fields = default_repo_manual_fields("MicrosoftLearning/mslearn-ai-language")
        self.assertEqual(fields["products"], ["Foundry"])

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
                    "kind": "issue",
                    "title": "Legacy title",
                    "state": "open",
                    "typeOfIssue": "Support reproduction/setup",
                    "resolution": "Updated code/sample",
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
        self.assertEqual(issue["kind"], "Issue")
        self.assertEqual(issue["state"], "Open")
        self.assertEqual(issue["typeOfIssue"], "User intent/setup mismatch")
        self.assertEqual(issue["resolution"], "Fixed in lab")
        self.assertEqual(
            sorted(issue.keys()),
            sorted(["_id", "issueId", "repoId", "kind", "title", "state", "typeOfIssue", "resolution", "status", "lastTested", "closingPrUrl"]),
        )

    def test_simplify_requires_confirm_flag(self):
        with self.assertRaises(RuntimeError):
            simplify_collections(settings=object(), confirm=False)

    def test_issue_report_filters_classified_issues(self):
        db = FakeDb(
            repos=[],
            issues=[
                {
                    "issueId": "owner/repo#1",
                    "repoId": "owner/repo",
                    "kind": "Issue",
                    "title": "Open UI issue",
                    "state": "Open",
                    "typeOfIssue": "UI drift",
                    "resolution": "Not applicable",
                    "status": "In review",
                },
                {
                    "issueId": "owner/repo#2",
                    "repoId": "owner/repo",
                    "kind": "Issue",
                    "title": "Closed setup issue",
                    "state": "Closed",
                    "typeOfIssue": "Support reproduction/setup",
                    "resolution": "Updated code/sample",
                    "status": "Closed",
                },
                {
                    "issueId": "owner/repo#3",
                    "repoId": "owner/repo",
                    "kind": "PR",
                    "title": "PR should not be in issue report",
                    "state": "Open",
                    "typeOfIssue": "UI drift",
                    "resolution": "Unknown",
                    "status": "In review",
                },
            ],
        )

        report = build_issue_report(db, {"state": "Open", "repoId": "All", "status": "All", "typeOfIssue": "All"})

        self.assertEqual(report["total"], 1)
        self.assertEqual(report["open"], 1)
        self.assertEqual(report["closed"], 0)
        self.assertEqual(report["byType"], [{"label": "UI drift", "count": 1}])


if __name__ == "__main__":
    unittest.main()
