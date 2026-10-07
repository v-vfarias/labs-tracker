import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

from labs_tracker.domain.workflow import progress_update
from labs_tracker.services.tracking import (
    DuplicateRecordError, IssueEdit, IssueFilters, RepoEdit, TrackingValidationError,
    classification_candidates, dashboard_counts, delete_issue, delete_repo,
    list_issues, product_source_statuses, repo_overview, save_issue, save_repo,
)
from labs_tracker.integrations.release_sources import PRODUCT_SOURCES
from test_models_tasks import FakeCollection, FakeDb


class TrackingWriteTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.repos.find_one.return_value = None
        self.db.issues.find_one.return_value = None
        self.db.productSources.find_one.return_value = None
        self.repo = RepoEdit(repo_id="owner/repo", name="Lab")
        self.issue = IssueEdit(issue_id="owner/repo#1", repo_id="owner/repo", title="Issue")

    def test_repo_create_keeps_defaults_and_normalizes_inputs(self):
        save_repo(self.db, replace(self.repo, involved_devs=" Owner, ,Other ", products=[" Foundry "], last_tested="2026-09-18"))
        self.db.repos.update_one.assert_called_once_with(
            {"id": "owner/repo"}, {"$setOnInsert": {
                "_id": "owner/repo", "id": "owner/repo", "name": "Lab", "status": "Live", "lastUpdated": None,
                "involvedDevs": ["Owner", "Other"], "products": ["Foundry"],
                "lastTested": datetime(2026, 9, 18, tzinfo=timezone.utc),
            }}, upsert=True,
        )

    def test_repo_edit_does_not_change_synced_fields(self):
        save_repo(self.db, replace(self.repo, existing_id="original/repo", name="Changed"))
        self.db.repos.update_one.assert_called_once_with(
            {"id": "original/repo"}, {"$set": {"involvedDevs": [], "products": [], "lastTested": None}},
        )

    def test_repo_validation_precedes_all_writes(self):
        for edit in (replace(self.repo, last_tested="invalid"), replace(self.repo, repo_id=""),
                     replace(self.repo, source_urls={"Foundry": "https://example.com/"})):
            with self.subTest(edit=edit), self.assertRaises(TrackingValidationError):
                save_repo(self.db, edit)
        self.db.repos.update_one.assert_not_called()
        self.db.productSources.update_one.assert_not_called()

    def test_duplicate_repo_is_a_distinct_validation_error(self):
        self.db.repos.find_one.return_value = {"id": "owner/repo"}
        with self.assertRaisesRegex(DuplicateRecordError, "repo already exists"):
            save_repo(self.db, self.repo)
        self.db.repos.update_one.assert_not_called()

    def test_repo_source_override_is_saved(self):
        url = "https://github.blog/changelog/"
        save_repo(self.db, replace(self.repo, source_urls={"Foundry": url}))
        self.db.productSources.update_one.assert_called_once_with({"_id": "Foundry"}, {"$set": {"url": url}}, upsert=True)

    def test_issue_create_initializes_history_and_normalizes_aliases(self):
        save_issue(self.db, replace(self.issue, type_of_issue="SDK/code update", resolution="Updated instructions", reproduction_notes=" Evidence "))
        query, update = self.db.issues.update_one.call_args.args
        self.assertEqual(query, {"issueId": "owner/repo#1"})
        self.assertEqual(update["$setOnInsert"], {"_id": "owner/repo#1"})
        self.assertEqual(update["$set"]["typeOfIssue"], "SDK/code issues")
        self.assertEqual(update["$set"]["resolution"], "Fixed in lab")
        self.assertEqual(update["$set"]["title"], "Issue")
        self.assertEqual(update["$push"]["handlingHistory"]["evidence"]["reproductionNotes"], "Evidence")
        self.assertTrue(self.db.issues.update_one.call_args.kwargs["upsert"])

    def test_issue_edit_updates_manual_fields_only(self):
        self.db.issues.find_one.return_value = {"issueId": "original#1", "title": "Original", "handlingStage": "Raised"}
        save_issue(self.db, replace(self.issue, existing_id="original#1", title="Changed", state="Closed"))
        query, update = self.db.issues.update_one.call_args.args
        self.assertEqual(query, {"issueId": "original#1"})
        for field in ("title", "state", "kind", "repoId", "issueId"):
            self.assertNotIn(field, update["$set"])
        self.assertNotIn("$setOnInsert", update)
        self.assertEqual(self.db.issues.update_one.call_args.kwargs, {})

    def test_issue_validation_and_duplicates_do_not_write(self):
        for edit in (replace(self.issue, last_tested="invalid"), replace(self.issue, title=""),
                     replace(self.issue, handling_stage="Investigating"),
                     replace(self.issue, handling_stage="Waiting", progress_note="Waiting")):
            with self.subTest(edit=edit), self.assertRaises(TrackingValidationError):
                save_issue(self.db, edit)
        self.db.issues.find_one.return_value = {"issueId": "owner/repo#1"}
        with self.assertRaisesRegex(DuplicateRecordError, "issue already exists"):
            save_issue(self.db, self.issue)
        self.db.issues.update_one.assert_not_called()

    def test_unchanged_save_does_not_append_history_but_evidence_edit_does(self):
        initial = progress_update({}, "Raised", "", now=datetime(2026, 9, 18, tzinfo=timezone.utc))
        existing = {**initial["$set"], "handlingHistory": [initial["$push"]["handlingHistory"]]}
        self.db.issues.find_one.return_value = existing
        edit = replace(self.issue, existing_id=self.issue.issue_id)
        save_issue(self.db, edit)
        self.assertNotIn("$push", self.db.issues.update_one.call_args.args[1])
        save_issue(self.db, replace(edit, external_response="New evidence"))
        update = self.db.issues.update_one.call_args.args[1]
        self.assertEqual(update["$push"]["handlingHistory"]["evidence"]["externalResponse"], "New evidence")
        self.assertEqual(existing["handlingHistory"], [initial["$push"]["handlingHistory"]])

    def test_explicit_deletions_preserve_cascade_scope(self):
        delete_repo(self.db, "owner/repo")
        self.db.repos.delete_one.assert_called_once_with({"id": "owner/repo"})
        self.db.issues.delete_many.assert_called_once_with({"repoId": "owner/repo"})
        delete_issue(self.db, "other/repo#3")
        self.db.issues.delete_one.assert_called_once_with({"issueId": "other/repo#3"})


class TrackingReadTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.productSources.find_one.return_value = None
        self.db.sourceValidations.find_one.return_value = None

    def test_issue_filter_combination_keeps_alias_matching_and_includes_prs(self):
        self.db.issues = FakeCollection([
            {"issueId": "b", "repoId": "repo", "state": "Open", "status": "Open", "typeOfIssue": "SDK/code update", "kind": "PR"},
            {"issueId": "a", "repoId": "repo", "state": "Open", "status": "Open", "typeOfIssue": "SDK/code issues"},
            {"issueId": "c", "repoId": "other", "state": "Open", "typeOfIssue": "SDK/code issues"},
        ])
        rows = list_issues(self.db, IssueFilters(repo_id="repo", state="Open", status="Open", type_of_issue="SDK/code issues", missing_classification=True))
        self.assertEqual([row["issueId"] for row in rows], ["a", "b"])

    def test_missing_classification_is_not_restricted_to_open_issues(self):
        self.db.issues = FakeCollection([
            {"issueId": "a", "state": "Closed", "typeOfIssue": "UI drift", "resolution": "Unknown"},
            {"issueId": "b", "state": "Open", "typeOfIssue": "UI drift", "resolution": "Fixed in lab"},
            {"issueId": "c", "state": "Open"},
        ])
        rows = list_issues(self.db, IssueFilters(missing_classification=True))
        self.assertEqual([row["issueId"] for row in rows], ["a", "c"])
        self.assertEqual(len(list_issues(self.db, IssueFilters())), 3)

    def test_source_statuses_deduplicate_products_and_do_not_reuse_old_urls(self):
        self.db.productSources.find_one.return_value = {"url": "https://github.blog/changelog/"}
        self.db.sourceValidations.find_one.return_value = {"url": PRODUCT_SOURCES["Foundry"]["url"], "status": "Validated"}
        entries = product_source_statuses(self.db, ["Foundry", "Foundry", "Unknown"])
        self.assertEqual([entry["product"] for entry in entries], ["Foundry", "Unknown"])
        self.assertEqual(entries[0]["validation"], {})
        self.assertIsNone(entries[1]["source"])

    def test_dashboard_counts_unique_products_not_repositories(self):
        self.db.repos = FakeCollection([
            {"id": "a", "products": ["Foundry", "GitHub"]},
            {"id": "b", "products": ["Foundry", "Unknown"]},
        ])
        self.db.issues = FakeCollection([
            {"issueId": "a#1", "state": "Closed", "typeOfIssue": "Unknown"},
            {"issueId": "b#1", "state": "Open", "typeOfIssue": "UI drift", "resolution": "Fixed in lab"},
        ])
        self.db.sourceValidations.find_one.side_effect = lambda query: {"url": PRODUCT_SOURCES["GitHub"]["url"], "status": "Validated"} if query["product"] == "GitHub" else None
        self.assertEqual(dashboard_counts(self.db), {"repos": 2, "openIssues": 1, "missingClassification": 1, "sourcesNeedingValidation": 2})

    def test_repo_overview_preserves_sort_defaults_and_counts(self):
        self.db.repos = FakeCollection([
            {"id": "z", "products": []},
            {"id": "MicrosoftLearning/mslearn-ai-language", "products": []},
        ])
        self.db.issues = FakeCollection([{"repoId": "z", "state": "Open"}, {"repoId": "z", "state": "Closed"}])
        rows = repo_overview(self.db)
        self.assertEqual([row["id"] for row in rows], ["MicrosoftLearning/mslearn-ai-language", "z"])
        self.assertEqual(rows[0]["products"], ["Foundry"])
        self.assertEqual(rows[1]["openIssues"], 1)
        self.assertEqual(self.db.repos.docs[1]["products"], [])

    def test_cli_candidate_query_keeps_its_existing_policy(self):
        self.db.issues.find.return_value.sort.return_value.limit.return_value = []
        self.assertEqual(classification_candidates(self.db, 7), [])
        self.db.issues.find.assert_called_once_with({"state": "Open", "$or": [
            {"typeOfIssue": "Unknown"}, {"resolution": "Unknown"}, {"lastTested": None},
        ]})
        self.db.issues.find.return_value.sort.assert_called_once_with([("issueId", 1)])
        self.db.issues.find.return_value.sort.return_value.limit.assert_called_once_with(7)


