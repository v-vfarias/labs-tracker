"""Explicitly confirmed normalization of legacy collections."""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import Settings, load_settings
from ..db import ensure_indexes, get_database
from ..domain.models import KIND_ISSUE, STATUS_VALUES, default_issue_manual_fields, default_repo_manual_fields, normalize_issue_type, normalize_resolution
from ..domain.workflow import handling_stage, progress_update, waiting_details
from ..integrations.github import _github_dt, _state
from .worklog import retire_ineligible_suggestions


def _enum(value: str | None, options: list[str], fallback: str) -> str:
    return value if value in options else fallback


def resolve_local_baseline(db, *, confirm: bool = False, now: datetime | None = None) -> dict:
    """Apply a user-asserted baseline, preserving GitHub metadata and prior history."""
    if not confirm:
        raise RuntimeError("Local baseline changes all stored issues and repos; pass confirm=True")
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("Baseline timestamp must include a timezone")
    timestamp = timestamp.astimezone(timezone.utc)
    note = (
        "User-confirmed baseline: treated as resolved locally and tested at this time. "
        "No automated test was run; GitHub state and existing classification/evidence are unchanged."
    )
    issues = 0
    for issue in db.issues.find({}):
        update = progress_update(issue, "Resolved", note, now=timestamp)
        update["$set"].update(status="Resolved locally", lastTested=timestamp)
        result = db.issues.update_one({"_id": issue["_id"]}, update)
        if result.matched_count != 1:
            raise RuntimeError("Issue disappeared during baseline update; inspect the backup before retrying")
        issues += 1
    repos = 0
    for repo in db.repos.find({}):
        result = db.repos.update_one({"_id": repo["_id"]}, {"$set": {"lastTested": timestamp}})
        if result.matched_count != 1:
            raise RuntimeError("Repository disappeared during baseline update; inspect the backup before retrying")
        repos += 1
    retired = retire_ineligible_suggestions(db, now=timestamp)
    return {"repos": repos, "issues": issues, "retiredTasks": retired, "testedAt": timestamp}


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
