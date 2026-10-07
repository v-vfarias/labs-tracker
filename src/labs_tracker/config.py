"""Environment-backed configuration."""
from __future__ import annotations

from dataclasses import dataclass
import json
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
    "MicrosoftLearning/mslearn-fabric"
]


@dataclass(frozen=True)
class ReleaseCheckSettings:
    enabled: bool = False
    backend: str = "mock"
    lab_ref: str = "main"
    lab_paths: tuple[str, ...] = ("Instructions/Exercises/*.md", "Labfiles/0*/**/requirements*.txt",
                                  "Labfiles/0*/**/pyproject.toml", "Labfiles/0*/**/*.py")
    timeout_seconds: int = 300


@dataclass(frozen=True)
class Settings:
    mongo_uri: str
    mongo_db: str
    github_token: str | None
    tracked_repos: list[str]
    release_check: ReleaseCheckSettings = ReleaseCheckSettings()


def _parse_tracked_repos(value: str) -> list[str]:
    return [repo.strip() for repo in value.split(",") if repo.strip()]


def load_settings() -> Settings:
    load_dotenv()
    repos = _parse_tracked_repos(
        os.getenv("TRACKED_REPOS", ",".join(DEFAULT_TRACKED_REPOS))
    )
    paths = json.loads(os.getenv("RELEASE_CHECK_LAB_PATHS", json.dumps(ReleaseCheckSettings().lab_paths)))
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) and path.startswith(("Instructions/", "Labfiles/")) and ".." not in path for path in paths):
        raise ValueError("RELEASE_CHECK_LAB_PATHS must be a JSON array of Instructions/ or Labfiles/ patterns")
    return Settings(
        mongo_uri=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        mongo_db=os.getenv("MONGO_DB", "labs_tracker"),
        github_token=os.getenv("GITHUB_TOKEN") or None,
        tracked_repos=repos,
        release_check=ReleaseCheckSettings(
            enabled=os.getenv("RELEASE_CHECK_ENABLED", "false").lower() == "true",
            backend=os.getenv("RELEASE_CHECK_BACKEND", "mock"),
            lab_ref=os.getenv("RELEASE_CHECK_LAB_REF", "main"),
            lab_paths=tuple(paths),
        ),
    )
