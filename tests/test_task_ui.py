import unittest
from unittest.mock import patch

from pymongo.errors import ConnectionFailure

from labs_tracker.domain.tasks import TaskDraft
from labs_tracker.services import worklog
from test_models_tasks import FakeCollection, FakeDb
from test_worklog import TaskCollection


class TasksUITests(unittest.TestCase):
    def setUp(self):
        from nicegui import Client, ui
        from nicegui.page import page
        from labs_tracker.ui.app import build_ui

        self.ui = ui
        self.db = FakeDb([], [])
        self.db.tasks = TaskCollection()
        self.db.productSources = FakeCollection([])
        self.db.sourceValidations = FakeCollection([])
        self.client = Client(page("/task-ui-test"), request=None)
        self.addCleanup(self.client.delete)
        self.enterContext(self.client)
        self.notify = self.enterContext(patch.object(ui, "notify"))
        self.state = build_ui(self.db)

    def element(self, **props):
        return next(element for element in reversed(list(self.client.elements.values()))
                    if all(element._props.get(key) == value for key, value in props.items()))

    def fire(self, element, event="click", args=None):
        from nicegui.events import GenericEventArguments

        listener = next(listener for listener in element._event_listeners.values() if listener.type == event)
        listener.handler(GenericEventArguments(sender=element, client=self.client, args=args))

    def dialog(self):
        return next(element for element in reversed(list(self.client.elements.values())) if isinstance(element, self.ui.dialog))

    def open_task(self):
        self.element(label="Queue").set_value("All")
        table = next(element for element in self.client.elements.values()
                     if isinstance(element, self.ui.table) and any(column["name"] == "bucket" for column in element.columns))
        self.fire(table, "rowClick", {"row": table.rows[0]})

    def test_navigation_creation_decisions_and_weekly_download(self):
        self.fire(self.element(label="Tasks"))
        self.assertEqual(self.state.active_view, "tasks")
        self.fire(self.element(label="New task"))
        self.fire(self.element(label="Create task"))
        self.assertTrue(self.dialog().value)
        self.assertEqual(len(self.db.tasks.docs), 0)
        self.element(label="Title").set_value("Read Foundry updates")
        self.element(label="Task type").set_value("Product update review")
        self.fire(self.element(label="Create task"))
        self.assertFalse(self.dialog().value)
        self.assertEqual(len(self.db.tasks.docs), 1)
        self.open_task()
        self.fire(self.element(label="Save action"))
        self.assertIsNotNone(self.db.tasks.docs[0]["selectedForDate"])
        self.open_task()
        self.element(label="Action").set_value("Won't do")
        self.fire(self.element(label="Save action"))
        self.assertTrue(self.dialog().value)
        self.assertEqual(self.db.tasks.docs[0]["status"], "Open")
        self.element(label="Won't do reason").set_value("Out of scope")
        self.fire(self.element(label="Save action"))
        self.assertFalse(self.dialog().value)
        self.assertEqual(self.db.tasks.docs[0]["status"], "Won't do")
        self.fire(self.element(label="Preview week"))
        with patch.object(self.ui, "download") as download:
            self.fire(self.element(label="Download Markdown"))
            content, filename = download.call_args.args
            self.assertIn(b"Won't do tasks: 1", content)
            self.assertTrue(filename.endswith(".md"))
            self.fire(self.element(label="Download CSV"))
            self.assertIn(b"Out of scope", download.call_args.args[0])
        self.fire(self.element(icon="arrow_back"))
        self.assertEqual(self.state.active_view, "dashboard")

    def test_database_failure_keeps_dialog_open_without_success(self):
        self.fire(self.element(label="Tasks"))
        self.fire(self.element(label="New task"))
        self.element(label="Title").set_value("Task")
        self.notify.reset_mock()
        with patch.object(self.db.tasks, "update_one", side_effect=ConnectionFailure("offline")), \
                self.assertLogs("labs_tracker.ui.views.tasks", level="ERROR"):
            self.fire(self.element(label="Create task"))
        self.assertTrue(self.dialog().value)
        self.assertEqual(self.notify.call_args.kwargs["color"], "negative")

    def test_done_and_defer_forms_and_invalid_week(self):
        worklog.create_task(self.db, TaskDraft(title="Review PR", kind="PR validation"), task_id="task")
        self.fire(self.element(label="Tasks"))
        self.open_task()
        self.element(label="Action").set_value("Deferred")
        self.assertTrue(self.element(label="Revisit date").visible)
        self.fire(self.element(label="Save action"))
        self.assertTrue(self.dialog().value)
        self.element(label="Action").set_value("Done")
        self.assertFalse(self.element(label="Revisit date").visible)
        self.element(label="Outcome / progress / supporting detail").set_value("Needs changes; head abc123, not executed")
        self.fire(self.element(label="Save action"))
        self.assertEqual(self.db.tasks.docs[0]["status"], "Done")
        self.element(label="Any date in the week").set_value("invalid")
        with patch.object(self.ui, "download") as download:
            self.fire(self.element(label="Download CSV"))
            download.assert_not_called()
        self.assertEqual(self.notify.call_args.kwargs["color"], "warning")
