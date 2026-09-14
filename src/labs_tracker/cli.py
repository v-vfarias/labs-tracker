"""Typer command line interface for the local lab tracker."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import load_settings
from .db import ensure_indexes, get_database
from .models import ISSUE_TYPE_VALUES, RESOLUTION_VALUES, STATUS_VALUES
from .report import generate_report
from .sync import simplify_collections, sync as run_sync
from .tasks import generate_tasks

app = typer.Typer(help="Local GitHub lab issue/PR validation tracker.")
console = Console()


def _db():
    db = get_database(load_settings())
    ensure_indexes(db)
    return db


def _choose(prompt: str, choices: list[str], default: str) -> str:
    console.print(f"\n{prompt}")
    for index, choice in enumerate(choices, start=1):
        console.print(f"  {index}. {choice}")
    value = typer.prompt("Choose number or enter value", default=default)
    if value.isdigit() and 1 <= int(value) <= len(choices):
        return choices[int(value) - 1]
    return value


@app.command()
def sync(recently_closed_days: int = typer.Option(30, help="Closed items updated within this many days are synced.")):
    """Run GitHub sync for TRACKED_REPOS."""
    result = run_sync(recently_closed_days=recently_closed_days)
    console.print(f"Synced {result['repoCount']} repo(s) and {result['issueCount']} issue/pr record(s).")


@app.command()
def simplify():
    """Normalize existing data to strict simplified repos/issues schema."""
    result = simplify_collections()
    console.print(f"Simplified collections: {result['repos']} repo(s), {result['issues']} issue/pr record(s).")


@app.command()
def tasks():
    """Print generated tasks of the day."""
    generated = generate_tasks(_db())
    table = Table(title="Tasks of the day")
    for column in ["priority", "reason", "repoId", "issueId", "kind", "state", "title"]:
        table.add_column(column)
    for task in generated:
        table.add_row(*[str(task.get(column) or "") for column in ["priority", "reason", "repoId", "issueId", "kind", "state", "title"]])
    console.print(table)


@app.command()
def classify(limit: int = typer.Option(10, help="Maximum open unknown/untested items to offer.")):
    """Interactively update manual simplified classification fields."""
    db = _db()
    query = {
        "state": "Open",
        "$or": [
            {"typeOfIssue": "Unknown"},
            {"resolution": "Unknown"},
            {"lastTested": None},
        ],
    }
    items = list(db.issues.find(query).sort([("issueId", 1)]).limit(limit))
    if not items:
        console.print("No open unknown/untested issue/pr records found.")
        return

    for index, item in enumerate(items, start=1):
        console.print(f"[{index}] {item.get('issueId')} {item.get('kind')} {item.get('state')}: {item.get('title')}")
    selected = typer.prompt("Select item number to classify", default="1")
    if not selected.isdigit() or not (1 <= int(selected) <= len(items)):
        raise typer.BadParameter("Select a listed item number")
    item = items[int(selected) - 1]

    type_of_issue = _choose("Type of issue", ISSUE_TYPE_VALUES, item.get("typeOfIssue", "Unknown"))
    resolution = _choose("Resolution", RESOLUTION_VALUES, item.get("resolution", "Unknown"))
    status = _choose("Manual status", STATUS_VALUES, item.get("status", "Open"))
    default_last_tested = date.today().isoformat() if item.get("lastTested") is None else ""
    last_tested_input = typer.prompt("Last tested date (YYYY-MM-DD, blank to keep empty)", default=default_last_tested)
    last_tested = None
    if last_tested_input.strip():
        last_tested = datetime.fromisoformat(last_tested_input.strip()).replace(tzinfo=timezone.utc)

    db.issues.update_one(
        {"issueId": item["issueId"]},
        {
            "$set": {
                "typeOfIssue": type_of_issue,
                "resolution": resolution,
                "status": status,
                "lastTested": last_tested,
            }
        },
    )
    console.print(f"Updated {item['issueId']}.")


@app.command()
def export(output_dir: Path = typer.Option(Path("reports"), help="Directory for Markdown and CSV exports.")):
    """Write Markdown report plus repo, issues, and task CSV files."""
    report_path = generate_report(_db(), output_dir)
    console.print(f"Report written to {report_path}")


@app.command()
def web(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(8080)):
    """Start the local NiceGUI CRUD web app."""
    from .web import run

    run(host=host, port=port)


if __name__ == "__main__":
    app()
