"""Environment-backed configuration."""
from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


DEFAULT_TRACKED_REPOS = [
    "MicrosoftLearning/mslearn-ai-agents",
    "MicrosoftLearning/mslearn-ai-fundamentals",
    "MicrosoftLearning/mslearn-ai-language",
    "MicrosoftLearning/mslearn-ai-studio",
    "MicrosoftLearning/mslearn-ai-vision",
    "MicrosoftLearning/mslearn-devops",
    "MicrosoftLearning/mslearn-genaiops",
    "MicrosoftLearning/mslearn-mlops",
    "MicrosoftLearning/mslearn-azure-ai",
    "MicrosoftLearning/mslearn-ai-information-extraction",
    "MicrosoftLearning/dp-300-database-administrator",
    "MicrosoftLearning/PL-300-Microsoft-Power-BI-Data-Analyst",
    "MicrosoftLearning/mslearn-sql-developer",
]


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
        os.getenv("TRACKED_REPOS", ",".join(DEFAULT_TRACKED_REPOS))
    )
    return Settings(
        mongo_uri=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        mongo_db=os.getenv("MONGO_DB", "labs_tracker"),
        github_token=os.getenv("GITHUB_TOKEN") or None,
        tracked_repos=repos,
    )
