"""
Export journal articles from BrowZine API to per-CSV SQLite databases.

Each CSV in data/meta becomes one SQLite database under data/index.
Network fetching uses a thread pool while database writes use aiosqlite.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

import aiosqlite
import requests
from tqdm import tqdm

DEFAULT_LIBRARY_ID = "3050"
BASE_URL = "https://api.thirdiron.com/v2"
TOKEN_EXPIRY_BUFFER = 300
logger = logging.getLogger(__name__)


def to_int(value: Any) -> int | None:
    """
    Convert a value to int when possible.

    Args:
        value: Input value.

    Returns:
        Integer value or None when conversion fails.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_bool_int(value: Any) -> int | None:
    """
    Convert a value to 0 or 1 when possible.

    Args:
        value: Input value.

    Returns:
        0 or 1 when conversion succeeds, otherwise None.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return 1 if value else 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return 1
        if lowered in {"false", "0", "no"}:
            return 0
    return None


def to_text(value: Any) -> str | None:
    """
    Convert a value to a string or JSON string when needed.

    Args:
        value: Input value.

    Returns:
        String value or None when input is None.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


def to_float(value: Any) -> float | None:
    """
    Convert a value to float when possible.

    Args:
        value: Input value.

    Returns:
        Float value or None when conversion fails.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def chunked(items: list[Any], size: int) -> Iterable[list[Any]]:
    """
    Yield items in fixed-size chunks.

    Args:
        items: List of items to split.
        size: Chunk size.

    Returns:
        Iterable of item lists.
    """
    if size <= 0:
        size = 1
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


class BrowZineAPIClient:
    """
    Client for BrowZine API access with token caching.

    Args:
        library_id: Default library ID for requests.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(self, library_id: str = DEFAULT_LIBRARY_ID, timeout: int = 20) -> None:
        """
        Initialize the API client.

        Args:
            library_id: Default library ID for requests.
            timeout: HTTP request timeout in seconds.
        """
        self.default_library_id = library_id
        self.timeout = timeout
        self._tokens: dict[str, str] = {}
        self._token_expiry: dict[str, float] = {}
        self._lock = Lock()

    def _parse_expires_at(self, value: Any) -> float | None:
        """
        Parse expires_at string into a Unix timestamp.

        Args:
            value: expires_at value from the API response.

        Returns:
            Unix timestamp in seconds or None when parsing fails.
        """
        if not value or not isinstance(value, str):
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return None

    def _token_is_valid(self, library_id: str) -> bool:
        """
        Determine whether a cached token is still valid.

        Args:
            library_id: Library ID for the token.

        Returns:
            True if token is valid or expiry is unknown, otherwise False.
        """
        expires_at = self._token_expiry.get(library_id)
        if expires_at is None:
            return True
        return expires_at - time.time() > TOKEN_EXPIRY_BUFFER

    def _get_token(self, library_id: str, refresh: bool = False) -> str | None:
        """
        Request or reuse a token for the given library.

        Args:
            library_id: Library ID to authenticate.
            refresh: Whether to force refresh the token.

        Returns:
            Token string or None when authentication fails.
        """
        with self._lock:
            if (
                not refresh
                and library_id in self._tokens
                and self._token_is_valid(library_id)
            ):
                return self._tokens[library_id]

        if refresh:
            logger.debug("Refreshing token for library %s", library_id)
        else:
            logger.debug("Requesting token for library %s", library_id)

        url = f"{BASE_URL}/api-tokens"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json; charset=UTF-8",
            "Referer": "https://browzine.com/",
        }
        payload = {
            "libraryId": library_id,
            "returnPreproxy": True,
            "client": "bzweb",
            "forceAuth": False,
        }

        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=self.timeout
            )
            if response.status_code == 200:
                data = response.json()
                token_payload = data["api-tokens"][0]
                token = token_payload["id"]
                expires_at = self._parse_expires_at(token_payload.get("expires_at"))
                with self._lock:
                    self._tokens[library_id] = token
                    if expires_at is not None:
                        self._token_expiry[library_id] = expires_at
                    elif library_id in self._token_expiry:
                        self._token_expiry.pop(library_id)
                if expires_at is not None:
                    logger.debug(
                        "Token expires at %s for library %s",
                        datetime.fromtimestamp(expires_at).isoformat(),
                        library_id,
                    )
                return token
        except requests.RequestException:
            return None
        return None

    def _get_json(
        self,
        url: str,
        library_id: str,
        params: dict[str, Any],
        accept: str = "application/vnd.api+json",
        retries: int = 2,
    ) -> dict[str, Any] | None:
        """
        Perform an authenticated GET request and parse JSON.

        Args:
            url: Request URL.
            library_id: Library ID for authentication.
            params: Query parameters.
            accept: Accept header value.
            retries: Number of retries for transient errors.

        Returns:
            Parsed JSON dictionary or None when the request fails.
        """
        token = self._get_token(library_id)
        if not token:
            return None

        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "Referer": "https://browzine.com/",
        }

        for attempt in range(retries + 1):
            try:
                response = requests.get(
                    url, headers=headers, params=params, timeout=self.timeout
                )
            except requests.RequestException:
                if attempt < retries:
                    time.sleep(1 + attempt)
                    continue
                return None

            if response.status_code == 401 and attempt < retries:
                logger.debug("Token rejected for library %s", library_id)
                token = self._get_token(library_id, refresh=True)
                if not token:
                    return None
                headers["Authorization"] = f"Bearer {token}"
                continue

            if response.status_code == 200:
                return response.json()

            if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(1 + attempt)
                continue

            return None

        return None

    def get_journal_info(
        self, journal_id: int, library_id: str
    ) -> dict[str, Any] | None:
        """
        Fetch journal metadata for a journal ID.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID for the request.

        Returns:
            Journal JSON payload or None when unavailable.
        """
        url = f"{BASE_URL}/libraries/{library_id}/journals/{journal_id}"
        params = {"client": "bzweb"}
        data = self._get_json(url, library_id, params)
        if data and "data" in data:
            return data["data"]
        return None

    def get_publication_years(
        self, journal_id: int, library_id: str
    ) -> list[int] | None:
        """
        Fetch available publication years for a journal.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID for the request.

        Returns:
            List of publication years or None when unavailable.
        """
        url = (
            f"{BASE_URL}/libraries/{library_id}/journals/{journal_id}/publication-years"
        )
        params = {"client": "bzweb"}
        data = self._get_json(url, library_id, params)
        if not data:
            return None
        years = []
        for item in data.get("publicationYears", []):
            year = to_int(item.get("id"))
            if year:
                years.append(year)
        return years

    def get_issues_by_year(
        self, journal_id: int, library_id: str, year: int
    ) -> list[dict[str, Any]] | None:
        """
        Fetch issues for a journal year.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID for the request.
            year: Publication year.

        Returns:
            List of issue payloads or None when unavailable.
        """
        url = f"{BASE_URL}/libraries/{library_id}/journals/{journal_id}/issues"
        params = {"client": "bzweb", "publication-year": str(year)}
        data = self._get_json(url, library_id, params)
        if not data:
            return None
        return data.get("issues", [])

    def get_articles_from_issue(
        self, issue_id: int, library_id: str
    ) -> list[dict[str, Any]] | None:
        """
        Fetch all articles for an issue.

        Args:
            issue_id: BrowZine issue ID.
            library_id: Library ID for the request.

        Returns:
            List of article payloads or None when unavailable.
        """
        url = f"{BASE_URL}/libraries/{library_id}/issues/{issue_id}/articles"
        params = {"client": "bzweb"}
        data = self._get_json(url, library_id, params)
        if not data:
            return None
        return data.get("data", [])

    def get_articles_in_press(
        self, journal_id: int, library_id: str
    ) -> list[dict[str, Any]]:
        """
        Fetch all in-press articles for a journal.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID for the request.

        Returns:
            List of in-press article payloads.
        """
        url = (
            f"{BASE_URL}/libraries/{library_id}/journals/{journal_id}/articles-in-press"
        )
        cursor = None
        results: list[dict[str, Any]] = []
        seen_cursors: set[str] = set()
        page_count = 0
        max_pages = 1000

        while True:
            params: dict[str, Any] = {"client": "bzweb"}
            if cursor:
                if cursor in seen_cursors:
                    logger.debug("Stopping in-press pagination due to repeated cursor")
                    break
                seen_cursors.add(cursor)
                params["cursor"] = cursor
            data = self._get_json(url, library_id, params)
            if not data:
                break
            results.extend(data.get("data", []))
            cursor = data.get("meta", {}).get("cursor", {}).get("next")
            page_count += 1
            logger.debug(
                "In-press page %s fetched for journal %s, total %s",
                page_count,
                journal_id,
                len(results),
            )
            if page_count >= max_pages:
                logger.debug("Stopping in-press pagination due to page limit")
                break
            if not cursor:
                break

        return results


