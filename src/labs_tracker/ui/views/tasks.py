"""Tasks and weekly work log within the existing NiceGUI page."""
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from nicegui import ui
from pymongo.errors import PyMongoError

from ...domain.models import PRODUCT_VALUES
from ...domain.tasks import (
    TASK_ACTIONS, TASK_KINDS, TERMINAL_STATES, WONT_DO_REASONS,
    TaskDraft, TaskValidationError, local_day, parse_day, utc,
)
from ...services import worklog
from ...services.reports import build_work_report, work_report_csv, work_report_markdown
from ..formatting import _table_event_row


logger = logging.getLogger(__name__)


def _columns(fields: list[str]) -> list[dict]:
    labels = {
        "bucket": "Queue", "kind": "Task type", "repoId": "Repository",
        "deferredUntil": "Revisit date", "selectedForDate": "Selected date",
        "at": "Time (local)",
    }
    return [
        {"name": field, "label": labels.get(field, field.capitalize()), "field": field, "align": "left",
         "sortable": True, "classes": "wrap-cell"}
        for field in fields
    ]


class TasksView:
    def __init__(self, db):
        self.db = db
        with ui.column().classes("w-full gap-4") as self.tasks_panel:
            with ui.row().classes("section-header"):
                self.back_button = ui.button(icon="arrow_back").props("flat round dense")
                self.back_button.tooltip("Back to dashboard")
                ui.label("Tasks").classes("section-heading")
                ui.button("New task", icon="add_task", on_click=self.open_create)
                ui.button("Suggest from stored data", icon="playlist_add", on_click=self.suggest)
                ui.button(icon="refresh", on_click=self.refresh).props("flat round dense").tooltip("Refresh tasks")
            ui.label(
                "Choose today's work manually, without a limit. Unfinished selections carry forward. "
                "Dates use this machine's local timezone. Suggestions do not fetch GitHub or release notes."
            ).classes("section-hint")
            with ui.row().classes("filter-row"):
                self.queue_filter = ui.select(
                    ["Today", "Backlog", "History", "All"], value="Today", label="Queue",
                    on_change=self.refresh,
                )
                self.kind_filter = ui.select(
                    ["All", *TASK_KINDS], value="All", label="Task type", on_change=self.refresh,
                )
                self.search = ui.input("Search title, repo or product", on_change=self.refresh)
            self.summary = ui.label("").classes("section-hint")
            self.table = ui.table(
                columns=_columns(["bucket", "title", "kind", "repoId", "product", "status", "reason", "deferredUntil"]),
                rows=[], row_key="taskId", pagination=15,
            ).classes("tracker-table w-full").props("flat bordered")
            self.table.on("rowClick", lambda event: self.open_detail(_table_event_row(event.args).get("taskId")))
            with ui.expansion("Weekly work log", icon="summarize").classes("w-full"):
                today = local_day(datetime.now(timezone.utc))
                with ui.row():
                    self.week_day = ui.input(
                        "Any date in the week", value=(today - timedelta(days=today.weekday())).isoformat(),
                    ).props("type=date")
                    ui.button("Preview week", on_click=self.preview_week)
                    ui.button("Download Markdown", on_click=lambda: self.export_week("md"))
                    ui.button("Download CSV", on_click=lambda: self.export_week("csv"))
                self.week_summary = ui.label("Monday-start weeks. Completed tasks and Won't do decisions are counted separately.")
                self.week_table = ui.table(
                    columns=_columns(["at", "title", "action", "note", "reason"]),
                    rows=[], row_key="rowId", pagination=10,
                ).classes("tracker-table w-full").props("flat bordered")
                ui.label("Outstanding at the selected week's cutoff").classes("section-heading")
                self.outstanding_table = ui.table(
                    columns=_columns(["title", "kind", "status", "selectedForDate", "deferredUntil"]),
                    rows=[], row_key="taskId", pagination=10,
                ).classes("tracker-table w-full").props("flat bordered")
        self.tasks_panel.visible = False

    def _run(self, operation: Callable[[], object]) -> bool:
        try:
            operation()
        except TaskValidationError as error:
            ui.notify(str(error), color="warning")
            return False
        except PyMongoError:
            logger.exception("Task database operation failed")
            ui.notify("Task database operation failed. Refresh to check saved state before retrying.", color="negative")
            return False
        return True

    def refresh(self) -> None:
        def load():
            worklog.retire_ineligible_suggestions(self.db)
            tasks = worklog.list_tasks(self.db)
            queue = self.queue_filter.value
            search = (self.search.value or "").strip().casefold()
            rows = []
            for task in tasks:
                if queue == "Today" and task["bucket"] not in {"Today", "Carry-over"}:
                    continue
                if queue == "Backlog" and task["bucket"] == "History":
                    continue
                if queue == "History" and task["bucket"] != "History":
                    continue
                if self.kind_filter.value != "All" and task["kind"] != self.kind_filter.value:
                    continue
                if search not in " ".join(task[key] for key in ("title", "repoId", "product")).casefold():
                    continue
                rows.append({key: task.get(key) for key in (
                    "taskId", "bucket", "title", "kind", "repoId", "product", "status", "reason", "deferredUntil",
                )})
            self.table.rows = rows
            self.table.update()
            self.summary.text = (
                f"{len(rows)} shown. {sum(task['bucket'] == 'Carry-over' for task in tasks)} carried over. "
                "Click a task to act or view its history."
                if rows else "No matching tasks. Add a task or open Backlog to select work for Today."
            )
            self.summary.update()
        self._run(load)

    def suggest(self) -> None:
        def import_suggestions():
            count = worklog.suggest_tasks(self.db)
            ui.notify(f"{count} new suggestions. Existing decisions preserved; nothing selected automatically.", color="positive")
            self.queue_filter.set_value("Backlog")
            self.refresh()
        self._run(import_suggestions)

    def _save(self, operation: Callable[[], object], dialog: ui.dialog) -> None:
        if self._run(operation):
            dialog.close()
            self.refresh()
            ui.notify("Saved", color="positive")

    def open_create(self) -> None:
        task_id = uuid4().hex
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("New task").classes("section-heading")
            title = ui.input("Title").classes("w-full")
            kind = ui.select(TASK_KINDS, value=TASK_KINDS[0], label="Task type").classes("w-full")
            repo = ui.input("Repository (optional, owner/repo)").classes("w-full")
            product = ui.select(["", *PRODUCT_VALUES], value="", label="Product (optional)").classes("w-full")
            source = ui.input("Source URL (optional, HTTPS)").classes("w-full")
            reason = ui.textarea("Why / scope / review checklist").classes("w-full")
            with ui.row():
                ui.button("Create task", on_click=lambda: self._save(
                    lambda: worklog.create_task(
                        self.db, TaskDraft(title=title.value or "", kind=kind.value,
                                           repo_id=repo.value or "", product=product.value or "",
                                           source_url=source.value or "", reason=reason.value or ""),
                        task_id=task_id,
                    ), dialog,
                ))
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    def open_detail(self, task_id: str | None) -> None:
        if not task_id:
            ui.notify("Select a task first", color="warning")
            return
        self._run(lambda: self._detail(worklog.get_task(self.db, task_id)))

    def _detail(self, task: dict) -> None:
        event_id = uuid4().hex
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
            ui.label(task["title"]).classes("section-heading")
            ui.label(f"{task['kind']} | {task['status']} | {task['repoId']} | {task['product']}")
            ui.label(task["reason"]).classes("whitespace-pre-wrap")
            if task["sourceUrl"]:
                ui.link("Open source", task["sourceUrl"], new_tab=True)
            ui.label(
                "Done: describe the outcome and evidence. Issue triage: save classification in Issues first. "
                "PR review: include verdict, reviewed revision, and tests or limitations. "
                "Release review: include sources, impact, and any follow-up. No impact found counts as Done."
            ).classes("section-hint")
            terminal = task["status"] in TERMINAL_STATES
            actions = ["Reopen", "Add note"] if terminal else [action for action in TASK_ACTIONS if action != "Reopen"]
            action = ui.select(actions, value=actions[0], label="Action").classes("w-full")
            note = ui.textarea("Outcome / progress / supporting detail").classes("w-full")
            reason = ui.select(
                {"": "No preset / custom description", **{value: value for value in WONT_DO_REASONS}},
                value="", label="Won't do reason",
            ).classes("w-full")
            reason.bind_visibility_from(action, "value", backward=lambda value: value == "Won't do")
            revisit = ui.input("Revisit date").props("type=date").classes("w-full")
            revisit.bind_visibility_from(action, "value", backward=lambda value: value == "Deferred")
            with ui.row():
                ui.button("Save action", on_click=lambda: self._save(
                    lambda: worklog.update_task(
                        self.db, task["taskId"], task["version"], action.value, event_id=event_id,
                        note=note.value or "", reason=reason.value or "", revisit=revisit.value or "",
                    ), dialog,
                ))
                ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.label("History").classes("section-heading")
            ui.table(
                columns=_columns(["at", "action", "note", "reason"]),
                rows=[{
                    "eventId": event["eventId"], "at": utc(event["at"]).astimezone().isoformat(),
                    "action": event["action"], "note": event["note"],
                    "reason": event["snapshot"]["wontDoReason"],
                } for event in task["history"]],
                row_key="eventId", pagination=5,
            ).classes("w-full")
        dialog.open()

    def _week_report(self) -> dict:
        return build_work_report(self.db, parse_day(self.week_day.value or ""))

    def preview_week(self) -> None:
        def load():
            report = self._week_report()
            self.week_summary.text = (
                f"{report['completed']} completed tasks; {report['declined']} Won't do; "
                f"{len(report['outstanding'])} outstanding. "
                f"As of {report['asOf'].astimezone().isoformat()}. "
                "Stored/manual work only; no automatic source coverage."
            )
            self.week_summary.update()
            self.week_table.rows = [{"rowId": index, **event} for index, event in enumerate(report["events"])]
            self.week_table.update()
            self.outstanding_table.rows = report["outstanding"]
            self.outstanding_table.update()
        self._run(load)

    def export_week(self, extension: str) -> None:
        def download():
            report = self._week_report()
            content = work_report_markdown(report) if extension == "md" else work_report_csv(report)
            monday = local_day(report["start"]).isoformat()
            ui.download(content.encode("utf-8"), f"work-log-{monday}.{extension}")
        self._run(download)
