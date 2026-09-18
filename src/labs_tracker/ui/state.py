"""Selection and navigation mode for one NiceGUI client."""
from dataclasses import dataclass
from typing import Literal


@dataclass
class PageState:
    repo_id: str | None = None
    issue_id: str | None = None
    missing_classification: bool = False
    active_view: Literal["dashboard", "issues", "report"] = "dashboard"
