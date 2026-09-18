"""Tracking operations, input validation and classification query policies."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..domain.models import ISSUE_TYPE_ALIASES, ISSUE_TYPE_VALUES, RESOLUTION_ALIASES, RESOLUTION_VALUES, normalize_issue_type, normalize_resolution
from ..domain.products import repo_products
from ..domain.workflow import progress_update
from ..integrations.release_sources import PRODUCT_SOURCES, check_source_url, save_source_urls, source_for_product, source_validation


class TrackingValidationError(ValueError):
    """An edit cannot be saved with the supplied values."""


class DuplicateRecordError(TrackingValidationError):
    """A new record uses an existing identifier."""


@dataclass(frozen=True, kw_only=True)
class RepoEdit:
    repo_id: str
    name: str
    existing_id: str | None = None
    involved_devs: str | list[str] | tuple[str, ...] | None = None
    products: str | list[str] | tuple[str, ...] | None = None
    last_tested: str = ""
    source_urls: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class IssueEdit:
    issue_id: str
    repo_id: str
    title: str
    existing_id: str | None = None
    kind: str = "Issue"
    state: str = "Open"
    type_of_issue: str = "Unknown"
    resolution: str = "Unknown"
    status: str = "Open"
    handling_stage: str = "Raised"
    reproduction_notes: str = ""
    external_report_url: str = ""
    external_response: str = ""
    last_tested: str = ""
    closing_pr_url: str = ""
    progress_note: str = ""
    waiting_reason: str = "None"
    waiting_on: str = ""


def _edit_datetime(value: str) -> datetime | None:
    try:
        return _parse_dt(value)
    except ValueError as error:
        raise TrackingValidationError("Invalid lastTested format. Use ISO datetime.") from error


def save_repo(db, edit: RepoEdit) -> None:
    parsed_last_tested = _edit_datetime(edit.last_tested)
    payload = {
        "involvedDevs": _parse_csv(edit.involved_devs),
        "products": _parse_csv(edit.products),
        "lastTested": parsed_last_tested,
    }
    try:
        for url in edit.source_urls.values():
            check_source_url(url)
    except ValueError as error:
        raise TrackingValidationError(str(error)) from error
    if edit.existing_id:
        db.repos.update_one({"id": edit.existing_id}, {"$set": payload})
    else:
        if not edit.repo_id or not edit.name:
            raise TrackingValidationError("id and name are required")
        if db.repos.find_one({"id": edit.repo_id}):
            raise DuplicateRecordError("repo already exists")
        db.repos.update_one(
            {"id": edit.repo_id},
            {"$setOnInsert": {
                "_id": edit.repo_id,
                "id": edit.repo_id,
                "name": edit.name,
                "status": "Live",
                "lastUpdated": None,
                **payload,
            }},
            upsert=True,
        )
    save_source_urls(db, edit.source_urls)


def save_issue(db, edit: IssueEdit) -> None:
    parsed_last_tested = _edit_datetime(edit.last_tested)
    manual = {
        "typeOfIssue": normalize_issue_type(edit.type_of_issue),
        "resolution": normalize_resolution(edit.resolution),
        "status": edit.status,
        "reproductionNotes": edit.reproduction_notes.strip(),
        "externalReportUrl": edit.external_report_url.strip(),
        "externalResponse": edit.external_response.strip(),
        "lastTested": parsed_last_tested,
        "closingPrUrl": edit.closing_pr_url.strip(),
    }
    existing = db.issues.find_one({"issueId": edit.existing_id}) if edit.existing_id else {}
    try:
        update = progress_update(
            existing or {}, edit.handling_stage, edit.progress_note, edit.waiting_reason, edit.waiting_on,
            evidence={key: manual[key] for key in ("reproductionNotes", "externalReportUrl", "externalResponse")},
        )
    except ValueError as error:
        raise TrackingValidationError(str(error)) from error
    update["$set"].update(manual)
    if edit.existing_id:
        update_issue(db, edit.existing_id, update)
    else:
        if not edit.issue_id or not edit.repo_id or not edit.title:
            raise TrackingValidationError("issueId, repoId, and title are required")
        if db.issues.find_one({"issueId": edit.issue_id}):
            raise DuplicateRecordError("issue already exists")
        update["$set"].update({
            "issueId": edit.issue_id,
            "repoId": edit.repo_id,
            "kind": edit.kind,
            "title": edit.title,
            "state": edit.state,
        })
        update["$setOnInsert"] = {"_id": edit.issue_id}
        db.issues.update_one({"issueId": edit.issue_id}, update, upsert=True)


def update_issue(db, issue_id: str, update: dict) -> None:
    db.issues.update_one({"issueId": issue_id}, update)


def delete_repo(db, repo_id: str) -> None:
    db.repos.delete_one({"id": repo_id})
    db.issues.delete_many({"repoId": repo_id})


def delete_issue(db, issue_id: str) -> None:
    db.issues.delete_one({"issueId": issue_id})


@dataclass(frozen=True, kw_only=True)
class IssueFilters:
    repo_id: str = "All"
    state: str = "All"
    type_of_issue: str = "All"
    status: str = "All"
    missing_classification: bool = False


def get_repo(db, repo_id: str) -> dict | None:
    return db.repos.find_one({"id": repo_id})


def get_issue(db, issue_id: str) -> dict | None:
    return db.issues.find_one({"issueId": issue_id})


def repo_options(db) -> list[dict]:
    return list(db.repos.find({}, {"id": 1, "name": 1, "_id": 0}))


def configured_sources(db) -> dict[str, dict]:
    return {product: source_for_product(product, db) for product in PRODUCT_SOURCES}


def product_source_statuses(db, products: list[str]) -> list[dict]:
    statuses = []
    for product in dict.fromkeys(products):
        source = source_for_product(product, db)
        statuses.append({
            "product": product,
            "source": source,
            "validation": source_validation(db, source) if source else {},
        })
    return statuses


def repo_overview(db) -> list[dict]:
    rows = []
    for doc in db.repos.find({}).sort("id", 1):
        repo_id = doc.get("id")
        products = repo_products(repo_id, doc.get("products") or [])
        rows.append({
            **doc,
            "products": products,
            "openIssues": db.issues.count_documents({"repoId": repo_id, "state": "Open"}),
            "sourceStatuses": product_source_statuses(db, products),
        })
    return rows


def dashboard_counts(db) -> dict[str, int]:
    repos = list(db.repos.find({}, {"id": 1, "products": 1, "_id": 0}))
    products_needing_validation = set()
    for repo in repos:
        products = repo_products(repo.get("id"), repo.get("products") or [])
        for entry in product_source_statuses(db, products):
            if not entry["validation"] or entry["validation"].get("status") != "Validated":
                products_needing_validation.add(entry["product"])
    return {
        "repos": len(repos),
        "openIssues": db.issues.count_documents({"state": "Open"}),
        "missingClassification": db.issues.count_documents(_needs_classification_query()),
        "sourcesNeedingValidation": len(products_needing_validation),
    }


def list_issues(db, filters: IssueFilters) -> list[dict]:
    query = {}
    if filters.repo_id and filters.repo_id != "All":
        query["repoId"] = filters.repo_id
    if filters.state and filters.state != "All":
        query["state"] = filters.state
    if filters.type_of_issue and filters.type_of_issue != "All":
        query["typeOfIssue"] = _issue_type_query(filters.type_of_issue)
    elif filters.missing_classification:
        query.update(_needs_classification_query())
    if filters.status and filters.status != "All":
        query["status"] = filters.status
    return list(db.issues.find(query).sort("issueId", 1))


def classification_candidates(db, limit: int) -> list[dict]:
    query = {
        "state": "Open",
        "$or": [
            {"typeOfIssue": "Unknown"},
            {"resolution": "Unknown"},
            {"lastTested": None},
        ],
    }
    return list(db.issues.find(query).sort([("issueId", 1)]).limit(limit))


def _parse_dt(value: str):
    value = value.strip()
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_csv(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return [item.strip() for item in value.split(",") if item.strip()]


def _issue_type_query(value: str) -> dict:
    if value == "Unknown":
        known_values = [issue_type for issue_type in ISSUE_TYPE_VALUES if issue_type != "Unknown"]
        known_values.extend(ISSUE_TYPE_ALIASES)
        return {"$nin": known_values}
    return {"$in": [value, *[legacy for legacy, compact in ISSUE_TYPE_ALIASES.items() if compact == value]]}


def _resolution_query(value: str) -> dict:
    if value == "Unknown":
        known_values = [resolution for resolution in RESOLUTION_VALUES if resolution != "Unknown"]
        known_values.extend(RESOLUTION_ALIASES)
        return {"$nin": known_values}
    return {"$in": [value, *[legacy for legacy, compact in RESOLUTION_ALIASES.items() if compact == value]]}


def _needs_classification_query() -> dict:
    return {"$or": [{"typeOfIssue": _issue_type_query("Unknown")}, {"resolution": _resolution_query("Unknown")}]} 

