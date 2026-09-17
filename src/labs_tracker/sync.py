"""GitHub-to-MongoDB synchronization for the simplified local model."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from github import Github

from .config import Settings, load_settings
from .db import ensure_indexes, get_database
from .workflow import handling_stage, waiting_details
from .models import (
    HANDLING_STAGE_VALUES,
    KIND_ISSUE,
    ISSUE_TYPE_VALUES,
    RESOLUTION_VALUES,
    STATE_CLOSED,
    STATE_OPEN,
    STATUS_VALUES,
    default_issue_manual_fields,
    default_repo_manual_fields,
    normalize_issue_type,
    normalize_resolution,
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


def sync(settings: Settings | None = None, closed_issue_limit: int = 10, prune: bool = True) -> dict:
    settings = settings or load_settings()
    if not settings.github_token:
        raise RuntimeError("GITHUB_TOKEN is required to sync from GitHub")

    db = get_database(settings)
    ensure_indexes(db)
    github = Github(settings.github_token)

    repo_count = 0
    issue_count = 0
    synced_repo_ids: set[str] = set()
    synced_issue_ids: set[str] = set()

    for repo_name in settings.tracked_repos:
        gh_repo = github.get_repo(repo_name)
        repo_doc = _repo_document(gh_repo)
        repo_id = repo_doc["id"]
        synced_repo_ids.add(repo_id)

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
        issues = [issue for issue in gh_repo.get_issues(state="open") if not issue.pull_request]
        issues.extend(_latest_closed_issues(gh_repo, closed_issue_limit))

        for issue in issues:
            if issue.number in seen_numbers:
                continue
            seen_numbers.add(issue.number)
            issue_doc = _issue_document(repo_id, issue)
            issue_id = issue_doc["issueId"]
            synced_issue_ids.add(issue_id)
            db.issues.update_one(
                {"issueId": issue_id},
                {
                    "$set": issue_doc,
                    "$setOnInsert": {"_id": issue_id, **default_issue_manual_fields(issue.state)},
                },
                upsert=True,
            )
            issue_count += 1

    if prune:
        db.repos.delete_many({"id": {"$nin": list(synced_repo_ids)}})
        db.issues.delete_many({"handlingHistory.0": {"$exists": False}, "$or": [{"repoId": {"$nin": list(synced_repo_ids)}}, {"kind": {"$ne": KIND_ISSUE}}, {"issueId": {"$nin": list(synced_issue_ids)}}]})

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
            db.repos.update_one(
                {"id": repo_id},
                {
                    "$set": {key: value for key, value in repo_doc.items() if key != "_id"},
                    "$setOnInsert": {"_id": repo_id},
                },
                upsert=True,
            )
        db.repos.delete_many({"id": {"$nin": repo_ids}})

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

        if kind == "pr":
            continue

        normalized_issues[issue_id] = {
            "_id": issue_id,
            "issueId": issue_id,
            "repoId": repo_id,
            "kind": KIND_ISSUE,
            "title": issue.get("title") or "",
            "state": state,
            "typeOfIssue": normalize_issue_type(issue.get("typeOfIssue") or manual["typeOfIssue"]),
            "resolution": normalize_resolution(issue.get("resolution") or manual["resolution"]),
            "status": _enum(issue.get("status"), STATUS_VALUES, manual["status"]),
            "handlingStage": handling_stage({**issue, "state": state}),
            "handlingHistory": issue.get("handlingHistory") or [],
            "waitingReason": waiting_details(issue)[0],
            "waitingOn": waiting_details(issue)[1],
            "reproductionNotes": issue.get("reproductionNotes") or manual["reproductionNotes"],
            "externalReportUrl": issue.get("externalReportUrl") or manual["externalReportUrl"],
            "externalResponse": issue.get("externalResponse") or manual["externalResponse"],
            "handlingUpdatedAt": _github_dt(issue.get("handlingUpdatedAt")),
            "lastTested": _github_dt(issue.get("lastTested")),
            "closingPrUrl": issue.get("closingPrUrl") or manual["closingPrUrl"],
        }

    if normalized_issues:
        issue_ids = list(normalized_issues.keys())
        for issue_id, issue_doc in normalized_issues.items():
            db.issues.update_one(
                {"issueId": issue_id},
                {
                    "$set": {key: value for key, value in issue_doc.items() if key != "_id"},
                    "$setOnInsert": {"_id": issue_id},
                },
                upsert=True,
            )
        db.issues.delete_many({"issueId": {"$nin": issue_ids}})

    if "items" in collection_names:
        db.items.drop()
    if "syncRuns" in collection_names:
        db.syncRuns.drop()

    ensure_indexes(db)
    return {"repos": len(normalized_repos), "issues": len(normalized_issues)}
