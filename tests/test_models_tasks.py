import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from labs_tracker.models import HANDLING_STAGE_VALUES, ISSUE_TYPE_ALIASES, ISSUE_TYPE_VALUES, OWNER_VALUES, PRODUCT_VALUES, RESOLUTION_ALIASES, RESOLUTION_VALUES, STATUS_VALUES, default_issue_manual_fields, default_repo_manual_fields
from labs_tracker.report import build_issue_report, generate_report
from labs_tracker.sync import simplify_collections, sync
from labs_tracker.tasks import generate_tasks
from labs_tracker.workflow import handling_stage, progress_metrics, progress_update


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
            if key == "$or":
                if not any(self._matches(doc, clause) for clause in expected):
                    return False
                continue
            if key == "handlingHistory.0":
                if bool(doc.get("handlingHistory")) != expected["$exists"]:
                    return False
                continue
            actual = doc.get(key)
            if isinstance(expected, dict):
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$nin" in expected and actual in expected["$nin"]:
                    return False
            elif actual != expected:
                return False
        return True

    def delete_many(self, query=None):
        self.docs = [doc for doc in self.docs if not self._matches(doc, query or {})]

    def insert_many(self, docs):
        self.docs = list(docs)

    def update_one(self, query, update, upsert=False):
        key, value = next(iter(query.items()))
        for existing in self.docs:
            if existing.get(key) == value:
                existing.update(update.get("$set", {}))
                for field, event in update.get("$push", {}).items():
                    existing.setdefault(field, []).append(event)
                return
        if upsert:
            doc = dict(update.get("$setOnInsert", {}))
            doc.update(update.get("$set", {}))
            for field, event in update.get("$push", {}).items():
                doc.setdefault(field, []).append(event)
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
        self.assertEqual(
            HANDLING_STAGE_VALUES,
            ["Raised", "Investigating", "In progress", "Waiting", "Validating", "Resolved"],
        )

    def test_progress_requires_explanation_and_waiting_reason(self):
        with self.assertRaises(ValueError):
            progress_update({}, "In progress", "")
        with self.assertRaises(ValueError):
            progress_update({}, "Waiting", "Need vendor response")
        self.assertEqual(handling_stage({"handlingStage": "Reported to Skillable"}), "Waiting")

    def test_progress_tracks_waits_reopening_and_unchanged_saves(self):
        issue = {}
        for day, stage, note, reason in [
            (1, "Investigating", "Reproducing", "None"),
            (2, "Waiting", "Ticket filed", "External dependency"),
            (4, "Waiting", "Vendor requested logs", "External dependency"),
            (5, "Validating", "Patch received", "None"),
            (6, "Resolved", "Retest passed", "None"),
            (8, "In progress", "Regression: reopened", "None"),
        ]:
            update = progress_update(issue, stage, note, reason, now=datetime(2026, 9, day, tzinfo=timezone.utc))
            issue.update(update["$set"])
            issue.setdefault("handlingHistory", []).append(update["$push"]["handlingHistory"])
        result = progress_metrics(issue, now=datetime(2026, 9, 9, tzinfo=timezone.utc))
        self.assertEqual(result["observedHours"], 144)
        self.assertEqual(result["waitingHours"], 72)
        self.assertEqual(result["stageHours"], 24)
        self.assertIn("External dependency", result["delayReasons"])
        self.assertEqual(progress_update(issue, "In progress", ""), {"$set": {}})
        self.assertIsNone(progress_metrics({})["observedHours"])

    def test_progress_preserves_legacy_evidence_without_backdating(self):
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)
        update = progress_update({"handlingStage": "Reported to Skillable", "externalResponse": "Logs requested"}, "Waiting", "", "External dependency", "Skillable", now=now)
        event = update["$push"]["handlingHistory"]
        self.assertEqual(event["previousStage"], "Reported to Skillable")
        self.assertEqual(event["evidence"]["externalResponse"], "Logs requested")
        self.assertEqual(event["at"], now)

    def test_evidence_only_update_preserves_latest_note_and_stage_age(self):
        issue = {}
        for day, note, evidence in [(1, "Investigate intermittent timeout", {}), (2, "", {"reproductionNotes": "Logs attached"})]:
            update = progress_update(issue, "Investigating", note, now=datetime(2026, 9, day, tzinfo=timezone.utc), evidence=evidence)
            issue.update(update["$set"])
            issue.setdefault("handlingHistory", []).append(update["$push"]["handlingHistory"])
        metrics = progress_metrics(issue, now=datetime(2026, 9, 3, tzinfo=timezone.utc))
        self.assertEqual(metrics["stageHours"], 48)
        self.assertEqual(metrics["latestProgress"], "Investigate intermittent timeout")

    def test_sync_retains_history_outside_sync_window(self):
        db = FakeDb([], [
            {"issueId": "owner/repo#1", "repoId": "owner/repo", "kind": "Issue", "handlingHistory": [{"stage": "Resolved"}]},
            {"issueId": "owner/repo#2", "repoId": "owner/repo", "kind": "Issue", "handlingHistory": []},
            {"issueId": "owner/repo#3", "repoId": "owner/repo", "kind": "Issue"},
        ])
        with patch("labs_tracker.sync.get_database", return_value=db), patch("labs_tracker.sync.ensure_indexes"), patch("labs_tracker.sync.Github"):
            sync(SimpleNamespace(github_token="test", tracked_repos=[]))
        self.assertEqual([issue["issueId"] for issue in db.issues.docs], ["owner/repo#1"])

    def test_progress_report_exports_measured_time_and_notes(self):
        issue = {"issueId": "owner/repo#1", "repoId": "owner/repo", "kind": "Issue", "state": "Closed", "handlingStage": "Resolved", "handlingHistory": [
            {"at": datetime(2026, 9, 1), "stage": "Waiting", "waitingReason": "Other", "note": "Intermittent failure | needs logs"},
            {"at": datetime(2026, 9, 3), "stage": "Resolved", "note": "Verified"},
        ]}
        with TemporaryDirectory() as output:
            path = generate_report(FakeDb([], [issue]), output)
            self.assertIn("Other (48.0h)", path.read_text(encoding="utf-8"))
            self.assertIn("observedHours", (Path(output) / "issues.csv").read_text(encoding="utf-8"))
            self.assertIn("needs logs", (Path(output) / "issues.csv").read_text(encoding="utf-8"))

    def test_default_manual_fields_preserve_unknown_classification(self):
        fields = default_issue_manual_fields("open")
        self.assertEqual(fields["typeOfIssue"], "Unknown")
        self.assertEqual(fields["resolution"], "Unknown")
        self.assertEqual(fields["status"], "Open")
        self.assertEqual(fields["handlingStage"], "Raised")
        self.assertEqual(fields["reproductionNotes"], "")
        self.assertEqual(fields["externalReportUrl"], "")
        self.assertEqual(fields["externalResponse"], "")
        self.assertIsNone(fields["handlingUpdatedAt"])
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
        self.assertEqual(issue["handlingStage"], "Raised")
        self.assertEqual(issue["reproductionNotes"], "")
        self.assertEqual(issue["externalReportUrl"], "")
        self.assertEqual(issue["externalResponse"], "")
        self.assertIsNone(issue["handlingUpdatedAt"])

    def test_simplify_requires_confirm_flag(self):
        with self.assertRaises(RuntimeError):
            simplify_collections(settings=object(), confirm=False)

    def test_simplify_preserves_progress_and_reports_delay(self):
        issue = {"issueId": "owner/repo#1", "repoId": "owner/repo", "kind": "Issue", "state": "Open", "handlingStage": "Reported to Skillable", "externalResponse": "Investigating"}
        db = FakeDb([], [issue])
        db.issues.update_one({"issueId": issue["issueId"]}, progress_update(issue, "Waiting", "Awaiting logs", "External dependency", "Skillable", now=datetime(2026, 9, 1, tzinfo=timezone.utc)))
        history = list(issue["handlingHistory"])
        with patch("labs_tracker.sync.get_database", return_value=db), patch("labs_tracker.sync.ensure_indexes"):
            simplify_collections(settings=object(), confirm=True)
        self.assertEqual(db.issues.docs[0]["handlingHistory"], history)
        report = build_issue_report(db)
        self.assertEqual(report["longestRunning"][0]["handlingStage"], "Waiting")
        self.assertIn("Skillable", report["longestRunning"][0]["delayReasons"])
        self.assertEqual(report["longestRunning"][0]["latestProgress"], "Awaiting logs")

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
