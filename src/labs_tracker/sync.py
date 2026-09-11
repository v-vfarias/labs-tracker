"""GitHub-to-MongoDB synchronization."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from github import Github, GithubException

from .config import Settings, load_settings
from .db import ensure_indexes, get_database
from .models import KIND_ISSUE, KIND_PR, default_manual_fields


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _github_dt(value) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _names(values) -> list[str]:
    return [value.name for value in values]


def _logins(values) -> list[str]:
    return [value.login for value in values]


def _repo_products(full_name: str) -> list[str]:
    if full_name.lower() == "microsoftlearning/mslearn-ai-language":
        return ["Azure AI Language"]
    return []


def _repo_document(repo: Any, synced_at: datetime) -> dict:
    full_name = repo.full_name
    return {
        "id": full_name,
        "owner": repo.owner.login,
        "name": repo.name,
        "fullName": full_name,
        "htmlUrl": repo.html_url,
        "status": "Archived" if repo.archived else "Live",
        "lastUpdated": _github_dt(repo.pushed_at),
        "github": {
            "id": repo.id,
            "description": repo.description,
            "defaultBranch": repo.default_branch,
            "openIssuesCount": repo.open_issues_count,
            "private": repo.private,
        },
        "syncedAt": synced_at,
    }


def _item_document(repo_full_name: str, issue: Any, pr: Any | None, synced_at: datetime) -> dict:
    kind = KIND_PR if issue.pull_request else KIND_ISSUE
    document = {
        "id": f"{repo_full_name}#{issue.number}",
        "repoId": repo_full_name,
        "number": issue.number,
        "kind": kind,
        "title": issue.title,
        "url": issue.html_url,
        "state": issue.state,
        "author": issue.user.login if issue.user else None,
        "labels": _names(issue.labels),
        "assignees": _logins(issue.assignees),
        "createdAt": _github_dt(issue.created_at),
        "updatedAt": _github_dt(issue.updated_at),
        "closedAt": _github_dt(issue.closed_at),
        "github": {
            "id": issue.id,
            "nodeId": issue.node_id,
            "comments": issue.comments,
        },
        "syncedAt": synced_at,
    }
    if pr is not None:
        document.update(
            {
                "branch": pr.head.ref if pr.head else None,
                "draft": bool(getattr(pr, "draft", False)),
                "mergedAt": _github_dt(pr.merged_at),
            }
        )
    return document


def sync(settings: Settings | None = None, recently_closed_days: int = 90) -> dict:
    settings = settings or load_settings()
    if not settings.github_token:
        raise RuntimeError("GITHUB_TOKEN is required to sync from GitHub")

    db = get_database(settings)
    ensure_indexes(db)
    started_at = _now()
    run_id = db.syncRuns.insert_one(
        {
            "startedAt": started_at,
            "endedAt": None,
            "success": False,
            "repoCount": 0,
            "itemCount": 0,
            "error": None,
        }
    ).inserted_id

    repo_count = 0
    item_count = 0
    github = Github(settings.github_token)
    since = started_at - timedelta(days=recently_closed_days)

    try:
        for repo_name in settings.tracked_repos:
            gh_repo = github.get_repo(repo_name)
            synced_at = _now()
            repo_doc = _repo_document(gh_repo, synced_at)
            db.repos.update_one(
                {"id": repo_doc["id"]},
                {
                    "$set": repo_doc,
                    "$setOnInsert": {
                        "devs": [],
                        "products": _repo_products(repo_doc["id"]),
                        "lastTested": None,
                    },
                },
                upsert=True,
            )
            repo_count += 1

            seen_numbers: set[int] = set()
            issues = list(gh_repo.get_issues(state="open"))
            issues.extend(gh_repo.get_issues(state="closed", since=since))

            for issue in issues:
                if issue.number in seen_numbers:
                    continue
                seen_numbers.add(issue.number)
                pr = None
                if issue.pull_request:
                    try:
                        pr = gh_repo.get_pull(issue.number)
                    except GithubException:
                        pr = None
                item_doc = _item_document(repo_doc["id"], issue, pr, _now())
                db.items.update_one(
                    {"id": item_doc["id"]},
                    {
                        "$set": item_doc,
                        "$setOnInsert": default_manual_fields(issue.state),
                    },
                    upsert=True,
                )
                item_count += 1

        db.syncRuns.update_one(
            {"_id": run_id},
            {
                "$set": {
                    "endedAt": _now(),
                    "success": True,
                    "repoCount": repo_count,
                    "itemCount": item_count,
                }
            },
        )
        return {"success": True, "repoCount": repo_count, "itemCount": item_count}
    except Exception as exc:
        db.syncRuns.update_one(
            {"_id": run_id},
            {
                "$set": {
                    "endedAt": _now(),
                    "success": False,
                    "repoCount": repo_count,
                    "itemCount": item_count,
                    "error": str(exc),
                }
            },
        )
        raise
