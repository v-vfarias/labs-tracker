"""Daily task generation from simplified MongoDB state."""
from __future__ import annotations

from ..domain.models import KIND_ISSUE, KIND_PR, normalize_issue_type, normalize_resolution


def _number_from_issue_id(issue_id: str | None) -> str:
    if not issue_id or "#" not in issue_id:
        return ""
    return issue_id.split("#")[-1]


def _number_for_sort(task: dict) -> int:
    number = str(task.get("number") or "").strip()
    return int(number) if number.isdigit() else 0


def _issue_task(priority: int, reason: str, issue: dict) -> dict:
    issue_id = issue.get("issueId")
    return {
        "priority": priority,
        "reason": reason,
        "repoId": issue.get("repoId"),
        "issueId": issue_id,
        "number": _number_from_issue_id(issue_id),
        "title": issue.get("title"),
        "kind": issue.get("kind"),
        "state": issue.get("state"),
    }


def generate_tasks(db) -> list[dict]:
    """Suggest one next action per locally unresolved issue/PR, never from test age."""
    tasks: list[dict] = []

    for issue in db.issues.find({}):
        if issue.get("kind") not in {KIND_ISSUE, KIND_PR}:
            continue
        if issue.get("handlingStage") == "Resolved" or issue.get("status") in {
            "Closed", "Resolved locally", "Not applicable",
        }:
            continue
        if issue.get("handlingStage") == "Waiting" and issue.get("waitingReason") == "Information needed":
            tasks.append(_issue_task(25, "Pending details: gather the requested information", issue))
        elif issue.get("status") in {"In review", "Waiting owner review"} or issue.get("handlingStage") == "Validating":
            tasks.append(_issue_task(30, "In review: assess the issue or proposed change", issue))
        elif normalize_issue_type(issue.get("typeOfIssue")) == "Unknown" or normalize_resolution(issue.get("resolution")) == "Unknown":
            tasks.append(_issue_task(20, "Pending classification: classify the issue or PR", issue))

    return sorted(tasks, key=lambda task: (task["priority"], task.get("repoId") or "", _number_for_sort(task)))
