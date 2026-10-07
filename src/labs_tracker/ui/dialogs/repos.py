"""Repository forms and shared product source fields."""
from collections.abc import Callable

from nicegui import ui

from ...domain.models import OWNER_VALUES, PRODUCT_VALUES
from ...domain.release_checks import PILOT_REPO
from ...domain.products import repo_products as _repo_products
from ...services import tracking
from ...services.tracking import RepoEdit, _parse_csv
from ..formatting import _fmt_dt, _repo_lab_name, source_signal


def source_url_fields(db, products_input):
    inputs = {}
    originals = {}
    with ui.column().classes("w-full gap-2"):
        for product, source in tracking.configured_sources(db).items():
            originals[product] = source["url"]
            field = ui.input(f"{product} source URL (shared)", value=source["url"]).classes("w-full").props("type=url")
            field.tooltip("Shared by all repos using this product. Save, then run source validation.")
            field.bind_visibility_from(products_input, "value", backward=lambda values, product=product: product in (values or []))
            inputs[product] = field
    return lambda: {product: field.value.strip() for product, field in inputs.items()
                    if product in (products_input.value or []) and field.value.strip() != originals[product]}


def open_repo_dialog(db, save_repo: Callable[[RepoEdit], bool], existing_id: str | None = None):
    existing = tracking.get_repo(db, existing_id) if existing_id else {}
    with ui.dialog() as dialog, ui.card().classes("dialog-card"):
        with ui.row().classes("dialog-header"):
            ui.label("Edit repo" if existing_id else "New repo").classes("section-heading dialog-header-title")
            close_button = ui.button(icon="close", on_click=dialog.close).props("flat round dense").classes("dialog-close")
            close_button.tooltip("Close")
        repo_id_input = ui.input("Repo id", placeholder="owner/repo", value=existing.get("id", "")).classes("w-full")
        repo_name_input = ui.input("Lab name", value=existing.get("name", "")).classes("w-full")
        involved_input = ui.select(OWNER_VALUES, value=existing.get("involvedDevs") or [], label="Owners", multiple=True).classes("w-full").props("use-chips")
        products_input = ui.select(PRODUCT_VALUES, value=_repo_products(existing.get("id"), existing.get("products") or []), label="Products", multiple=True).classes("w-full").props("use-chips")
        edited_sources = source_url_fields(db, products_input)
        last_tested_input = ui.input("Last tested", placeholder="ISO datetime or blank", value=_fmt_dt(existing.get("lastTested"))).classes("w-full")
        if existing_id:
            repo_id_input.disable()
            repo_name_input.disable()

        def save_and_close():
            if save_repo(RepoEdit(
                existing_id=existing_id,
                repo_id=repo_id_input.value,
                name=repo_name_input.value,
                involved_devs=involved_input.value,
                products=products_input.value,
                last_tested=last_tested_input.value,
                source_urls=edited_sources(),
            )):
                dialog.close()

        with ui.row().classes("dialog-actions"):
            ui.button("Save", icon="save", on_click=save_and_close).props("unelevated no-caps").classes("dialog-primary-action")
    dialog.open()

