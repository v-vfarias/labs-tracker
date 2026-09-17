"""Markdown and CSV report generation for simplified collections."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

import pandas as pd

from .models import KIND_ISSUE, KIND_PR, STATE_OPEN, normalize_issue_type, normalize_resolution
from .tasks import generate_tasks
from .workflow import progress_metrics


REPORT_FILTER_KEYS = {"repoId", "state", "status", "typeOfIssue"}


def _records(cursor) -> list[dict]:
    records = []
    for doc in cursor:
        doc = dict(doc)
        doc.pop("_id", None)
        records.append(doc)
    return records


def _count_table(df: pd.DataFrame, column: str) -> str:
    if df.empty or column not in df:
        return "No data."
    counts = df[column].fillna("Unknown").value_counts().reset_index()
    counts.columns = [column, "count"]
    return _markdown_table(counts)


def _items_table(df: pd.DataFrame, columns: list[str], limit: int = 20) -> str:
    if df.empty:
        return "No items."
    existing = [column for column in columns if column in df]
    return _markdown_table(df[existing].head(limit))


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "No data."
    headers = list(df.columns)
    rows = []
    for _, row in df.iterrows():
        rows.append([_format_cell(row.get(header)) for header in headers])
    header_line = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header_line, separator, *body])


def _format_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(item) for item in value)
    elif pd.isna(value):
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _issue_query(filters: dict | None = None) -> dict:
    query = {"kind": KIND_ISSUE}
    filters = filters or {}
    for key in REPORT_FILTER_KEYS:
        value = filters.get(key)
        if value and value != "All":
            query[key] = value
    return query


def _issue_url(issue_id: str | None) -> str:
    if not issue_id or "#" not in issue_id:
        return ""
    repo_id, number = issue_id.rsplit("#", 1)
    return f"https://github.com/{repo_id}/issues/{number}" if repo_id and number else ""


def _count_rows(values) -> list[dict[str, int | str]]:
    return [
        {"label": label, "count": count}
        for label, count in Counter(value or "Unknown" for value in values).most_common()
    ]


def build_issue_report(db, filters: dict | None = None) -> dict:
    now = datetime.now(timezone.utc)
    rows = []
    for doc in db.issues.find(_issue_query(filters)).sort("issueId", 1):
        issue_id = doc.get("issueId")
        rows.append(
            {
                "issueId": issue_id,
                "repoId": doc.get("repoId") or "Unknown",
                "title": doc.get("title") or "Untitled issue",
                "state": doc.get("state") or "Unknown",
                "status": doc.get("status") or "Unknown",
                "typeOfIssue": normalize_issue_type(doc.get("typeOfIssue")),
                "resolution": normalize_resolution(doc.get("resolution")),
                "issueUrl": _issue_url(issue_id),
                **progress_metrics(doc, now=now),
            }
        )

    return {
        "generatedAt": datetime.now(timezone.utc),
        "filters": {key: (filters or {}).get(key, "All") for key in sorted(REPORT_FILTER_KEYS)},
        "total": len(rows),
        "open": sum(1 for row in rows if row["state"] == STATE_OPEN),
        "closed": sum(1 for row in rows if row["state"] != STATE_OPEN),
        "byType": _count_rows(row["typeOfIssue"] for row in rows),
        "byResolution": _count_rows(row["resolution"] for row in rows),
        "byStatus": _count_rows(row["status"] for row in rows),
        "byRepo": _count_rows(row["repoId"] for row in rows),
        "rows": rows,
        "longestRunning": sorted(rows, key=lambda row: row["observedHours"] if row["observedHours"] is not None else -1, reverse=True),
    }


def generate_report(db, output_dir: str | Path = "reports") -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    repos = _records(db.repos.find({}))
    issues = _records(db.issues.find({}))
    now = datetime.now(timezone.utc)
    for issue in issues:
        issue.update(progress_metrics(issue, now=now))
    tasks = generate_tasks(db)

    repos_df = pd.DataFrame(repos)
    issues_df = pd.DataFrame(issues)
    tasks_df = pd.DataFrame(tasks)
    if not issues_df.empty:
        if "typeOfIssue" in issues_df:
            issues_df["typeOfIssue"] = issues_df["typeOfIssue"].apply(normalize_issue_type)
        if "resolution" in issues_df:
            issues_df["resolution"] = issues_df["resolution"].apply(normalize_resolution)

    repos_df.to_csv(output_path / "repos.csv", index=False)
    issues_df.to_csv(output_path / "issues.csv", index=False)
    tasks_df.to_csv(output_path / "tasks.csv", index=False)

    open_items = issues_df[issues_df.get("state", pd.Series(dtype=str)) == STATE_OPEN] if not issues_df.empty else issues_df
    open_issues = open_items[open_items.get("kind", pd.Series(dtype=str)) == KIND_ISSUE] if not open_items.empty else open_items
    open_prs = open_items[open_items.get("kind", pd.Series(dtype=str)) == KIND_PR] if not open_items.empty else open_items
    closed_items = issues_df[issues_df.get("state", pd.Series(dtype=str)) != STATE_OPEN] if not issues_df.empty else issues_df

    markdown = [
        "# Labs Tracker Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Repos",
        "",
        _items_table(repos_df, ["id", "name", "status", "lastUpdated", "lastTested", "products", "involvedDevs"]),
        "",
        "## Open Issues",
        "",
        _items_table(open_issues, ["issueId", "repoId", "title", "typeOfIssue", "status", "lastTested"]),
        "",
        "## Open PRs",
        "",
        _items_table(open_prs, ["issueId", "repoId", "title", "typeOfIssue", "status", "lastTested"]),
        "",
        "## Closed Items",
        "",
        _items_table(closed_items, ["issueId", "repoId", "kind", "title", "resolution", "status", "lastTested"]),
        "",
        "## Counts by typeOfIssue",
        "",
        _count_table(issues_df, "typeOfIssue"),
        "",
        "## Resolution Progress (Longest Observed First)",
        "",
        "Observed hours exclude resolved periods. Blank timing means no recorded history; this is elapsed time, not effort or full issue age.",
        "",
        _items_table(issues_df.sort_values("observedHours", ascending=False) if not issues_df.empty else issues_df, ["issueId", "handlingStage", "trackedSince", "observedHours", "waitingHours", "stageDurations", "delayReasons", "latestProgress"]),
        "",
        "## Counts by resolution",
        "",
        _count_table(issues_df, "resolution"),
        "",
        "## Counts by status",
        "",
        _count_table(issues_df, "status"),
        "",
        "## Tasks",
        "",
        _items_table(tasks_df, ["priority", "reason", "repoId", "issueId", "kind", "title", "state"], limit=50),
        "",
    ]

    report_path = output_path / "report.md"
    report_path.write_text("\n".join(markdown), encoding="utf-8")
    return report_path