class WebTrackingTests(unittest.TestCase):
    def setUp(self):
        from nicegui import Client, ui
        from nicegui.page import page
        from labs_tracker.ui import app

        self.ui = ui
        self.db = FakeDb(
            [{"id": "owner/repo", "name": "Lab", "products": ["Foundry"], "involvedDevs": []}],
            [{"issueId": "owner/repo#1", "repoId": "owner/repo", "title": "Original title", "kind": "Issue",
              "state": "Open", "status": "Open", "typeOfIssue": "Unknown", "resolution": "Unknown", "handlingStage": "Raised"}],
        )
        self.db.productSources = FakeCollection([])
        self.db.sourceValidations = FakeCollection([])
        self.client = Client(page("/tracking-test"), request=None)
        self.addCleanup(self.client.delete)
        self.enterContext(self.client)
        self.notify = self.enterContext(patch.object(app.ui, "notify"))
        self.state = app.build_ui(self.db)

    def element(self, **props):
        return next(element for element in reversed(list(self.client.elements.values()))
                    if all(element._props.get(key) == value for key, value in props.items()))

    def fire(self, element, event="click", args=None):
        from nicegui.events import GenericEventArguments

        listener = next(listener for listener in element._event_listeners.values() if listener.type == event)
        listener.handler(GenericEventArguments(sender=element, client=self.client, args=args))

    def dialog(self):
        return next(element for element in reversed(list(self.client.elements.values())) if isinstance(element, self.ui.dialog))

    def test_repo_create_callback_validates_and_then_closes(self):
        self.fire(self.element(icon="add"))
        self.element(label="Repo id").set_value("owner/new")
        self.element(label="Lab name").set_value("New lab")
        self.element(label="Last tested").set_value("invalid")
        self.fire(self.element(label="Save"))
        self.assertIsNone(self.db.repos.find_one({"id": "owner/new"}))
        self.assertTrue(self.dialog().value)
        self.notify.assert_called_with("Invalid lastTested format. Use ISO datetime.", color="negative")
        self.element(label="Last tested").set_value("2026-09-18")
        self.fire(self.element(label="Save"))
        saved = self.db.repos.find_one({"id": "owner/new"})
        self.assertEqual(saved["name"], "New lab")
        self.assertEqual(saved["lastTested"], datetime(2026, 9, 18, tzinfo=timezone.utc))
        self.assertFalse(self.dialog().value)
        self.notify.assert_called_with("Saved", color="positive")

    def test_duplicate_repo_warning_keeps_dialog_open(self):
        self.fire(self.element(icon="add"))
        self.element(label="Repo id").set_value("owner/repo")
        self.element(label="Lab name").set_value("Duplicate")
        self.fire(self.element(label="Save"))
        self.assertTrue(self.dialog().value)
        self.notify.assert_called_with("repo already exists", color="warning")
        self.assertEqual(len(self.db.repos.docs), 1)

    def test_report_row_save_updates_history_and_visible_report(self):
        self.fire(self.element(icon="analytics"))
        progress_table = next(element for element in self.client.elements.values()
                              if isinstance(element, self.ui.table) and any(column["name"] == "observedHours" for column in element.columns))
        self.fire(progress_table, "rowClick", {"row": progress_table.rows[0]})
        self.element(label="Handling stage").set_value("Investigating")
        self.fire(self.element(label="Save"))
        self.assertTrue(self.dialog().value)
        self.notify.assert_called_with("Add a progress note explaining the stage or waiting change", color="negative")
        self.element(label="Progress note / next action").set_value("Investigate")
        self.element(label="External response").set_value("Evidence")
        self.fire(self.element(label="Save"))
        saved = self.db.issues.docs[0]
        self.assertEqual(saved["title"], "Original title")
        self.assertEqual(saved["handlingHistory"][-1]["evidence"]["externalResponse"], "Evidence")
        self.assertEqual(progress_table.rows[0]["handlingStage"], "Investigating")
        self.assertFalse(self.dialog().value)

    def test_repo_details_save_keeps_source_urls_shared(self):
        repo_table = next(element for element in self.client.elements.values()
                          if isinstance(element, self.ui.table) and any(column["name"] == "lab" for column in element.columns)
                          and any(column["name"] == "products" for column in element.columns))
        self.fire(repo_table, "rowClick", [None, repo_table.rows[0]])
        url = "https://github.blog/changelog/"
        self.element(label="Foundry source URL (shared)").set_value(url)
        self.fire(self.element(label="Save"))
        self.assertEqual(self.db.productSources.find_one({"_id": "Foundry"})["url"], url)
        self.assertEqual(repo_table.rows[0]["releaseSources"][0]["url"], url)
        self.assertFalse(self.dialog().value)

    def test_navigation_resets_classification_mode_and_retains_repo_filters(self):
        cards = [element for element in self.client.elements.values() if "clickable-summary" in element.classes]
        issues_panel = self.element(id="issues-panel")
        repo_filter = next(element for element in issues_panel.descendants() if element._props.get("label") == "Repo")
        state_filter = next(element for element in issues_panel.descendants() if element._props.get("label") == "State")
        back = next(element for element in issues_panel.descendants() if element._props.get("icon") == "arrow_back")
        self.fire(cards[1])
        self.assertTrue(self.state.missing_classification)
        self.assertEqual(self.state.active_view, "issues")
        self.assertEqual(state_filter.value, "All")
        self.fire(back)
        self.assertFalse(issues_panel.visible)
        self.assertFalse(self.state.missing_classification)
        self.assertEqual(self.state.active_view, "dashboard")
        self.fire(cards[0])
        self.assertEqual(state_filter.value, "Open")
        self.fire(back)
        repo_table = next(element for element in self.client.elements.values()
                          if isinstance(element, self.ui.table) and element.row_key == "id")
        self.fire(repo_table, "openIssues", repo_table.rows[0])
        self.assertEqual(repo_filter.value, "owner/repo")
        self.assertEqual(state_filter.value, "Open")
        self.assertEqual(self.state.repo_id, "owner/repo")
        self.assertTrue(issues_panel.visible)

    def test_two_clients_keep_selections_filters_and_dialogs_separate(self):
        from nicegui import Client
        from nicegui.page import page
        from labs_tracker.ui.app import build_ui

        second = Client(page("/tracking-second"), request=None)
        self.addCleanup(second.delete)
        with second:
            second_state = build_ui(self.db)
        second_elements = set(second.elements)
        self.fire(self.element(icon="analytics"))
        self.fire(self.element(icon="add"))
        self.element(label="Lab name").set_value("Only first client")
        self.assertEqual(self.state.active_view, "report")
        self.assertEqual(second_state.active_view, "dashboard")
        self.assertIsNone(second_state.repo_id)
        self.assertEqual(set(second.elements), second_elements)
        self.assertFalse(any(isinstance(element, self.ui.dialog) for element in second.elements.values()))
        first_filter = self.element(label="State")
        first_filter.set_value("Closed")
        self.assertTrue(all(element.value == "All" for element in second.elements.values()
                            if isinstance(element, self.ui.select) and element._props.get("label") == "State"))
        self.fire(self.element(icon="close"))
        self.fire(self.element(icon="add"))
        self.assertEqual(self.element(label="Lab name").value, "")

    def test_report_refresh_mutates_existing_chart_options(self):
        charts = [element for element in self.client.elements.values() if isinstance(element, self.ui.echart)]
        options = [chart.options for chart in charts]
        self.db.issues.docs.append({**self.db.issues.docs[0], "issueId": "owner/repo#2"})
        self.fire(self.element(icon="analytics"))
        for chart, original in zip(charts, options):
            self.assertIs(chart.options, original)
        self.assertEqual(charts[0].options["series"][0]["data"], [2])


class PageActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from labs_tracker.ui import actions

        self.module = actions
        self.buttons = [Mock(), Mock()]
        self.source_button = Mock()
        self.on_sync = Mock()
        self.on_sources = Mock()
        self.db = Mock()
        self.actions = actions.PageActions(self.db, self.buttons, self.source_button, self.on_sync, self.on_sources)
        self.io_bound = self.enterContext(patch.object(actions.nicegui_run, "io_bound", new_callable=AsyncMock))
        self.notify = self.enterContext(patch.object(actions.ui, "notify"))
        self.notification = self.enterContext(patch.object(actions.ui, "notification")).return_value
        self.timer_factory = self.enterContext(patch.object(actions.ui, "timer"))

    def assert_sync_cleaned_up(self):
        self.assertFalse(self.actions.sync_state["running"])
        self.assertIsNone(self.actions.sync_state["timer"])
        self.assertIsNone(self.actions.sync_state["notification"])
        self.timer_factory.return_value.cancel.assert_called_once()
        self.notification.dismiss.assert_called_once()
        for button in self.buttons:
            button.disable.assert_called_once()
            button.enable.assert_called_once()
            button.classes.assert_any_call(remove="syncing-button")

    async def test_sync_guard_refresh_and_cleanup(self):
        async def sync_result(*args):
            self.assertTrue(self.actions.sync_state["running"])
            self.timer_factory.call_args.args[1]()
            self.assertEqual(self.notification.message, "Syncing issues.")
            await self.actions.run_issue_sync()
            return {"repoCount": 1, "issueCount": 2}

        self.io_bound.side_effect = sync_result
        await self.actions.run_issue_sync()
        self.io_bound.assert_awaited_once_with(self.module.sync)
        self.on_sync.assert_called_once_with()
        self.notify.assert_called_once_with("Synced 1 repo(s), 2 issue records", color="positive")
        self.assert_sync_cleaned_up()

    async def test_sync_failure_restores_controls_without_refreshing(self):
        self.io_bound.side_effect = RuntimeError("offline")
        await self.actions.run_issue_sync()
        self.notify.assert_called_once_with("Sync failed: offline", color="negative", multi_line=True)
        self.on_sync.assert_not_called()
        self.assert_sync_cleaned_up()

    async def test_sync_cancellation_still_cleans_up(self):
        self.io_bound.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.actions.run_issue_sync()
        self.on_sync.assert_not_called()
        self.assert_sync_cleaned_up()

    async def test_source_validation_refreshes_and_reports_partial_failure(self):
        self.io_bound.return_value = [{"status": "Validated"}, {"status": "Failed"}]
        await self.actions.run_source_validation()
        self.io_bound.assert_awaited_once_with(self.module.validate_all_sources, self.db)
        self.notify.assert_called_once_with("Validated 1/2 product sources", color="warning")
        self.on_sources.assert_called_once_with()
        self.source_button.disable.assert_called_once()
        self.source_button.enable.assert_called_once()
        self.notification.dismiss.assert_called_once()

    async def test_source_validation_failure_restores_button(self):
        self.io_bound.side_effect = RuntimeError("offline")
        await self.actions.run_source_validation()
        self.notify.assert_called_once_with("Source validation failed: offline", color="negative", multi_line=True)
        self.on_sources.assert_not_called()
        self.source_button.enable.assert_called_once()
        self.notification.dismiss.assert_called_once()

    async def test_action_state_is_client_local(self):
        other = self.module.PageActions(self.db, [Mock()], Mock(), Mock(), Mock())
        self.actions.sync_state["running"] = True
        self.io_bound.return_value = {"repoCount": 0, "issueCount": 0}
        await other.run_issue_sync()
        self.io_bound.assert_awaited_once()
        self.assertTrue(self.actions.sync_state["running"])
        self.assertFalse(other.sync_state["running"])