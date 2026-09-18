"""Shared values and helpers for the simplified lab tracker data model."""

KIND_ISSUE = "Issue"
KIND_PR = "PR"
KIND_VALUES = [KIND_ISSUE, KIND_PR]

STATE_OPEN = "Open"
STATE_CLOSED = "Closed"
STATE_VALUES = [STATE_OPEN, STATE_CLOSED]

ISSUE_TYPE_VALUES = [
    "UI drift",
    "Skillable",
    "SDK/code issues",
    "Outdated versions",
    "User intent/setup mismatch",
    "Lab content clarity",
    "Product/service behavior",
    "Enhancement request",
    "Unknown",
]

ISSUE_TYPE_ALIASES = {
    "Lab instructions": "Lab content clarity",
    "SDK/code update": "SDK/code issues",
    "Support reproduction/setup": "User intent/setup mismatch",
    "Azure service/portal drift": "UI drift",
    "Environment/setup": "User intent/setup mismatch",
    "Content clarity": "Lab content clarity",
    "Outdated version": "Outdated versions",
    "Nice to have": "Enhancement request",
    "Modular suggestion": "Enhancement request",
    "Lab-specific suggestion": "Enhancement request",
    "Skillable capacity": "Skillable",
    "Product consistency": "Product/service behavior",
    "Code/runtime error": "SDK/code issues",
    "Dependency/version drift": "Outdated versions",
}

RESOLUTION_VALUES = [
    "Fixed in lab",
    "Linked PR",
    "Replied/no lab change",
    "Reported externally",
    "Duplicate",
    "Cannot reproduce",
    "Not applicable",
    "Unknown",
]

RESOLUTION_ALIASES = {
    "Updated instructions": "Fixed in lab",
    "Updated code/sample": "Fixed in lab",
    "Updated dependency/version": "Fixed in lab",
    "Updated UI or code or versions": "Fixed in lab",
    "Commented or added the requested content": "Replied/no lab change",
    "Report to Skillable": "Reported externally",
    "Reported to product/service team": "Reported externally",
    "Added note or warning": "Fixed in lab",
}

def normalize_issue_type(value: str | None) -> str:
    if value in ISSUE_TYPE_VALUES:
        return value
    normalized = ISSUE_TYPE_ALIASES.get(value or "")
    return normalized if normalized in ISSUE_TYPE_VALUES else "Unknown"

def normalize_resolution(value: str | None) -> str:
    if value in RESOLUTION_VALUES:
        return value
    normalized = RESOLUTION_ALIASES.get(value or "")
    return normalized if normalized in RESOLUTION_VALUES else "Unknown"

STATUS_VALUES = ["Closed", "In review", "Resolved locally", "Waiting owner review", "Temporary/out of scope", "Not applicable", "Open"]

HANDLING_STAGE_VALUES = [
    "Raised",
    "Investigating",
    "In progress",
    "Waiting",
    "Validating",
    "Resolved",
]

WAIT_REASON_VALUES = ["None", "Information needed", "External dependency", "Review/approval", "Capacity/priority", "Other"]

OWNER_VALUES = [
    "Graeme Malcolm",
    "Ivor Berry",
    "Mary-Jo Diepeeven",
    "Hope Rosen",
    "Angie Rudduck",
    "Carlos Lopes",
    "Becky Zahid",
    "Jeff Koch",
    "Peter De Tender",
    "Simon Dickenson",
    "Rob Barefoot",
    "Wesley De Bolster",
    "Juliane Padrao",
]

PRODUCT_VALUES = [
    "Foundry",
    "Foundry SDK",
    "Foundry Toolkit for VS Code",
    "Azure Machine Learning Studio",
    "Microsoft Fabric",
    "Power BI",
    "Azure SQL",
    "GitHub Copilot",
    "GitHub Actions",
    "GitHub",
    "Azure DevOps",
]


def default_repo_manual_fields(repo_id: str) -> dict:
    products = ["Foundry"] if repo_id.lower() == "microsoftlearning/mslearn-ai-language" else []
    return {
        "involvedDevs": [],
        "products": products,
        "lastTested": None,
    }


def default_issue_manual_fields(github_state: str | None = None) -> dict:
    state = (github_state or "").lower()
    status = "Closed" if state == "closed" else "Open"
    return {
        "typeOfIssue": "Unknown",
        "resolution": "Unknown",
        "status": status,
        "handlingStage": "Resolved" if state == "closed" else "Raised",
        "reproductionNotes": "",
        "externalReportUrl": "",
        "externalResponse": "",
        "handlingUpdatedAt": None,
        "handlingHistory": [],
        "waitingReason": "None",
        "waitingOn": "",
        "lastTested": None,
        "closingPrUrl": "",
    }
