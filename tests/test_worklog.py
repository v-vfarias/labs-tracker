import csv
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from labs_tracker.domain.tasks import (
    TASK_KINDS, TaskDraft, TaskValidationError, draft_fields, local_day, local_week,
    parse_day, queue_bucket, task_changes,
)
from labs_tracker.services import worklog
from labs_tracker.services.reports import build_work_report, work_report_csv, work_report_markdown
from test_models_tasks import FakeCollection


class TaskCollection:
    def __init__(self):
        self.docs = []

    def find(self, query):
        return deepcopy([doc for doc in self.docs if all(doc.get(key) == value for key, value in query.items())])

    def find_one(self, query):
        return next(iter(self.find(query)), None)

    def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                doc.update(deepcopy(update.get("$set", {})))
                for key, value in update.get("$push", {}).items():
                    doc.setdefault(key, []).append(deepcopy(value))
                return SimpleNamespace(matched_count=1)
        if upsert:
            self.docs.append({**query, **deepcopy(update.get("$setOnInsert", {}))})
        return SimpleNamespace(matched_count=0)


def database():
    return SimpleNamespace(tasks=TaskCollection(), repos=FakeCollection([]), issues=FakeCollection([]))


def local_instant(day, hour=12):
    return datetime.combine(day, datetime.min.time()).replace(hour=hour).astimezone(timezone.utc)


class TaskRulesTests(unittest.TestCase):
    def setUp(self):
        self.now = local_instant(date(2026, 9, 28))
        self.task = draft_fields(TaskDraft(title="Read release", kind="Product update review"))

    def test_invalid_drafts_and_dates(self):
        for draft in (
            TaskDraft(title=" ", kind=TASK_KINDS[0]),
            TaskDraft(title="Title", kind="Unknown"),
            TaskDraft(title="Title", kind=TASK_KINDS[0], product="Unrecognized"),
            TaskDraft(title="Title", kind=TASK_KINDS[0], source_url="javascript:alert(1)"),
            TaskDraft(title="Title", kind=TASK_KINDS[0], source_url="https://user:pass@example.com"),
        ):
            with self.subTest(draft=draft), self.assertRaises(TaskValidationError):
                draft_fields(draft)
        for value in ("", "tomorrow", "2026-02-30", "20260928"):
            with self.subTest(value=value), self.assertRaises(TaskValidationError):
                parse_day(value)

    def test_done_requires_outcome_and_wont_do_requires_reason_or_description(self):
        for action, reason, note in [
            ("Done", "", " "), ("Won't do", "", " "), ("Won't do", "Other", ""),
            ("Won't do", "Duplicate", ""), ("Won't do", "Already handled elsewhere", ""),
            ("Won't do", "Accepted risk / low value", ""), ("Won't do", "Bad reason", "detail"),
        ]:
            with self.subTest(action=action, reason=reason), self.assertRaises(TaskValidationError):
                task_changes(self.task, action, reason=reason, note=note, now=self.now)
        changes = task_changes(self.task, "Won't do", reason="Out of scope", now=self.now)
        self.assertEqual(changes["wontDoReason"], "Out of scope")
        changes = task_changes(self.task, "Won't do", note="Handled by our other tracker", now=self.now)
        self.assertEqual(changes["wontDoReason"], "Other")
        changes = task_changes(self.task, "Done", note="No impact found; read release", now=self.now)
        self.assertEqual(changes["status"], "Done")

    def test_selection_carryover_and_deferral_are_not_completion(self):
        selected = {**self.task, **task_changes(self.task, "Select for today", now=self.now)}
        self.assertEqual(queue_bucket(selected, local_day(self.now)), "Today")
        self.assertEqual(queue_bucket(selected, local_day(self.now) + timedelta(days=8)), "Carry-over")
        deferred = {**selected, **task_changes(selected, "Deferred", revisit="2026-10-05", now=self.now)}
        self.assertIsNone(deferred["selectedForDate"])
        self.assertEqual(queue_bucket(deferred, date(2026, 10, 4)), "Deferred")
        self.assertEqual(queue_bucket(deferred, date(2026, 10, 5)), "Backlog")
        with self.assertRaises(TaskValidationError):
            task_changes(deferred, "Select for today", now=self.now)
        with self.assertRaises(TaskValidationError):
            task_changes(selected, "Deferred", revisit="2026-09-28", now=self.now)
        returned = task_changes(deferred, "Return to backlog", now=self.now)
        self.assertIsNone(returned["deferredUntil"])
        self.assertEqual(returned["status"], "Open")


