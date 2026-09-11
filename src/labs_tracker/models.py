"""Shared values and helpers for the lab tracker data model."""

KIND_ISSUE = "issue"
KIND_PR = "pr"
KIND_VALUES = [KIND_ISSUE, KIND_PR]

ISSUE_TYPE_VALUES = [
    "UI drift",
    "Outdated version",
    "Nice to have",
    "Skillable capacity",
    "Product consistency",
    "Unknown",
]

RESOLUTION_VALUES = [
    "Updated UI/code/version",
    "Added requested content",
    "Reported to Skillable",
    "Added note or warning",
    "Not applicable",
    "Unresolved",
    "Unknown",
]

STATUS_VALUES = ["Open", "In review", "Closed", "Not applicable"]
TEST_RESULT_VALUES = ["Reproduced", "Not reproduced", "Blocked", "Not tested"]


def default_manual_fields(github_state: str | None = None) -> dict:
    """Return manual fields used only when an item is first inserted."""
    status = "Closed" if github_state == "closed" else "Open"
    return {
        "typeOfIssue": "Unknown",
        "resolution": "Unknown",
        "status": status,
        "testResult": "Not tested",
        "lastTested": None,
        "notes": "",
    }
