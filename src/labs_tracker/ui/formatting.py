"""Presentation-only dates, labels, links and table event parsing."""
from datetime import datetime, timezone


def _to_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _fmt_dt(value) -> str:
    dt = _to_dt(value)
    return dt.isoformat() if dt else ""


def _fmt_table_dt(value) -> str:
    dt = _to_dt(value)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def _issue_url(issue_id: str | None, kind: str | None = None) -> str | None:
    if not issue_id or "#" not in issue_id:
        return None
    repo_id, number = issue_id.rsplit("#", 1)
    if not repo_id or not number:
        return None
    route = "pull" if kind == "PR" else "issues"
    return f"https://github.com/{repo_id}/{route}/{number}"


def _issue_number(issue_id: str | None) -> str:
    if not issue_id or "#" not in issue_id:
        return issue_id or ""
    return f"#{issue_id.rsplit('#', 1)[1]}"


def _repo_url(repo_id: str | None) -> str | None:
    return f"https://github.com/{repo_id}" if repo_id else None


def _repo_lab_name(repo_id: str | None, name: str | None = None) -> str:
    return name or (repo_id or "").split("/")[-1]


def _table_event_row(args):
    if isinstance(args, dict):
        row = args.get("row")
    elif isinstance(args, list | tuple) and len(args) > 1:
        row = args[1]
    else:
        row = None
    return row if isinstance(row, dict) else {}