JOURNAL_COLUMNS = [
    "journal_id",
    "library_id",
    "title",
    "issn",
    "eissn",
    "scimago_rank",
    "cover_url",
    "available",
    "toc_data_approved_and_live",
    "has_articles",
]

JOURNAL_UPSERT = f"""
INSERT INTO journals ({", ".join(JOURNAL_COLUMNS)})
VALUES ({", ".join(["?"] * len(JOURNAL_COLUMNS))})
ON CONFLICT(journal_id) DO UPDATE SET
{", ".join(f"{col}=excluded.{col}" for col in JOURNAL_COLUMNS[1:])}
"""

META_COLUMNS = [
    "journal_id",
    "source_csv",
    "area",
    "rank",
    "csv_title",
    "csv_issn",
    "csv_library",
]

META_UPSERT = f"""
INSERT INTO journal_meta ({", ".join(META_COLUMNS)})
VALUES ({", ".join(["?"] * len(META_COLUMNS))})
ON CONFLICT(journal_id) DO UPDATE SET
{", ".join(f"{col}=excluded.{col}" for col in META_COLUMNS[1:])}
"""

ISSUE_COLUMNS = [
    "issue_id",
    "journal_id",
    "publication_year",
    "title",
    "volume",
    "number",
    "date",
    "is_valid_issue",
    "suppressed",
    "embargoed",
    "within_subscription",
]

