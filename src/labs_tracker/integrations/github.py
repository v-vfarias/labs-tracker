"""GitHub issue fetching and document mapping."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from github import Github

from ..domain.models import KIND_ISSUE, STATE_CLOSED, STATE_OPEN


def get_github(token: str):
    return Github(token)


def _github_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _state(value: str | None) -> str:
    return STATE_CLOSED if (value or "").lower() == "closed" else STATE_OPEN


def _repo_document(repo: Any) -> dict:
    return {
        "id": repo.full_name,
        "name": repo.name,
        "status": "Archived" if repo.archived else "Live",
        "lastUpdated": _github_dt(repo.pushed_at),
    }


def _issue_document(repo_id: str, issue: Any) -> dict:
    return {
        "issueId": f"{repo_id}#{issue.number}",
        "repoId": repo_id,
        "kind": KIND_ISSUE,
        "title": issue.title,
        "state": _state(issue.state),
    }


def _latest_closed_issues(repo: Any, limit: int) -> list[Any]:
    issues = []
    for issue in repo.get_issues(state="closed", sort="updated", direction="desc"):
        if issue.pull_request:
            continue
        issues.append(issue)
        if len(issues) >= limit:
            break
    return issues

