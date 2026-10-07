"""Release check contracts and deterministic comparison rules."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json


PILOT_REPO = "MicrosoftLearning/mslearn-ai-agents"
PRODUCT = "Foundry"
NORMALIZER_VERSION = "foundry-article-v1"


def fingerprint(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


@dataclass(frozen=True)
class Article:
    article_id: str
    url: str
    title: str
    published_at: datetime
    content: str
    raw_hash: str

    @property
    def content_hash(self) -> str:
        return fingerprint([NORMALIZER_VERSION, self.title, self.content])

    @property
    def snapshot_id(self) -> str:
        return fingerprint([self.article_id, self.content_hash])

    def document(self) -> dict:
        return {
            **asdict(self), "_id": self.snapshot_id,
            "contentHash": self.content_hash, "normalizerVersion": NORMALIZER_VERSION,
        }


def compare_articles(previous: dict[str, str] | None, articles: list[Article]) -> dict:
    current = {article.article_id: article.content_hash for article in articles}
    if len(current) != len(articles) or not current:
        raise ValueError("Release coverage must contain unique, nonempty articles")
    previous = previous or {}
    if set(previous) - set(current):
        raise ValueError("Previously watched articles are missing from this check")
    new = sorted(set(current) - set(previous))
    edited = sorted(identity for identity in current if identity in previous and current[identity] != previous[identity])
    return {
        "status": "First check" if not previous else "Updated" if new or edited else "No changes",
        "new": new, "edited": edited, "hashes": current,
    }