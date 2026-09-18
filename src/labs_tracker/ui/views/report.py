"""Report widgets and refresh behavior for one client."""
from nicegui import ui

from ...domain.models import ISSUE_TYPE_VALUES, STATE_VALUES, STATUS_VALUES
from ...services import tracking
from ...services.reports import build_issue_report
from ..formatting import _fmt_table_dt


def _chart_options(title: str, rows: list[dict], *, chart_type: str = "bar") -> dict:
    labels = [str(row.get("label", "Unknown")) for row in rows[:8]]
    values = [int(row.get("count", 0)) for row in rows[:8]]
    if chart_type == "donut":
        return {
            "title": {"text": title, "left": "center", "textStyle": {"fontSize": 14, "fontWeight": 700, "color": "#183642"}},
            "tooltip": {"trigger": "item"},
            "legend": {"bottom": 0, "type": "scroll"},
            "series": [
                {
                    "type": "pie",
                    "radius": ["44%", "68%"],
                    "center": ["50%", "46%"],
                    "avoidLabelOverlap": True,
                    "itemStyle": {"borderRadius": 6, "borderColor": "#fffdf8", "borderWidth": 2},
                    "data": [{"name": label, "value": value} for label, value in zip(labels, values, strict=False)],
                }
            ],
        }
    return {
        "title": {"text": title, "left": 8, "textStyle": {"fontSize": 14, "fontWeight": 700, "color": "#183642"}},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 44, "right": 18, "top": 54, "bottom": 72},
        "xAxis": {"type": "category", "data": labels, "axisLabel": {"interval": 0, "rotate": 28, "fontSize": 10}},
        "yAxis": {"type": "value", "minInterval": 1},
        "series": [{"type": "bar", "data": values, "barMaxWidth": 34, "itemStyle": {"color": "#0f766e", "borderRadius": [6, 6, 0, 0]}}],
    }


