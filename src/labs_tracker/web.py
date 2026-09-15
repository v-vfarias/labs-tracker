"""Local NiceGUI CRUD app for simplified labs tracker data."""
from __future__ import annotations

from datetime import datetime, timezone

from nicegui import run as nicegui_run, ui

from .config import load_settings
from .db import ensure_indexes, get_database
from .models import ISSUE_TYPE_ALIASES, ISSUE_TYPE_VALUES, KIND_VALUES, OWNER_VALUES, PRODUCT_VALUES, RESOLUTION_VALUES, STATE_VALUES, STATUS_VALUES, normalize_issue_type, normalize_resolution
from .sync import sync


REPO_PRODUCT_DEFAULTS = {
    "MicrosoftLearning/mslearn-ai-agents": ["Foundry"],
    "MicrosoftLearning/mslearn-ai-fundamentals": ["Foundry"],
    "MicrosoftLearning/mslearn-ai-language": ["Foundry"],
    "MicrosoftLearning/mslearn-ai-studio": ["Foundry"],
    "MicrosoftLearning/mslearn-ai-vision": ["Foundry"],
    "MicrosoftLearning/mslearn-devops": ["Azure DevOps", "GitHub", "GitHub Actions"],
    "MicrosoftLearning/mslearn-genaiops": ["Foundry", "Azure Machine Learning Studio"],
    "MicrosoftLearning/mslearn-mlops": ["Azure Machine Learning Studio"],
    "MicrosoftLearning/mslearn-azure-ai": ["Foundry"],
    "MicrosoftLearning/mslearn-ai-information-extraction": ["Foundry"],
    "MicrosoftLearning/dp-300-database-administrator": ["Azure SQL"],
    "MicrosoftLearning/PL-300-Microsoft-Power-BI-Data-Analyst": ["Power BI", "Microsoft Fabric"],
    "MicrosoftLearning/mslearn-sql-developer": ["Azure SQL"],
}

LEGACY_PRODUCT_ALIASES = {
    "Azure AI services": "Foundry",
    "Azure AI Language": "Foundry",
    "Azure AI Vision": "Foundry",
    "Azure AI Document Intelligence": "Foundry",
    "Azure Machine Learning": "Azure Machine Learning Studio",
    "PowerBI": "Power BI",
}

MOCK_PRODUCT_UPDATES = {
    "Foundry": {
        "source": "Foundry release notes",
        "url": "https://learn.microsoft.com/azure/ai-foundry/whats-new",
        "summary": "Agent tooling and model catalog updates may affect setup and screenshots.",
    },
    "Azure AI Language": {
        "source": "Azure AI Language updates",
        "url": "https://learn.microsoft.com/azure/ai-services/language-service/whats-new",
        "summary": "Language service API and portal flow changes may require lab step review.",
    },
    "Azure AI Vision": {
        "source": "Azure AI Vision updates",
        "url": "https://learn.microsoft.com/azure/ai-services/computer-vision/whats-new",
        "summary": "Vision Studio and SDK updates may affect image analysis exercises.",
    },
    "Azure SQL": {
        "source": "Azure SQL updates",
        "url": "https://learn.microsoft.com/azure/azure-sql/database/doc-changes-updates-release-notes-whats-new",
        "summary": "Portal, security, and database management updates may affect SQL labs.",
    },
    "Power BI": {
        "source": "Power BI monthly update",
        "url": "https://powerbi.microsoft.com/blog/",
        "summary": "Desktop and service UX updates may change report-building steps.",
    },
    "Microsoft Fabric": {
        "source": "Fabric updates blog",
        "url": "https://blog.fabric.microsoft.com/",
        "summary": "Fabric workload updates may affect analytics and Power BI integrations.",
    },
    "Azure Machine Learning Studio": {
        "source": "Azure Machine Learning release notes",
        "url": "https://learn.microsoft.com/azure/machine-learning/azure-machine-learning-release-notes",
        "summary": "CLI, SDK, and studio updates may affect MLOps workflow labs.",
    },
    "Azure DevOps": {
        "source": "Azure DevOps release notes",
        "url": "https://learn.microsoft.com/azure/devops/release-notes/",
        "summary": "Pipeline and security updates may affect DevOps lab instructions.",
    },
    "Azure AI Document Intelligence": {
        "source": "Document Intelligence updates",
        "url": "https://learn.microsoft.com/azure/ai-services/document-intelligence/whats-new",
        "summary": "Model and API changes may affect information extraction labs.",
    },
}


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


def _fmt_table_dt(value) -> str:
    dt = _to_dt(value)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def _issue_url(issue_id: str | None, kind: str | None = None) -> str | None:
    if not issue_id or "#" not in issue_id:
        return None
    repo_id, number = issue_id.rsplit("#", 1)
    if not repo_id or not number:
        return None
    route = "pull" if kind == "PR" else "issues"
    return f"https://github.com/{repo_id}/{route}/{number}"


def _issue_number(issue_id: str | None) -> str:
    if not issue_id or "#" not in issue_id:
        return issue_id or ""
    return f"#{issue_id.rsplit('#', 1)[1]}"


