"""Issue editing and progress history dialog."""
from collections.abc import Callable

from nicegui import ui

from ...domain.models import HANDLING_STAGE_VALUES, ISSUE_TYPE_VALUES, KIND_VALUES, RESOLUTION_VALUES, STATE_VALUES, STATUS_VALUES, WAIT_REASON_VALUES, normalize_issue_type, normalize_resolution
from ...domain.workflow import handling_stage as current_handling_stage, progress_metrics, waiting_details
from ...services import tracking
from ...services.tracking import IssueEdit
from ..formatting import _fmt_dt, _fmt_table_dt, _issue_url


def open_issue_dialog(db, save_issue: Callable[[IssueEdit], bool], existing_id: str | None = None):
    existing = tracking.get_issue(db, existing_id) if existing_id else {}
    with ui.dialog() as dialog, ui.card().classes("dialog-card"):
        with ui.row().classes("dialog-header"):
            ui.label("Issue details" if existing_id else "New issue").classes("section-heading dialog-header-title")
            close_button = ui.button(icon="close", on_click=dialog.close).props("flat round dense").classes("dialog-close")
            close_button.tooltip("Close")
        current_stage = current_handling_stage(existing or {})
        reason, waiting_on = waiting_details(existing or {})
        with ui.element("div").classes("manual-grid"):
            handling_input = ui.select(HANDLING_STAGE_VALUES, value=current_stage, label="Handling stage").classes("w-full")
            progress_note_input = ui.textarea("Progress note / next action", value="").classes("w-full").props("autogrow")
            waiting_reason_input = ui.select(WAIT_REASON_VALUES, value=reason, label="Waiting reason").classes("w-full")
            waiting_on_input = ui.input("Waiting on (person/team/vendor)", value=waiting_on).classes("w-full")
            waiting_reason_input.bind_visibility_from(handling_input, "value", value="Waiting")
            waiting_on_input.bind_visibility_from(handling_input, "value", value="Waiting")
        metrics = progress_metrics(existing or {})
        if metrics["trackedSince"]:
            ui.label(f"Observed: {metrics['observedHours']}h | Waiting: {metrics['waitingHours']}h").classes("issue-meta").tooltip("Elapsed time since first recorded progress, excluding resolved periods; not effort or full issue age.")
        with ui.expansion("Progress history", icon="history").classes("w-full"):
            for event in reversed((existing or {}).get("handlingHistory") or []):
                ui.label(f"{_fmt_table_dt(event['at'])} UTC | {event['stage']}").classes("text-weight-medium")
                ui.label(event.get("note") or "Tracking started").classes("w-full break-words whitespace-pre-wrap")
                if event.get("waitingReason") != "None":
                    ui.label(f"{event.get('waitingReason', '')} | {event.get('waitingOn', '')}").classes("issue-meta")
                if event.get("previousStage"):
                    ui.label(f"Previous recorded stage: {event['previousStage']}").classes("issue-meta")
                with ui.expansion("Evidence", icon="description").classes("w-full"):
                    for key, label in [("reproductionNotes", "Investigation notes"), ("externalReportUrl", "External reference"), ("externalResponse", "External response")]:
                        value = event.get("evidence", {}).get(key)
                        if value:
                            ui.label(f"{label}: {value}").classes("w-full break-words whitespace-pre-wrap")
        if existing_id:
            ui.label(existing.get("title", "Untitled issue")).classes("issue-title")
            ui.label(f"{existing.get('state', '')} · {existing_id}").classes("issue-meta")
            issue_link = _issue_url(existing_id, existing.get("kind"))
            if issue_link:
                ui.link("Open in GitHub", issue_link, new_tab=True).classes("external-link")
            if existing.get("closingPrUrl"):
                ui.link("Open closing PR", existing["closingPrUrl"], new_tab=True).classes("external-link")
            if existing.get("externalReportUrl"):
                ui.link("Open external reference", existing["externalReportUrl"], new_tab=True).classes("external-link")
            with ui.element("div").classes("manual-grid"):
                type_input = ui.select(ISSUE_TYPE_VALUES, value=normalize_issue_type(existing.get("typeOfIssue")), label="Issue type").classes("w-full")
                resolution_input = ui.select(RESOLUTION_VALUES, value=normalize_resolution(existing.get("resolution")), label="Resolution").classes("w-full")
                status_input = ui.select(STATUS_VALUES, value=existing.get("status", "Open"), label="Status").classes("w-full")
                reproduction_input = ui.textarea("Investigation notes", value=existing.get("reproductionNotes") or "").classes("w-full")
                external_report_input = ui.input("External reference URL", value=existing.get("externalReportUrl") or "").classes("w-full")
                external_response_input = ui.textarea("External response", value=existing.get("externalResponse") or "").classes("w-full")
                last_tested_input = ui.input("Last tested", placeholder="ISO datetime or blank", value=_fmt_dt(existing.get("lastTested"))).classes("w-full")
                closing_pr_input = ui.input("Closing PR URL", placeholder="https://github.com/owner/repo/pull/123", value=existing.get("closingPrUrl") or "").classes("w-full")

            def save_and_close():
                if save_issue(IssueEdit(
                    existing_id=existing_id,
                    issue_id=existing.get("issueId", ""),
                    repo_id=existing.get("repoId", ""),
                    kind=existing.get("kind", KIND_VALUES[0]),
                    title=existing.get("title", ""),
                    state=existing.get("state", STATE_VALUES[0]),
                    type_of_issue=type_input.value,
                    resolution=resolution_input.value,
                    status=status_input.value,
                    handling_stage=handling_input.value,
                    reproduction_notes=reproduction_input.value,
                    external_report_url=external_report_input.value,
                    external_response=external_response_input.value,
                    last_tested=last_tested_input.value,
                    closing_pr_url=closing_pr_input.value,
                    progress_note=progress_note_input.value,
                    waiting_reason=waiting_reason_input.value,
                    waiting_on=waiting_on_input.value,
                )):
                    dialog.close()
        else:
            issue_id_input = ui.input("Issue id", placeholder="owner/repo#number", value="").classes("w-full")
            repo_id_input = ui.input("Repo id", placeholder="owner/repo", value="").classes("w-full")
            kind_input = ui.select(KIND_VALUES, value=KIND_VALUES[0], label="Kind").classes("w-full")
            title_input = ui.input("Title", value="").classes("w-full")
            state_input = ui.select(STATE_VALUES, value=STATE_VALUES[0], label="State").classes("w-full")
            type_input = ui.select(ISSUE_TYPE_VALUES, value="Unknown", label="Issue type").classes("w-full")
            resolution_input = ui.select(RESOLUTION_VALUES, value="Unknown", label="Resolution").classes("w-full")
            status_input = ui.select(STATUS_VALUES, value="Open", label="Status").classes("w-full")
            reproduction_input = ui.textarea("Investigation notes", value="").classes("w-full")
            external_report_input = ui.input("External reference URL", value="").classes("w-full")
            external_response_input = ui.textarea("External response", value="").classes("w-full")
            last_tested_input = ui.input("Last tested", placeholder="ISO datetime or blank", value="").classes("w-full")
            closing_pr_input = ui.input("Closing PR URL", placeholder="https://github.com/owner/repo/pull/123", value="").classes("w-full")

            def save_and_close():
                if save_issue(IssueEdit(
                    issue_id=issue_id_input.value,
                    repo_id=repo_id_input.value,
                    kind=kind_input.value,
                    title=title_input.value,
                    state=state_input.value,
                    type_of_issue=type_input.value,
                    resolution=resolution_input.value,
                    status=status_input.value,
                    handling_stage=handling_input.value,
                    reproduction_notes=reproduction_input.value,
                    external_report_url=external_report_input.value,
                    external_response=external_response_input.value,
                    last_tested=last_tested_input.value,
                    closing_pr_url=closing_pr_input.value,
                    progress_note=progress_note_input.value,
                    waiting_reason=waiting_reason_input.value,
                    waiting_on=waiting_on_input.value,
                )):
                    dialog.close()

        with ui.row().classes("dialog-actions"):
            ui.button("Save", icon="save", on_click=save_and_close).props("unelevated no-caps").classes("dialog-primary-action")
    dialog.open()

