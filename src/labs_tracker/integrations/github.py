"""GitHub issue fetching and document mapping."""
from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatchcase
from typing import Any

from github import Github

from ..domain.models import KIND_ISSUE, STATE_CLOSED, STATE_OPEN
from ..domain.release_checks import PILOT_REPO, fingerprint


def get_github(token: str):
    return Github(token)


def load_lab_context(repo_id: str, token: str | None, ref: str, patterns: tuple[str, ...]) -> dict:
    if repo_id != PILOT_REPO:
        raise ValueError("Release checking is limited to the configured pilot")
    if not patterns or any(not pattern.startswith(("Instructions/", "Labfiles/")) or ".." in pattern for pattern in patterns):
        raise ValueError("Lab context paths must stay inside Instructions/ or Labfiles/")
    client = Github(token, timeout=20, retry=0)
    try:
        repo = client.get_repo(repo_id)
        commit = repo.get_commit(ref).sha
        tree = repo.get_git_tree(commit, recursive=True)
        if tree.truncated:
            raise ValueError("GitHub tree is truncated; lab coverage is incomplete")
        selected = [entry for entry in tree.tree if entry.type == "blob" and any(
            fnmatchcase(entry.path, pattern) or fnmatchcase(entry.path, pattern.replace("**/", ""))
            for pattern in patterns
        )]
        if not selected or not any(entry.path.startswith("Instructions/") for entry in selected):
            raise ValueError("No selected lab instructions were found")
        if len(selected) > 50:
            raise ValueError("More than 50 selected lab files; narrow RELEASE_CHECK_LAB_PATHS")
        files = []
        total = 0
        for entry in sorted(selected, key=lambda entry: entry.path):
            if entry.mode not in ("100644", "100755") or entry.size > 200_000:
                raise ValueError("Selected lab file is oversized or is not a regular file")
            blob = repo.get_contents(entry.path, ref=commit)
            content = blob.decoded_content
            total += len(content)
            if len(content) > 200_000 or total > 1_000_000 or b"\x00" in content:
                raise ValueError("Selected lab context exceeds text/size limits")
            text = content.decode("utf-8-sig")
            files.append({"path": entry.path, "blob": entry.sha, "content": text, "lines": len(text.splitlines()),
                          "url": f"https://github.com/{repo_id}/blob/{commit}/{entry.path}"})
        return {"commit": commit, "files": files, "hash": fingerprint([(item["path"], item["blob"]) for item in files])}
    finally:
        client.close()


def _github_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _state(value: str | None) -> str:
    return STATE_CLOSED if (value or "").lower() == "closed" else STATE_OPEN


def _repo_document(repo: Any) -> dict:
    return {
        "id": repo.full_name,
        "name": repo.name,
        "status": "Archived" if repo.archived else "Live",
        "lastUpdated": _github_dt(repo.pushed_at),
    }


def _issue_document(repo_id: str, issue: Any) -> dict:
    return {
        "issueId": f"{repo_id}#{issue.number}",
        "repoId": repo_id,
        "kind": KIND_ISSUE,
        "title": issue.title,
        "state": _state(issue.state),
    }


def _latest_closed_issues(repo: Any, limit: int) -> list[Any]:
    issues = []
    for issue in repo.get_issues(state="closed", sort="updated", direction="desc"):
        if issue.pull_request:
            continue
        issues.append(issue)
        if len(issues) >= limit:
            break
    return issues

