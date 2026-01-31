"""
Export journal articles from BrowZine API to per-CSV SQLite databases.

Each CSV in data/meta becomes one SQLite database under data/index.
Network fetching uses async HTTP while database writes use aiosqlite.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import multiprocessing as mp
import sqlite3
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import aiosqlite
import httpx
from tqdm import tqdm

DEFAULT_LIBRARY_ID = "3050"
BASE_URL = "https://api.thirdiron.com/v2"
TOKEN_EXPIRY_BUFFER = 300
DB_TIMEOUT_SECONDS = 30
DB_RETRY_ATTEMPTS = 6
DB_RETRY_BASE_DELAY = 0.5


async def execute_with_retry(
    db: aiosqlite.Connection, sql: str, params: tuple[Any, ...] | None = None
) -> None:
    """
    Execute a SQL statement with retries on database lock errors.

    Args:
        db: Open aiosqlite connection.
        sql: SQL statement to execute.
        params: SQL parameters.

    Returns:
        None.
    """
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            if params is None:
                await db.execute(sql)
            else:
                await db.execute(sql, params)
            return
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            if attempt >= DB_RETRY_ATTEMPTS - 1:
                raise
            await asyncio.sleep(DB_RETRY_BASE_DELAY * (attempt + 1))


async def executemany_with_retry(
    db: aiosqlite.Connection, sql: str, rows: list[tuple[Any, ...]]
) -> None:
    """
    Execute many SQL statements with retries on database lock errors.

    Args:
        db: Open aiosqlite connection.
        sql: SQL statement to execute.
        rows: SQL parameter rows.

    Returns:
        None.
    """
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            await db.executemany(sql, rows)
            return
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            if attempt >= DB_RETRY_ATTEMPTS - 1:
                raise
            await asyncio.sleep(DB_RETRY_BASE_DELAY * (attempt + 1))


async def commit_with_retry(db: aiosqlite.Connection) -> None:
    """
    Commit a transaction with retries on database lock errors.

    Args:
        db: Open aiosqlite connection.

    Returns:
        None.
    """
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            await db.commit()
            return
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            if attempt >= DB_RETRY_ATTEMPTS - 1:
                raise
            await asyncio.sleep(DB_RETRY_BASE_DELAY * (attempt + 1))


class DatabaseWriter:
    """
    Serialize database writes through a single async worker.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        """
        Initialize the writer with an open database connection.

        Args:
            db: Open aiosqlite connection.
        """
        self._db = db
        self._queue: asyncio.Queue[
            tuple[str, Any, Any, asyncio.Future[None]] | None
        ] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """
        Start the background writer task.

        Returns:
            None.
        """
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        """
        Stop the background writer task after pending work completes.

        Returns:
            None.
        """
        if self._task is None:
            return
        await self._queue.put(None)
        await self._task
        self._task = None

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """
        Enqueue a SQL statement for execution.

        Args:
            sql: SQL statement to execute.
            params: SQL parameters.

        Returns:
            None.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        await self._queue.put(("execute", sql, params, future))
        await future

    async def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        """
        Enqueue a SQL executemany operation.

        Args:
            sql: SQL statement to execute.
            rows: SQL parameter rows.

        Returns:
            None.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        await self._queue.put(("executemany", sql, rows, future))
        await future

    async def commit(self) -> None:
        """
        Enqueue a commit operation.

        Returns:
            None.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        await self._queue.put(("commit", None, None, future))
        await future

    async def _run(self) -> None:
        """
        Execute queued write operations sequentially.

        Returns:
            None.
        """
        while True:
            item = await self._queue.get()
            if item is None:
                break
            kind, sql, payload, future = item
            try:
                if kind == "execute":
                    await execute_with_retry(self._db, sql, payload)
                elif kind == "executemany":
                    await executemany_with_retry(self._db, sql, payload)
                elif kind == "commit":
                    await commit_with_retry(self._db)
                if not future.done():
                    future.set_result(None)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)


class DatabaseClient(Protocol):
    """
    Database client protocol for read and write operations.
    """

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """
        Execute a SQL statement.

        Args:
            sql: SQL statement to execute.
            params: SQL parameters.

        Returns:
            None.
        """

    async def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        """
        Execute many SQL statements.

        Args:
            sql: SQL statement to execute.
            rows: SQL parameter rows.

        Returns:
            None.
        """

    async def commit(self) -> None:
        """
        Commit a transaction.

        Returns:
            None.
        """

    async def fetchall(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> list[tuple[Any, ...]]:
        """
        Fetch all rows for a query.

        Args:
            sql: SQL statement to execute.
            params: SQL parameters.

        Returns:
            Query result rows.
        """

    async def fetchone(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> tuple[Any, ...] | None:
        """
        Fetch a single row for a query.

        Args:
            sql: SQL statement to execute.
            params: SQL parameters.

        Returns:
            Single row or None.
        """


class LocalDatabaseClient:
    """
    Local database client that uses a writer for serialized writes.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        """
        Initialize the client.

        Args:
            db: Open aiosqlite connection.
        """
        self._db = db
        self._writer = DatabaseWriter(db)

    async def start(self) -> None:
        """
        Start the write worker.

        Returns:
            None.
        """
        await self._writer.start()

    async def close(self) -> None:
        """
        Stop the write worker.

        Returns:
            None.
        """
        await self._writer.close()

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """
        Execute a SQL statement.

        Args:
            sql: SQL statement to execute.
            params: SQL parameters.

        Returns:
            None.
        """
        await self._writer.execute(sql, params)

    async def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        """
        Execute many SQL statements.

        Args:
            sql: SQL statement to execute.
            rows: SQL parameter rows.

        Returns:
            None.
        """
        await self._writer.executemany(sql, rows)

    async def commit(self) -> None:
        """
        Commit a transaction.

        Returns:
            None.
        """
        await self._writer.commit()

    async def fetchall(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> list[tuple[Any, ...]]:
        """
        Fetch all rows for a query.

        Args:
            sql: SQL statement to execute.
            params: SQL parameters.

        Returns:
            Query result rows.
        """
        cursor = await self._db.execute(sql, params or ())
        rows = await cursor.fetchall()
        await cursor.close()
        return [tuple(row) for row in rows]

    async def fetchone(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> tuple[Any, ...] | None:
        """
        Fetch a single row for a query.

        Args:
            sql: SQL statement to execute.
            params: SQL parameters.

        Returns:
            Single row or None.
        """
        cursor = await self._db.execute(sql, params or ())
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return tuple(row)


class IPCDatabaseClient:
    """
    IPC database client for single-writer multiprocessing.
    """

    def __init__(self, request_queue: Any, response_queue: Any, worker_id: int) -> None:
        """
        Initialize the IPC client.

        Args:
            request_queue: Multiprocessing request queue.
            response_queue: Multiprocessing response queue.
            worker_id: Worker identifier for response routing.
        """
        self._request_queue = request_queue
        self._response_queue = response_queue
        self._worker_id = worker_id

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """
        Execute a SQL statement.

        Args:
            sql: SQL statement to execute.
            params: SQL parameters.

        Returns:
            None.
        """
        await self._send_request("execute", {"sql": sql, "params": params})

    async def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        """
        Execute many SQL statements.

        Args:
            sql: SQL statement to execute.
            rows: SQL parameter rows.

        Returns:
            None.
        """
        await self._send_request("executemany", {"sql": sql, "rows": rows})

    async def commit(self) -> None:
        """
        Commit a transaction.

        Returns:
            None.
        """
        await self._send_request("commit", {})

    async def fetchall(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> list[tuple[Any, ...]]:
        """
        Fetch all rows for a query.

        Args:
            sql: SQL statement to execute.
            params: SQL parameters.

        Returns:
            Query result rows.
        """
        return await self._send_request("fetchall", {"sql": sql, "params": params})

    async def fetchone(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> tuple[Any, ...] | None:
        """
        Fetch a single row for a query.

        Args:
            sql: SQL statement to execute.
            params: SQL parameters.

        Returns:
            Single row or None.
        """
        return await self._send_request("fetchone", {"sql": sql, "params": params})

    async def _send_request(self, kind: str, payload: dict[str, Any]) -> Any:
        """
        Send a request to the writer process and await the response.

        Args:
            kind: Request type.
            payload: Request payload.

        Returns:
            Response payload.
        """
        request_id = f"{time.time_ns()}"
        message = {
            "id": request_id,
            "type": kind,
            "payload": payload,
            "worker_id": self._worker_id,
        }
        await asyncio.to_thread(self._request_queue.put, message)
        response = await asyncio.to_thread(self._response_queue.get)
        if response.get("id") != request_id:
            raise RuntimeError("Mismatched IPC response id")
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "IPC database error")
        return response.get("result")


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
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=self.timeout)

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

    async def _get_token(self, library_id: str, refresh: bool = False) -> str | None:
        """
        Request or reuse a token for the given library.

        Args:
            library_id: Library ID to authenticate.
            refresh: Whether to force refresh the token.

        Returns:
            Token string or None when authentication fails.
        """
        async with self._lock:
            if (
                not refresh
                and library_id in self._tokens
                and self._token_is_valid(library_id)
            ):
                return self._tokens[library_id]

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
            response = await self._client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                data = response.json()
                token_payload = data["api-tokens"][0]
                token = token_payload["id"]
                expires_at = self._parse_expires_at(token_payload.get("expires_at"))
                async with self._lock:
                    self._tokens[library_id] = token
                    if expires_at is not None:
                        self._token_expiry[library_id] = expires_at
                    elif library_id in self._token_expiry:
                        self._token_expiry.pop(library_id)
                return token
        except httpx.RequestError:
            return None
        return None

    async def _get_json(
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
        token = await self._get_token(library_id)
        if not token:
            return None

        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "Referer": "https://browzine.com/",
        }

        for attempt in range(retries + 1):
            try:
                response = await self._client.get(url, headers=headers, params=params)
            except httpx.RequestError:
                if attempt < retries:
                    await asyncio.sleep(1 + attempt)
                    continue
                return None

            if response.status_code == 401 and attempt < retries:
                token = await self._get_token(library_id, refresh=True)
                if not token:
                    return None
                headers["Authorization"] = f"Bearer {token}"
                continue

            if response.status_code == 200:
                return response.json()

            if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                await asyncio.sleep(1 + attempt)
                continue

            return None

        return None

    async def get_journal_info(
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
        data = await self._get_json(url, library_id, params)
        if data and "data" in data:
            return data["data"]
        return None

    async def get_publication_years(
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
        data = await self._get_json(url, library_id, params)
        if not data:
            return None
        years = []
        for item in data.get("publicationYears", []):
            year = to_int(item.get("id"))
            if year:
                years.append(year)
        return years

    async def get_issues_by_year(
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
        data = await self._get_json(url, library_id, params)
        if not data:
            return None
        return data.get("issues", [])

    async def get_articles_from_issue(
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
        data = await self._get_json(url, library_id, params)
        if not data:
            return None
        return data.get("data", [])

    async def get_articles_in_press(
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
                    break
                seen_cursors.add(cursor)
                params["cursor"] = cursor
            data = await self._get_json(url, library_id, params)
            if not data:
                break
            results.extend(data.get("data", []))
            cursor = data.get("meta", {}).get("cursor", {}).get("next")
            page_count += 1
            if page_count >= max_pages:
                break
            if not cursor:
                break

        return results

    async def aclose(self) -> None:
        """
        Close the underlying HTTP client.

        Returns:
            None.
        """
        await self._client.aclose()


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

ARTICLE_LISTING_COLUMNS = [
    "article_id",
    "journal_id",
    "issue_id",
    "publication_year",
    "date",
    "open_access",
    "in_press",
    "suppressed",
    "within_library_holdings",
    "doi",
    "pmid",
    "area",
    "rank",
]

ARTICLE_LISTING_BATCH_SIZE = 500


async def init_db(db: aiosqlite.Connection) -> None:
    """
    Initialize database schema and indexes.

    Args:
        db: Open aiosqlite connection.

    Returns:
        None.
    """
    await execute_with_retry(db, "PRAGMA journal_mode=WAL;")
    await execute_with_retry(db, "PRAGMA foreign_keys=ON;")
    await execute_with_retry(db, "PRAGMA synchronous=NORMAL;")
    await execute_with_retry(db, f"PRAGMA busy_timeout={DB_TIMEOUT_SECONDS * 1000};")

    await execute_with_retry(
        db,
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
        """,
    )

    await execute_with_retry(
        db,
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
        """,
    )

    await execute_with_retry(
        db,
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
        """,
    )

    await execute_with_retry(
        db,
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
        """,
    )

    await execute_with_retry(
        db,
        """
        CREATE TABLE IF NOT EXISTS article_listing (
            article_id INTEGER PRIMARY KEY,
            journal_id INTEGER NOT NULL,
            issue_id INTEGER,
            publication_year INTEGER,
            date TEXT,
            open_access INTEGER,
            in_press INTEGER,
            suppressed INTEGER,
            within_library_holdings INTEGER,
            doi TEXT,
            pmid TEXT,
            area TEXT,
            rank TEXT,
            FOREIGN KEY (journal_id) REFERENCES journals(journal_id)
                ON DELETE CASCADE,
            FOREIGN KEY (issue_id) REFERENCES issues(issue_id)
                ON DELETE SET NULL
        );
        """,
    )

    await execute_with_retry(
        db,
        """
        CREATE TABLE IF NOT EXISTS listing_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            status TEXT,
            updated_at TEXT
        );
        """,
    )

    await execute_with_retry(
        db,
        """
        CREATE TABLE IF NOT EXISTS journal_year_state (
            journal_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (journal_id, year)
        );
        """,
    )

    await execute_with_retry(
        db,
        """
        CREATE TABLE IF NOT EXISTS journal_state (
            journal_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    )

    await execute_with_retry(
        db,
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS article_search
        USING fts5(
            article_id UNINDEXED,
            title,
            abstract,
            doi,
            authors,
            journal_title
        );
        """,
    )

    await execute_with_retry(
        db, "CREATE INDEX IF NOT EXISTS idx_journals_issn ON journals(issn);"
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_journals_library_id ON journals(library_id);",
    )
    await execute_with_retry(
        db, "CREATE INDEX IF NOT EXISTS idx_journals_available ON journals(available);"
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_journals_has_articles "
        "ON journals(has_articles);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_journals_scimago_rank "
        "ON journals(scimago_rank);",
    )
    await execute_with_retry(
        db, "CREATE INDEX IF NOT EXISTS idx_journal_meta_area ON journal_meta(area);"
    )
    await execute_with_retry(
        db, "CREATE INDEX IF NOT EXISTS idx_journal_meta_rank ON journal_meta(rank);"
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_journal_meta_area_journal "
        "ON journal_meta(area, journal_id);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_journal_meta_rank_journal "
        "ON journal_meta(rank, journal_id);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_issues_journal_year "
        "ON issues(journal_id, publication_year);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_issues_publication_year "
        "ON issues(publication_year);",
    )
    await execute_with_retry(
        db, "CREATE INDEX IF NOT EXISTS idx_articles_journal ON articles(journal_id);"
    )
    await execute_with_retry(
        db, "CREATE INDEX IF NOT EXISTS idx_articles_issue ON articles(issue_id);"
    )
    await execute_with_retry(
        db, "CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(date);"
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_articles_date_id "
        "ON articles(date, article_id);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_articles_journal_date_id "
        "ON articles(journal_id, date, article_id);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_articles_issue_date_id "
        "ON articles(issue_id, date, article_id);",
    )
    await execute_with_retry(
        db, "CREATE INDEX IF NOT EXISTS idx_articles_doi ON articles(doi);"
    )
    await execute_with_retry(
        db, "CREATE INDEX IF NOT EXISTS idx_articles_pmid ON articles(pmid);"
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_articles_open_access ON articles(open_access);",
    )
    await execute_with_retry(
        db, "CREATE INDEX IF NOT EXISTS idx_articles_in_press ON articles(in_press);"
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_articles_suppressed ON articles(suppressed);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_articles_within_holdings "
        "ON articles(within_library_holdings);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_articles_open_access_date_id "
        "ON articles(open_access, date, article_id);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_articles_in_press_date_id "
        "ON articles(in_press, date, article_id);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_articles_suppressed_date_id "
        "ON articles(suppressed, date, article_id);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_articles_within_holdings_date_id "
        "ON articles(within_library_holdings, date, article_id);",
    )

    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_article_listing_date_id "
        "ON article_listing(date, article_id);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_article_listing_area ON article_listing(area);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_article_listing_rank ON article_listing(rank);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_article_listing_publication_year "
        "ON article_listing(publication_year);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_article_listing_journal "
        "ON article_listing(journal_id);",
    )
    await execute_with_retry(
        db,
        "CREATE INDEX IF NOT EXISTS idx_article_listing_issue "
        "ON article_listing(issue_id);",
    )

    await commit_with_retry(db)


async def optimize_db(db: aiosqlite.Connection) -> None:
    """
    Run SQLite optimizations after data load.

    Args:
        db: Open aiosqlite connection.

    Returns:
        None.
    """
    await execute_with_retry(db, "ANALYZE;")
    await execute_with_retry(db, "PRAGMA optimize;")
    await commit_with_retry(db)


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


async def upsert_journal(db: DatabaseClient, record: dict[str, Any]) -> None:
    """
    Insert or update a journal record.

    Args:
        db: Database client.
        record: Journal record data.

    Returns:
        None.
    """
    await db.execute(JOURNAL_UPSERT, tuple(record[col] for col in JOURNAL_COLUMNS))


async def upsert_meta(db: DatabaseClient, record: dict[str, Any]) -> None:
    """
    Insert or update a journal meta record.

    Args:
        db: Database client.
        record: Journal meta record data.

    Returns:
        None.
    """
    await db.execute(META_UPSERT, tuple(record[col] for col in META_COLUMNS))


async def upsert_issues(db: DatabaseClient, records: list[dict[str, Any]]) -> None:
    """
    Insert or update issue records.

    Args:
        db: Database client.
        records: List of issue record data.

    Returns:
        None.
    """
    if not records:
        return
    rows = [tuple(record[col] for col in ISSUE_COLUMNS) for record in records]
    await db.executemany(ISSUE_UPSERT, rows)


async def upsert_articles(db: DatabaseClient, records: list[dict[str, Any]]) -> None:
    """
    Insert or update article records.

    Args:
        db: Database client.
        records: List of article record data.

    Returns:
        None.
    """
    if not records:
        return
    rows = [tuple(record[col] for col in ARTICLE_COLUMNS) for record in records]
    await db.executemany(ARTICLE_UPSERT, rows)


async def upsert_article_search(
    db: DatabaseClient,
    records: list[dict[str, Any]],
    journal_title: str | None,
) -> None:
    """
    Update FTS index rows for articles.

    Args:
        db: Database client.
        records: Article record data.
        journal_title: Journal title for the article.

    Returns:
        None.
    """
    if not records:
        return
    title_value = journal_title or ""
    insert_rows = [
        (
            record["article_id"],
            record["article_id"],
            record.get("title") or "",
            record.get("abstract") or "",
            record.get("doi") or "",
            record.get("authors") or "",
            title_value,
        )
        for record in records
    ]
    await db.executemany(
        """
        INSERT OR REPLACE INTO article_search (
            rowid,
            article_id,
            title,
            abstract,
            doi,
            authors,
            journal_title
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        insert_rows,
    )


def build_article_listing_upsert(where_sql: str) -> str:
    """
    Build the upsert SQL for article listing rows.

    Args:
        where_sql: WHERE clause string starting with WHERE.

    Returns:
        SQL statement for inserting listing rows.
    """
    return f"""
    INSERT INTO article_listing ({", ".join(ARTICLE_LISTING_COLUMNS)})
    SELECT
        a.article_id,
        a.journal_id,
        a.issue_id,
        i.publication_year,
        a.date,
        a.open_access,
        a.in_press,
        a.suppressed,
        a.within_library_holdings,
        a.doi,
        a.pmid,
        m.area,
        m.rank
    FROM articles a
    LEFT JOIN issues i ON i.issue_id = a.issue_id
    LEFT JOIN journal_meta m ON m.journal_id = a.journal_id
    {where_sql}
    ON CONFLICT(article_id) DO UPDATE SET
    {", ".join(f"{col}=excluded.{col}" for col in ARTICLE_LISTING_COLUMNS[1:])}
    """


async def refresh_article_listing_for_articles(
    db: DatabaseClient, article_ids: list[int]
) -> None:
    """
    Refresh listing rows for the provided article ids.

    Args:
        db: Database client.
        article_ids: Article id list to refresh.

    Returns:
        None.
    """
    if not article_ids:
        return
    for batch in chunked(article_ids, ARTICLE_LISTING_BATCH_SIZE):
        placeholders = ", ".join(["?"] * len(batch))
        sql = build_article_listing_upsert(f"WHERE a.article_id IN ({placeholders})")
        await db.execute(sql, tuple(batch))


async def refresh_article_listing_for_issues(
    db: DatabaseClient, issue_ids: list[int]
) -> None:
    """
    Refresh listing rows for the provided issue ids.

    Args:
        db: Database client.
        issue_ids: Issue id list to refresh.

    Returns:
        None.
    """
    if not issue_ids:
        return
    for batch in chunked(issue_ids, ARTICLE_LISTING_BATCH_SIZE):
        placeholders = ", ".join(["?"] * len(batch))
        sql = build_article_listing_upsert(f"WHERE a.issue_id IN ({placeholders})")
        await db.execute(sql, tuple(batch))


async def get_issue_ids_with_articles(
    db: DatabaseClient, journal_id: int, year: int
) -> set[int]:
    """
    Fetch issue IDs that already have articles for a journal year.

    Args:
        db: Database client.
        journal_id: BrowZine journal ID.
        year: Publication year.

    Returns:
        Set of issue IDs with existing articles.
    """
    rows = await db.fetchall(
        """
        SELECT DISTINCT a.issue_id
        FROM articles a
        JOIN issues i ON i.issue_id = a.issue_id
        WHERE i.journal_id = ? AND i.publication_year = ?
        """,
        (journal_id, year),
    )
    return {row[0] for row in rows if row[0] is not None}


async def get_completed_years(db: DatabaseClient, journal_id: int) -> set[int]:
    """
    Fetch completed years for a journal.

    Args:
        db: Database client.
        journal_id: BrowZine journal ID.

    Returns:
        Set of completed years.
    """
    rows = await db.fetchall(
        "SELECT year FROM journal_year_state WHERE journal_id = ? AND status = 'done'",
        (journal_id,),
    )
    return {row[0] for row in rows}


async def is_journal_complete(db: DatabaseClient, journal_id: int) -> bool:
    """
    Check whether a journal is marked as completed.

    Args:
        db: Database client.
        journal_id: BrowZine journal ID.

    Returns:
        True when the journal is completed.
    """
    row = await db.fetchone(
        "SELECT status FROM journal_state WHERE journal_id = ?",
        (journal_id,),
    )
    return row is not None and row[0] == "done"


async def mark_year_done(db: DatabaseClient, journal_id: int, year: int) -> None:
    """
    Mark a year as completed for a journal.

    Args:
        db: Database client.
        journal_id: BrowZine journal ID.
        year: Publication year.

    Returns:
        None.
    """
    timestamp = datetime.utcnow().isoformat()
    await db.execute(
        """
        INSERT INTO journal_year_state (journal_id, year, status, updated_at)
        VALUES (?, ?, 'done', ?)
        ON CONFLICT(journal_id, year) DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (journal_id, year, timestamp),
    )


async def mark_journal_done(db: DatabaseClient, journal_id: int) -> None:
    """
    Mark a journal as completed.

    Args:
        db: Database client.
        journal_id: BrowZine journal ID.

    Returns:
        None.
    """
    timestamp = datetime.utcnow().isoformat()
    await db.execute(
        """
        INSERT INTO journal_state (journal_id, status, updated_at)
        VALUES (?, 'done', ?)
        ON CONFLICT(journal_id) DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (journal_id, timestamp),
    )


async def mark_listing_ready(db: aiosqlite.Connection) -> None:
    """
    Mark the article listing as ready for query use.

    Args:
        db: Database client.

    Returns:
        None.
    """
    timestamp = datetime.utcnow().isoformat()
    await execute_with_retry(
        db,
        """
        INSERT INTO listing_state (id, status, updated_at)
        VALUES (1, 'ready', ?)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (timestamp,),
    )
    await commit_with_retry(db)


async def fetch_issue_articles(
    semaphore: asyncio.Semaphore,
    client: BrowZineAPIClient,
    issue_id: int,
    library_id: str,
) -> tuple[int, list[dict[str, Any]] | None]:
    """
    Fetch articles for a single issue with concurrency control.

    Args:
        semaphore: Semaphore for limiting concurrent requests.
        client: BrowZine API client.
        issue_id: BrowZine issue ID.
        library_id: Library ID for the request.

    Returns:
        Tuple of issue ID and article list or None.
    """
    async with semaphore:
        articles = await client.get_articles_from_issue(issue_id, library_id)
    return issue_id, articles


async def process_journal(
    db: DatabaseClient,
    client: BrowZineAPIClient,
    csv_path: Path,
    row: dict[str, str],
    issue_batch_size: int,
    request_workers: int,
    show_year_progress: bool,
    resume: bool,
    update: bool,
) -> None:
    """
    Export a single journal to the database.

    Args:
        db: Database client.
        client: BrowZine API client.
        csv_path: Source CSV path.
        row: CSV row for the journal.
        issue_batch_size: Number of issues per fetch batch.
        request_workers: Maximum concurrent HTTP requests.
        show_year_progress: Whether to display year progress with tqdm.
        resume: Whether to resume from completed years and journals.
        update: Whether to perform incremental updates for existing years.

    Returns:
        None.
    """
    journal_id = to_int(row.get("id"))
    if not journal_id:
        print(f"  - Skipping journal with missing id: {row.get('title')}")
        return

    library_id = row.get("library") or DEFAULT_LIBRARY_ID

    journal_info = await client.get_journal_info(journal_id, library_id)

    journal_record = build_journal_record(journal_id, library_id, row, journal_info)
    meta_record = build_meta_record(journal_id, csv_path, row)
    journal_title = journal_record.get("title") or row.get("title") or ""

    await upsert_journal(db, journal_record)
    await upsert_meta(db, meta_record)
    await db.commit()

    years = await client.get_publication_years(journal_id, library_id)
    if not years:
        print(f"  - No publication years for journal {journal_id}")
        return

    if resume and not update and await is_journal_complete(db, journal_id):
        return

    completed_years: set[int] = set()
    if resume and not update:
        completed_years = await get_completed_years(db, journal_id)

    seen_issue_ids: set[int] = set()
    if update:
        years_to_process = years
    else:
        years_to_process = [year for year in years if year not in completed_years]
    total_years = len(years_to_process)
    progress = None
    if show_year_progress:
        progress = tqdm(
            total=total_years,
            desc=f"Journal {journal_id} years",
            unit="year",
        )

    semaphore = asyncio.Semaphore(max(1, request_workers))
    for index, year in enumerate(years_to_process, start=1):
        if progress:
            progress.set_postfix_str(f"{year} ({index}/{total_years})")
        issues = await client.get_issues_by_year(journal_id, library_id, year)
        if not issues:
            if progress:
                progress.update(1)
            continue

        issue_records: list[dict[str, Any]] = []
        issue_ids: list[int] = []
        for issue in issues:
            record = build_issue_record(issue, journal_id, year)
            if record:
                issue_id = record["issue_id"]
                if issue_id in seen_issue_ids:
                    continue
                seen_issue_ids.add(issue_id)
                issue_records.append(record)
                issue_ids.append(issue_id)

        if issue_records:
            await upsert_issues(db, issue_records)
        if update and issue_ids:
            await refresh_article_listing_for_issues(db, issue_ids)

        issue_ids_to_fetch = issue_ids
        if update and issue_ids:
            existing_issue_ids = await get_issue_ids_with_articles(db, journal_id, year)
            issue_ids_to_fetch = [
                issue_id for issue_id in issue_ids if issue_id not in existing_issue_ids
            ]

        if issue_ids_to_fetch:
            for batch in chunked(issue_ids_to_fetch, issue_batch_size):
                tasks = [
                    asyncio.create_task(
                        fetch_issue_articles(semaphore, client, issue_id, library_id)
                    )
                    for issue_id in batch
                ]
                batch_records: list[dict[str, Any]] = []
                for completed in asyncio.as_completed(tasks):
                    try:
                        issue_id, articles = await completed
                    except Exception:
                        print("  - Failed to fetch articles for an issue batch")
                        continue
                    if not articles:
                        continue
                    for article in articles:
                        record = build_article_record(article, journal_id, issue_id)
                        if record:
                            batch_records.append(record)
                if batch_records:
                    await upsert_articles(db, batch_records)
                    await upsert_article_search(db, batch_records, journal_title)
                    batch_article_ids = list(
                        {record["article_id"] for record in batch_records}
                    )
                    await refresh_article_listing_for_articles(db, batch_article_ids)

        if progress:
            progress.update(1)
        await mark_year_done(db, journal_id, year)
        await db.commit()

    if progress:
        progress.close()

    in_press = await client.get_articles_in_press(journal_id, library_id)
    if in_press:
        in_press_records = []
        for article in in_press:
            record = build_article_record(article, journal_id, None)
            if record:
                in_press_records.append(record)
        await upsert_articles(db, in_press_records)
        await upsert_article_search(db, in_press_records, journal_title)
        in_press_article_ids = list(
            {record["article_id"] for record in in_press_records}
        )
        await refresh_article_listing_for_articles(db, in_press_article_ids)
        await db.commit()

    await mark_journal_done(db, journal_id)
    await db.commit()


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


async def writer_main(
    db_path: str, request_queue: Any, response_queues: list[Any]
) -> None:
    """
    Run the single-writer database process loop.

    Args:
        db_path: SQLite database path.
        request_queue: Multiprocessing request queue.

    Returns:
        None.
    """
    async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT_SECONDS) as db:
        await init_db(db)
        while True:
            message = await asyncio.to_thread(request_queue.get)
            if message is None:
                continue
            if message.get("type") == "stop":
                break
            worker_id = message.get("worker_id")
            if worker_id is None or not isinstance(worker_id, int):
                continue
            if worker_id < 0 or worker_id >= len(response_queues):
                continue
            response_queue = response_queues[worker_id]
            request_id = message.get("id")
            try:
                message_type = message.get("type")
                payload = message.get("payload") or {}
                result: Any = None
                if message_type == "execute":
                    sql = payload.get("sql")
                    if not sql:
                        raise RuntimeError("Missing SQL for execute request")
                    await execute_with_retry(db, sql, payload.get("params"))
                elif message_type == "executemany":
                    sql = payload.get("sql")
                    if not sql:
                        raise RuntimeError("Missing SQL for executemany request")
                    await executemany_with_retry(db, sql, payload.get("rows", []))
                elif message_type == "commit":
                    await commit_with_retry(db)
                elif message_type == "fetchall":
                    cursor = await db.execute(
                        payload.get("sql"), payload.get("params") or ()
                    )
                    result = await cursor.fetchall()
                    await cursor.close()
                elif message_type == "fetchone":
                    cursor = await db.execute(
                        payload.get("sql"), payload.get("params") or ()
                    )
                    result = await cursor.fetchone()
                    await cursor.close()
                else:
                    raise RuntimeError(f"Unknown IPC request type: {message_type}")
                await asyncio.to_thread(
                    response_queue.put,
                    {"id": request_id, "ok": True, "result": result},
                )
            except Exception as exc:
                await asyncio.to_thread(
                    response_queue.put,
                    {"id": request_id, "ok": False, "error": str(exc)},
                )


def writer_process(
    db_path: str, request_queue: Any, response_queues: list[Any]
) -> None:
    """
    Entry point for the writer process.

    Args:
        db_path: SQLite database path.
        request_queue: Multiprocessing request queue.

    Returns:
        None.
    """
    asyncio.run(writer_main(db_path, request_queue, response_queues))


def process_journal_worker_ipc(
    worker_id: int,
    request_queue: Any,
    response_queue: Any,
    csv_path: str,
    row: dict[str, str],
    issue_batch_size: int,
    thread_workers: int,
    timeout: int,
    show_year_progress: bool,
    resume: bool,
    update: bool,
) -> tuple[str, str]:
    """
    Run journal processing in a worker process with IPC database access.

    Args:
        worker_id: Worker identifier for response routing.
        request_queue: Multiprocessing request queue.
        response_queue: Multiprocessing response queue.
        csv_path: Source CSV path.
        row: CSV row for the journal.
        issue_batch_size: Number of issues per fetch batch.
        thread_workers: Maximum concurrent HTTP requests.
        timeout: HTTP request timeout in seconds.
        show_year_progress: Whether to display year progress with tqdm.
        resume: Whether to resume from completed years and journals.
        update: Whether to perform incremental updates for existing years.

    Returns:
        Tuple of journal ID and journal title.
    """

    async def run_worker() -> None:
        client = BrowZineAPIClient(library_id=DEFAULT_LIBRARY_ID, timeout=timeout)
        db_client = IPCDatabaseClient(request_queue, response_queue, worker_id)
        try:
            await process_journal(
                db_client,
                client,
                Path(csv_path),
                row,
                issue_batch_size,
                thread_workers,
                show_year_progress,
                resume,
                update,
            )
        finally:
            await client.aclose()

    asyncio.run(run_worker())
    journal_id = row.get("id") or ""
    title = row.get("title") or ""
    return journal_id, title


def run_worker_batch(
    worker_id: int,
    request_queue: Any,
    response_queue: Any,
    status_queue: Any,
    csv_path: str,
    rows: list[dict[str, str]],
    issue_batch_size: int,
    request_workers: int,
    timeout: int,
    resume: bool,
    update: bool,
) -> None:
    """
    Run a batch of journal rows in a worker process.

    Args:
        worker_id: Worker identifier for response routing.
        request_queue: Multiprocessing request queue.
        response_queue: Multiprocessing response queue.
        status_queue: Multiprocessing status queue.
        csv_path: Source CSV path.
        rows: CSV rows for this worker.
        issue_batch_size: Number of issues per fetch batch.
        request_workers: Maximum concurrent HTTP requests.
        timeout: HTTP request timeout in seconds.
        resume: Whether to resume from completed years and journals.
        update: Whether to perform incremental updates for existing years.

    Returns:
        None.
    """

    async def run_batch() -> None:
        client = BrowZineAPIClient(library_id=DEFAULT_LIBRARY_ID, timeout=timeout)
        db_client = IPCDatabaseClient(request_queue, response_queue, worker_id)
        try:
            for row in rows:
                try:
                    await process_journal(
                        db_client,
                        client,
                        Path(csv_path),
                        row,
                        issue_batch_size,
                        request_workers,
                        False,
                        resume,
                        update,
                    )
                    status_queue.put(
                        {
                            "ok": True,
                            "journal_id": row.get("id"),
                            "title": row.get("title"),
                        }
                    )
                except Exception as exc:
                    status_queue.put(
                        {
                            "ok": False,
                            "journal_id": row.get("id"),
                            "title": row.get("title"),
                            "error": str(exc),
                        }
                    )
        finally:
            await client.aclose()

    asyncio.run(run_batch())


async def export_csv(
    csv_path: Path,
    db_path: Path,
    issue_batch_size: int,
    thread_workers: int,
    processes: int,
    timeout: int,
    resume: bool,
    update: bool,
) -> None:
    """
    Export a CSV file to a SQLite database.

    Args:
        csv_path: Path to the CSV file.
        db_path: Output SQLite database path.
        issue_batch_size: Number of issues per fetch batch.
        thread_workers: Maximum concurrent HTTP requests.
        processes: Process workers for journal-level parallelism.
        timeout: HTTP request timeout in seconds.
        resume: Whether to resume from completed years and journals.
        update: Whether to perform incremental updates for existing years.

    Returns:
        None.
    """
    rows = load_csv_rows(csv_path)
    if not rows:
        print(f"Skipping empty CSV: {csv_path.name}")
        return

    print(f"\nProcessing {csv_path.name} -> {db_path.name}")

    if processes <= 1:
        client = BrowZineAPIClient(library_id=DEFAULT_LIBRARY_ID, timeout=timeout)
        async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT_SECONDS) as db:
            await init_db(db)
            local_db = LocalDatabaseClient(db)
            await local_db.start()
            try:
                for index, row in enumerate(rows, start=1):
                    title = row.get("title", "Unknown")
                    print(f"  [{index}/{len(rows)}] Exporting {title}")
                    await process_journal(
                        local_db,
                        client,
                        csv_path,
                        row,
                        issue_batch_size,
                        thread_workers,
                        True,
                        resume,
                        update,
                    )
            finally:
                await local_db.close()
                await optimize_db(db)
                if not update:
                    await mark_listing_ready(db)
                await client.aclose()
        return

    ctx = mp.get_context()
    request_queue = ctx.Queue()
    response_queues = [ctx.Queue() for _ in range(processes)]
    status_queue = ctx.Queue()
    writer = ctx.Process(
        target=writer_process, args=(str(db_path), request_queue, response_queues)
    )
    writer.start()

    workers: list[mp.Process] = []
    for worker_id in range(processes):
        worker_rows = rows[worker_id::processes]
        if not worker_rows:
            continue
        worker = ctx.Process(
            target=run_worker_batch,
            args=(
                worker_id,
                request_queue,
                response_queues[worker_id],
                status_queue,
                str(csv_path),
                worker_rows,
                issue_batch_size,
                thread_workers,
                timeout,
                resume,
                update,
            ),
        )
        worker.start()
        workers.append(worker)

    completed = 0
    total = len(rows)
    try:
        while completed < total:
            message = await asyncio.to_thread(status_queue.get)
            if message is None:
                continue
            completed += 1
            if message.get("ok"):
                title = message.get("title") or message.get("journal_id") or "Unknown"
                print(f"  Finished {title}")
            else:
                title = message.get("title") or message.get("journal_id") or "Unknown"
                error = message.get("error") or "Unknown error"
                print(f"  - Journal worker failed: {title} ({error})")
    finally:
        request_queue.put({"type": "stop"})
        writer.join()
        for worker in workers:
            worker.join()

    async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT_SECONDS) as db:
        await optimize_db(db)
        if not update:
            await mark_listing_ready(db)


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

    print("=" * 60)
    print("BrowZine Article Indexer")
    print("=" * 60)
    print(f"Found {len(csv_paths)} CSV file(s)")
    print(f"Request workers: {args.workers}")
    print(f"Process workers: {args.processes}")
    print(f"Issue batch size: {issue_batch_size}")

    for csv_path in csv_paths:
        db_path = index_dir / f"{csv_path.stem}.sqlite"
        await export_csv(
            csv_path,
            db_path,
            issue_batch_size,
            args.workers,
            args.processes,
            args.timeout,
            args.resume,
            args.update,
        )

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
        help="Maximum concurrent HTTP requests",
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
        "--processes",
        type=int,
        default=1,
        help="Process workers for journal-level parallelism",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from completed years and journals",
    )
    parser.add_argument(
        "--update",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Incrementally update existing years and journals",
    )
    args = parser.parse_args()

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
