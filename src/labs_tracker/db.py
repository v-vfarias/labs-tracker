"""MongoDB connection and index helpers."""
from __future__ import annotations

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

from .config import Settings, load_settings


def get_client(settings: Settings | None = None) -> MongoClient:
    settings = settings or load_settings()
    return MongoClient(settings.mongo_uri)


def get_database(settings: Settings | None = None) -> Database:
    settings = settings or load_settings()
    return get_client(settings)[settings.mongo_db]


def ensure_indexes(db: Database) -> None:
    db.repos.create_index([("id", ASCENDING)], unique=True)
    db.repos.create_index([("status", ASCENDING)])
    db.repos.create_index([("lastUpdated", ASCENDING)])

    db.items.create_index([("id", ASCENDING)], unique=True)
    db.items.create_index([("repoId", ASCENDING), ("kind", ASCENDING)])
    db.items.create_index([("state", ASCENDING), ("updatedAt", ASCENDING)])
    db.items.create_index([("status", ASCENDING), ("testResult", ASCENDING)])

    db.syncRuns.create_index([("startedAt", ASCENDING)])
