"""Persistent, on-demand release checking for the Foundry pilot."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..config import Settings, load_settings
from ..domain.release_checks import NORMALIZER_VERSION, PILOT_REPO, PRODUCT, compare_articles, fingerprint
from ..integrations.github import load_lab_context
from ..integrations.release_agent import MockReleaseAnalyzer
from ..integrations.release_notes import IncompleteCheck, article_url, discover_articles
from ..integrations.release_sources import source_for_product


class CheckBusyError(ValueError):
    pass


def get_release_check(db, repo_id: str) -> dict:
    return db.repoReleaseChecks.find_one({"_id": f"{repo_id}:{PRODUCT}"}) or {}


def _scope(source: dict, settings: Settings) -> str:
    return fingerprint([source["url"], asdict(settings.release_check), NORMALIZER_VERSION])


def _acquire(db, repo_id: str, run_id: str, now: datetime) -> dict:
    key = f"{repo_id}:{PRODUCT}"
    try:
        db.repoReleaseChecks.update_one({"_id": key}, {"$setOnInsert": {
            "repoId": repo_id, "product": PRODUCT, "version": 0, "leaseUntil": now,
            "findings": [], "reviewStatus": "Not assessed",
        }}, upsert=True)
    except DuplicateKeyError:
        pass
    state = db.repoReleaseChecks.find_one_and_update(
        {"_id": key, "leaseUntil": {"$lte": now}},
        {"$set": {"leaseToken": run_id, "leaseUntil": now + timedelta(minutes=10),
                  "lastAttempt": {"runId": run_id, "status": "Running", "checkedAt": now}}, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if state is None:
        raise CheckBusyError("A release check is already running for this repo")
    return state


def _validation(db, source: dict, articles: list, now: datetime) -> dict:
    seed = next((article for article in articles if article.url == article_url(source["url"])), None)
    validation = {**source, "checkedAt": now, "status": "Invalid", "reason": "Saved source could not be matched"}
    if seed is not None:
        current = now - timedelta(days=400) <= seed.published_at <= now + timedelta(days=1)
        validation.update(status="Validated" if current else "Invalid", title=seed.title, finalUrl=seed.url,
                          httpStatus=200, latestPublicDate=seed.published_at, contentHash=seed.raw_hash,
                          reason="Official Foundry article fetched and extracted" if current else "Saved article is more than 400 days old")
    if source_for_product(PRODUCT, db)["url"] == source["url"]:
        try:
            db.sourceValidations.update_one({"product": PRODUCT}, {"$setOnInsert": {"_id": PRODUCT, "product": PRODUCT}}, upsert=True)
        except DuplicateKeyError:
            pass
        db.sourceValidations.update_one(
            {"product": PRODUCT, "$or": [{"checkedAt": {"$exists": False}}, {"checkedAt": {"$lte": now}}]},
            {"$set": validation},
        )
    return validation


async def check_release_notes(db, repo_id: str, settings: Settings | None = None, *, analyzer=None,
                              discover=discover_articles, context_loader=load_lab_context) -> dict:
    settings = settings or load_settings()
    config = settings.release_check
    if not config.enabled or repo_id != PILOT_REPO:
        raise ValueError("Release checking is enabled only for the mslearn-ai-agents pilot; set RELEASE_CHECK_ENABLED=true")
    if config.backend != "mock":
        raise ValueError("Only the mock backend is implemented; Copilot integration is the next milestone")
    if not 1 <= config.timeout_seconds <= 300:
        raise ValueError("Release timeout must be between 1 and 300 seconds")
    if not await asyncio.to_thread(db.repos.find_one, {"id": repo_id}):
        raise ValueError("The pilot repository must be added to the tracker first")
    source = await asyncio.to_thread(source_for_product, PRODUCT, db)
    article_url(source["url"])
    analyzer = analyzer or MockReleaseAnalyzer()
    started = datetime.now(timezone.utc)
    run_id = uuid4().hex
    state = await asyncio.to_thread(_acquire, db, repo_id, run_id, started)
    scope = _scope(source, settings)
    lease_query = {"_id": state["_id"], "leaseToken": run_id, "version": state["version"]}
    run = {"_id": run_id, "repoId": repo_id, "product": PRODUCT, "recordType": "check", "checkedAt": started,
           "scope": scope, "sourceUrl": source["url"], "backend": analyzer.backend}

    async def execute():
        previous = state.get("articles", []) if state.get("scope") == scope else []
        articles = await asyncio.to_thread(discover, source["url"], [item["url"] for item in previous])
        changes = compare_articles({item["article_id"]: item["contentHash"] for item in previous}, articles)
        snapshots = [article.document() for article in articles]
        run["snapshotIds"] = [article.snapshot_id for article in articles]
        run["previousSnapshotIds"] = [item["snapshotId"] for item in previous]
        for snapshot in snapshots:
            await asyncio.to_thread(db.releaseSnapshots.update_one, {"_id": snapshot["_id"]}, {"$setOnInsert": snapshot}, upsert=True)
        validation = await asyncio.to_thread(_validation, db, source, articles, started)
        context = await asyncio.to_thread(context_loader, repo_id, settings.github_token, config.lab_ref, config.lab_paths)
        assessment_key = fingerprint([scope, sorted(changes["hashes"].items()), context["hash"], analyzer.backend, analyzer.version])
        assessment = state.get("assessment") if state.get("assessmentKey") == assessment_key else None
        if assessment is None:
            assessment = await analyzer.analyze(snapshots, context, changes)
        if assessment.get("backend") != "mock" or assessment.get("impact") != "Not assessed" or assessment.get("findings"):
            raise ValueError("A placeholder cannot publish real impact findings")
        run.update(status=changes["status"], new=changes["new"], edited=changes["edited"], assessment=assessment,
                   labCommit=context["commit"], labFiles=[{key: value for key, value in item.items() if key != "content"} for item in context["files"]],
                   contextHash=context["hash"], sourceValidation=validation, completedAt=datetime.now(timezone.utc))

        def publish():
            if _scope(source_for_product(PRODUCT, db), settings) != scope or not db.repos.find_one({"id": repo_id}):
                raise ValueError("Repo or source configuration changed during the check; run it again")
            db.releaseCheckRuns.insert_one(run)
            update = {
                "scope": scope, "articles": [{"article_id": article.article_id, "url": article.url, "title": article.title,
                                               "contentHash": article.content_hash, "snapshotId": article.snapshot_id} for article in articles],
                "assessmentKey": assessment_key, "assessment": assessment, "lastSuccessfulCheck": run,
                "lastAttempt": {"runId": run_id, "status": run["status"], "checkedAt": started},
                "reviewStatus": "Needs revision" if state.get("findings") else state.get("reviewStatus", "Not assessed"),
            }
            result = db.repoReleaseChecks.update_one({**lease_query, "leaseUntil": {"$gt": datetime.now(timezone.utc)}},
                                                     {"$set": update, "$inc": {"version": 1}})
            if result.matched_count != 1:
                raise CheckBusyError("A newer check or review replaced this run")
        await asyncio.to_thread(publish)
        return run

    try:
        return await asyncio.wait_for(execute(), timeout=config.timeout_seconds)
    except (Exception, asyncio.CancelledError) as error:
        status = "Cancelled" if isinstance(error, asyncio.CancelledError) else "Incomplete" if isinstance(error, IncompleteCheck) else "Failed"
        message = str(error) if isinstance(error, ValueError) else f"{type(error).__name__}: release check did not complete"
        failure = {**run, "status": status, "error": message, "completedAt": datetime.now(timezone.utc)}
        await asyncio.to_thread(db.releaseCheckRuns.update_one, {"_id": run_id}, {"$setOnInsert": failure}, upsert=True)
        await asyncio.to_thread(db.repoReleaseChecks.update_one, lease_query, {"$set": {
            "lastAttempt": {"runId": run_id, "status": status, "error": message, "checkedAt": started},
        }})
        if isinstance(error, asyncio.CancelledError):
            raise
        return failure
    finally:
        await asyncio.to_thread(db.repoReleaseChecks.update_one, {"_id": state["_id"], "leaseToken": run_id},
                                {"$set": {"leaseUntil": datetime.now(timezone.utc)}, "$unset": {"leaseToken": ""}})


def mark_reviewed(db, repo_id: str, finding_ids: list[str], note: str, version: int) -> dict:
    note = note.strip()
    if repo_id != PILOT_REPO or not note or len(note) > 4000 or not finding_ids:
        raise ValueError("Select pilot findings and provide a review note (1-4000 characters)")
    state = get_release_check(db, repo_id)
    findings = state.get("findings", [])
    if not set(finding_ids).issubset({finding["id"] for finding in findings}):
        raise ValueError("Findings changed; refresh before reviewing")
    remaining = [finding for finding in findings if finding["id"] not in finding_ids]
    now = datetime.now(timezone.utc)
    review = {"_id": uuid4().hex, "recordType": "review", "repoId": repo_id, "product": PRODUCT,
              "findingIds": finding_ids, "note": note, "checkedAt": now}
    db.releaseCheckRuns.insert_one(review)
    result = db.repoReleaseChecks.update_one(
        {"_id": state.get("_id"), "version": version, "leaseToken": {"$exists": False}},
        {"$set": {"findings": remaining, "reviewStatus": "Needs revision" if remaining else "Reviewed", "lastReview": review}, "$inc": {"version": 1}},
    )
    if result.matched_count != 1:
        raise CheckBusyError("A check or review changed this repo; refresh before reviewing")
    return get_release_check(db, repo_id)