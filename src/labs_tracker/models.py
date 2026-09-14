"""Shared values and helpers for the simplified lab tracker data model."""

KIND_ISSUE = "Issue"
KIND_PR = "PR"
KIND_VALUES = [KIND_ISSUE, KIND_PR]

STATE_OPEN = "Open"
STATE_CLOSED = "Closed"
STATE_VALUES = [STATE_OPEN, STATE_CLOSED]

ISSUE_TYPE_VALUES = [
    "UI drift",
    "Outdated version",
    "Nice to have",
    "Skillable capacity",
    "Product consistency",
    "Unknown",
]

RESOLUTION_VALUES = [
    "Updated UI or code or versions",
    "Commented or added the requested add",
    "Report to Skillable",
    "Added note or warning",
    "Not applicable",
    "Unknown",
]

STATUS_VALUES = ["Closed", "In review", "Not applicable", "Open"]


def default_repo_manual_fields(repo_id: str) -> dict:
    products = ["Azure AI Language"] if repo_id.lower() == "microsoftlearning/mslearn-ai-language" else []
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
        "lastTested": None,
    }
