"""Daily task generation from simplified MongoDB state."""
from __future__ import annotations

from datetime import datetime, timezone

from .models import KIND_ISSUE, KIND_PR, STATE_OPEN


def _as_aware(value):
    if value is None:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _number_from_issue_id(issue_id: str | None) -> str:
    if not issue_id or "#" not in issue_id:
        return ""
    return issue_id.split("#")[-1]


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


def _repo_task(priority: int, reason: str, repo: dict) -> dict:
    return {
        "priority": priority,
        "reason": reason,
        "repoId": repo.get("id"),
        "issueId": None,
        "number": "",
        "title": repo.get("name"),
        "kind": "Repo",
        "state": repo.get("status"),
    }


def generate_tasks(db) -> list[dict]:
    tasks: list[dict] = []

    for issue in db.issues.find({}):
        state = issue.get("state")
        kind = issue.get("kind")
        last_tested = _as_aware(issue.get("lastTested"))

        if state == STATE_OPEN and issue.get("typeOfIssue") == "Unknown":
            tasks.append(_issue_task(20, "Open issue/PR with unknown type: classify", issue))

        if state == STATE_OPEN and kind == KIND_ISSUE and last_tested is None:
            tasks.append(_issue_task(30, "Open issue missing lastTested: test whether it reproduces", issue))

        if state == STATE_OPEN and kind == KIND_PR and last_tested is None:
            tasks.append(_issue_task(30, "Open PR missing lastTested: validate PR for maintainers", issue))

        if state != STATE_OPEN and last_tested is None:
            tasks.append(_issue_task(40, "Closed item missing lastTested: record validation", issue))

    for repo in db.repos.find({}):
        last_updated = _as_aware(repo.get("lastUpdated"))
        last_tested = _as_aware(repo.get("lastTested"))
        if last_updated and (last_tested is None or last_updated > last_tested):
            tasks.append(_repo_task(35, "Repo changed after last tested (or never tested): retest repo/lab", repo))

    return sorted(tasks, key=lambda task: (task["priority"], task.get("repoId") or "", task.get("number") or ""))
