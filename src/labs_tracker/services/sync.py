"""Synchronize GitHub-owned fields while preserving manual progress."""
from __future__ import annotations

from ..config import Settings, load_settings
from ..db import ensure_indexes, get_database
from ..domain.models import KIND_ISSUE, default_issue_manual_fields, default_repo_manual_fields
from ..integrations.github import get_github, _repo_document, _issue_document, _latest_closed_issues


def sync(settings: Settings | None = None, closed_issue_limit: int = 10, prune: bool = True) -> dict:
    settings = settings or load_settings()
    if not settings.github_token:
        raise RuntimeError("GITHUB_TOKEN is required to sync from GitHub")

    db = get_database(settings)
    ensure_indexes(db)
    github = get_github(settings.github_token)

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