class WorklogTests(unittest.TestCase):
    def setUp(self):
        self.db = database()
        self.now = local_instant(date(2026, 9, 28))
        self.create()

    def create(self, task_id="task", now=None):
        return worklog.create_task(
            self.db, TaskDraft(title="Review", kind="Product update review", product="Foundry"),
            task_id=task_id, now=now or self.now,
        )

    def act(self, action, *, task_id="task", now=None, **kwargs):
        task = worklog.get_task(self.db, task_id)
        worklog.update_task(self.db, task_id, task["version"], action, event_id=uuid4().hex,
                            now=now or self.now, **kwargs)

    def test_creation_and_action_retries_preserve_history(self):
        self.create()
        self.assertEqual(len(self.db.tasks.docs), 1)
        for _ in range(2):
            worklog.update_task(self.db, "task", 0, "Done", event_id="retry",
                                note="No impact", now=self.now)
        saved = worklog.get_task(self.db, "task")
        self.assertEqual(len(saved["history"]), 2)
        self.assertEqual(saved["history"][-1]["snapshot"]["outcome"], "No impact")
        self.assertEqual(saved["completedAt"], self.now)
        with self.assertRaises(TaskValidationError):
            self.act("Select for today")

    def test_conflicting_and_invalid_updates_do_not_write(self):
        before = deepcopy(self.db.tasks.docs)
        with self.assertRaises(TaskValidationError):
            self.act("Done", note=" ")
        self.assertEqual(before, self.db.tasks.docs)
        self.act("In progress")
        with self.assertRaises(worklog.TaskConflictError):
            worklog.update_task(self.db, "task", 0, "Done", note="Evidence", event_id="old")
        with patch.object(self.db.tasks, "update_one", return_value=SimpleNamespace(matched_count=0)):
            with self.assertRaises(worklog.TaskConflictError):
                self.act("Done", note="Evidence")
        self.assertEqual(worklog.get_task(self.db, "task")["status"], "In progress")

    def test_unlimited_manual_selection_and_restart_read(self):
        for index in range(20):
            task_id = str(index)
            self.create(task_id)
            self.act("Select for today", task_id=task_id)
        restarted = SimpleNamespace(tasks=self.db.tasks)
        rows = worklog.list_tasks(restarted, now=self.now + timedelta(days=7))
        self.assertEqual(sum(row["bucket"] == "Carry-over" for row in rows), 20)
        self.assertEqual(sum(row["bucket"] == "Backlog" for row in rows), 1)

    def test_suggestions_are_deduplicated_and_never_selected(self):
        self.db.repos.docs = [{"id": "owner/repo", "name": "Repo", "lastUpdated": self.now}]
        self.db.issues.docs = [{
            "issueId": "owner/repo#1", "repoId": "owner/repo", "kind": "Issue",
            "title": "Issue", "state": "Open", "typeOfIssue": "Unknown", "lastTested": None,
        }]
        self.assertEqual(worklog.suggest_tasks(self.db, now=self.now), 1)
        suggestion = next(task for task in self.db.tasks.docs if task["kind"] == "Issue triage")
        self.act("Won't do", task_id=suggestion["taskId"], reason="Out of scope")
        before = deepcopy(self.db.tasks.docs)
        self.assertEqual(worklog.suggest_tasks(self.db, now=self.now + timedelta(days=1)), 0)
        self.assertEqual(self.db.tasks.docs, before)
        self.assertTrue(all(task["selectedForDate"] is None for task in self.db.tasks.docs))
        self.db.repos.docs[0]["lastUpdated"] = self.now + timedelta(days=1)
        self.assertEqual(worklog.suggest_tasks(self.db, now=self.now), 0)

    def test_obsolete_suggestions_are_retired_without_counting_as_done(self):
        self.db.issues.docs = [{
            "issueId": "owner/repo#1", "repoId": "owner/repo", "kind": "Issue",
            "title": "Issue", "state": "Open", "typeOfIssue": "Unknown",
        }]
        worklog.suggest_tasks(self.db, now=self.now)
        task = next(task for task in self.db.tasks.docs if task["taskId"].startswith("suggested:"))
        self.act("Select for today", task_id=task["taskId"])
        self.db.issues.docs[0]["status"] = "Resolved locally"
        self.assertEqual(worklog.retire_ineligible_suggestions(self.db, now=self.now), 1)
        retired = worklog.get_task(self.db, task["taskId"])
        self.assertEqual(retired["status"], "Won't do")
        self.assertEqual(retired["wontDoReason"], "Superseded / obsolete")
        self.assertIsNone(retired["completedAt"])
        self.assertIsNone(retired["selectedForDate"])
        self.assertEqual(worklog.get_task(self.db, "task")["status"], "Open")
        self.assertEqual(worklog.retire_ineligible_suggestions(self.db, now=self.now), 0)
        report = build_work_report(self.db, date(2026, 9, 28), now=self.now)
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["declined"], 1)
        self.db.issues.docs[0]["status"] = "Open"
        self.assertEqual(worklog.suggest_tasks(self.db, now=self.now), 0)
        reopened = worklog.get_task(self.db, task["taskId"])
        self.assertEqual(reopened["status"], "Open")
        self.assertIsNone(reopened["selectedForDate"])
        self.assertEqual(reopened["history"][-1]["action"], "Reopen")

    def test_legacy_repo_and_untested_tasks_are_retired_but_manual_and_done_remain(self):
        draft = TaskDraft(title="Old suggestion", kind="Repository health review")
        for identifier in ("suggested:repo", "suggested:untested", "manual"):
            worklog.create_task(self.db, draft, task_id=identifier, now=self.now)
        self.act("Done", task_id="suggested:untested", note="Already completed")
        self.assertEqual(worklog.retire_ineligible_suggestions(self.db, now=self.now), 1)
        self.assertEqual(worklog.get_task(self.db, "suggested:repo")["status"], "Won't do")
        self.assertEqual(worklog.get_task(self.db, "suggested:untested")["status"], "Done")
        self.assertEqual(worklog.get_task(self.db, "manual")["status"], "Open")

    def test_week_report_uses_event_snapshots_and_distinct_tasks(self):
        earlier = local_instant(date(2026, 9, 25))
        self.create("older", now=earlier)
        self.act("Done", task_id="older", note="Previously created, completed now")
        self.act("Done", note="No impact")
        self.act("Reopen", note="Correction", now=self.now + timedelta(days=1))
        self.act("Done", note="Confirmed", now=self.now + timedelta(days=2))
        self.create("declined")
        self.act("Won't do", task_id="declined", reason="Out of scope")
        self.create("pending")
        self.act("Select for today", task_id="pending")
        next_week = local_instant(date(2026, 10, 5))
        self.act("Done", task_id="pending", note="Next week", now=next_week)
        report = build_work_report(self.db, date(2026, 9, 30), now=next_week + timedelta(days=1))
        self.assertEqual(report["completed"], 2)
        self.assertEqual(report["declined"], 1)
        self.assertEqual([row["taskId"] for row in report["outstanding"]], ["pending"])
        self.assertEqual(sum(event["action"] == "Done" for event in report["events"]), 3)
        self.db.tasks.docs[0]["title"] = "Later title edit"
        rerun = build_work_report(self.db, date(2026, 9, 30), now=next_week + timedelta(days=1))
        self.assertEqual(rerun["events"], report["events"])
        markdown = work_report_markdown(report)
        self.assertIn("## Won't do decisions", markdown)
        self.assertIn("No impact", markdown)
        self.assertIn("Correction", markdown)
        self.assertNotIn("Later title edit", markdown)
        csv_rows = list(csv.DictReader(StringIO(work_report_csv(report))))
        self.assertEqual(csv_rows[0]["section"], "Summary")
        self.assertTrue(any(row["section"] == "Outstanding" for row in csv_rows))

    def test_week_boundaries_and_empty_report(self):
        start, end = local_week(date(2026, 9, 30))
        self.assertEqual(local_day(start), date(2026, 9, 28))
        self.assertEqual(local_day(end), date(2026, 10, 5))
        self.assertEqual(start, datetime(2026, 9, 28).astimezone(timezone.utc))
        self.assertEqual(end, datetime(2026, 10, 5).astimezone(timezone.utc))
        self.db = database()
        self.create(now=start)
        self.act("Done", note="At start", now=start)
        self.create("at-end")
        self.act("Done", task_id="at-end", note="At end", now=end)
        report = build_work_report(self.db, date(2026, 9, 30), now=end)
        self.assertEqual(report["completed"], 1)
        self.assertEqual(build_work_report(self.db, date(2026, 10, 5), now=end)["completed"], 1)
        empty = build_work_report(database(), date(2026, 9, 30), now=end)
        self.assertIn("Completed tasks: 0", work_report_markdown(empty))

    def test_csv_treats_user_notes_as_text(self):
        self.act("Done", note="=1+1")
        report = build_work_report(self.db, date(2026, 9, 30), now=self.now)
        rows = list(csv.DictReader(StringIO(work_report_csv(report))))
        self.assertEqual(next(row["note"] for row in rows if row["action"] == "Done"), "'=1+1")
