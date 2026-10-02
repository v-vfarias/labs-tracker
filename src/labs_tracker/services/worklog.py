"""Persistence for tasks; suggestion reads never imply completed work."""
from datetime import datetime, timezone
from hashlib import sha256
import json

from pymongo.errors import DuplicateKeyError

from ..domain.tasks import TERMINAL_STATES, TaskDraft, TaskValidationError, draft_fields, local_day, queue_bucket, task_changes, utc
from .tasks import generate_tasks


class TaskConflictError(TaskValidationError):
    pass


def _event(task: dict, action: str, note: str, event_id: str, now: datetime) -> dict:
    return {
        "eventId": event_id, "at": now, "action": action, "note": note.strip(),
        "snapshot": {key: value for key, value in task.items() if key not in {"_id", "history"}},
    }


def create_task(db, draft: TaskDraft, *, task_id: str, dedupe_key: str | None = None,
                now: datetime | None = None, priority: int = 50) -> str:
    fields = draft_fields(draft)
    if not task_id.strip():
        raise TaskValidationError("A task identifier is required")
    timestamp = utc(now or datetime.now(timezone.utc))
    key = dedupe_key or f"manual:{task_id}"
    task = {
        **fields, "taskId": task_id, "dedupeKey": key, "priority": priority,
        "version": 0, "createdAt": timestamp, "updatedAt": timestamp,
    }
    task["history"] = [_event(task, "Created", "", task_id, timestamp)]
    try:
        db.tasks.update_one({"dedupeKey": key}, {"$setOnInsert": task}, upsert=True)
    except DuplicateKeyError:
        existing = db.tasks.find_one({"dedupeKey": key})
        if existing is None:
            raise
    saved = db.tasks.find_one({"dedupeKey": key})
    if saved is None:
        raise TaskConflictError("Task was not saved; refresh and try again")
    return saved["taskId"]


def get_task(db, task_id: str) -> dict:
    task = db.tasks.find_one({"taskId": task_id})
    if task is None:
        raise TaskValidationError("Task no longer exists; refresh the list")
    return task


def update_task(db, task_id: str, version: int, action: str, *, event_id: str,
                note: str = "", reason: str = "", revisit: str = "",
                now: datetime | None = None) -> None:
    if not event_id.strip():
        raise TaskValidationError("An action identifier is required")
    task = get_task(db, task_id)
    if any(event["eventId"] == event_id for event in task["history"]):
        return
    if task["version"] != version:
        raise TaskConflictError("Task changed in another window; reopen it and try again")
    timestamp = utc(now or datetime.now(timezone.utc))
    changes = task_changes(task, action, note=note, reason=reason, revisit=revisit, now=timestamp)
    if action != "Add note" and all(task.get(key) == value for key, value in changes.items()):
        return
    changes.update(version=version + 1, updatedAt=timestamp)
    event = _event({**task, **changes}, action, note, event_id, timestamp)
    result = db.tasks.update_one(
        {"taskId": task_id, "version": version},
        {"$set": changes, "$push": {"history": event}},
    )
    if result.matched_count != 1:
        latest = get_task(db, task_id)
        if any(item["eventId"] == event_id for item in latest["history"]):
            return
        raise TaskConflictError("Task changed in another window; reopen it and try again")


def list_tasks(db, *, now: datetime | None = None) -> list[dict]:
    today = local_day(now or datetime.now(timezone.utc))
    tasks = [
        {**task, "bucket": queue_bucket(task, today)}
        for task in db.tasks.find({})
    ]
    return sorted(tasks, key=lambda task: (task["priority"], utc(task["createdAt"]), task["taskId"]))


def _suggestion_key(suggestion: dict) -> str:
    return sha256(json.dumps(
        [suggestion.get("repoId") or "", suggestion.get("issueId") or "", suggestion["reason"], ""],
        ensure_ascii=True,
    ).encode()).hexdigest()


def retire_ineligible_suggestions(db, *, now: datetime | None = None) -> int:
    """Retain obsolete suggestions as explained decisions, never completed work."""
    eligible = {_suggestion_key(suggestion) for suggestion in generate_tasks(db)}
    retired = 0
    for task in db.tasks.find({}):
        if not task["taskId"].startswith("suggested:") or task["status"] in TERMINAL_STATES:
            continue
        if task["dedupeKey"] in eligible:
            continue
        update_task(
            db, task["taskId"], task["version"], "Won't do",
            event_id=f"ineligible:{task['version']}", reason="Superseded / obsolete",
            note="Automatically retired: the source no longer qualifies for a pending classification, review, or details task.",
            now=now,
        )
        retired += 1
    return retired


def suggest_tasks(db, *, now: datetime | None = None) -> int:
    """Reconcile and import eligible stored-data work without automatic selection."""
    retire_ineligible_suggestions(db, now=now)
    created = 0
    for suggestion in generate_tasks(db):
        repo_id = suggestion.get("repoId") or ""
        kind = "PR validation" if suggestion["kind"] == "PR" else (
            "Issue triage" if suggestion["priority"] in {20, 25} else "Issue validation"
        )
        number = suggestion["number"]
        route = "pull" if suggestion["kind"] == "PR" else "issues"
        source = f"https://github.com/{repo_id}/{route}/{number}"
        key = _suggestion_key(suggestion)
        existing = db.tasks.find_one({"dedupeKey": key})
        create_task(
            db, TaskDraft(title=suggestion.get("title") or suggestion["reason"], kind=kind,
                          repo_id=repo_id, source_url=source, reason=suggestion["reason"]),
            task_id=f"suggested:{key}", dedupe_key=key, now=now, priority=suggestion["priority"],
        )
        if existing and existing["status"] == "Won't do" and existing["history"][-1]["eventId"].startswith("ineligible:"):
            update_task(
                db, existing["taskId"], existing["version"], "Reopen",
                event_id=f"eligible:{existing['version']}",
                note="Automatically reopened: the source qualifies for this pending task again.", now=now,
            )
        created += existing is None
    return created