def _repo_url(repo_id: str | None) -> str | None:
    return f"https://github.com/{repo_id}" if repo_id else None


def _repo_lab_name(repo_id: str | None, name: str | None = None) -> str:
    return name or (repo_id or "").split("/")[-1]


def _repo_products(repo_id: str | None, products: list[str] | None) -> list[str]:
    values = products or REPO_PRODUCT_DEFAULTS.get(repo_id or "", [])
    normalized = []
    for product in values:
        normalized_product = LEGACY_PRODUCT_ALIASES.get(product, product)
        if normalized_product not in normalized:
            normalized.append(normalized_product)
    return normalized


def _mock_product_signal(products: list[str]) -> dict[str, str]:
    for product in products:
        if product in MOCK_PRODUCT_UPDATES:
            return {**MOCK_PRODUCT_UPDATES[product], "status": "Review"}
    return {
        "status": "Mock needed",
        "source": "No mocked source",
        "url": "https://azure.microsoft.com/updates/",
        "summary": "No product release signal is mocked for this repo yet.",
    }


def _parse_dt(value: str):
    value = value.strip()
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_csv(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return [item.strip() for item in value.split(",") if item.strip()]


def _table_event_row(args):
    if isinstance(args, dict):
        row = args.get("row")
    elif isinstance(args, list | tuple) and len(args) > 1:
        row = args[1]
    else:
        row = None
    return row if isinstance(row, dict) else {}


def _issue_type_query_values(value: str) -> list[str]:
    return [value, *[legacy for legacy, compact in ISSUE_TYPE_ALIASES.items() if compact == value]]


def _apply_theme():
    ui.add_head_html(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=IBM+Plex+Mono:wght@500;600&display=swap');

            :root {
                --tracker-bg: #f6f2ea;
                --tracker-surface: #fffdf8;
                --tracker-surface-strong: #ffffff;
                --tracker-border: #dfd6c9;
                --tracker-border-strong: #c8b9a7;
                --tracker-text: #27313a;
                --tracker-muted: #6f756f;
                --tracker-ink: #183642;
                --tracker-accent: #0f766e;
                --tracker-accent-strong: #0b5f59;
                --tracker-amber: #b7791f;
                --tracker-blue: #245f8f;
                --tracker-font-ui: "Atkinson Hyperlegible", "Verdana", "Segoe UI", sans-serif;
                --tracker-font-code: "IBM Plex Mono", "Cascadia Mono", "Consolas", monospace;
            }

            body {
                background:
                    radial-gradient(circle at 20% 0%, rgba(15, 118, 110, .08), transparent 28%),
                    linear-gradient(135deg, #f6f2ea 0%, #eef5f3 48%, #f8f4ed 100%);
                color: var(--tracker-text);
                font-family: var(--tracker-font-ui);
                font-size: 15px;
                line-height: 1.45;
            }

            .nicegui-content {
                min-height: 100vh;
            }

            .tracker-shell {
                max-width: 1180px;
                margin: 0 auto;
                padding: 28px 24px 40px;
                gap: 18px;
                width: 100%;
                animation: tracker-fade-up .35s ease-out both;
            }

            .tracker-header {
                width: 100%;
                align-items: flex-end;
                justify-content: space-between;
                gap: 16px;
            }

            .summary-grid {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 12px;
                width: 100%;
            }

            .summary-card {
                background: linear-gradient(180deg, var(--tracker-surface-strong), var(--tracker-surface));
                border: 1px solid var(--tracker-border);
                border-radius: 8px;
                box-shadow: 0 14px 34px rgba(39, 49, 58, .07);
                padding: 15px 16px;
                transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
            }

            .summary-card:hover {
                border-color: var(--tracker-border-strong);
                box-shadow: 0 18px 38px rgba(39, 49, 58, .1);
                transform: translateY(-1px);
            }

            .summary-label {
                color: var(--tracker-muted);
                font-size: .74rem;
                font-weight: 650;
                letter-spacing: .04em;
                text-transform: uppercase;
            }

            .summary-value {
                color: var(--tracker-ink);
                font-family: var(--tracker-font-code);
                font-size: 1.5rem;
                font-weight: 750;
                line-height: 1.2;
                margin-top: 2px;
            }

            .tracker-title {
                color: var(--tracker-ink);
                font-size: 2.15rem;
                font-weight: 800;
                letter-spacing: 0;
                line-height: 1.15;
            }

            .tracker-subtitle {
                color: var(--tracker-muted);
                font-size: .98rem;
                line-height: 1.5;
                max-width: 640px;
            }

            .tracker-tabs {
                align-self: flex-start;
                background: white;
                border: 1px solid #dbe4ea;
                border-radius: 8px;
                box-shadow: 0 1px 2px rgba(31, 41, 51, .06);
                color: #334e68;
            }

            .tracker-panel {
                width: 100%;
                padding: 0;
                background: transparent;
            }

            .tracker-panel .nicegui-tab-panel {
                padding: 24px 0 0;
            }

            .section-heading {
                color: var(--tracker-ink);
                font-size: 1.22rem;
                font-weight: 780;
                margin-bottom: 2px;
            }

            .section-header {
                width: 100%;
                align-items: flex-end;
                justify-content: space-between;
                gap: 12px;
            }

            .dashboard-toolbar {
                width: 100%;
                align-items: center;
                justify-content: flex-end;
                gap: 6px;
                margin-bottom: -6px;
            }

            .section-actions {
                align-items: center;
                gap: 6px;
            }

            .dashboard-toolbar .q-btn,
            .section-actions .q-btn,
            .view-toolbar .q-btn {
                background: rgba(255, 253, 248, .82);
                border: 1px solid var(--tracker-border);
                box-shadow: 0 6px 18px rgba(39, 49, 58, .07);
                color: var(--tracker-accent-strong);
                transition: transform .16s ease, box-shadow .16s ease, background .16s ease, border-color .16s ease;
            }

            .dashboard-toolbar .q-btn:hover,
            .section-actions .q-btn:hover,
            .view-toolbar .q-btn:hover {
                background: #e9f7f4;
                border-color: rgba(15, 118, 110, .35);
                box-shadow: 0 10px 24px rgba(15, 118, 110, .13);
                transform: translateY(-1px);
            }

            .view-toolbar {
                align-items: center;
                gap: 8px;
            }

            .section-hint {
                color: var(--tracker-muted);
                font-size: .92rem;
                line-height: 1.45;
                margin-bottom: 12px;
            }

            .tracker-table {
                background: var(--tracker-surface-strong);
                border: 1px solid var(--tracker-border);
                border-radius: 8px;
                box-shadow: 0 18px 42px rgba(39, 49, 58, .08);
                overflow: hidden;
            }

            .tracker-table thead tr {
                background: #edf4f1;
            }

            .tracker-table th {
                color: #52605a;
                font-size: .74rem;
                font-weight: 780;
                letter-spacing: .035em;
                text-transform: uppercase;
            }

            .tracker-table tbody tr {
                transition: background .14s ease, box-shadow .14s ease;
            }

            .tracker-table tbody tr:hover {
                background: #f4fbf8;
            }

            .tracker-table td,
            .tracker-table th {
                direction: ltr;
                text-align: left !important;
                white-space: nowrap;
            }

            .tracker-table td {
                font-size: .89rem;
                line-height: 1.45;
            }

            .tracker-table td.issue-id-cell,
            .tracker-table td.compact-cell,
            .tracker-table td.medium-cell {
                font-size: .85rem;
            }

            .tracker-table td.wrap-cell,
            .tracker-table th.wrap-cell {
                max-width: 360px;
                min-width: 240px;
                white-space: normal;
            }

            .tracker-table td.title-cell,
            .tracker-table th.title-cell {
                max-width: 330px;
                min-width: 220px;
                white-space: normal;
            }

            .tracker-table td.lab-cell,
            .tracker-table th.lab-cell {
                max-width: 190px;
                min-width: 150px;
                white-space: normal;
            }

            .tracker-table td.medium-cell,
            .tracker-table th.medium-cell {
                max-width: 150px;
                min-width: 118px;
                white-space: normal;
            }

            .tracker-table td.compact-cell,
            .tracker-table th.compact-cell {
                max-width: 120px;
                min-width: 56px;
                width: 1%;
            }

            .tracker-table td.issue-id-cell,
            .tracker-table th.issue-id-cell {
                max-width: 72px;
                min-width: 56px;
                width: 56px;
            }

            .action-row {
                margin-top: 12px;
                gap: 10px;
                flex-wrap: wrap;
            }

            .filter-row {
                width: 100%;
                gap: 12px;
                flex-wrap: wrap;
                align-items: center;
                margin-bottom: 16px;
            }

            .filter-row .q-field__control,
            .manual-grid .q-field__control {
                background: rgba(255, 253, 248, .9);
                border-radius: 8px;
            }

            .filter-row .q-field__control {
                padding-left: 8px;
            }

            .filter-row .q-field__native,
            .filter-row .q-field__input,
            .filter-row .q-field__label {
                font-family: var(--tracker-font-ui);
                padding-left: 8px !important;
            }

            .filter-row .q-field__native,
            .filter-row .q-field__input {
                font-size: .92rem;
                font-weight: 500;
            }

            .filter-row .q-field__label {
                color: var(--tracker-muted);
                font-size: .78rem;
                font-weight: 700;
            }

            .filter-row .q-field__append {
                padding-right: 8px;
            }

            .filter-select {
                min-width: 150px;
                width: 160px;
            }

            .repo-filter {
                min-width: 300px;
                width: 300px;
            }

            .report-copy {
                color: #627d98;
                margin-bottom: 8px;
            }

            .dialog-card,
            .q-card.dialog-card {
                width: min(680px, calc(100vw - 32px));
                max-height: calc(100vh - 48px);
                overflow: auto;
                gap: 12px;
                border: 1px solid rgba(223, 214, 201, .92);
                border-radius: 16px !important;
                box-shadow: 0 24px 70px rgba(39, 49, 58, .22);
                padding: 18px;
            }

            .dialog-header {
                align-items: flex-start;
                justify-content: space-between;
                width: 100%;
                gap: 12px;
            }

            .dialog-header-title {
                margin-right: 8px;
            }

            .dialog-close {
                color: var(--tracker-muted);
                margin: -6px -6px 0 0;
                transition: background .14s ease, color .14s ease, transform .14s ease;
            }

            .dialog-close:hover {
                background: #f1ebe2;
                color: var(--tracker-ink);
                transform: rotate(4deg);
            }

            .dialog-actions {
                align-items: center;
                gap: 8px;
                justify-content: flex-end;
                margin-top: 8px;
                width: 100%;
            }

            .dialog-actions .q-btn {
                border-radius: 999px;
                font-size: .82rem;
                height: 30px !important;
                min-height: 30px !important;
                padding: 0 12px !important;
                text-transform: none;
            }

            .dialog-actions .q-btn__content {
                gap: 5px;
                line-height: 1;
                min-height: 30px;
            }

            .dialog-actions .q-icon {
                font-size: 16px;
            }

            .dialog-primary-action {
                background: var(--tracker-accent-strong) !important;
                color: white !important;
                box-shadow: 0 8px 18px rgba(15, 118, 110, .16);
            }

            .dialog-subtle-action {
                background: #f4fbf8 !important;
                border: 1px solid rgba(15, 118, 110, .18);
                color: var(--tracker-accent-strong) !important;
            }

            .issue-title {
                font-size: 1.02rem;
                font-weight: 650;
                line-height: 1.35;
            }

            .issue-meta {
                color: var(--tracker-muted);
                font-family: var(--tracker-font-code);
                font-size: .82rem;
            }

            .external-link {
                align-self: flex-start;
                color: var(--tracker-accent-strong);
                font-weight: 650;
                text-decoration: none;
            }

            .table-link {
                color: var(--tracker-accent-strong);
                font-weight: 650;
                text-decoration: none;
            }

            .table-link:hover {
                text-decoration: underline;
            }

            .repo-title-cell {
                display: flex;
                align-items: center;
                gap: 8px;
                white-space: normal;
            }

            .repo-lab-name {
                font-weight: 650;
                line-height: 1.25;
            }

            .mini-link-button {
                background: #edf7f4;
                border: 1px solid rgba(15, 118, 110, .24);
                border-radius: 999px;
                color: var(--tracker-accent-strong);
                font-family: var(--tracker-font-code);
                font-size: .73rem;
                font-weight: 700;
                line-height: 1;
                padding: 4px 8px;
                text-decoration: none;
                transition: background .14s ease, border-color .14s ease, transform .14s ease;
                white-space: nowrap;
            }

            .mini-link-button:hover {
                background: #dff2ee;
                border-color: rgba(15, 118, 110, .4);
                transform: translateY(-1px);
            }

            .issues-link-button {
                background: transparent;
                border: 1px solid rgba(15, 118, 110, .22);
                border-radius: 999px;
                color: var(--tracker-accent-strong);
                cursor: pointer;
                font-family: var(--tracker-font-code);
                font-size: .75rem;
                font-weight: 750;
                line-height: 1;
                padding: 5px 9px;
                transition: background .14s ease, border-color .14s ease, transform .14s ease;
                white-space: nowrap;
            }

            .issues-link-button:hover {
                background: #edf7f4;
                border-color: rgba(15, 118, 110, .38);
                transform: translateY(-1px);
            }

            .signal-text {
                margin-left: 6px;
                font-weight: 650;
                color: #7a4f01;
            }

            @keyframes tracker-fade-up {
                from {
                    opacity: 0;
                    transform: translateY(8px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }

            @media (prefers-reduced-motion: reduce) {
                *, *::before, *::after {
                    animation-duration: .01ms !important;
                    scroll-behavior: auto !important;
                    transition-duration: .01ms !important;
                }
            }

            .manual-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 12px;
                width: 100%;
            }

            @media (max-width: 760px) {
                .tracker-shell {
                    padding: 20px 14px 32px;
                }

                .tracker-tabs {
                    width: 100%;
                }

                .summary-grid {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }

                .filter-select,
                .repo-filter {
                    min-width: 100%;
                    width: 100%;
                }

                .manual-grid {
                    grid-template-columns: 1fr;
                }
            }

            @media (max-width: 520px) {
                .summary-grid {
                    grid-template-columns: 1fr;
                }
            }
        </style>
        """
    )


def _build_ui():
    _apply_theme()
    db = _db()

    with ui.column().classes("tracker-shell"):
        with ui.row().classes("tracker-header"):
            with ui.column().classes("gap-1"):
                ui.label("Labs Tracker").classes("tracker-title")
                ui.label("Monitor lab repositories, issue health, and product update signals in one focused workspace.").classes("tracker-subtitle")

        repo_selected: dict[str, str | None] = {"id": None}
        issue_selected: dict[str, str | None] = {"id": None}

        with ui.column().classes("w-full gap-4") as dashboard_view:
            with ui.element("div").classes("summary-grid"):
                with ui.column().classes("summary-card"):
                    ui.label("Tracked repos").classes("summary-label")
                    repos_value = ui.label("0").classes("summary-value")
                with ui.column().classes("summary-card"):
                    ui.label("Open issues").classes("summary-label")
                    open_issues_value = ui.label("0").classes("summary-value")
                with ui.column().classes("summary-card"):
                    ui.label("Needs classification").classes("summary-label")
                    unknown_issues_value = ui.label("0").classes("summary-value")
                with ui.column().classes("summary-card"):
                    ui.label("Release notes to review").classes("summary-label")
                    release_notes_value = ui.label("0").classes("summary-value")

            with ui.row().classes("section-header"):
                with ui.column().classes("gap-1"):
                    ui.label("Repos").classes("section-heading")
                    ui.label("Scan ownership, open issue load, and release-note signals across tracked labs.").classes("section-hint")

            with ui.row().classes("dashboard-toolbar"):
                sync_button = ui.button(icon="sync").props("flat round dense")
                sync_button.tooltip("Sync issues")
                refresh_repo_button = ui.button(icon="refresh").props("flat round dense")
                refresh_repo_button.tooltip("Refresh dashboard")
                new_repo_button = ui.button(icon="add").props("flat round dense")
                new_repo_button.tooltip("New repo")

            repo_table = ui.table(
                columns=[
                    {"name": "lab", "label": "Lab", "field": "lab", "sortable": True, "align": "left", "classes": "wrap-cell", "headerClasses": "wrap-cell"},
                    {"name": "products", "label": "Products", "field": "products", "align": "left", "classes": "wrap-cell", "headerClasses": "wrap-cell"},
                    {"name": "owners", "label": "Owners", "field": "owners", "align": "left", "classes": "wrap-cell", "headerClasses": "wrap-cell"},
                    {"name": "openIssues", "label": "Open issues", "field": "openIssues", "sortable": True, "align": "left"},
                    {"name": "releaseStatus", "label": "Signal", "field": "releaseStatus", "sortable": True, "align": "left"},
                    {"name": "releaseSummary", "label": "Mocked change summary", "field": "releaseSummary", "align": "left", "classes": "wrap-cell", "headerClasses": "wrap-cell"},
                    {"name": "releaseSource", "label": "Source", "field": "releaseSource", "align": "left"},
                ],
                rows=[],
                row_key="id",
                pagination=20,
            ).classes("tracker-table w-full").props("flat bordered")
            repo_table.add_slot(
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
            repo_table.add_slot(
                "body-cell-releaseStatus",
                """
                <q-td :props="props">
                    <q-icon name="warning" color="amber-8" size="18px" />
                    <span class="signal-text">{{ props.row.releaseStatus }}</span>
                </q-td>
                """,
            )
            repo_table.add_slot(
                "body-cell-releaseSource",
                """
                <q-td :props="props">
                    <a :href="props.row.releaseUrl" target="_blank" class="table-link" @click.stop>{{ props.row.releaseSource }}</a>
                </q-td>
                """,
            )
            repo_table.add_slot(
                "body-cell-openIssues",
                """
                <q-td :props="props">
                    <button class="issues-link-button" @click.stop="$parent.$emit('openIssues', props.row)">{{ props.row.openIssues }} open</button>
                </q-td>
                """,
            )

        with ui.column().classes("w-full").props("id=issues-panel") as issues_panel:
            with ui.row().classes("section-header"):
                with ui.row().classes("view-toolbar"):
                    back_button = ui.button(icon="arrow_back").props("flat round dense")
                    back_button.tooltip("Back to dashboard")
                    with ui.column().classes("gap-1"):
                        issues_heading = ui.label("Issues").classes("section-heading")
                        ui.label("Classify root causes, track outcomes, and jump to GitHub when context matters.").classes("section-hint")
                with ui.row().classes("section-actions"):
                    issue_sync_button = ui.button(icon="sync").props("flat round dense")
                    issue_sync_button.tooltip("Sync issues")
                    issue_refresh_button = ui.button(icon="refresh").props("flat round dense")
                    issue_refresh_button.tooltip("Refresh issues")

            with ui.row().classes("filter-row"):
                repo_filter = ui.select(["All"], value="All", label="Repo").classes("repo-filter")
                state_filter = ui.select(["All", *STATE_VALUES], value="All", label="State").classes("filter-select")
                type_filter = ui.select(["All", *ISSUE_TYPE_VALUES], value="All", label="Issue type").classes("filter-select")
                status_filter = ui.select(["All", *STATUS_VALUES], value="All", label="Status").classes("filter-select")
            issue_summary = ui.label("").classes("section-hint")

            issues_table = ui.table(
                columns=[
                    {"name": "issueNumber", "label": "#", "field": "issueNumber", "sortable": True, "align": "left", "classes": "issue-id-cell", "headerClasses": "issue-id-cell"},
                    {"name": "lab", "label": "Lab", "field": "lab", "sortable": True, "align": "left", "classes": "lab-cell", "headerClasses": "lab-cell"},
                    {"name": "title", "label": "Title", "field": "title", "sortable": True, "align": "left", "classes": "title-cell", "headerClasses": "title-cell"},
                    {"name": "status", "label": "Status", "field": "status", "sortable": True, "align": "left", "classes": "medium-cell", "headerClasses": "medium-cell"},
                    {"name": "typeOfIssue", "label": "Issue type", "field": "typeOfIssue", "sortable": True, "align": "left", "classes": "medium-cell", "headerClasses": "medium-cell"},
                    {"name": "resolution", "label": "Resolution", "field": "resolution", "sortable": True, "align": "left", "classes": "medium-cell", "headerClasses": "medium-cell"},
                    {"name": "closingPrUrl", "label": "PR", "field": "closingPrUrl", "align": "left", "classes": "compact-cell", "headerClasses": "compact-cell"},
                ],
                rows=[],
                row_key="issueId",
                pagination=20,
            ).classes("tracker-table w-full").props("flat bordered")
            issues_table.add_slot(
                "body-cell-issueNumber",
                """
                <q-td :props="props">
                    <a :href="props.row.issueUrl" target="_blank" class="mini-link-button" @click.stop>{{ props.row.issueNumber }}</a>
                </q-td>
                """,
            )
            issues_table.add_slot(
                "body-cell-closingPrUrl",
                """
                <q-td :props="props">
                    <a v-if="props.row.closingPrUrl" :href="props.row.closingPrUrl" target="_blank" class="mini-link-button" @click.stop>PR</a>
                    <span v-else class="issue-meta">-</span>
                </q-td>
                """,
            )
        issues_panel.visible = False

        def refresh_summary():
            repos = list(db.repos.find({}, {"id": 1, "products": 1, "_id": 0}))
            release_notes_to_review = 0
            for repo in repos:
                products = _repo_products(repo.get("id"), repo.get("products") or [])
                if _mock_product_signal(products)["status"] == "Review":
                    release_notes_to_review += 1
            repos_value.text = str(len(repos))
            open_issues_value.text = str(db.issues.count_documents({"state": "Open"}))
            unknown_issues_value.text = str(db.issues.count_documents({"$or": [{"typeOfIssue": "Unknown"}, {"resolution": "Unknown"}]}))
            release_notes_value.text = str(release_notes_to_review)
            for value in [repos_value, open_issues_value, unknown_issues_value, release_notes_value]:
                value.update()

        def refresh_repos():
            rows = []
            for doc in db.repos.find({}).sort("id", 1):
                repo_id = doc.get("id")
                products = _repo_products(repo_id, doc.get("products") or [])
                release_signal = _mock_product_signal(products)
                rows.append(
                    {
                        "id": repo_id,
                        "lab": _repo_lab_name(repo_id, doc.get("name")),
                        "products": ", ".join(products),
                        "owners": ", ".join(doc.get("involvedDevs") or []),
                        "openIssues": db.issues.count_documents({"repoId": repo_id, "state": "Open"}),
                        "repoUrl": _repo_url(repo_id),
                        "releaseStatus": release_signal["status"],
                        "releaseSummary": release_signal["summary"],
                        "releaseSource": release_signal["source"],
                        "releaseUrl": release_signal["url"],
                    }
                )
            repo_table.rows = rows
            repo_table.update()
            refresh_summary()

        def save_repo(existing_id: str | None, repo_id: str, name: str, involved_devs, products, last_tested: str) -> bool:
            try:
                parsed_last_tested = _parse_dt(last_tested)
            except ValueError:
                ui.notify("Invalid lastTested format. Use ISO datetime.", color="negative")
                return False
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
                    return False
                if db.repos.find_one({"id": repo_id}):
                    ui.notify("repo already exists", color="warning")
                    return False
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
            return True

        def open_repo_dialog(existing_id: str | None = None):
            existing = db.repos.find_one({"id": existing_id}) if existing_id else {}
            with ui.dialog() as dialog, ui.card().classes("dialog-card"):
                with ui.row().classes("dialog-header"):
                    ui.label("Edit repo" if existing_id else "New repo").classes("section-heading dialog-header-title")
                    close_button = ui.button(icon="close", on_click=dialog.close).props("flat round dense").classes("dialog-close")
                    close_button.tooltip("Close")
                repo_id_input = ui.input("Repo id", placeholder="owner/repo", value=existing.get("id", "")).classes("w-full")
                repo_name_input = ui.input("Lab name", value=existing.get("name", "")).classes("w-full")
                involved_input = ui.select(OWNER_VALUES, value=existing.get("involvedDevs") or [], label="Owners", multiple=True).classes("w-full").props("use-chips")
                products_input = ui.select(PRODUCT_VALUES, value=_repo_products(existing.get("id"), existing.get("products") or []), label="Products", multiple=True).classes("w-full").props("use-chips")
                last_tested_input = ui.input("Last tested", placeholder="ISO datetime or blank", value=_fmt_dt(existing.get("lastTested"))).classes("w-full")
                if existing_id:
                    repo_id_input.disable()
                    repo_name_input.disable()

                def save_and_close():
                    if save_repo(
                        existing_id,
                        repo_id_input.value,
                        repo_name_input.value,
                        involved_input.value,
                        products_input.value,
                        last_tested_input.value,
                    ):
                        dialog.close()

                with ui.row().classes("dialog-actions"):
                    ui.button("Save", icon="save", on_click=save_and_close).props("unelevated no-caps").classes("dialog-primary-action")
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

        async def run_issue_sync():
            result = await nicegui_run.io_bound(sync)
            ui.notify(f"Synced {result['repoCount']} repo(s), {result['issueCount']} issue records", color="positive")
            refresh_repos()
            refresh_issues()

        def repo_id_from_args(args) -> str | None:
            row = args if isinstance(args, dict) else _table_event_row(args)
            repo_id = row.get("id") if isinstance(row, dict) else None
            return repo_id if isinstance(repo_id, str) else None

        def refresh_issues():
            repo_docs = list(db.repos.find({}, {"id": 1, "name": 1, "_id": 0}))
            repo_values = sorted(doc.get("id") for doc in repo_docs if doc.get("id"))
            repo_names = {doc.get("id"): _repo_lab_name(doc.get("id"), doc.get("name")) for doc in repo_docs if doc.get("id")}
            repo_filter.options = ["All", *repo_values]
            query = {}
            if repo_filter.value and repo_filter.value != "All":
                query["repoId"] = repo_filter.value
                issues_heading.text = f"Issues for {_repo_lab_name(repo_filter.value)}"
            else:
                issues_heading.text = "All issues"
            issues_heading.update()
            if state_filter.value and state_filter.value != "All":
                query["state"] = state_filter.value
            if type_filter.value and type_filter.value != "All":
                query["typeOfIssue"] = {"$in": _issue_type_query_values(type_filter.value)}
            if status_filter.value and status_filter.value != "All":
                query["status"] = status_filter.value

            rows = []
            for doc in db.issues.find(query).sort("issueId", 1):
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
                        "typeOfIssue": normalize_issue_type(doc.get("typeOfIssue")),
                        "resolution": normalize_resolution(doc.get("resolution")),
                        "status": doc.get("status"),
                        "closingPrUrl": doc.get("closingPrUrl") or "",
                    }
                )
            rows.sort(key=lambda row: (0 if row.get("state") == "Open" else 1, row.get("issueId") or ""))
            open_count = sum(1 for row in rows if row.get("state") == "Open")
            closed_count = sum(1 for row in rows if row.get("state") == "Closed")
            issue_summary.text = f"Showing {open_count} open and {closed_count} closed issue(s)."
            issue_summary.update()
            issues_table.rows = rows
            issues_table.update()
            refresh_summary()

        def reveal_repo_issues(args):
            repo_id = repo_id_from_args(args)
            if not repo_id:
                return
            repo_selected["id"] = repo_id
            issue_selected["id"] = None
            repo_filter.set_value(repo_id)
            dashboard_view.visible = False
            dashboard_view.update()
            issues_panel.visible = True
            issues_panel.update()
            refresh_issues()

        def back_to_dashboard():
            issue_selected["id"] = None
            issues_panel.visible = False
            issues_panel.update()
            dashboard_view.visible = True
            dashboard_view.update()

        def open_repo_details(args):
            row = _table_event_row(args)
            repo_id = repo_id_from_args(args)
            if not repo_id:
                return
            existing = db.repos.find_one({"id": repo_id}) or {}
            repo_selected["id"] = repo_id
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
                if row.get("releaseUrl"):
                    ui.link(row.get("releaseSource") or "Release source", row["releaseUrl"], new_tab=True).classes("external-link")
                if row.get("repoUrl"):
                    ui.link("Open repo in GitHub", row["repoUrl"], new_tab=True).classes("external-link")

                def open_issues_and_close():
                    dialog.close()
                    reveal_repo_issues(row)

                def save_details_and_close():
                    if save_repo(
                        repo_id,
                        repo_id,
                        existing.get("name") or row.get("lab") or _repo_lab_name(repo_id),
                        owners_input.value,
                        products_input.value,
                        _fmt_dt(existing.get("lastTested")),
                    ):
                        dialog.close()

                with ui.row().classes("dialog-actions"):
                    ui.button("Issues", icon="bug_report", on_click=open_issues_and_close).props("flat no-caps").classes("dialog-subtle-action")
                    ui.button("Save", icon="save", on_click=save_details_and_close).props("unelevated no-caps").classes("dialog-primary-action")
            dialog.open()

        def save_issue(existing_id: str | None, issue_id: str, repo_id: str, kind: str, title: str, state: str, type_of_issue: str, resolution: str, status: str, last_tested: str, closing_pr_url: str) -> bool:
            try:
                parsed_last_tested = _parse_dt(last_tested)
            except ValueError:
                ui.notify("Invalid lastTested format. Use ISO datetime.", color="negative")
                return False
            manual = {
                "typeOfIssue": normalize_issue_type(type_of_issue),
                "resolution": normalize_resolution(resolution),
                "status": status,
                "lastTested": parsed_last_tested,
                "closingPrUrl": closing_pr_url.strip(),
            }
            if existing_id:
                db.issues.update_one({"issueId": existing_id}, {"$set": manual})
            else:
                if not issue_id or not repo_id or not title:
                    ui.notify("issueId, repoId, and title are required", color="negative")
                    return False
                if db.issues.find_one({"issueId": issue_id}):
                    ui.notify("issue already exists", color="warning")
                    return False
                db.issues.update_one(
                    {"issueId": issue_id},
                    {
                        "$set": {
                            "issueId": issue_id,
                            "repoId": repo_id,
                            "kind": kind,
                            "title": title,
                            "state": state,
                            **manual,
                        },
                        "$setOnInsert": {"_id": issue_id},
                    },
                    upsert=True,
                )
            refresh_issues()
            ui.notify("Saved", color="positive")
            return True

        def open_issue_dialog(existing_id: str | None = None):
            existing = db.issues.find_one({"issueId": existing_id}) if existing_id else {}
            with ui.dialog() as dialog, ui.card().classes("dialog-card"):
                with ui.row().classes("dialog-header"):
                    ui.label("Issue details" if existing_id else "New issue").classes("section-heading dialog-header-title")
                    close_button = ui.button(icon="close", on_click=dialog.close).props("flat round dense").classes("dialog-close")
                    close_button.tooltip("Close")
                if existing_id:
                    ui.label(existing.get("title", "Untitled issue")).classes("issue-title")
                    ui.label(f"{existing.get('state', '')} · {existing_id}").classes("issue-meta")
                    issue_link = _issue_url(existing_id, existing.get("kind"))
                    if issue_link:
                        ui.link("Open in GitHub", issue_link, new_tab=True).classes("external-link")
                    if existing.get("closingPrUrl"):
                        ui.link("Open closing PR", existing["closingPrUrl"], new_tab=True).classes("external-link")
                    with ui.element("div").classes("manual-grid"):
                        type_input = ui.select(ISSUE_TYPE_VALUES, value=normalize_issue_type(existing.get("typeOfIssue")), label="Issue type").classes("w-full")
                        resolution_input = ui.select(RESOLUTION_VALUES, value=normalize_resolution(existing.get("resolution")), label="Resolution").classes("w-full")
                        status_input = ui.select(STATUS_VALUES, value=existing.get("status", "Open"), label="Status").classes("w-full")
                        last_tested_input = ui.input("Last tested", placeholder="ISO datetime or blank", value=_fmt_dt(existing.get("lastTested"))).classes("w-full")
                        closing_pr_input = ui.input("Closing PR URL", placeholder="https://github.com/owner/repo/pull/123", value=existing.get("closingPrUrl") or "").classes("w-full")

                    def save_and_close():
                        if save_issue(
                            existing_id,
                            existing.get("issueId", ""),
                            existing.get("repoId", ""),
                            existing.get("kind", KIND_VALUES[0]),
                            existing.get("title", ""),
                            existing.get("state", STATE_VALUES[0]),
                            type_input.value,
                            resolution_input.value,
                            status_input.value,
                            last_tested_input.value,
                            closing_pr_input.value,
                        ):
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
                    last_tested_input = ui.input("Last tested", placeholder="ISO datetime or blank", value="").classes("w-full")
                    closing_pr_input = ui.input("Closing PR URL", placeholder="https://github.com/owner/repo/pull/123", value="").classes("w-full")

                    def save_and_close():
                        if save_issue(
                            None,
                            issue_id_input.value,
                            repo_id_input.value,
                            kind_input.value,
                            title_input.value,
                            state_input.value,
                            type_input.value,
                            resolution_input.value,
                            status_input.value,
                            last_tested_input.value,
                            closing_pr_input.value,
                        ):
                            dialog.close()

                with ui.row().classes("dialog-actions"):
                    ui.button("Save", icon="save", on_click=save_and_close).props("unelevated no-caps").classes("dialog-primary-action")
            dialog.open()

        def delete_issue():
            if not issue_selected["id"]:
                ui.notify("Select an issue first", color="warning")
                return
            db.issues.delete_one({"issueId": issue_selected["id"]})
            issue_selected["id"] = None
            refresh_issues()
            ui.notify("Issue deleted", color="positive")

        def open_clicked_issue(args):
            issue_id = _table_event_row(args).get("issueId")
            if not issue_id:
                return
            issue_selected["id"] = issue_id
            open_issue_dialog(issue_id)

        sync_button.on_click(run_issue_sync)
        issue_sync_button.on_click(run_issue_sync)
        refresh_repo_button.on_click(lambda: (refresh_repos(), refresh_issues()))
        issue_refresh_button.on_click(lambda: refresh_issues())
        new_repo_button.on_click(lambda: open_repo_dialog(None))
        back_button.on_click(back_to_dashboard)

        repo_table.on("rowClick", lambda e: open_repo_details(e.args))
        repo_table.on("openIssues", lambda e: reveal_repo_issues(e.args))
        issues_table.on("rowClick", lambda e: open_clicked_issue(e.args))
        for control in [repo_filter, state_filter, type_filter, status_filter]:
            control.on("update:model-value", lambda _: refresh_issues())

        refresh_repos()
        refresh_issues()


def run(host: str = "127.0.0.1", port: int = 8080):
    @ui.page("/")
    def _home():
        _build_ui()

    ui.run(host=host, port=port, title="Labs Tracker", reload=False)


if __name__ == "__main__":
    run()