ISSUE_UPSERT = f"""
INSERT INTO issues ({", ".join(ISSUE_COLUMNS)})
VALUES ({", ".join(["?"] * len(ISSUE_COLUMNS))})
ON CONFLICT(issue_id) DO UPDATE SET
{", ".join(f"{col}=excluded.{col}" for col in ISSUE_COLUMNS[1:])}
"""

ARTICLE_COLUMNS = [
    "article_id",
    "journal_id",
    "issue_id",
    "sync_id",
    "title",
    "date",
    "authors",
    "start_page",
    "end_page",
    "abstract",
    "doi",
    "pmid",
    "ill_url",
    "link_resolver_openurl_link",
    "email_article_request_link",
    "permalink",
    "suppressed",
    "in_press",
    "open_access",
    "platform_id",
    "retraction_doi",
    "retraction_date",
    "retraction_related_urls",
    "unpaywall_data_suppressed",
    "expression_of_concern_doi",
    "within_library_holdings",
    "noodletools_export_link",
    "avoid_unpaywall_publisher_links",
    "browzine_web_in_context_link",
    "content_location",
    "libkey_content_location",
    "full_text_file",
    "libkey_full_text_file",
    "nomad_fallback_url",
]

ARTICLE_UPSERT = f"""
INSERT INTO articles ({", ".join(ARTICLE_COLUMNS)})
VALUES ({", ".join(["?"] * len(ARTICLE_COLUMNS))})
ON CONFLICT(article_id) DO UPDATE SET
{", ".join(f"{col}=excluded.{col}" for col in ARTICLE_COLUMNS[1:])}
"""