class ReportView:
    def __init__(self, db):
        self.db = db
        with ui.column().classes("w-full gap-4") as self.report_panel:
            with ui.row().classes("section-header"):
                with ui.row().classes("view-toolbar"):
                    self.report_back_button = ui.button(icon="arrow_back").props("flat round dense")
                    self.report_back_button.tooltip("Back to dashboard")
                    with ui.column().classes("gap-1"):
                        ui.label("Issue report").classes("section-heading")
                        ui.label("A compact view of classification, resolution, and workflow patterns across the selected issues.").classes("section-hint")
                with ui.row().classes("section-actions"):
                    self.report_pdf_button = ui.button(icon="picture_as_pdf").props("flat round dense")
                    self.report_pdf_button.tooltip("Print or save as PDF")
                    self.report_refresh_button = ui.button(icon="refresh").props("flat round dense")
                    self.report_refresh_button.tooltip("Refresh report")

            with ui.row().classes("filter-row"):
                self.report_repo_filter = ui.select(["All"], value="All", label="Repo").classes("repo-filter")
                self.report_state_filter = ui.select(["All", *STATE_VALUES], value="All", label="State").classes("filter-select")
                self.report_type_filter = ui.select(["All", *ISSUE_TYPE_VALUES], value="All", label="Issue type").classes("filter-select")
                self.report_status_filter = ui.select(["All", *STATUS_VALUES], value="All", label="Status").classes("filter-select")

            with ui.element("div").classes("summary-grid"):
                with ui.column().classes("summary-card report-metric"):
                    ui.label("Total issues").classes("summary-label")
                    self.report_total_value = ui.label("0").classes("summary-value")
                with ui.column().classes("summary-card report-metric"):
                    ui.label("Open").classes("summary-label")
                    self.report_open_value = ui.label("0").classes("summary-value")
                with ui.column().classes("summary-card report-metric"):
                    ui.label("Closed").classes("summary-label")
                    self.report_closed_value = ui.label("0").classes("summary-value")
                with ui.column().classes("summary-card report-metric"):
                    ui.label("Classification types").classes("summary-label")
                    self.report_type_count_value = ui.label("0").classes("summary-value")

            with ui.element("div").classes("report-chart-grid"):
                self.type_chart = ui.echart(_chart_options("Issue Classification", [])).classes("report-chart")
                self.resolution_chart = ui.echart(_chart_options("Resolution", [], chart_type="donut")).classes("report-chart")
                self.status_chart = ui.echart(_chart_options("Workflow Status", [])).classes("report-chart")
                self.repo_chart = ui.echart(_chart_options("Issues by Repo", [])).classes("report-chart")

            self.report_summary = ui.label("").classes("section-hint")
            ui.label("Resolution progress").classes("section-heading")
            self.progress_table = ui.table(
                columns=[
                    {"name": field, "label": label, "field": field, "sortable": True, "align": "left", "classes": "wrap-cell"}
                    for field, label in [
                        ("issueId", "Issue"), ("handlingStage", "Handling"),
                        ("trackedSince", "Tracked since (UTC)"), ("observedHours", "Observed hours"),
                        ("waitingHours", "Waiting hours"), ("stageDurations", "Time by stage"),
                        ("delayReasons", "Delay reasons"), ("latestProgress", "Latest progress"),
                    ]
                ], rows=[], row_key="issueId", pagination=10,
            ).classes("tracker-table w-full").props("flat bordered")
            self.progress_table.tooltip("Elapsed time since first progress entry, excluding resolved periods; not effort or full issue age. Blank times mean no recorded history.")
            self.report_table = ui.table(
                columns=[
                    {"name": "label", "label": "Classification", "field": "label", "sortable": True, "align": "left", "classes": "wrap-cell", "headerClasses": "wrap-cell"},
                    {"name": "count", "label": "Issues", "field": "count", "sortable": True, "align": "left", "classes": "compact-cell", "headerClasses": "compact-cell"},
                ],
                rows=[],
                row_key="label",
                pagination=10,
            ).classes("tracker-table w-full").props("flat bordered")

        self.report_panel.visible = False

    def filters(self) -> dict[str, str]:
        return {
            "repoId": self.report_repo_filter.value or "All",
            "state": self.report_state_filter.value or "All",
            "typeOfIssue": self.report_type_filter.value or "All",
            "status": self.report_status_filter.value or "All",
        }

    def refresh(self):
        repo_values = sorted(doc.get("id") for doc in tracking.repo_options(self.db) if doc.get("id"))
        self.report_repo_filter.options = ["All", *repo_values]
        report = build_issue_report(self.db, self.filters())
        self.report_total_value.text = str(report["total"])
        self.report_open_value.text = str(report["open"])
        self.report_closed_value.text = str(report["closed"])
        self.report_type_count_value.text = str(len(report["byType"]))
        for value in [self.report_total_value, self.report_open_value, self.report_closed_value, self.report_type_count_value]:
            value.update()
        for chart, options in [
            (self.type_chart, _chart_options("Issue Classification", report["byType"])),
            (self.resolution_chart, _chart_options("Resolution", report["byResolution"], chart_type="donut")),
            (self.status_chart, _chart_options("Workflow Status", report["byStatus"])),
            (self.repo_chart, _chart_options("Issues by Repo", report["byRepo"])),
        ]:
            chart.options.clear()
            chart.options.update(options)
            chart.update()
        self.report_table.rows = report["byType"]
        self.report_table.update()
        self.progress_table.rows = [{**row, "trackedSince": _fmt_table_dt(row["trackedSince"])} for row in report["longestRunning"]]
        self.progress_table.update()
        self.report_summary.text = f"Showing {report['total']} issue(s) for the selected parameters. Print or save as PDF uses this same filtered report view."
        self.report_summary.update()

    async def export_pdf(self):
        self.refresh()
        ui.notify("Use the print dialog to save this report as PDF", color="info")
        await ui.run_javascript("setTimeout(() => window.print(), 150)")

