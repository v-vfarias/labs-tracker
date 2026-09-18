"""Issues widgets and refresh behavior for one client."""
from collections.abc import Callable
from nicegui import ui

from ...domain.models import ISSUE_TYPE_VALUES, STATE_VALUES, STATUS_VALUES, normalize_issue_type, normalize_resolution
from ...domain.workflow import progress_metrics, waiting_details
from ...services import tracking
from ...services.tracking import IssueFilters
from ..formatting import _issue_url, _issue_number, _repo_lab_name
from ..state import PageState


class IssuesView:
    def __init__(self, db, state: PageState, on_change: Callable[[], None]):
        self.db = db
        self.state = state
        self.on_change = on_change
        with ui.column().classes("w-full").props("id=issues-panel") as self.issues_panel:
            with ui.row().classes("section-header"):
                with ui.row().classes("view-toolbar"):
                    self.back_button = ui.button(icon="arrow_back").props("flat round dense")
                    self.back_button.tooltip("Back to dashboard")
                    with ui.column().classes("gap-1"):
                        self.issues_heading = ui.label("Issues").classes("section-heading")
                        ui.label("Classify root causes, track outcomes, and jump to GitHub when context matters.").classes("section-hint")
                with ui.row().classes("section-actions"):
                    self.issue_sync_button = ui.button(icon="sync").props("flat round dense")
                    self.issue_sync_button.tooltip("Sync issues")
                    self.issue_refresh_button = ui.button(icon="refresh").props("flat round dense")
                    self.issue_refresh_button.tooltip("Refresh issues")

            with ui.row().classes("filter-row"):
                self.repo_filter = ui.select(["All"], value="All", label="Repo").classes("repo-filter")
                self.state_filter = ui.select(["All", *STATE_VALUES], value="All", label="State").classes("filter-select")
                self.type_filter = ui.select(["All", *ISSUE_TYPE_VALUES], value="All", label="Issue type").classes("filter-select")
                self.status_filter = ui.select(["All", *STATUS_VALUES], value="All", label="Status").classes("filter-select")
            self.issue_summary = ui.label("").classes("section-hint")

            self.issues_table = ui.table(
                columns=[
                    {"name": "issueNumber", "label": "#", "field": "issueNumber", "sortable": True, "align": "left", "classes": "issue-id-cell", "headerClasses": "issue-id-cell"},
                    {"name": "lab", "label": "Lab", "field": "lab", "sortable": True, "align": "left", "classes": "lab-cell", "headerClasses": "lab-cell"},
                    {"name": "title", "label": "Title", "field": "title", "sortable": True, "align": "left", "classes": "title-cell", "headerClasses": "title-cell"},
                    {"name": "handlingStage", "label": "Handling", "field": "handlingStage", "sortable": True, "align": "left", "classes": "medium-cell", "headerClasses": "medium-cell"},
                    {"name": "stageHours", "label": "Stage hours", "field": "stageHours", "sortable": True, "align": "left"},
                    {"name": "waitingOn", "label": "Waiting on", "field": "waitingOn", "align": "left", "classes": "wrap-cell"},
                    {"name": "status", "label": "Status", "field": "status", "sortable": True, "align": "left", "classes": "medium-cell", "headerClasses": "medium-cell"},
                    {"name": "typeOfIssue", "label": "Issue type", "field": "typeOfIssue", "sortable": True, "align": "left", "classes": "medium-cell", "headerClasses": "medium-cell"},
                    {"name": "resolution", "label": "Resolution", "field": "resolution", "sortable": True, "align": "left", "classes": "medium-cell", "headerClasses": "medium-cell"},
                    {"name": "closingPrUrl", "label": "PR", "field": "closingPrUrl", "align": "left", "classes": "compact-cell", "headerClasses": "compact-cell"},
                ],
                rows=[],
                row_key="issueId",
                pagination=20,
            ).classes("tracker-table w-full").props("flat bordered")
            self.issues_table.add_slot(
                "body-cell-issueNumber",
                """
                <q-td :props="props">
                    <a :href="props.row.issueUrl" target="_blank" class="mini-link-button" @click.stop>{{ props.row.issueNumber }}</a>
                </q-td>
                """,
            )
            self.issues_table.add_slot(
                "body-cell-closingPrUrl",
                """
                <q-td :props="props">
                    <a v-if="props.row.closingPrUrl" :href="props.row.closingPrUrl" target="_blank" class="mini-link-button" @click.stop>PR</a>
                    <span v-else class="issue-meta">-</span>
                </q-td>
                """,
            )

        self.issues_panel.visible = False

    def refresh(self):
        repo_docs = tracking.repo_options(self.db)
        repo_values = sorted(doc.get("id") for doc in repo_docs if doc.get("id"))
        repo_names = {doc.get("id"): _repo_lab_name(doc.get("id"), doc.get("name")) for doc in repo_docs if doc.get("id")}
        self.repo_filter.options = ["All", *repo_values]
        if self.repo_filter.value and self.repo_filter.value != "All":
            self.issues_heading.text = f"Issues for {_repo_lab_name(self.repo_filter.value)}"
        elif self.state.missing_classification:
            self.issues_heading.text = "Issues missing classification"
        else:
            self.issues_heading.text = "All issues"
        self.issues_heading.update()
        filters = IssueFilters(
            repo_id=self.repo_filter.value,
            state=self.state_filter.value,
            type_of_issue=self.type_filter.value,
            status=self.status_filter.value,
            missing_classification=self.state.missing_classification,
        )

        rows = []
        for doc in tracking.list_issues(self.db, filters):
            issue_id = doc.get("issueId")
            repo_id = doc.get("repoId")
            rows.append(
                {
                    "issueId": issue_id,
                    "issueNumber": _issue_number(issue_id),
                    "issueUrl": _issue_url(issue_id),
                    "lab": repo_names.get(repo_id, _repo_lab_name(repo_id)),
                    "title": doc.get("title"),
                    "state": doc.get("state"),
                    **progress_metrics(doc),
                    "waitingOn": " / ".join(value for value in waiting_details(doc) if value and value != "None"),
                    "typeOfIssue": normalize_issue_type(doc.get("typeOfIssue")),
                    "resolution": normalize_resolution(doc.get("resolution")),
                    "status": doc.get("status"),
                    "closingPrUrl": doc.get("closingPrUrl") or "",
                }
            )
        rows.sort(key=lambda row: (0 if row.get("state") == "Open" else 1, row.get("issueId") or ""))
        open_count = sum(1 for row in rows if row.get("state") == "Open")
        closed_count = sum(1 for row in rows if row.get("state") == "Closed")
        self.issue_summary.text = f"Showing {open_count} open and {closed_count} closed issue(s)."
        self.issue_summary.update()
        self.issues_table.rows = rows
        self.issues_table.update()
        self.on_change()

