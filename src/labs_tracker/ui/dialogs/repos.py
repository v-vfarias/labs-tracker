"""Repository forms and shared product source fields."""
from collections.abc import Callable

from nicegui import ui

from ...domain.models import OWNER_VALUES, PRODUCT_VALUES
from ...domain.products import repo_products as _repo_products
from ...services import tracking
from ...services.tracking import RepoEdit, _parse_csv
from ..formatting import _fmt_dt, _repo_lab_name


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


def open_repo_details(db, repo_id: str, row: dict, save_repo: Callable[[RepoEdit], bool], reveal_repo_issues: Callable[[dict], None]):
    existing = tracking.get_repo(db, repo_id) or {}
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
                ui.label(row.get("releaseStatus") or "Unknown").classes("issue-title")
        ui.label(row.get("releaseSummary") or "No release summary.").classes("section-hint")
        edited_sources = source_url_fields(db, products_input)
        for source in row.get("releaseSources", []):
            with ui.column().classes("w-full gap-1"):
                if source["url"]:
                    ui.link(source["product"], source["url"], new_tab=True).classes("external-link")
                else:
                    ui.label(source["product"])
                ui.label(f"{source['status']}: {source['summary']}").classes("section-hint w-full break-words")
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

