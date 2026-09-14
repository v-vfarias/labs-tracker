"""Local NiceGUI CRUD app for simplified labs tracker data."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from nicegui import run as nicegui_run, ui

from .config import load_settings
from .db import ensure_indexes, get_database
from .models import ISSUE_TYPE_VALUES, KIND_VALUES, RESOLUTION_VALUES, STATE_VALUES, STATUS_VALUES
from .report import generate_report
from .sync import simplify_collections, sync
from .tasks import generate_tasks


def _db():
    db = get_database(load_settings())
    ensure_indexes(db)
    return db


def _to_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _fmt_dt(value) -> str:
    dt = _to_dt(value)
    return dt.isoformat() if dt else ""


def _parse_dt(value: str):
    value = value.strip()
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_ui():
    db = _db()
    ui.label("Labs Tracker").classes("text-h4")

    tabs = ui.tabs().classes("w-full")
    repos_tab = ui.tab("Repos")
    issues_tab = ui.tab("Issues/PRs")
    tasks_tab = ui.tab("Tasks")
    reports_tab = ui.tab("Reports/Export")

    repo_selected: dict[str, str | None] = {"id": None}
    issue_selected: dict[str, str | None] = {"id": None}

    with ui.tab_panels(tabs, value=repos_tab).classes("w-full"):
        with ui.tab_panel(repos_tab):
            ui.label("Repos").classes("text-h6")
            repo_table = ui.table(
                columns=[
                    {"name": "id", "label": "id", "field": "id"},
                    {"name": "name", "label": "name", "field": "name"},
                    {"name": "involvedDevs", "label": "involvedDevs", "field": "involvedDevs"},
                    {"name": "products", "label": "products", "field": "products"},
                    {"name": "status", "label": "status", "field": "status"},
                    {"name": "lastUpdated", "label": "lastUpdated", "field": "lastUpdated"},
                    {"name": "lastTested", "label": "lastTested", "field": "lastTested"},
                ],
                rows=[],
                row_key="id",
                pagination=20,
            ).classes("w-full")

            def refresh_repos():
                rows = []
                for doc in db.repos.find({}).sort("id", 1):
                    rows.append(
                        {
                            "id": doc.get("id"),
                            "name": doc.get("name"),
                            "involvedDevs": ", ".join(doc.get("involvedDevs") or []),
                            "products": ", ".join(doc.get("products") or []),
                            "status": doc.get("status"),
                            "lastUpdated": _fmt_dt(doc.get("lastUpdated")),
                            "lastTested": _fmt_dt(doc.get("lastTested")),
                        }
                    )
                repo_table.rows = rows
                repo_table.update()

            def save_repo(existing_id: str | None, repo_id: str, name: str, involved_devs: str, products: str, last_tested: str):
                try:
                    parsed_last_tested = _parse_dt(last_tested)
                except ValueError:
                    ui.notify("Invalid lastTested format. Use ISO datetime.", color="negative")
                    return
                payload = {
                    "involvedDevs": _parse_csv(involved_devs),
                    "products": _parse_csv(products),
                    "lastTested": parsed_last_tested,
                }
                if existing_id:
                    db.repos.update_one({"id": existing_id}, {"$set": payload})
                else:
                    if not repo_id or not name:
                        ui.notify("id and name are required", color="negative")
                        return
                    if db.repos.find_one({"id": repo_id}):
                        ui.notify("repo already exists", color="warning")
                        return
                    db.repos.update_one(
                        {"id": repo_id},
                        {
                            "$setOnInsert": {
                                "_id": repo_id,
                                "id": repo_id,
                                "name": name,
                                "status": "Live",
                                "lastUpdated": None,
                                "involvedDevs": payload["involvedDevs"],
                                "products": payload["products"],
                                "lastTested": payload["lastTested"],
                            },
                        },
                        upsert=True,
                    )
                refresh_repos()
                ui.notify("Saved", color="positive")

            def open_repo_dialog(existing_id: str | None = None):
                existing = db.repos.find_one({"id": existing_id}) if existing_id else {}
                with ui.dialog() as dialog, ui.card().classes("w-96"):
                    ui.label("Edit repo" if existing_id else "New repo")
                    repo_id_input = ui.input("id (owner/repo)", value=existing.get("id", ""))
                    repo_name_input = ui.input("name", value=existing.get("name", ""))
                    involved_input = ui.input("involvedDevs (comma-separated)", value=", ".join(existing.get("involvedDevs") or []))
                    products_input = ui.input("products (comma-separated)", value=", ".join(existing.get("products") or []))
                    last_tested_input = ui.input("lastTested (ISO datetime or blank)", value=_fmt_dt(existing.get("lastTested")))
                    if existing_id:
                        repo_id_input.disable()
                        repo_name_input.disable()
                    with ui.row():
                        ui.button(
                            "Save",
                            on_click=lambda: (
                                save_repo(
                                    existing_id,
                                    repo_id_input.value,
                                    repo_name_input.value,
                                    involved_input.value,
                                    products_input.value,
                                    last_tested_input.value,
                                ),
                                dialog.close(),
                            ),
                        )
                        ui.button("Cancel", on_click=dialog.close)
                dialog.open()

            def delete_repo():
                if not repo_selected["id"]:
                    ui.notify("Select a repo first", color="warning")
                    return
                db.repos.delete_one({"id": repo_selected["id"]})
                db.issues.delete_many({"repoId": repo_selected["id"]})
                repo_selected["id"] = None
                refresh_repos()
                refresh_issues()
                ui.notify("Repo deleted", color="positive")

            repo_table.on("rowClick", lambda e: repo_selected.update({"id": e.args["row"]["id"]}))

            with ui.row():
                ui.button("Refresh", on_click=refresh_repos)
                ui.button("New repo", on_click=lambda: open_repo_dialog(None))
                ui.button("Edit selected", on_click=lambda: open_repo_dialog(repo_selected["id"]))
                ui.button("Delete selected", on_click=delete_repo, color="negative")

            refresh_repos()

        with ui.tab_panel(issues_tab):
            ui.label("Issues / PRs").classes("text-h6")
            with ui.row().classes("items-center"):
                repo_filter = ui.select([], value="All", label="repo")
                kind_filter = ui.select(["All", *KIND_VALUES], value="All", label="kind")
                state_filter = ui.select(["All", *STATE_VALUES], value="All", label="state")
                type_filter = ui.select(["All", *ISSUE_TYPE_VALUES], value="All", label="typeOfIssue")
                status_filter = ui.select(["All", *STATUS_VALUES], value="All", label="status")

            issues_table = ui.table(
                columns=[
                    {"name": "issueId", "label": "issueId", "field": "issueId"},
                    {"name": "repoId", "label": "repoId", "field": "repoId"},
                    {"name": "kind", "label": "kind", "field": "kind"},
                    {"name": "title", "label": "title", "field": "title"},
                    {"name": "state", "label": "state", "field": "state"},
                    {"name": "typeOfIssue", "label": "typeOfIssue", "field": "typeOfIssue"},
                    {"name": "resolution", "label": "resolution", "field": "resolution"},
                    {"name": "status", "label": "status", "field": "status"},
                    {"name": "lastTested", "label": "lastTested", "field": "lastTested"},
                ],
                rows=[],
                row_key="issueId",
                pagination=20,
            ).classes("w-full")

            def refresh_issues():
                repo_values = sorted(doc.get("id") for doc in db.repos.find({}, {"id": 1, "_id": 0}) if doc.get("id"))
                repo_filter.options = ["All", *repo_values]
                query = {}
                if repo_filter.value and repo_filter.value != "All":
                    query["repoId"] = repo_filter.value
                if kind_filter.value and kind_filter.value != "All":
                    query["kind"] = kind_filter.value
                if state_filter.value and state_filter.value != "All":
                    query["state"] = state_filter.value
                if type_filter.value and type_filter.value != "All":
                    query["typeOfIssue"] = type_filter.value
                if status_filter.value and status_filter.value != "All":
                    query["status"] = status_filter.value

                rows = []
                for doc in db.issues.find(query).sort("issueId", 1):
                    rows.append(
                        {
                            "issueId": doc.get("issueId"),
                            "repoId": doc.get("repoId"),
                            "kind": doc.get("kind"),
                            "title": doc.get("title"),
                            "state": doc.get("state"),
                            "typeOfIssue": doc.get("typeOfIssue"),
                            "resolution": doc.get("resolution"),
                            "status": doc.get("status"),
                            "lastTested": _fmt_dt(doc.get("lastTested")),
                        }
                    )
                issues_table.rows = rows
                issues_table.update()

            def save_issue(existing_id: str | None, issue_id: str, repo_id: str, kind: str, title: str, state: str, type_of_issue: str, resolution: str, status: str, last_tested: str):
                try:
                    parsed_last_tested = _parse_dt(last_tested)
                except ValueError:
                    ui.notify("Invalid lastTested format. Use ISO datetime.", color="negative")
                    return
                manual = {
                    "typeOfIssue": type_of_issue,
                    "resolution": resolution,
                    "status": status,
                    "lastTested": parsed_last_tested,
                }
                if existing_id:
                    db.issues.update_one({"issueId": existing_id}, {"$set": manual})
                else:
                    if not issue_id or not repo_id or not title:
                        ui.notify("issueId, repoId, and title are required", color="negative")
                        return
                    if db.issues.find_one({"issueId": issue_id}):
                        ui.notify("issue/pr already exists", color="warning")
                        return
                    db.issues.update_one(
                        {"_id": issue_id},
                        {
                            "$set": {
                                "issueId": issue_id,
                                "repoId": repo_id,
                                "kind": kind,
                                "title": title,
                                "state": state,
                                **manual,
                            }
                        },
                        upsert=True,
                    )
                refresh_issues()
                ui.notify("Saved", color="positive")

            def open_issue_dialog(existing_id: str | None = None):
                existing = db.issues.find_one({"issueId": existing_id}) if existing_id else {}
                with ui.dialog() as dialog, ui.card().classes("w-[40rem]"):
                    ui.label("Edit issue/pr" if existing_id else "New issue/pr")
                    issue_id_input = ui.input("issueId (owner/repo#number)", value=existing.get("issueId", ""))
                    repo_id_input = ui.input("repoId (owner/repo)", value=existing.get("repoId", ""))
                    kind_input = ui.select(KIND_VALUES, value=existing.get("kind", KIND_VALUES[0]), label="kind")
                    title_input = ui.input("title", value=existing.get("title", ""))
                    state_input = ui.select(STATE_VALUES, value=existing.get("state", STATE_VALUES[0]), label="state")
                    type_input = ui.select(ISSUE_TYPE_VALUES, value=existing.get("typeOfIssue", "Unknown"), label="typeOfIssue")
                    resolution_input = ui.select(RESOLUTION_VALUES, value=existing.get("resolution", "Unknown"), label="resolution")
                    status_input = ui.select(STATUS_VALUES, value=existing.get("status", "Open"), label="status")
                    last_tested_input = ui.input("lastTested (ISO datetime or blank)", value=_fmt_dt(existing.get("lastTested")))
                    if existing_id:
                        issue_id_input.disable()
                        repo_id_input.disable()
                        kind_input.disable()
                        title_input.disable()
                        state_input.disable()
                    with ui.row():
                        ui.button(
                            "Save",
                            on_click=lambda: (
                                save_issue(
                                    existing_id,
                                    issue_id_input.value,
                                    repo_id_input.value,
                                    kind_input.value,
                                    title_input.value,
                                    state_input.value,
                                    type_input.value,
                                    resolution_input.value,
                                    status_input.value,
                                    last_tested_input.value,
                                ),
                                dialog.close(),
                            ),
                        )
                        ui.button("Cancel", on_click=dialog.close)
                dialog.open()

            def delete_issue():
                if not issue_selected["id"]:
                    ui.notify("Select an issue/pr first", color="warning")
                    return
                db.issues.delete_one({"issueId": issue_selected["id"]})
                issue_selected["id"] = None
                refresh_issues()
                ui.notify("Issue/PR deleted", color="positive")

            issues_table.on("rowClick", lambda e: issue_selected.update({"id": e.args["row"]["issueId"]}))
            for control in [repo_filter, kind_filter, state_filter, type_filter, status_filter]:
                control.on("update:model-value", lambda _: refresh_issues())

            with ui.row():
                ui.button("Refresh", on_click=refresh_issues)
                ui.button("New issue/pr", on_click=lambda: open_issue_dialog(None))
                ui.button("Edit selected", on_click=lambda: open_issue_dialog(issue_selected["id"]))
                ui.button("Delete selected", on_click=delete_issue, color="negative")

            refresh_issues()

        with ui.tab_panel(tasks_tab):
            ui.label("Tasks").classes("text-h6")
            tasks_table = ui.table(
                columns=[
                    {"name": "priority", "label": "priority", "field": "priority"},
                    {"name": "reason", "label": "reason", "field": "reason"},
                    {"name": "repoId", "label": "repoId", "field": "repoId"},
                    {"name": "issueId", "label": "issueId", "field": "issueId"},
                    {"name": "kind", "label": "kind", "field": "kind"},
                    {"name": "state", "label": "state", "field": "state"},
                    {"name": "title", "label": "title", "field": "title"},
                ],
                rows=[],
                row_key="issueId",
                pagination=30,
            ).classes("w-full")

            def refresh_tasks():
                tasks_table.rows = generate_tasks(db)
                tasks_table.update()

            ui.button("Refresh tasks", on_click=refresh_tasks)
            refresh_tasks()

        with ui.tab_panel(reports_tab):
            ui.label("Reports / Export").classes("text-h6")
            ui.label("Generate local markdown and CSV exports from simplified model.")

            async def export_reports():
                path = await nicegui_run.io_bound(generate_report, db, Path("reports"))
                ui.notify(f"Exported report to {path}", color="positive")

            async def run_sync():
                result = await nicegui_run.io_bound(sync)
                ui.notify(f"Synced {result['repoCount']} repo(s), {result['issueCount']} issue/pr records", color="positive")
                refresh_repos()
                refresh_issues()
                refresh_tasks()

            async def run_simplify():
                result = await nicegui_run.io_bound(simplify_collections, None, True)
                ui.notify(f"Simplified to {result['repos']} repos and {result['issues']} issue/pr records", color="positive")
                refresh_repos()
                refresh_issues()
                refresh_tasks()

            with ui.row():
                ui.button("Sync from GitHub", on_click=run_sync)
                ui.button("Simplify existing data", on_click=run_simplify)
                ui.button("Export markdown + CSV", on_click=export_reports)


def run(host: str = "127.0.0.1", port: int = 8080):
    @ui.page("/")
    def _home():
        _build_ui()

    ui.run(host=host, port=port, title="Labs Tracker", reload=False)


if __name__ == "__main__":
    run()
