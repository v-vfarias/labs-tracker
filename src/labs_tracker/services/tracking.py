"""Tracking input parsing and classification query policies."""
from datetime import datetime, timezone

from ..domain.models import ISSUE_TYPE_ALIASES, ISSUE_TYPE_VALUES, RESOLUTION_ALIASES, RESOLUTION_VALUES


def _parse_dt(value: str):
    value = value.strip()
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_csv(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return [item.strip() for item in value.split(",") if item.strip()]


def _issue_type_query(value: str) -> dict:
    if value == "Unknown":
        known_values = [issue_type for issue_type in ISSUE_TYPE_VALUES if issue_type != "Unknown"]
        known_values.extend(ISSUE_TYPE_ALIASES)
        return {"$nin": known_values}
    return {"$in": [value, *[legacy for legacy, compact in ISSUE_TYPE_ALIASES.items() if compact == value]]}


def _resolution_query(value: str) -> dict:
    if value == "Unknown":
        known_values = [resolution for resolution in RESOLUTION_VALUES if resolution != "Unknown"]
        known_values.extend(RESOLUTION_ALIASES)
        return {"$nin": known_values}
    return {"$in": [value, *[legacy for legacy, compact in RESOLUTION_ALIASES.items() if compact == value]]}


def _needs_classification_query() -> dict:
    return {"$or": [{"typeOfIssue": _issue_type_query("Unknown")}, {"resolution": _resolution_query("Unknown")}]} 

