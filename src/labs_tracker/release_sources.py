"""Authoritative product release sources and document validation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PRODUCT_SOURCES = {
    "Foundry": {
        "name": "Microsoft Foundry updates",
        "url": "https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-july-august-2026/",
        "expected": ("microsoft foundry", "what", "new"),
    },
    "Foundry SDK": {
        "name": "Azure SDK for Python releases",
        "url": "https://github.com/Azure/azure-sdk-for-python/releases",
        "expected": ("releases", "azure-sdk-for-python"),
    },
    "Foundry Toolkit for VS Code": {
        "name": "Foundry Toolkit for VS Code changelog",
        "url": "https://microsoft.github.io/foundry-dev-tools/",
        "expected": ("foundry toolkit", "release date"),
    },
    "Azure Machine Learning Studio": {
        "name": "Azure Machine Learning release notes",
        "url": "https://learn.microsoft.com/en-us/azure/machine-learning/azure-machine-learning-release-notes",
        "expected": ("release", "azure"),
    },
    "Microsoft Fabric": {
        "name": "Microsoft Fabric what's new",
        "url": "https://learn.microsoft.com/en-us/fabric/fundamentals/whats-new",
        "expected": ("what's new", "fabric"),
    },
    "Power BI": {
        "name": "Power BI monthly update",
        "url": "https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-latest-update",
        "expected": ("what's new", "power bi"),
    },
    "Azure SQL": {
        "name": "Azure SQL Database what's new",
        "url": "https://learn.microsoft.com/en-us/azure/azure-sql/database/doc-changes-updates-release-notes-whats-new",
        "expected": ("what's new", "azure sql"),
    },
    "GitHub Copilot": {
        "name": "GitHub Copilot changelog",
        "url": "https://github.blog/changelog/label/copilot/",
        "expected": ("changelog", "copilot"),
    },
    "GitHub Actions": {
        "name": "GitHub Actions changelog",
        "url": "https://github.blog/changelog/label/actions/",
        "expected": ("changelog", "actions"),
    },
    "GitHub": {
        "name": "GitHub changelog",
        "url": "https://github.blog/changelog/",
        "expected": ("changelog",),
    },
    "Azure DevOps": {
        "name": "Azure DevOps release notes",
        "url": "https://aka.ms/azuredevops/releasenotes",
        "expected": ("azure devops", "release"),
    },
}

TRUSTED_HOSTS = {
    "aka.ms",
    "azure.github.io",
    "devblogs.microsoft.com",
    "github.blog",
    "github.com",
    "learn.microsoft.com",
    "microsoft.github.io",
}

_DATE_PATTERNS = (
    re.compile(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b"),
    re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(0?[1-9]|[12]\d|3[01])\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(20\d{2})\b",
        re.IGNORECASE,
    ),
)
_MONTHS = {
    month: index
    for index, month in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"),
        start=1,
    )
}


class _DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.structured_dates: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "time" and attributes.get("datetime"):
            self.structured_dates.append(attributes["datetime"])
        if tag.lower() == "meta":
            date_kind = " ".join(
                attributes.get(name, "") for name in ("name", "property", "itemprop")
            ).lower()
            if ("date" in date_kind or "modified" in date_kind or "published" in date_kind) and attributes.get("content"):
                self.structured_dates.append(attributes["content"])

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data):
        value = data.strip()
        if not value:
            return
        self.text_parts.append(value)
        if self._in_title:
            self.title_parts.append(value)


def _latest_public_date(text: str) -> datetime | None:
    dates: list[datetime] = []
    for match in _DATE_PATTERNS[0].finditer(text):
        try:
            dates.append(datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone.utc))
        except ValueError:
            continue
    for match in _DATE_PATTERNS[1].finditer(text):
        dates.append(datetime(int(match.group(2)), _MONTHS[match.group(1).lower()], 1, tzinfo=timezone.utc))
    for match in _DATE_PATTERNS[2].finditer(text):
        try:
            dates.append(datetime(int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1)), tzinfo=timezone.utc))
        except ValueError:
            continue
    return max(dates) if dates else None


def source_for_product(product: str, db=None) -> dict | None:
    source = PRODUCT_SOURCES.get(product)
    if not source:
        return None
    configured = db.productSources.find_one({"_id": product}) if db is not None else None
    return {"product": product, **source, "url": configured["url"] if configured else source["url"]}


def check_source_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in TRUSTED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Source URL must use HTTPS on a trusted documentation host without credentials or a custom port")
    return url


def save_source_urls(db, urls: dict[str, str]) -> None:
    checked = {}
    for product, url in urls.items():
        if product not in PRODUCT_SOURCES:
            raise ValueError(f"No source is configured for {product}")
        checked[product] = check_source_url(url)
    for product, url in checked.items():
        if url != source_for_product(product, db)["url"]:
            db.productSources.update_one({"_id": product}, {"$set": {"url": url}}, upsert=True)


def source_validation(db, source: dict) -> dict:
    validation = db.sourceValidations.find_one({"product": source["product"]}) or {}
    return validation if validation.get("url") == source["url"] else {}


def validate_source(product: str, *, db=None, opener=urlopen, now: datetime | None = None) -> dict:
    source = source_for_product(product, db)
    checked_at = now or datetime.now(timezone.utc)
    if source is None:
        return {"product": product, "status": "Invalid", "reason": "No source is configured", "checkedAt": checked_at}

    try:
        check_source_url(source["url"])
        request = Request(source["url"], headers={"User-Agent": "labs-tracker/0.1 release-source-validator"})
        with opener(request, timeout=20) as response:
            body = response.read(2_000_000)
            final_url = response.geturl()
            http_status = response.getcode()
    except Exception as error:
        return {
            **source,
            "status": "Unavailable",
            "reason": str(error),
            "checkedAt": checked_at,
        }

    parser = _DocumentParser()
    decoded = body.decode("utf-8", errors="replace")
    parser.feed(decoded)
    title = " ".join(parser.title_parts).strip()
    document_text = " ".join(parser.text_parts)
    searchable = f"{title} {document_text}".lower()
    final_host = (urlparse(final_url).hostname or "").lower()
    structured_date = _latest_public_date(" ".join(parser.structured_dates))
    text_dates = [
        date
        for date in (_latest_public_date(match.group(0)) for pattern in _DATE_PATTERNS for match in pattern.finditer(document_text))
        if date is not None and date <= checked_at + timedelta(days=31)
    ]
    latest_date = structured_date or (max(text_dates) if text_dates else None)

    failures = []
    if http_status != 200:
        failures.append(f"HTTP {http_status}")
    if final_host not in TRUSTED_HOSTS:
        failures.append(f"redirected to untrusted host {final_host or 'unknown'}")
    if not all(marker in searchable for marker in source["expected"]):
        failures.append("page identity did not match the configured product")
    if latest_date is None:
        failures.append("no public release date was found")
    elif latest_date > checked_at + timedelta(days=31):
        failures.append("newest release date is unexpectedly in the future")
    elif latest_date < checked_at - timedelta(days=400):
        failures.append("newest release evidence is more than 400 days old")

    return {
        **source,
        "status": "Invalid" if failures else "Validated",
        "reason": "; ".join(failures) if failures else "First-party source is reachable, recognizable, and current",
        "title": title,
        "finalUrl": final_url,
        "httpStatus": http_status,
        "latestPublicDate": latest_date,
        "contentHash": sha256(body).hexdigest(),
        "checkedAt": checked_at,
    }


def validate_all_sources(db, *, opener=urlopen, now: datetime | None = None) -> list[dict]:
    results = []
    for product in PRODUCT_SOURCES:
        result = validate_source(product, db=db, opener=opener, now=now)
        db.sourceValidations.update_one(
            {"product": product},
            {"$set": result, "$setOnInsert": {"_id": product}},
            upsert=True,
        )
        results.append(result)
    return results
