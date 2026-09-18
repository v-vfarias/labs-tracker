"""Page composition, navigation, and callbacks between independent views."""
from nicegui import ui

from ..services import tracking
from ..services.tracking import DuplicateRecordError, IssueEdit, RepoEdit, TrackingValidationError
from .actions import PageActions
from .dialogs import issues as issue_dialogs, repos as repo_dialogs
from .formatting import _table_event_row
from .state import PageState
from .theme import apply_theme
from .views.dashboard import DashboardView
from .views.issues import IssuesView
from .views.report import ReportView


def build_ui(db) -> PageState:
    apply_theme()

    with ui.column().classes("tracker-shell"):
        with ui.row().classes("tracker-header"):
            with ui.column().classes("gap-1"):
                ui.label("Labs Tracker").classes("tracker-title")
                ui.label("Monitor lab repositories, issue health, and product update signals in one focused workspace.").classes("tracker-subtitle")

        state = PageState()

        dashboard = DashboardView(db)

        issues = IssuesView(db, state, dashboard.refresh_summary)

        report = ReportView(db)

        def refresh_all():
            dashboard.refresh()
            issues.refresh()
            report.refresh()

        actions = PageActions(
            db,
            [dashboard.sync_button, issues.issue_sync_button],
            dashboard.source_validate_button,
            refresh_all,
            dashboard.refresh,
        )

        def show_report_page():
            state.active_view = "report"
            state.issue_id = None
            state.missing_classification = False
            dashboard.dashboard_view.visible = False
            dashboard.dashboard_view.update()
            issues.issues_panel.visible = False
            issues.issues_panel.update()
            report.report_panel.visible = True
            report.report_panel.update()
            report.refresh()

        def back_from_report():
            state.active_view = "dashboard"
            report.report_panel.visible = False
            report.report_panel.update()
            dashboard.dashboard_view.visible = True
            dashboard.dashboard_view.update()

        def save_repo(edit: RepoEdit) -> bool:
            try:
                tracking.save_repo(db, edit)
            except DuplicateRecordError as error:
                ui.notify(str(error), color="warning")
                return False
            except TrackingValidationError as error:
                ui.notify(str(error), color="negative")
                return False
            dashboard.refresh()
            ui.notify("Saved", color="positive")
            return True

        def open_repo_dialog(existing_id: str | None = None):
            repo_dialogs.open_repo_dialog(db, save_repo, existing_id)

        def delete_repo():
            if not state.repo_id:
                ui.notify("Select a repo first", color="warning")
                return
            tracking.delete_repo(db, state.repo_id)
            state.repo_id = None
            dashboard.refresh()
            issues.refresh()
            ui.notify("Repo deleted", color="positive")

        def repo_id_from_args(args) -> str | None:
            row = args if isinstance(args, dict) else _table_event_row(args)
            repo_id = row.get("id") if isinstance(row, dict) else None
            return repo_id if isinstance(repo_id, str) else None

        def show_all_open_issues():
            state.active_view = "issues"
            state.missing_classification = False
            state.issue_id = None
            issues.repo_filter.set_value("All")
            issues.state_filter.set_value("Open")
            issues.type_filter.set_value("All")
            issues.status_filter.set_value("All")
            dashboard.dashboard_view.visible = False
            dashboard.dashboard_view.update()
            issues.issues_panel.visible = True
            issues.issues_panel.update()
            issues.refresh()

        def show_missing_classification_issues():
            state.active_view = "issues"
            state.missing_classification = True
            state.issue_id = None
            issues.repo_filter.set_value("All")
            issues.state_filter.set_value("All")
            issues.type_filter.set_value("All")
            issues.status_filter.set_value("All")
            dashboard.dashboard_view.visible = False
            dashboard.dashboard_view.update()
            issues.issues_panel.visible = True
            issues.issues_panel.update()
            issues.refresh()

        def reveal_repo_issues(args):
            repo_id = repo_id_from_args(args)
            if not repo_id:
                return
            state.active_view = "issues"
            state.repo_id = repo_id
            state.issue_id = None
            state.missing_classification = False
            issues.repo_filter.set_value(repo_id)
            dashboard.dashboard_view.visible = False
            dashboard.dashboard_view.update()
            issues.issues_panel.visible = True
            issues.issues_panel.update()
            issues.refresh()

        def back_to_dashboard():
            state.active_view = "dashboard"
            state.issue_id = None
            state.missing_classification = False
            issues.issues_panel.visible = False
            issues.issues_panel.update()
            report.report_panel.visible = False
            report.report_panel.update()
            dashboard.dashboard_view.visible = True
            dashboard.dashboard_view.update()

        def open_repo_details(args):
            row = _table_event_row(args)
            repo_id = repo_id_from_args(args)
            if not repo_id:
                return
            state.repo_id = repo_id
            repo_dialogs.open_repo_details(db, repo_id, row, save_repo, reveal_repo_issues)

        def save_issue(edit: IssueEdit) -> bool:
            try:
                tracking.save_issue(db, edit)
            except DuplicateRecordError as error:
                ui.notify(str(error), color="warning")
                return False
            except TrackingValidationError as error:
                ui.notify(str(error), color="negative")
                return False
            issues.refresh()
            if report.report_panel.visible:
                report.refresh()
            ui.notify("Saved", color="positive")
            return True

        def open_issue_dialog(existing_id: str | None = None):
            issue_dialogs.open_issue_dialog(db, save_issue, existing_id)

        def delete_issue():
            if not state.issue_id:
                ui.notify("Select an issue first", color="warning")
                return
            tracking.delete_issue(db, state.issue_id)
            state.issue_id = None
            issues.refresh()
            ui.notify("Issue deleted", color="positive")

        def open_clicked_issue(args):
            issue_id = _table_event_row(args).get("issueId")
            if not issue_id:
                return
            state.issue_id = issue_id
            open_issue_dialog(issue_id)

        dashboard.sync_button.on_click(actions.run_issue_sync)
        dashboard.source_validate_button.on_click(actions.run_source_validation)
        issues.issue_sync_button.on_click(actions.run_issue_sync)
        dashboard.report_button.on_click(show_report_page)
        report.report_back_button.on_click(back_from_report)
        report.report_refresh_button.on_click(report.refresh)
        report.report_pdf_button.on_click(report.export_pdf)
        dashboard.refresh_repo_button.on_click(lambda: (dashboard.refresh(), issues.refresh()))
        issues.issue_refresh_button.on_click(lambda: issues.refresh())
        dashboard.new_repo_button.on_click(lambda: open_repo_dialog(None))
        issues.back_button.on_click(back_to_dashboard)
        dashboard.open_issues_card.on("click", lambda _: show_all_open_issues())
        dashboard.open_issues_card.tooltip("Show all open issues")
        dashboard.unknown_issues_card.on("click", lambda _: show_missing_classification_issues())
        dashboard.unknown_issues_card.tooltip("Show issues missing classification")

        dashboard.repo_table.on("rowClick", lambda e: open_repo_details(e.args))
        dashboard.repo_table.on("openIssues", lambda e: reveal_repo_issues(e.args))
        issues.issues_table.on("rowClick", lambda e: open_clicked_issue(e.args))
        report.progress_table.on("rowClick", lambda e: open_clicked_issue(e.args))
        for control in [issues.repo_filter, issues.state_filter, issues.type_filter, issues.status_filter]:
            control.on("update:model-value", lambda _: issues.refresh())
        for control in [report.report_repo_filter, report.report_state_filter, report.report_type_filter, report.report_status_filter]:
            control.on("update:model-value", lambda _: report.refresh())

        dashboard.refresh()
        issues.refresh()
        report.refresh()
    return state
