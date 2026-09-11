"""Daily task generation from current MongoDB state."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from .models import KIND_PR


def _as_aware(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _item_task(priority: int, reason: str, item: dict) -> dict:
    return {
        "priority": priority,
        "reason": reason,
        "repoId": item.get("repoId"),
        "itemId": item.get("id"),
        "number": item.get("number"),
        "title": item.get("title"),
        "kind": item.get("kind"),
        "url": item.get("url"),
    }


def _repo_task(priority: int, reason: str, repo: dict) -> dict:
    return {
        "priority": priority,
        "reason": reason,
        "repoId": repo.get("id"),
        "itemId": None,
        "number": None,
        "title": repo.get("fullName") or repo.get("name"),
        "kind": "repo",
        "url": repo.get("htmlUrl"),
    }


def generate_tasks(db) -> list[dict]:
    tasks: list[dict] = []
    now = datetime.now(timezone.utc)

    for item in db.items.find({}):
        state = item.get("state")
        kind = item.get("kind")
        test_result = item.get("testResult")
        last_tested = _as_aware(item.get("lastTested"))
        updated_at = _as_aware(item.get("updatedAt"))
        created_at = _as_aware(item.get("createdAt"))
        is_untested = last_tested is None or test_result == "Not tested"

        if item.get("typeOfIssue") == "Unknown" or item.get("resolution") == "Unknown":
            tasks.append(_item_task(20, "New/unclassified issue or PR: triage/classify", item))

        if state == "open" and kind != KIND_PR and is_untested:
            tasks.append(_item_task(30, "Open issue needs reproduction verification", item))

        if state == "open" and kind == KIND_PR and not item.get("draft", False) and is_untested:
            tasks.append(_item_task(30, "Open PR needs maintainer validation", item))

        if state == "closed" and last_tested is None:
            tasks.append(_item_task(40, "Closed GitHub issue/PR needs validation recorded", item))

        if (
            state == "open"
            and kind == KIND_PR
            and is_untested
            and created_at is not None
            and created_at < now - timedelta(days=14)
        ):
            tasks.append(_item_task(50, "Aging contribution: PR open over 14 days and untested", item))

        if updated_at and last_tested and updated_at > last_tested:
            tasks.append(_item_task(60, "Item changed after last validation", item))

    for repo in db.repos.find({}):
        last_updated = _as_aware(repo.get("lastUpdated"))
        last_tested = _as_aware(repo.get("lastTested"))
        if last_updated and (last_tested is None or last_updated > last_tested):
            tasks.append(_repo_task(35, "Repo changed after last test; retest after repo changes", repo))

    return sorted(tasks, key=lambda task: (task["priority"], task.get("repoId") or "", task.get("number") or 0))