def open_repo_details(db, repo_id: str, row: dict, save_repo: Callable[[RepoEdit], bool], reveal_repo_issues: Callable[[dict], None], *,
                      check_release=None, review_release=None, release_state=None, release_enabled=False):
    existing = tracking.get_repo(db, repo_id) or {}
    source_labels = {}
    with ui.dialog() as dialog, ui.card().classes("dialog-card"):
        with ui.row().classes("dialog-header"):
            ui.label(row.get("lab") or _repo_lab_name(repo_id)).classes("section-heading dialog-header-title")
            close_button = ui.button(icon="close", on_click=dialog.close).props("flat round dense").classes("dialog-close")
            close_button.tooltip("Close")
        ui.label(repo_id).classes("issue-meta")
        with ui.element("div").classes("manual-grid"):
            products_input = ui.select(PRODUCT_VALUES, value=_parse_csv(row.get("products") or ""), label="Products", multiple=True).classes("w-full").props("use-chips")
            owners_input = ui.select(OWNER_VALUES, value=_parse_csv(row.get("owners") or ""), label="Owners", multiple=True).classes("w-full").props("use-chips")
            with ui.column().classes("gap-1"):
                ui.label("Open issues").classes("summary-label")
                ui.label(str(row.get("openIssues", 0))).classes("issue-title")
            with ui.column().classes("gap-1"):
                ui.label("Release signal").classes("summary-label")
                source_status_label = ui.label(row.get("releaseStatus") or "Unknown").classes("issue-title")
            source_summary_label = ui.label(row.get("releaseSummary") or "No release summary.").classes("section-hint")
        if repo_id == PILOT_REPO and check_release is not None:
            with ui.column().classes("w-full gap-2"):
                ui.label("Release check").classes("section-heading")
                ui.badge("Mock backend / impact not assessed", color="amber-8")
                progress = ui.label("").classes("section-hint")
                result_panel = ui.column().classes("w-full gap-2 break-words")

                def render_result(state):
                    if "sourceStatuses" in state:
                        signal = source_signal(state["sourceStatuses"])
                        source_status_label.set_text(signal["status"])
                        source_summary_label.set_text(signal["summary"])
                        for source in signal["sources"]:
                            if source["product"] in source_labels:
                                source_labels[source["product"]].set_text(f"{source['status']}: {source['summary']}")
                    result_panel.clear()
                    with result_panel:
                        attempt = state.get("lastAttempt", {})
                        result = state.get("lastSuccessfulCheck", {})
                        ui.label(f"Last attempt: {attempt.get('status', 'Not checked')} | {_fmt_dt(attempt.get('checkedAt'))}")
                        if attempt.get("error"):
                            ui.label(attempt["error"]).classes("text-negative w-full break-words")
                        ui.label(f"Lab revision: {state.get('reviewStatus', 'Not assessed')}")
                        if result:
                            ui.label(f"Last completed check: {result['status']} | {_fmt_dt(result.get('checkedAt'))}")
                            ui.label(f"{len(result.get('new', []))} new / {len(result.get('edited', []))} edited article(s)")
                            validation = result.get("sourceValidation", {})
                            ui.label(f"Source: {validation.get('status', 'Unknown')} | {validation.get('reason', '')}")
                            for summary in result.get("assessment", {}).get("summary", []):
                                ui.label(summary).classes("w-full break-words")
                            for article in state.get("articles", []):
                                ui.link(article["title"], article["url"], new_tab=True).classes("external-link w-full break-words")
                            with ui.expansion(f"Lab evidence ({len(result.get('labFiles', []))} files)").classes("w-full"):
                                ui.label(f"Commit: {result.get('labCommit', '')}").classes("w-full break-all")
                                for entry in result.get("labFiles", []):
                                    ui.link(entry["path"], entry["url"], new_tab=True).classes("external-link w-full break-words")
                        findings = state.get("findings", [])
                        if findings and review_release is not None:
                            for finding in findings:
                                ui.label(finding.get("summary", finding["id"])).classes("w-full break-words")
                            note = ui.textarea("Review note").classes("w-full")

                            async def review():
                                review_button.disable()
                                try:
                                    updated = await review_release(repo_id, [item["id"] for item in findings], note.value or "", state["version"])
                                    render_result(updated)
                                except Exception as error:
                                    ui.notify(str(error), color="negative")
                                finally:
                                    review_button.enable()
                            review_button = ui.button("Mark reviewed", icon="done_all", on_click=review).props("flat no-caps")

                async def check():
                    if edited_sources():
                        ui.notify("Save source URL changes before checking release notes", color="warning")
                        return
                    check_button.disable()
                    check_button.props("loading")
                    progress.set_text("Checking official articles and pinned lab evidence...")
                    try:
                        render_result(await check_release(repo_id))
                    except Exception as error:
                        ui.notify(str(error), color="negative")
                    finally:
                        progress.set_text("")
                        check_button.props(remove="loading")
                        check_button.enable()

                check_button = ui.button("Check release note", icon="fact_check", on_click=check).props("outline no-caps")
                if not release_enabled:
                    check_button.disable()
                    check_button.tooltip("Enable RELEASE_CHECK_ENABLED=true and restart")
                render_result(release_state or {})
        edited_sources = source_url_fields(db, products_input)
        for source in row.get("releaseSources", []):
            with ui.column().classes("w-full gap-1"):
                if source["url"]:
                    ui.link(source["product"], source["url"], new_tab=True).classes("external-link")
                else:
                    ui.label(source["product"])
                source_labels[source["product"]] = ui.label(f"{source['status']}: {source['summary']}").classes("section-hint w-full break-words")
        if row.get("repoUrl"):
            ui.link("Open repo in GitHub", row["repoUrl"], new_tab=True).classes("external-link")

        def open_issues_and_close():
            dialog.close()
            reveal_repo_issues(row)

        def save_details_and_close():
            if save_repo(RepoEdit(
                existing_id=repo_id,
                repo_id=repo_id,
                name=existing.get("name") or row.get("lab") or _repo_lab_name(repo_id),
                involved_devs=owners_input.value,
                products=products_input.value,
                last_tested=_fmt_dt(existing.get("lastTested")),
                source_urls=edited_sources(),
            )):
                dialog.close()

        with ui.row().classes("dialog-actions"):
            ui.button("Issues", icon="bug_report", on_click=open_issues_and_close).props("flat no-caps").classes("dialog-subtle-action")
            ui.button("Save", icon="save", on_click=save_details_and_close).props("unelevated no-caps").classes("dialog-primary-action")
    dialog.open()

