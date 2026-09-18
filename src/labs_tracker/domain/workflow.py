"""General issue progress updates and observed elapsed-time metrics."""
from datetime import datetime, timezone

from .models import HANDLING_STAGE_VALUES, WAIT_REASON_VALUES


LEGACY_STAGES = {
    "Reproducing": "Investigating",
    "Confirmed": "In progress",
    "External report required": "In progress",
    "Reported to Skillable": "Waiting",
    "Skillable responded": "Investigating",
}


def handling_stage(issue: dict) -> str:
    stage = issue.get("handlingStage")
    if stage in HANDLING_STAGE_VALUES:
        return stage
    return LEGACY_STAGES.get(stage, "Resolved" if issue.get("state") == "Closed" else "Raised")


def waiting_details(issue: dict) -> tuple[str, str]:
    if issue.get("handlingStage") == "Reported to Skillable":
        return "External dependency", issue.get("waitingOn") or "Skillable"
    return issue.get("waitingReason") or "None", issue.get("waitingOn") or ""


def progress_update(issue: dict, stage: str, note: str, reason: str = "None", waiting_on: str = "", *, now: datetime | None = None, evidence: dict | None = None) -> dict:
    if stage not in HANDLING_STAGE_VALUES:
        raise ValueError("Choose a valid handling stage")
    note = note.strip()
    if stage == "Waiting":
        if reason not in WAIT_REASON_VALUES or reason == "None":
            raise ValueError("Choose a waiting reason")
    else:
        reason, waiting_on = "None", ""
    changed = stage != handling_stage(issue) or (reason, waiting_on.strip()) != waiting_details(issue)
    if changed and not note:
        raise ValueError("Add a progress note explaining the stage or waiting change")
    evidence = evidence or {}
    evidence_changed = any(value != (issue.get(key) or "") for key, value in evidence.items())
    if issue.get("handlingHistory") and not (changed or note or evidence_changed):
        return {"$set": {}}
    timestamp = now or datetime.now(timezone.utc)
    event = {
        "at": timestamp, "stage": stage, "note": note,
        "waitingReason": reason, "waitingOn": waiting_on.strip(),
        "evidence": {key: evidence.get(key, issue.get(key) or "") for key in ("reproductionNotes", "externalReportUrl", "externalResponse")},
    }
    if not issue.get("handlingHistory") and issue.get("handlingStage"):
        event["previousStage"] = issue["handlingStage"]
    return {
        "$set": {"handlingStage": stage, "handlingUpdatedAt": timestamp, "waitingReason": reason, "waitingOn": waiting_on.strip()},
        "$push": {"handlingHistory": event},
    }


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def progress_metrics(issue: dict, *, now: datetime | None = None) -> dict:
    current = _utc(now or datetime.now(timezone.utc))
    history = sorted(issue.get("handlingHistory") or [], key=lambda event: _utc(event["at"]))
    durations = {stage: 0.0 for stage in HANDLING_STAGE_VALUES}
    waits: dict[str, float] = {}
    for index, event in enumerate(history):
        end = min(_utc(history[index + 1]["at"]), current) if index + 1 < len(history) else current
        hours = max(0.0, (end - _utc(event["at"])).total_seconds() / 3600)
        stage = event["stage"]
        if stage == "Resolved":
            continue
        durations[stage] = durations.get(stage, 0.0) + hours
        if stage == "Waiting":
            label = event.get("waitingReason") or "Other"
            if event.get("waitingOn"):
                label += f": {event['waitingOn']}"
            waits[label] = waits.get(label, 0.0) + hours
    stage_since = None
    for event in reversed(history):
        if event["stage"] != history[-1]["stage"]:
            break
        stage_since = _utc(event["at"])
    return {
        "handlingStage": handling_stage(issue),
        "trackedSince": _utc(history[0]["at"]) if history else None,
        "observedHours": round(sum(durations.values()), 2) if history else None,
        "waitingHours": round(durations["Waiting"], 2) if history else None,
        "stageHours": round(max(0.0, (current - stage_since).total_seconds() / 3600), 2) if stage_since and history[-1]["stage"] != "Resolved" else (0.0 if history else None),
        "delayReasons": "; ".join(f"{label} ({hours:.1f}h)" for label, hours in waits.items()),
        "stageDurations": "; ".join(f"{stage} ({hours:.1f}h)" for stage, hours in durations.items() if hours),
        "latestProgress": next((event["note"] for event in reversed(history) if event.get("note")), ""),
    }