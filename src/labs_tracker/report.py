"""Markdown and CSV report generation for simplified collections."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .models import KIND_ISSUE, KIND_PR, STATE_OPEN, normalize_issue_type, normalize_resolution
from .tasks import generate_tasks


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


def generate_report(db, output_dir: str | Path = "reports") -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    repos = _records(db.repos.find({}))
    issues = _records(db.issues.find({}))
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