async def init_db(db: aiosqlite.Connection) -> None:
    """
    Initialize database schema and indexes.

    Args:
        db: Open aiosqlite connection.

    Returns:
        None.
    """
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    await db.execute("PRAGMA synchronous=NORMAL;")

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS journals (
            journal_id INTEGER PRIMARY KEY,
            library_id TEXT NOT NULL,
            title TEXT,
            issn TEXT,
            eissn TEXT,
            scimago_rank REAL,
            cover_url TEXT,
            available INTEGER,
            toc_data_approved_and_live INTEGER,
            has_articles INTEGER
        );
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_meta (
            journal_id INTEGER PRIMARY KEY,
            source_csv TEXT NOT NULL,
            area TEXT,
            rank TEXT,
            csv_title TEXT,
            csv_issn TEXT,
            csv_library TEXT,
            FOREIGN KEY (journal_id) REFERENCES journals(journal_id)
                ON DELETE CASCADE
        );
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS issues (
            issue_id INTEGER PRIMARY KEY,
            journal_id INTEGER NOT NULL,
            publication_year INTEGER,
            title TEXT,
            volume TEXT,
            number TEXT,
            date TEXT,
            is_valid_issue INTEGER,
            suppressed INTEGER,
            embargoed INTEGER,
            within_subscription INTEGER,
            FOREIGN KEY (journal_id) REFERENCES journals(journal_id)
                ON DELETE CASCADE
        );
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            article_id INTEGER PRIMARY KEY,
            journal_id INTEGER NOT NULL,
            issue_id INTEGER,
            sync_id INTEGER,
            title TEXT,
            date TEXT,
            authors TEXT,
            start_page TEXT,
            end_page TEXT,
            abstract TEXT,
            doi TEXT,
            pmid TEXT,
            ill_url TEXT,
            link_resolver_openurl_link TEXT,
            email_article_request_link TEXT,
            permalink TEXT,
            suppressed INTEGER,
            in_press INTEGER,
            open_access INTEGER,
            platform_id TEXT,
            retraction_doi TEXT,
            retraction_date TEXT,
            retraction_related_urls TEXT,
            unpaywall_data_suppressed INTEGER,
            expression_of_concern_doi TEXT,
            within_library_holdings INTEGER,
            noodletools_export_link TEXT,
            avoid_unpaywall_publisher_links INTEGER,
            browzine_web_in_context_link TEXT,
            content_location TEXT,
            libkey_content_location TEXT,
            full_text_file TEXT,
            libkey_full_text_file TEXT,
            nomad_fallback_url TEXT,
            FOREIGN KEY (journal_id) REFERENCES journals(journal_id)
                ON DELETE CASCADE,
            FOREIGN KEY (issue_id) REFERENCES issues(issue_id)
                ON DELETE SET NULL
        );
        """
    )

    await db.execute("CREATE INDEX IF NOT EXISTS idx_journals_issn ON journals(issn);")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_journal_meta_area ON journal_meta(area);"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_issues_journal_year "
        "ON issues(journal_id, publication_year);"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_journal ON articles(journal_id);"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_issue ON articles(issue_id);"
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(date);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_articles_doi ON articles(doi);")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_open_access ON articles(open_access);"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_in_press ON articles(in_press);"
    )

    await db.commit()


def build_journal_record(
    journal_id: int,
    library_id: str,
    csv_row: dict[str, str],
    journal_info: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Build a journal record for database insertion.

    Args:
        journal_id: BrowZine journal ID.
        library_id: Library ID used for the journal.
        csv_row: Source CSV row.
        journal_info: BrowZine journal payload.

    Returns:
        Dictionary of journal fields.
    """
    attrs = journal_info.get("attributes", {}) if journal_info else {}

    def pick_attr(*keys: str) -> Any:
        """
        Choose the first available attribute key.

        Args:
            keys: Attribute keys to check.

        Returns:
            Attribute value or None.
        """
        for key in keys:
            if key in attrs:
                return attrs[key]
        return None

    return {
        "journal_id": journal_id,
        "library_id": library_id,
        "title": pick_attr("title") or csv_row.get("title"),
        "issn": pick_attr("issn") or csv_row.get("issn"),
        "eissn": pick_attr("eissn"),
        "scimago_rank": to_float(pick_attr("scimagoRank", "scimago_rank")),
        "cover_url": pick_attr("coverURL", "coverUrl"),
        "available": to_bool_int(pick_attr("available")),
        "toc_data_approved_and_live": to_bool_int(
            pick_attr("tocDataApprovedAndLive", "toc_data_approved_and_live")
        ),
        "has_articles": to_bool_int(pick_attr("hasArticles", "has_articles")),
    }


