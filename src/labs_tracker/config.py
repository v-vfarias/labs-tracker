"""Environment-backed configuration."""
from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    mongo_uri: str
    mongo_db: str
    github_token: str | None
    tracked_repos: list[str]


def _parse_tracked_repos(value: str) -> list[str]:
    return [repo.strip() for repo in value.split(",") if repo.strip()]


def load_settings() -> Settings:
    load_dotenv()
    repos = _parse_tracked_repos(
        os.getenv("TRACKED_REPOS", "MicrosoftLearning/mslearn-ai-language")
    )
    return Settings(
        mongo_uri=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        mongo_db=os.getenv("MONGO_DB", "labs_tracker"),
        github_token=os.getenv("GITHUB_TOKEN") or None,
        tracked_repos=repos,
    )
