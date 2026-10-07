"""Bounded, read-only discovery of official Foundry release articles."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup
from defusedxml import ElementTree

from ..domain.release_checks import Article
from .release_sources import check_source_url


ARCHIVE_URL = "https://devblogs.microsoft.com/foundry/category/whats-new/"
FEED_URL = ARCHIVE_URL + "feed/"


class IncompleteCheck(ValueError):
    pass


def checked_url(url: str) -> str:
    parsed = urlsplit(check_source_url(url))
    if parsed.hostname != "devblogs.microsoft.com" or not parsed.path.startswith("/foundry/"):
        raise ValueError("The pilot only reads the official Foundry blog")
    if parsed.query:
        raise ValueError("Foundry article URLs must not include query parameters")
    return urlunsplit(("https", "devblogs.microsoft.com", parsed.path.rstrip("/") + "/", "", ""))


class SafeRedirectHandler(HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, request, response, code, message, headers, newurl):
        return super().redirect_request(request, response, code, message, headers, checked_url(newurl))


def fetch_document(url: str, *, limit: int = 2_000_000, opener=None) -> tuple[bytes, str]:
    url = checked_url(url)
    open_url = opener or build_opener(SafeRedirectHandler()).open
    request = Request(url, headers={"User-Agent": "labs-tracker/0.1 release-check", "Accept-Encoding": "identity"})
    with open_url(request, timeout=20) as response:
        final_url = checked_url(response.geturl())
        if response.getcode() != 200:
            raise IncompleteCheck("The source did not return HTTP 200")
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/rss+xml", "application/xml", "text/xml"}:
            raise IncompleteCheck("Unexpected source content type")
        body = response.read(limit + 1)
        if len(body) > limit:
            raise IncompleteCheck("Source exceeds the download size limit")
        if not body:
            raise IncompleteCheck("Source returned an empty document")
    return body, final_url


def article_url(url: str) -> str:
    url = checked_url(url)
    if not urlsplit(url).path.startswith(("/foundry/whats-new-", "/foundry/whats-new/")):
        raise ValueError("Select a Foundry What's New article as the saved source")
    return url


def parse_feed(body: bytes) -> list[str]:
    root = ElementTree.fromstring(body)
    channel = root.find("channel")
    if channel is None or "foundry" not in (channel.findtext("title") or "").lower():
        raise IncompleteCheck("RSS identity does not match Foundry")
    urls = [article_url(item.findtext("link") or "") for item in channel.findall("item")]
    if not urls:
        raise IncompleteCheck("No release articles found in RSS")
    return list(dict.fromkeys(urls))


def parse_archive(body: bytes, url: str) -> tuple[list[str], str | None]:
    soup = BeautifulSoup(body, "html.parser")
    urls = []
    for link in soup.select("h2 a[href], h3 a[href], .entry-title a[href]"):
        target = urljoin(url, str(link["href"]))
        if urlsplit(target).path.startswith("/foundry/whats-new-"):
            urls.append(article_url(target))
    next_link = soup.select_one('a[rel~="next"], a.next, a.nextpostslink')
    if next_link is None:
        next_link = next((link for link in soup.select("a[href]") if "Load more posts" in link.get_text()), None)
    next_url = checked_url(urljoin(url, str(next_link["href"]))) if next_link else None
    if next_url and not next_url.startswith(ARCHIVE_URL + "page/"):
        raise IncompleteCheck("Unexpected archive pagination URL")
    if not urls:
        raise IncompleteCheck("No release article links found in archive")
    return list(dict.fromkeys(urls)), next_url


def extract_article(body: bytes, url: str) -> Article:
    url = article_url(url)
    soup = BeautifulSoup(body, "html.parser")
    title_node = soup.select_one("h1")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    if not all(marker in title.lower() for marker in ("foundry", "what", "new")):
        raise IncompleteCheck("Article title does not match a Foundry release note")
    date_node = soup.select_one('meta[property="article:published_time"], meta[name="date"], time[datetime]')
    if date_node is None:
        raise IncompleteCheck("Article publication date is missing")
    date_text = str(date_node.get("content") or date_node.get("datetime") or "")
    try:
        published = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
    except ValueError as error:
        raise IncompleteCheck("Article publication date is invalid") from error
    published = published.replace(tzinfo=timezone.utc) if published.tzinfo is None else published.astimezone(timezone.utc)
    content_node = soup.select_one(".entry-content, .post-content, [itemprop=articleBody]")
    if content_node is None:
        raise IncompleteCheck("Article body could not be identified")
    for node in content_node.select("script, style, nav, footer, form, iframe, .comments, #comments"):
        node.decompose()
    for link in content_node.select("a[href]"):
        target = urljoin(url, str(link["href"]))
        link.replace_with(f"{link.get_text(' ', strip=True)} ({target})")
    for image in content_node.select("img"):
        image.replace_with(str(image.get("alt") or ""))
    blocks = []
    for node in content_node.select("h2, h3, h4, h5, p, li, pre, table"):
        if any(parent.name in {"p", "li", "pre", "table"} for parent in node.parents if parent is not content_node):
            continue
        if node.name == "pre":
            text = node.get_text().replace("\r\n", "\n").strip()
        else:
            text = " ".join(node.get_text(" ", strip=True).split())
        if text:
            blocks.append(f"{node.name}: {text}")
    if not blocks:
        raise IncompleteCheck("Article body is empty")
    return Article(url, url, title, published, "\n\n".join(blocks), sha256(body).hexdigest())


def discover_articles(seed_url: str, watched: list[str], *, fetcher=fetch_document, now=None) -> list[Article]:
    seed_url = article_url(seed_url)
    body, final_seed = fetcher(seed_url)
    seed = extract_article(body, final_seed)
    feed_body, _ = fetcher(FEED_URL, limit=5_000_000)
    feed_urls = parse_feed(feed_body)
    discovered = []
    archive_url = ARCHIVE_URL
    seen_pages = set()
    boundary_found = False
    for _ in range(10):
        if archive_url in seen_pages:
            raise IncompleteCheck("Archive pagination loop")
        seen_pages.add(archive_url)
        archive_body, final_archive = fetcher(archive_url)
        urls, next_url = parse_archive(archive_body, final_archive)
        discovered.extend(urls)
        if seed.url in urls or seed_url in urls:
            boundary_found = True
            break
        if not next_url:
            break
        archive_url = next_url
    if not boundary_found:
        raise IncompleteCheck("Archive scan could not reach the saved release article")
    boundary = next(index for index, url in enumerate(discovered) if url in {seed.url, seed_url})
    candidates = list(dict.fromkeys([seed_url, *discovered[:boundary], *watched]))
    if seed_url in feed_urls:
        candidates = list(dict.fromkeys([*candidates, *feed_urls[:feed_urls.index(seed_url)]]))
    if len(candidates) > 20:
        raise IncompleteCheck("More than 20 watched articles; narrow the saved source scope")
    articles = {seed.article_id: seed}
    for url in candidates:
        if url in {seed_url, seed.url}:
            continue
        article_body, final_url = fetcher(article_url(url))
        article = extract_article(article_body, final_url)
        if article.published_at >= seed.published_at or url in watched:
            articles[article.article_id] = article
    checked_at = now or datetime.now(timezone.utc)
    latest = max(article.published_at for article in articles.values())
    if latest > checked_at + timedelta(days=1) or latest < checked_at - timedelta(days=400):
        raise IncompleteCheck("Latest release publication date is not current")
    return list(articles.values())