def build_meta_record(
    journal_id: int, csv_path: Path, csv_row: dict[str, str]
) -> dict[str, Any]:
    """
    Build CSV metadata for the journal.

    Args:
        journal_id: BrowZine journal ID.
        csv_path: Path to the source CSV.
        csv_row: Source CSV row.

    Returns:
        Dictionary of CSV metadata fields.
    """
    return {
        "journal_id": journal_id,
        "source_csv": csv_path.name,
        "area": csv_row.get("area"),
        "rank": csv_row.get("rank"),
        "csv_title": csv_row.get("title"),
        "csv_issn": csv_row.get("issn"),
        "csv_library": csv_row.get("library"),
    }


def build_issue_record(
    issue: dict[str, Any], journal_id: int, year: int
) -> dict[str, Any] | None:
    """
    Build an issue record for database insertion.

    Args:
        issue: Issue payload.
        journal_id: BrowZine journal ID fallback.
        year: Publication year.

    Returns:
        Dictionary of issue fields or None when issue ID is missing.
    """
    issue_id = to_int(issue.get("id"))
    if not issue_id:
        return None
    attrs = issue.get("attributes", {})
    return {
        "issue_id": issue_id,
        "journal_id": to_int(attrs.get("journal")) or journal_id,
        "publication_year": year,
        "title": attrs.get("title"),
        "volume": attrs.get("volume"),
        "number": attrs.get("number"),
        "date": attrs.get("date"),
        "is_valid_issue": to_bool_int(attrs.get("isValidIssue")),
        "suppressed": to_bool_int(attrs.get("suppressed")),
        "embargoed": to_bool_int(attrs.get("embargoed")),
        "within_subscription": to_bool_int(attrs.get("withinSubscription")),
    }


def build_article_record(
    article: dict[str, Any],
    fallback_journal_id: int,
    fallback_issue_id: int | None,
) -> dict[str, Any] | None:
    """
    Build an article record for database insertion.

    Args:
        article: Article payload.
        fallback_journal_id: Journal ID fallback when relationship is missing.
        fallback_issue_id: Issue ID fallback when relationship is missing.

    Returns:
        Dictionary of article fields or None when article ID is missing.
    """
    article_id = to_int(article.get("id"))
    if not article_id:
        return None
    attrs = article.get("attributes", {})
    relationships = article.get("relationships", {})
    journal_rel = relationships.get("journal", {}).get("data", {})
    issue_rel = relationships.get("issue", {}).get("data", {})

    journal_id = to_int(journal_rel.get("id")) or fallback_journal_id
    issue_id = to_int(issue_rel.get("id")) or fallback_issue_id

    return {
        "article_id": article_id,
        "journal_id": journal_id,
        "issue_id": issue_id,
        "sync_id": to_int(attrs.get("syncId")),
        "title": attrs.get("title"),
        "date": attrs.get("date"),
        "authors": attrs.get("authors"),
        "start_page": attrs.get("startPage"),
        "end_page": attrs.get("endPage"),
        "abstract": attrs.get("abstract"),
        "doi": attrs.get("doi"),
        "pmid": attrs.get("pmid"),
        "ill_url": attrs.get("ILLURL"),
        "link_resolver_openurl_link": attrs.get("linkResolverOpenurlLink"),
        "email_article_request_link": attrs.get("emailArticleRequestLink"),
        "permalink": attrs.get("permalink"),
        "suppressed": to_bool_int(attrs.get("suppressed")),
        "in_press": to_bool_int(attrs.get("inPress")),
        "open_access": to_bool_int(attrs.get("openAccess")),
        "platform_id": attrs.get("platformId"),
        "retraction_doi": attrs.get("retractionDoi"),
        "retraction_date": attrs.get("retractionDate"),
        "retraction_related_urls": to_text(attrs.get("retractionRelatedUrls")),
        "unpaywall_data_suppressed": to_bool_int(attrs.get("unpaywallDataSuppressed")),
        "expression_of_concern_doi": attrs.get("expressionOfConcernDoi"),
        "within_library_holdings": to_bool_int(attrs.get("withinLibraryHoldings")),
        "noodletools_export_link": attrs.get("noodleToolsExportLink"),
        "avoid_unpaywall_publisher_links": to_bool_int(
            attrs.get("avoidUnpaywallPublisherLinks")
        ),
        "browzine_web_in_context_link": attrs.get("browzineWebInContextLink"),
        "content_location": attrs.get("contentLocation"),
        "libkey_content_location": attrs.get("libkeyContentLocation"),
        "full_text_file": attrs.get("fullTextFile"),
        "libkey_full_text_file": attrs.get("libkeyFullTextFile"),
        "nomad_fallback_url": attrs.get("nomadFallbackURL"),
    }


