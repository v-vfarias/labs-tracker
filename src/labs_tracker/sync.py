"""GitHub-to-MongoDB synchronization for the simplified local model."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from github import Github

from .config import Settings, load_settings
from .db import ensure_indexes, get_database
from .models import (
    KIND_ISSUE,
    KIND_PR,
    ISSUE_TYPE_VALUES,
    RESOLUTION_VALUES,
    STATE_CLOSED,
    STATE_OPEN,
    STATUS_VALUES,
    default_issue_manual_fields,
    default_repo_manual_fields,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _enum(value: str | None, options: list[str], fallback: str) -> str:
    return value if value in options else fallback


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
        "kind": KIND_PR if issue.pull_request else KIND_ISSUE,
        "title": issue.title,
        "state": _state(issue.state),
    }


def sync(settings: Settings | None = None, recently_closed_days: int = 30) -> dict:
    settings = settings or load_settings()
    if not settings.github_token:
        raise RuntimeError("GITHUB_TOKEN is required to sync from GitHub")

    db = get_database(settings)
    ensure_indexes(db)
    github = Github(settings.github_token)
    since = _now() - timedelta(days=recently_closed_days)

    repo_count = 0
    issue_count = 0

    for repo_name in settings.tracked_repos:
        gh_repo = github.get_repo(repo_name)
        repo_doc = _repo_document(gh_repo)
        repo_id = repo_doc["id"]

        db.repos.update_one(
            {"id": repo_id},
            {
                "$set": repo_doc,
                "$setOnInsert": {"_id": repo_id, **default_repo_manual_fields(repo_id)},
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
            issue_doc = _issue_document(repo_id, issue)
            issue_id = issue_doc["issueId"]
            db.issues.update_one(
                {"issueId": issue_id},
                {
                    "$set": issue_doc,
                    "$setOnInsert": {"_id": issue_id, **default_issue_manual_fields(issue.state)},
                },
                upsert=True,
            )
            issue_count += 1

    return {"success": True, "repoCount": repo_count, "issueCount": issue_count}


def simplify_collections(settings: Settings | None = None, confirm: bool = False) -> dict:
    """Normalize existing data to strict simplified `repos` and `issues` collections."""
    if not confirm:
        raise RuntimeError("simplify_collections is destructive; pass confirm=True to continue")
    settings = settings or load_settings()
    db = get_database(settings)
    collection_names = set(db.list_collection_names())

    normalized_repos: dict[str, dict] = {}
    for repo in list(db.repos.find({})):
        repo_id = repo.get("id") or repo.get("fullName")
        if not repo_id and repo.get("owner") and repo.get("name"):
            repo_id = f"{repo['owner']}/{repo['name']}"
        if not repo_id:
            continue

        manual = default_repo_manual_fields(repo_id)
        normalized_repos[repo_id] = {
            "_id": repo_id,
            "id": repo_id,
            "name": repo.get("name") or repo_id.split("/")[-1],
            "involvedDevs": list(repo.get("involvedDevs") or repo.get("devs") or manual["involvedDevs"]),
            "products": list(repo.get("products") or manual["products"]),
            "status": "Archived" if str(repo.get("status", "")).lower() == "archived" else "Live",
            "lastUpdated": _github_dt(repo.get("lastUpdated")),
            "lastTested": _github_dt(repo.get("lastTested")),
        }

    if normalized_repos:
        repo_ids = list(normalized_repos.keys())
        for repo_id, repo_doc in normalized_repos.items():
            db.repos.replace_one({"_id": repo_id}, repo_doc, upsert=True)
        db.repos.delete_many({"_id": {"$nin": repo_ids}})

    source_issues = []
    if "items" in collection_names and db.items.count_documents({}) > 0:
        source_issues.extend(list(db.items.find({})))
    source_issues.extend(list(db.issues.find({})))

    normalized_issues: dict[str, dict] = {}
    for issue in source_issues:
        issue_id = issue.get("issueId") or issue.get("id")
        if not issue_id:
            continue
        repo_id = issue.get("repoId") or issue_id.split("#")[0]
        kind = str(issue.get("kind") or "").lower()
        state = _state(issue.get("state"))
        manual = default_issue_manual_fields(state)

        normalized_issues[issue_id] = {
            "_id": issue_id,
            "issueId": issue_id,
            "repoId": repo_id,
            "kind": KIND_PR if kind == "pr" else KIND_ISSUE,
            "title": issue.get("title") or "",
            "state": state,
            "typeOfIssue": _enum(issue.get("typeOfIssue"), ISSUE_TYPE_VALUES, manual["typeOfIssue"]),
            "resolution": _enum(issue.get("resolution"), RESOLUTION_VALUES, manual["resolution"]),
            "status": _enum(issue.get("status"), STATUS_VALUES, manual["status"]),
            "lastTested": _github_dt(issue.get("lastTested")),
        }

    if normalized_issues:
        issue_ids = list(normalized_issues.keys())
        for issue_id, issue_doc in normalized_issues.items():
            db.issues.replace_one({"_id": issue_id}, issue_doc, upsert=True)
        db.issues.delete_many({"_id": {"$nin": issue_ids}})

    if "items" in collection_names:
        db.items.drop()
    if "syncRuns" in collection_names:
        db.syncRuns.drop()

    ensure_indexes(db)
    return {"repos": len(normalized_repos), "issues": len(normalized_issues)}
