"""Markdown and CSV report generation."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

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
    if isinstance(value, dict):
        value = str(value)
    elif pd.isna(value):
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def generate_report(db, output_dir: str | Path = "reports") -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    repos = _records(db.repos.find({}))
    items = _records(db.items.find({}))
    tasks = generate_tasks(db)

    repos_df = pd.DataFrame(repos)
    items_df = pd.DataFrame(items)
    tasks_df = pd.DataFrame(tasks)

    repos_df.to_csv(output_path / "repos.csv", index=False)
    items_df.to_csv(output_path / "items.csv", index=False)
    tasks_df.to_csv(output_path / "tasks.csv", index=False)

    open_items = items_df[items_df.get("state", pd.Series(dtype=str)) == "open"] if not items_df.empty else items_df
    open_issues = open_items[open_items.get("kind", pd.Series(dtype=str)) == "issue"] if not open_items.empty else open_items
    open_prs = open_items[open_items.get("kind", pd.Series(dtype=str)) == "pr"] if not open_items.empty else open_items
    pr_queue = open_prs[
        (open_prs.get("draft", pd.Series(False, index=open_prs.index)) != True)
        & (open_prs.get("testResult", pd.Series(dtype=str)) == "Not tested")
    ] if not open_prs.empty else open_prs
    closed_items = items_df[items_df.get("state", pd.Series(dtype=str)) == "closed"] if not items_df.empty else items_df
    if not closed_items.empty and "closedAt" in closed_items:
        closed_items = closed_items.sort_values("closedAt", ascending=False)

    markdown = [
        "# Labs Tracker Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Repos tracked and health signals",
        "",
        _items_table(repos_df, ["id", "status", "lastUpdated", "lastTested", "products"]),
        "",
        "## Open issues",
        "",
        _items_table(open_issues, ["repoId", "number", "title", "typeOfIssue", "testResult", "url"]),
        "",
        "## Open PRs needing validation",
        "",
        _items_table(pr_queue, ["repoId", "number", "title", "branch", "testResult", "url"]),
        "",
        "## Recently resolved/closed items",
        "",
        _items_table(closed_items, ["repoId", "number", "kind", "title", "resolution", "lastTested", "url"]),
        "",
        "## Counts by issue type",
        "",
        _count_table(items_df, "typeOfIssue"),
        "",
        "## Counts by resolution",
        "",
        _count_table(items_df, "resolution"),
        "",
        "## Counts by status",
        "",
        _count_table(items_df, "status"),
        "",
        "## Counts by test result",
        "",
        _count_table(items_df, "testResult"),
        "",
        "## Tasks of the day",
        "",
        _items_table(tasks_df, ["priority", "reason", "repoId", "number", "kind", "title", "url"], limit=50),
        "",
    ]
    report_path = output_path / "report.md"
    report_path.write_text("\n".join(markdown), encoding="utf-8")
    return report_path