async def upsert_journal(db: aiosqlite.Connection, record: dict[str, Any]) -> None:
    """
    Insert or update a journal record.

    Args:
        db: Open aiosqlite connection.
        record: Journal record data.

    Returns:
        None.
    """
    await db.execute(JOURNAL_UPSERT, tuple(record[col] for col in JOURNAL_COLUMNS))


async def upsert_meta(db: aiosqlite.Connection, record: dict[str, Any]) -> None:
    """
    Insert or update a journal meta record.

    Args:
        db: Open aiosqlite connection.
        record: Journal meta record data.

    Returns:
        None.
    """
    await db.execute(META_UPSERT, tuple(record[col] for col in META_COLUMNS))


async def upsert_issues(
    db: aiosqlite.Connection, records: list[dict[str, Any]]
) -> None:
    """
    Insert or update issue records.

    Args:
        db: Open aiosqlite connection.
        records: List of issue record data.

    Returns:
        None.
    """
    if not records:
        return
    rows = [tuple(record[col] for col in ISSUE_COLUMNS) for record in records]
    await db.executemany(ISSUE_UPSERT, rows)


async def upsert_articles(
    db: aiosqlite.Connection, records: list[dict[str, Any]]
) -> None:
    """
    Insert or update article records.

    Args:
        db: Open aiosqlite connection.
        records: List of article record data.

    Returns:
        None.
    """
    if not records:
        return
    rows = [tuple(record[col] for col in ARTICLE_COLUMNS) for record in records]
    await db.executemany(ARTICLE_UPSERT, rows)


