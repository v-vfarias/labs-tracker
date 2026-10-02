"""Rules for a persistent, manually selected work queue."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit

from .models import PRODUCT_VALUES


TASK_KINDS = [
    "Repository health review", "Issue triage", "Issue validation", "PR validation",
    "Product update review", "Lab impact check",
]
TASK_STATES = ["Open", "In progress", "Deferred", "Done", "Won't do"]
TERMINAL_STATES = {"Done", "Won't do"}
WONT_DO_REASONS = [
    "Out of scope", "Duplicate", "Superseded / obsolete", "Already handled elsewhere",
    "Not relevant to tracked labs", "Accepted risk / low value", "Other",
]
DETAIL_REQUIRED = {"Duplicate", "Already handled elsewhere", "Accepted risk / low value", "Other"}
TASK_ACTIONS = [
    "Select for today", "Return to backlog", "In progress", "Done", "Deferred",
    "Won't do", "Reopen", "Add note",
]


class TaskValidationError(ValueError):
    pass


@dataclass(frozen=True, kw_only=True)
class TaskDraft:
    title: str
    kind: str
    repo_id: str = ""
    product: str = ""
    source_url: str = ""
    reason: str = ""


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def local_day(value: datetime) -> date:
    return utc(value).astimezone().date()


def parse_day(value: str) -> date:
    try:
        result = date.fromisoformat(value)
    except ValueError as error:
        raise TaskValidationError("Enter a date as YYYY-MM-DD") from error
    if result.isoformat() != value:
        raise TaskValidationError("Enter a date as YYYY-MM-DD")
    return result


def local_week(day: date) -> tuple[datetime, datetime]:
    monday = day - timedelta(days=day.weekday())
    # Convert each local midnight separately so DST weeks need not be 168 hours.
    start = datetime.combine(monday, time.min).astimezone(timezone.utc)
    end = datetime.combine(monday + timedelta(days=7), time.min).astimezone(timezone.utc)
    return start, end


def draft_fields(draft: TaskDraft) -> dict:
    if not draft.title.strip():
        raise TaskValidationError("Enter a task title")
    if draft.kind not in TASK_KINDS:
        raise TaskValidationError("Choose a valid task type")
    if draft.product.strip() and draft.product.strip() not in PRODUCT_VALUES:
        raise TaskValidationError("Choose a supported product")
    source = draft.source_url.strip()
    if source:
        try:
            parsed = urlsplit(source)
            valid = parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
        except ValueError as error:
            raise TaskValidationError("Source must be a valid HTTPS URL") from error
        if not valid:
            raise TaskValidationError("Source must be an HTTPS URL without credentials")
    return {
        "title": draft.title.strip(), "kind": draft.kind, "repoId": draft.repo_id.strip(),
        "product": draft.product.strip(), "sourceUrl": source, "reason": draft.reason.strip(),
        "status": "Open", "selectedForDate": None, "deferredUntil": None,
        "completedAt": None, "outcome": "", "wontDoReason": "", "decisionNote": "",
    }


def task_changes(task: dict, action: str, *, note: str = "", reason: str = "",
                 revisit: str = "", now: datetime) -> dict:
    if action not in TASK_ACTIONS:
        raise TaskValidationError("Choose a valid task action")
    note, reason = note.strip(), reason.strip()
    terminal = task["status"] in TERMINAL_STATES
    if terminal and action not in {"Reopen", "Add note"}:
        raise TaskValidationError("Reopen this task before changing its decision")
    if action == "Add note":
        if not note:
            raise TaskValidationError("Add a nonblank progress note")
        return {}
    if action == "Reopen":
        if not terminal or not note:
            raise TaskValidationError("Reopening a completed or declined task requires a note")
        return {"status": "Open", "completedAt": None, "selectedForDate": None,
                "deferredUntil": None, "outcome": "", "wontDoReason": "", "decisionNote": ""}
    if action == "Select for today":
        if task.get("deferredUntil") and parse_day(task["deferredUntil"]) > local_day(now):
            raise TaskValidationError("This task is deferred; return it to backlog before selecting it")
        return {"selectedForDate": local_day(now).isoformat(), "deferredUntil": None,
                "status": "Open" if task["status"] == "Deferred" else task["status"]}
    if action == "Return to backlog":
        return {"selectedForDate": None, "deferredUntil": None,
                "status": "Open" if task["status"] == "Deferred" else task["status"]}
    if action == "Deferred":
        if not revisit or parse_day(revisit) <= local_day(now):
            raise TaskValidationError("Choose a future revisit date")
        return {"status": action, "deferredUntil": revisit, "selectedForDate": None}
    if action == "Done":
        if not note:
            raise TaskValidationError("Add an outcome summary before marking done")
        return {"status": action, "outcome": note, "completedAt": now,
                "deferredUntil": None, "selectedForDate": None}
    if action == "Won't do":
        if reason and reason not in WONT_DO_REASONS:
            raise TaskValidationError("Choose a valid Won't do reason")
        if not reason and not note:
            raise TaskValidationError("Select a reason or provide a description")
        if reason in DETAIL_REQUIRED and not note:
            raise TaskValidationError("This reason requires supporting detail or a reference")
        return {"status": action, "wontDoReason": reason or "Other", "decisionNote": note,
                "deferredUntil": None, "selectedForDate": None}
    return {"status": "In progress", "deferredUntil": None}


def queue_bucket(task: dict, today: date) -> str:
    if task["status"] in TERMINAL_STATES:
        return "History"
    if task.get("deferredUntil") and parse_day(task["deferredUntil"]) > today:
        return "Deferred"
    selected = task.get("selectedForDate")
    if selected and parse_day(selected) <= today:
        return "Carry-over" if parse_day(selected) < today else "Today"
    return "Backlog"
