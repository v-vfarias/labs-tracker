"""Dashboard widgets and refresh behavior for one client."""
from nicegui import ui

from ...services import tracking
from ..formatting import _repo_url, _repo_lab_name, source_signal


class DashboardView:
    def __init__(self, db):
        self.db = db
        with ui.column().classes("w-full gap-4") as self.dashboard_view:
            with ui.element("div").classes("summary-grid"):
                with ui.column().classes("summary-card"):
                    ui.label("Tracked repos").classes("summary-label")
                    self.repos_value = ui.label("0").classes("summary-value")
                with ui.column().classes("summary-card clickable-summary") as self.open_issues_card:
                    ui.label("Open issues").classes("summary-label")
                    self.open_issues_value = ui.label("0").classes("summary-value")
                with ui.column().classes("summary-card clickable-summary") as self.unknown_issues_card:
                    ui.label("Needs classification").classes("summary-label")
                    self.unknown_issues_value = ui.label("0").classes("summary-value")
                with ui.column().classes("summary-card"):
                    ui.label("Sources needing validation").classes("summary-label")
                    self.release_notes_value = ui.label("0").classes("summary-value")

            with ui.row().classes("section-header"):
                with ui.column().classes("gap-1"):
                    ui.label("Repos").classes("section-heading")
                    ui.label("Scan ownership, open issue load, and release-note signals across tracked labs.").classes("section-hint")

            with ui.row().classes("dashboard-toolbar"):
                self.sync_button = ui.button(icon="sync").props("flat round dense")
                self.sync_button.tooltip("Sync issues")
                self.source_validate_button = ui.button(icon="fact_check").props("flat round dense")
                self.source_validate_button.tooltip("Validate release sources")
                self.report_button = ui.button(icon="analytics").props("flat round dense")
                self.report_button.tooltip("Open issue report")
                self.refresh_repo_button = ui.button(icon="refresh").props("flat round dense")
                self.refresh_repo_button.tooltip("Refresh dashboard")
                self.new_repo_button = ui.button(icon="add").props("flat round dense")
                self.new_repo_button.tooltip("New repo")

            self.repo_table = ui.table(
                columns=[
                    {"name": "lab", "label": "Lab", "field": "lab", "sortable": True, "align": "left", "classes": "wrap-cell", "headerClasses": "wrap-cell"},
                    {"name": "products", "label": "Products", "field": "products", "align": "left", "classes": "wrap-cell", "headerClasses": "wrap-cell"},
                    {"name": "owners", "label": "Owners", "field": "owners", "align": "left", "classes": "wrap-cell", "headerClasses": "wrap-cell"},
                    {"name": "openIssues", "label": "Open issues", "field": "openIssues", "sortable": True, "align": "left"},
                    {"name": "releaseStatus", "label": "Source status", "field": "releaseStatus", "sortable": True, "align": "left"},
                    {"name": "releaseSummary", "label": "Validation evidence", "field": "releaseSummary", "align": "left", "classes": "wrap-cell", "headerClasses": "wrap-cell"},
                    {"name": "releaseSources", "label": "Sources", "field": "releaseSources", "align": "left", "classes": "wrap-cell", "headerClasses": "wrap-cell"},
                ],
                rows=[],
                row_key="id",
                pagination=20,
            ).classes("tracker-table w-full").props("flat bordered")
            self.repo_table.add_slot(
                "body-cell-lab",
                """
                <q-td :props="props">
                    <div class="repo-title-cell">
                        <span class="repo-lab-name">{{ props.row.lab }}</span>
                        <a :href="props.row.repoUrl" target="_blank" class="mini-link-button" @click.stop>Repo</a>
                    </div>
                </q-td>
                """,
            )
            self.repo_table.add_slot(
                "body-cell-releaseStatus",
                """
                <q-td :props="props">
                    <q-icon :name="props.row.releaseStatus === 'Validated' ? 'check_circle' : 'warning'"
                            :color="props.row.releaseStatus === 'Validated' ? 'teal-7' : 'amber-8'" size="18px" />
                    <span class="signal-text">{{ props.row.releaseStatus }}</span>
                </q-td>
                """,
            )
            self.repo_table.add_slot(
                "body-cell-releaseSources",
                """
                <q-td :props="props">
                    <div v-for="source in props.row.releaseSources" :key="source.product" class="q-mb-xs">
                        <a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer" class="table-link" @click.stop>{{ source.product }}</a>
                        <span v-else>{{ source.product }}</span>
                        <span class="issue-meta"> · {{ source.status }}</span>
                        <q-tooltip>{{ source.summary }}</q-tooltip>
                    </div>
                </q-td>
                """,
            )
            self.repo_table.add_slot(
                "body-cell-openIssues",
                """
                <q-td :props="props">
                    <button class="issues-link-button" @click.stop="$parent.$emit('openIssues', props.row)">{{ props.row.openIssues }} open</button>
                </q-td>
                """,
            )

    def refresh_summary(self):
        counts = tracking.dashboard_counts(self.db)
        self.repos_value.text = str(counts["repos"])
        self.open_issues_value.text = str(counts["openIssues"])
        self.unknown_issues_value.text = str(counts["missingClassification"])
        self.release_notes_value.text = str(counts["sourcesNeedingValidation"])
        for value in [self.repos_value, self.open_issues_value, self.unknown_issues_value, self.release_notes_value]:
            value.update()

    def refresh(self):
        rows = []
        for doc in tracking.repo_overview(self.db):
            repo_id = doc.get("id")
            products = doc["products"]
            release_signal = source_signal(doc["sourceStatuses"])
            rows.append(
                {
                    "id": repo_id,
                    "lab": _repo_lab_name(repo_id, doc.get("name")),
                    "products": ", ".join(products),
                    "owners": ", ".join(doc.get("involvedDevs") or []),
                    "openIssues": doc["openIssues"],
                    "repoUrl": _repo_url(repo_id),
                    "releaseStatus": release_signal["status"],
                    "releaseSummary": release_signal["summary"],
                    "releaseSources": release_signal["sources"],
                }
            )
        self.repo_table.rows = rows
        self.repo_table.update()
        self.refresh_summary()