async def fetch_in_thread(executor: ThreadPoolExecutor, func: Any, *args: Any) -> Any:
    """
    Run a blocking function in a thread pool.

    Args:
        executor: Thread pool executor.
        func: Blocking function to execute.
        *args: Positional arguments for the function.

    Returns:
        Result of the function or None on failure.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(executor, func, *args)
    except Exception:
        return None


async def fetch_issue_articles(
    executor: ThreadPoolExecutor,
    client: BrowZineAPIClient,
    issue_id: int,
    library_id: str,
) -> tuple[int, list[dict[str, Any]] | None]:
    """
    Fetch articles for a single issue in a thread.

    Args:
        executor: Thread pool executor.
        client: BrowZine API client.
        issue_id: BrowZine issue ID.
        library_id: Library ID for the request.

    Returns:
        Tuple of issue ID and article list or None.
    """
    articles = await fetch_in_thread(
        executor, client.get_articles_from_issue, issue_id, library_id
    )
    return issue_id, articles


async def process_journal(
    db: aiosqlite.Connection,
    client: BrowZineAPIClient,
    executor: ThreadPoolExecutor,
    csv_path: Path,
    row: dict[str, str],
    issue_batch_size: int,
) -> None:
    """
    Export a single journal to the database.

    Args:
        db: Open aiosqlite connection.
        client: BrowZine API client.
        executor: Thread pool executor for API calls.
        csv_path: Source CSV path.
        row: CSV row for the journal.
        issue_batch_size: Number of issues per fetch batch.

    Returns:
        None.
    """
    journal_id = to_int(row.get("id"))
    if not journal_id:
        print(f"  - Skipping journal with missing id: {row.get('title')}")
        return

    library_id = row.get("library") or DEFAULT_LIBRARY_ID
    logger.debug(
        "Start journal %s (%s) with library %s",
        journal_id,
        row.get("title"),
        library_id,
    )

    journal_info = await fetch_in_thread(
        executor, client.get_journal_info, journal_id, library_id
    )

    journal_record = build_journal_record(journal_id, library_id, row, journal_info)
    meta_record = build_meta_record(journal_id, csv_path, row)

    await upsert_journal(db, journal_record)
    await upsert_meta(db, meta_record)
    await db.commit()

    years = await fetch_in_thread(
        executor, client.get_publication_years, journal_id, library_id
    )
    if not years:
        print(f"  - No publication years for journal {journal_id}")
        return

    seen_issue_ids: set[int] = set()
    issue_total = 0
    issue_duplicates = 0
    article_count = 0

    total_years = len(years)
    with tqdm(
        total=total_years,
        desc=f"Journal {journal_id} years",
        unit="year",
    ) as progress:
        for index, year in enumerate(years, start=1):
            progress.set_postfix_str(f"{year} ({index}/{total_years})")
            logger.debug("Fetching issues for journal %s year %s", journal_id, year)
            issues = await fetch_in_thread(
                executor, client.get_issues_by_year, journal_id, library_id, year
            )
            if not issues:
                progress.update(1)
                continue

            issue_records: list[dict[str, Any]] = []
            issue_ids: list[int] = []
            for issue in issues:
                record = build_issue_record(issue, journal_id, year)
                if record:
                    issue_total += 1
                    issue_id = record["issue_id"]
                    if issue_id in seen_issue_ids:
                        issue_duplicates += 1
                        continue
                    seen_issue_ids.add(issue_id)
                    issue_records.append(record)
                    issue_ids.append(issue_id)

            if issue_records:
                await upsert_issues(db, issue_records)
                await db.commit()

            if issue_ids:
                for batch in chunked(issue_ids, issue_batch_size):
                    logger.debug(
                        "Fetching articles for journal %s issue batch size %s",
                        journal_id,
                        len(batch),
                    )
                    tasks = [
                        asyncio.create_task(
                            fetch_issue_articles(executor, client, issue_id, library_id)
                        )
                        for issue_id in batch
                    ]
                    for completed in asyncio.as_completed(tasks):
                        try:
                            issue_id, articles = await completed
                        except Exception:
                            print("  - Failed to fetch articles for an issue batch")
                            continue
                        if not articles:
                            continue
                        article_records = []
                        for article in articles:
                            record = build_article_record(article, journal_id, issue_id)
                            if record:
                                article_records.append(record)
                        article_count += len(article_records)
                        logger.debug(
                            "Issue %s yielded %s articles for journal %s",
                            issue_id,
                            len(article_records),
                            journal_id,
                        )
                        await upsert_articles(db, article_records)
                        await db.commit()

            progress.update(1)

    logger.debug(
        "Fetched %s issues for journal %s (%s unique, %s duplicates)",
        issue_total,
        journal_id,
        len(seen_issue_ids),
        issue_duplicates,
    )

    in_press = await fetch_in_thread(
        executor, client.get_articles_in_press, journal_id, library_id
    )
    if in_press:
        logger.debug(
            "Fetched %s in-press articles for journal %s",
            len(in_press),
            journal_id,
        )
        in_press_records = []
        for article in in_press:
            record = build_article_record(article, journal_id, None)
            if record:
                in_press_records.append(record)
        article_count += len(in_press_records)
        await upsert_articles(db, in_press_records)
        await db.commit()
    logger.debug("Finished journal %s with %s articles", journal_id, article_count)


def configure_logging(debug: bool) -> Path:
    """
    Configure logging output and create a log file.

    Args:
        debug: Whether to enable debug logging.

    Returns:
        Log file path.
    """
    project_root = Path(__file__).parent.parent
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"index_{timestamp}.log"

    root_level = logging.DEBUG if debug else logging.INFO
    file_level = logging.DEBUG if debug else logging.INFO
    stream_level = logging.INFO

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(file_level)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(stream_level)

    logging.basicConfig(
        level=root_level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[file_handler, stream_handler],
    )
    return log_path


def load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    """
    Load CSV rows and ensure the library column exists.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of CSV row dictionaries.
    """
    with open(csv_path, encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        return []
    if "library" not in rows[0]:
        for row in rows:
            row["library"] = DEFAULT_LIBRARY_ID
    for row in rows:
        if not row.get("library"):
            row["library"] = DEFAULT_LIBRARY_ID
    return rows


async def export_csv(
    csv_path: Path,
    db_path: Path,
    client: BrowZineAPIClient,
    executor: ThreadPoolExecutor,
    issue_batch_size: int,
) -> None:
    """
    Export a CSV file to a SQLite database.

    Args:
        csv_path: Path to the CSV file.
        db_path: Output SQLite database path.
        client: BrowZine API client.
        executor: Thread pool executor for API calls.
        issue_batch_size: Number of issues per fetch batch.

    Returns:
        None.
    """
    rows = load_csv_rows(csv_path)
    if not rows:
        print(f"Skipping empty CSV: {csv_path.name}")
        return

    print(f"\nProcessing {csv_path.name} -> {db_path.name}")

    async with aiosqlite.connect(db_path) as db:
        await init_db(db)
        for index, row in enumerate(rows, start=1):
            title = row.get("title", "Unknown")
            print(f"  [{index}/{len(rows)}] Exporting {title}")
            await process_journal(db, client, executor, csv_path, row, issue_batch_size)


async def async_main(args: argparse.Namespace) -> None:
    """
    Run export process for all target CSV files.

    Args:
        args: Parsed CLI arguments.

    Returns:
        None.
    """
    project_root = Path(__file__).parent.parent
    meta_dir = project_root / "data" / "meta"
    index_dir = project_root / "data" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    if not meta_dir.exists():
        print(f"Directory not found: {meta_dir}")
        return

    if args.file:
        csv_paths = [meta_dir / args.file]
        if not csv_paths[0].exists():
            print(f"CSV not found: {csv_paths[0]}")
            return
    else:
        csv_paths = sorted(meta_dir.glob("*.csv"))

    if not csv_paths:
        print(f"No CSV files found in {meta_dir}")
        return

    issue_batch_size = max(1, args.issue_batch or args.workers * 3)

    client = BrowZineAPIClient(library_id=DEFAULT_LIBRARY_ID, timeout=args.timeout)

    print("=" * 60)
    print("BrowZine Article Indexer")
    print("=" * 60)
    print(f"Found {len(csv_paths)} CSV file(s)")
    print(f"Thread workers: {args.workers}")
    print(f"Issue batch size: {issue_batch_size}")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for csv_path in csv_paths:
            db_path = index_dir / f"{csv_path.stem}.sqlite"
            await export_csv(csv_path, db_path, client, executor, issue_batch_size)

    print("\nDone.")


def main() -> None:
    """
    Parse CLI arguments and run the exporter.

    Args:
        None.

    Returns:
        None.
    """
    parser = argparse.ArgumentParser(
        description="Export BrowZine journal articles to SQLite databases"
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        help="Specific CSV filename under data/meta (e.g., utd24.csv)",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=8,
        help="Thread workers for API fetching",
    )
    parser.add_argument(
        "--issue-batch",
        type=int,
        default=0,
        help="Issues per async batch (default: workers * 3)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP request timeout in seconds",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    log_path = configure_logging(args.debug)
    logger.info("Logging to %s", log_path)
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
