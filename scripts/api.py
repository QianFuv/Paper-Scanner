"""
FastAPI backend for querying BrowZine article index databases.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import aiosqlite
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from scripts.utility.weipu_api import WeipuAPISelectolax, normalize_years

PROJECT_ROOT = Path(__file__).parent.parent
INDEX_DIR = PROJECT_ROOT / "data" / "index"
MAX_LIMIT = 200
SIMPLE_TOKENIZER_ENV = "SIMPLE_TOKENIZER_PATH"
WEIPU_LIBRARY_ID = "-1"


class JournalRecord(BaseModel):
    """
    Journal record with optional CSV metadata.
    """

    journal_id: int
    library_id: str
    title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    scimago_rank: float | None = None
    cover_url: str | None = None
    available: int | None = None
    toc_data_approved_and_live: int | None = None
    has_articles: int | None = None
    source_csv: str | None = None
    area: str | None = None
    csv_title: str | None = None
    csv_issn: str | None = None
    csv_library: str | None = None


class IssueRecord(BaseModel):
    """
    Issue record.
    """

    issue_id: int
    journal_id: int
    publication_year: int | None = None
    title: str | None = None
    volume: str | None = None
    number: str | None = None
    date: str | None = None
    is_valid_issue: int | None = None
    suppressed: int | None = None
    embargoed: int | None = None
    within_subscription: int | None = None


class ArticleRecord(BaseModel):
    """
    Article record.
    """

    article_id: int
    journal_id: int
    issue_id: int | None = None
    sync_id: int | None = None
    title: str | None = None
    date: str | None = None
    authors: str | None = None
    start_page: str | None = None
    end_page: str | None = None
    abstract: str | None = None
    doi: str | None = None
    pmid: str | None = None
    ill_url: str | None = None
    link_resolver_openurl_link: str | None = None
    email_article_request_link: str | None = None
    permalink: str | None = None
    suppressed: int | None = None
    in_press: int | None = None
    open_access: int | None = None
    platform_id: str | None = None
    retraction_doi: str | None = None
    retraction_date: str | None = None
    retraction_related_urls: str | None = None
    unpaywall_data_suppressed: int | None = None
    expression_of_concern_doi: str | None = None
    within_library_holdings: int | None = None
    noodletools_export_link: str | None = None
    avoid_unpaywall_publisher_links: int | None = None
    browzine_web_in_context_link: str | None = None
    content_location: str | None = None
    libkey_content_location: str | None = None
    full_text_file: str | None = None
    libkey_full_text_file: str | None = None
    nomad_fallback_url: str | None = None
    journal_title: str | None = None
    volume: str | None = None
    number: str | None = None


class PageMeta(BaseModel):
    """
    Pagination metadata.
    """

    total: int | None
    limit: int
    offset: int
    next_cursor: str | None = None
    has_more: bool | None = None


class JournalPage(BaseModel):
    """
    Paginated journals response.
    """

    items: list[JournalRecord]
    page: PageMeta


class IssuePage(BaseModel):
    """
    Paginated issues response.
    """

    items: list[IssueRecord]
    page: PageMeta


class ArticlePage(BaseModel):
    """
    Paginated articles response.
    """

    items: list[ArticleRecord]
    page: PageMeta


class ValueCount(BaseModel):
    """
    Label and count tuple.
    """

    value: str
    count: int


class YearSummary(BaseModel):
    """
    Publication year summary.
    """

    year: int
    issue_count: int
    journal_count: int


@dataclass(frozen=True)
class SortSpec:
    """
    Sort specification entry.
    """

    column: str
    direction: str


app = FastAPI(title="Paper Scanner API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CacheControlMiddleware(BaseHTTPMiddleware):
    """
    Add cache control headers to API responses.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        is_articles = request.url.path.startswith("/articles")
        is_meta = request.url.path.startswith("/meta")
        if is_articles or is_meta:
            response.headers["Cache-Control"] = (
                "public, max-age=300, stale-while-revalidate=600"
            )
        return response


app.add_middleware(CacheControlMiddleware)


def resolve_db_path(db_name: str | None) -> Path:
    """
    Resolve the database path from a name or use the sole database when available.

    Args:
        db_name: Database name or filename under data/index.

    Returns:
        Path to the SQLite database.
    """
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    if db_name:
        candidate = Path(db_name).name
        if not candidate.endswith(".sqlite"):
            candidate = f"{candidate}.sqlite"
        db_path = INDEX_DIR / candidate
        if not db_path.exists():
            raise HTTPException(status_code=404, detail="Database not found")
        return db_path

    sqlite_files = sorted(INDEX_DIR.glob("*.sqlite"))
    if len(sqlite_files) == 1:
        return sqlite_files[0]
    if not sqlite_files:
        raise HTTPException(status_code=404, detail="No SQLite databases found")
    raise HTTPException(
        status_code=400, detail="Multiple databases found, specify ?db=<name>"
    )


def parse_sort(sort: str | None, allowed: dict[str, str]) -> list[SortSpec]:
    """
    Parse a multi-column sort string into SQL-safe specs.

    Args:
        sort: Comma-separated sort string.
        allowed: Mapping of public fields to SQL columns.

    Returns:
        List of sort specifications.
    """
    if not sort:
        return []
    specs: list[SortSpec] = []
    for raw_part in sort.split(","):
        part = raw_part.strip()
        if not part:
            continue
        direction = "ASC"
        field = part
        if part.startswith("-"):
            field = part[1:]
            direction = "DESC"
        elif ":" in part:
            field, raw_dir = part.split(":", 1)
            direction = "DESC" if raw_dir.strip().lower() == "desc" else "ASC"
        field = field.strip()
        column = allowed.get(field)
        if not column:
            raise HTTPException(
                status_code=400, detail=f"Unsupported sort field: {field}"
            )
        specs.append(SortSpec(column=column, direction=direction))
    return specs


def apply_sort(specs: list[SortSpec]) -> str:
    """
    Convert sort specs into an ORDER BY clause.

    Args:
        specs: List of sort specifications.

    Returns:
        ORDER BY clause or empty string.
    """
    if not specs:
        return ""
    parts = [f"{spec.column} {spec.direction}" for spec in specs]
    return f" ORDER BY {', '.join(parts)}"


def build_page_meta(
    total: int | None,
    limit: int,
    offset: int,
    next_cursor: str | None = None,
    has_more: bool | None = None,
) -> PageMeta:
    """
    Build pagination metadata.

    Args:
        total: Total rows.
        limit: Page size.
        offset: Page offset.
        next_cursor: Cursor for keyset pagination.
        has_more: Whether more rows are available.

    Returns:
        Page metadata.
    """
    return PageMeta(
        total=total,
        limit=limit,
        offset=offset,
        next_cursor=next_cursor,
        has_more=has_more,
    )


def parse_article_cursor(cursor: str) -> tuple[str, int]:
    """
    Parse a cursor string for keyset pagination.

    Args:
        cursor: Cursor string in "{date}|{article_id}" format.

    Returns:
        Tuple of date string and article id.
    """
    parts = cursor.split("|", 1)
    if len(parts) != 2 or not parts[0]:
        raise HTTPException(status_code=400, detail="Invalid cursor")
    try:
        article_id = int(parts[1])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc
    return parts[0], article_id


def build_article_cursor(date_value: str | None, article_id: int) -> str | None:
    """
    Build a cursor string from an article row.

    Args:
        date_value: Article date value.
        article_id: Article identifier.

    Returns:
        Cursor string or None when date is missing.
    """
    if not date_value:
        return None
    return f"{date_value}|{article_id}"


async def get_db(
    db: str | None = Query(
        default=None, description="Database name or filename under data/index"
    ),
) -> aiosqlite.Connection:
    """
    Provide a SQLite connection for a request.

    Args:
        db: Database name or filename under data/index.

    Returns:
        Open aiosqlite connection.
    """
    db_path = resolve_db_path(db)
    connection = await aiosqlite.connect(db_path)
    connection.row_factory = sqlite3.Row
    await load_simple_tokenizer(connection)
    return connection


async def get_db_dependency(
    connection: Annotated[aiosqlite.Connection, Depends(get_db)],
) -> AsyncGenerator[aiosqlite.Connection]:
    """
    FastAPI dependency that ensures connection cleanup.

    Args:
        connection: Open database connection.

    Returns:
        Open database connection.
    """
    try:
        yield connection
    finally:
        await connection.close()


async def fetch_all(
    db: aiosqlite.Connection, query: str, params: list[Any]
) -> list[dict[str, Any]]:
    """
    Fetch all rows and return dictionaries.

    Args:
        db: Database connection.
        query: SQL query.
        params: Query parameters.

    Returns:
        List of row dictionaries.
    """
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    await cursor.close()
    return [dict(row) for row in rows]


async def fetch_one(
    db: aiosqlite.Connection, query: str, params: list[Any]
) -> dict[str, Any] | None:
    """
    Fetch a single row and return a dictionary.

    Args:
        db: Database connection.
        query: SQL query.
        params: Query parameters.

    Returns:
        Row dictionary or None.
    """
    cursor = await db.execute(query, params)
    row = await cursor.fetchone()
    await cursor.close()
    return dict(row) if row else None


def resolve_simple_tokenizer_path() -> str | None:
    """
    Resolve the configured simple tokenizer extension path.

    Returns:
        Filesystem path or None when unset.
    """
    value = os.getenv(SIMPLE_TOKENIZER_ENV)
    if value:
        path = value.strip()
        return path or None
    libs_dir = PROJECT_ROOT / "libs"
    if sys.platform.startswith("win"):
        candidate = libs_dir / "simple-windows" / "libsimple-windows-x64" / "simple.dll"
    elif sys.platform.startswith("linux"):
        candidate = (
            libs_dir / "simple-linux" / "libsimple-linux-ubuntu-latest" / "libsimple.so"
        )
    else:
        return None
    return str(candidate) if candidate.exists() else None


async def load_simple_tokenizer(db: aiosqlite.Connection) -> bool:
    """
    Load the simple tokenizer extension for the current connection.

    Args:
        db: Open aiosqlite connection.

    Returns:
        True when the extension is loaded.
    """
    path = resolve_simple_tokenizer_path()
    if not path:
        return False
    try:
        await db.enable_load_extension(True)
        await db.load_extension(path)
        await db.enable_load_extension(False)
    except (sqlite3.OperationalError, OSError):
        return False
    return True


def article_search_uses_simple(sql: str | None) -> bool:
    """
    Determine whether the article_search table uses the simple tokenizer.

    Args:
        sql: SQLite schema SQL for article_search.

    Returns:
        True when the schema references the simple tokenizer.
    """
    if not sql:
        return False
    normalized = sql.lower()
    return "tokenize" in normalized and "simple" in normalized


async def fetch_article_search_sql(db: aiosqlite.Connection) -> str | None:
    """
    Fetch the schema SQL for the article_search table.

    Args:
        db: Database connection.

    Returns:
        Table SQL or None when missing.
    """
    row = await fetch_one(
        db, "SELECT sql FROM sqlite_master WHERE name = 'article_search'", []
    )
    if row and row.get("sql"):
        return str(row["sql"])
    return None


async def is_simple_search_enabled(db: aiosqlite.Connection) -> bool:
    """
    Check whether article_search was built with the simple tokenizer.

    Args:
        db: Database connection.

    Returns:
        True when simple tokenizer is enabled for article_search.
    """
    sql = await fetch_article_search_sql(db)
    return article_search_uses_simple(sql)


def contains_cjk(value: str) -> bool:
    """
    Check whether a string contains CJK characters.

    Args:
        value: Input string.

    Returns:
        True when the string contains CJK characters.
    """
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def should_use_simple_query(q: str | None, simple_enabled: bool) -> bool:
    """
    Decide whether to wrap the search query with simple_query().

    Args:
        q: Raw search query.
        simple_enabled: Whether the simple tokenizer is enabled.

    Returns:
        True when simple_query() should be used.
    """
    if not simple_enabled or not q:
        return False
    return not contains_cjk(q)


def normalize_issue_number(value: str | None) -> str | None:
    """
    Normalize an issue number for matching.

    Args:
        value: Raw issue number value.

    Returns:
        Normalized issue number or None.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    digits = re.findall(r"\d+", text)
    if digits:
        normalized = digits[-1].lstrip("0") or digits[-1]
        prefix = re.sub(r"\d+", "", text)
        prefix = prefix.strip()
        if prefix:
            return f"{prefix}{normalized}"
        return normalized
    return text


def normalize_title(value: str | None) -> str:
    """
    Normalize a title string for comparison.

    Args:
        value: Raw title value.

    Returns:
        Normalized title string.
    """
    if value is None:
        return ""
    text = str(value).strip().lower()
    if not text:
        return ""
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


async def resolve_weipu_detail_url(
    journal_title: str | None,
    issn: str | None,
    publication_year: int | None,
    issue_number: str | None,
    platform_id: str | None,
    article_title: str | None,
) -> str | None:
    """
    Resolve a signed WeiPu detail URL for an article.

    Args:
        journal_title: Journal title.
        issn: Journal ISSN.
        publication_year: Publication year if available.
        issue_number: Issue number or label.
        platform_id: WeiPu article identifier.
        article_title: Article title for fallback matching.

    Returns:
        Signed detail URL or None.
    """
    if not platform_id and not article_title:
        return None
    client = WeipuAPISelectolax()
    try:
        journal = None
        if issn:
            journal = await client.search_journal_by_issn(issn)
        if not journal and journal_title:
            journal = await client.search_journal_by_title(journal_title)
        journal_id = journal.get("journalId") if journal else None
        if not journal_id:
            return None
        payload = await client.fetch_nuxt_payload(
            f"https://www.cqvip.com/journal/{journal_id}/{journal_id}"
        )
        years: list[dict[str, Any]] = normalize_years(payload) if payload else []
        if not years:
            details = await client.get_journal_details(str(journal_id))
            details_years = details.get("years") if details else None
            if isinstance(details_years, list):
                years = [entry for entry in details_years if isinstance(entry, dict)]
        if not years:
            return None
        issue_number_norm = normalize_issue_number(issue_number)
        issue_candidates: list[dict[str, str]] = []
        for year_entry in years:
            year_value = year_entry.get("year")
            if publication_year and year_value != publication_year:
                continue
            issues = year_entry.get("issues") or []
            if issue_number_norm:
                for issue in issues:
                    name_norm = normalize_issue_number(issue.get("name"))
                    if name_norm == issue_number_norm:
                        issue_candidates.append(issue)
            else:
                issue_candidates.extend(issues)
        if not issue_candidates:
            for year_entry in years:
                issues = year_entry.get("issues") or []
                if issues:
                    issue_candidates.extend(issues)
                    break
        seen_ids: set[str] = set()
        issue_ids: list[str] = []
        for issue in issue_candidates:
            issue_id = issue.get("id")
            if issue_id is None:
                continue
            issue_key = str(issue_id)
            if issue_key in seen_ids:
                continue
            seen_ids.add(issue_key)
            issue_ids.append(issue_key)
            if len(issue_ids) >= 12:
                break
        title_norm = normalize_title(article_title)
        for issue_id in issue_ids:
            url = f"https://www.cqvip.com/journal/{journal_id}/{issue_id}"
            html_text = await client.fetch_html(url)
            if html_text:
                doc_links = client.extract_doc_links(html_text)
                if platform_id and doc_links:
                    detail_url = doc_links.get(str(platform_id))
                    if detail_url:
                        return str(detail_url)
            if not title_norm:
                continue
            payload = await client.get_issue_articles(
                str(journal_id),
                issue_id,
                enrich=False,
            )
            articles = payload.get("articles") if payload else None
            if not articles:
                continue
            for article in articles:
                if normalize_title(article.get("title")) == title_norm:
                    detail_url = article.get("detailUrl")
                    if detail_url:
                        return str(detail_url)
    finally:
        await client.aclose()
    return None


JOURNAL_SORT_FIELDS = {
    "journal_id": "j.journal_id",
    "title": "j.title",
    "issn": "j.issn",
    "eissn": "j.eissn",
    "scimago_rank": "j.scimago_rank",
    "available": "j.available",
    "has_articles": "j.has_articles",
}

ISSUE_SORT_FIELDS = {
    "issue_id": "i.issue_id",
    "publication_year": "i.publication_year",
    "title": "i.title",
    "date": "i.date",
    "volume": "i.volume",
    "number": "i.number",
}

ARTICLE_SORT_FIELDS = {
    "date": "l.date",
}


@app.get("/health")
async def health() -> dict[str, str]:
    """
    Health check endpoint.

    Returns:
        Health status payload.
    """
    return {"status": "ok"}


@app.get("/meta/databases", response_model=list[str])
async def list_databases() -> list[str]:
    """
    List available SQLite databases.

    Returns:
        List of database filenames.
    """
    if not INDEX_DIR.exists():
        return []
    return [f.name for f in sorted(INDEX_DIR.glob("*.sqlite"))]


@app.get("/meta/areas", response_model=list[ValueCount])
async def list_areas(
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
) -> list[ValueCount]:
    """
    List distinct journal areas.

    Args:
        db: Database connection.

    Returns:
        Area values with counts.
    """
    rows = await fetch_all(
        db,
        """
        SELECT area AS value, COUNT(*) AS count
        FROM journal_meta
        WHERE area IS NOT NULL AND area != ''
        GROUP BY area
        ORDER BY value ASC
        """,
        [],
    )
    return [ValueCount(**row) for row in rows]


@app.get("/meta/libraries", response_model=list[ValueCount])
async def list_libraries(
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
) -> list[ValueCount]:
    """
    List distinct library IDs from journal metadata.

    Args:
        db: Database connection.

    Returns:
        Library values with counts.
    """
    rows = await fetch_all(
        db,
        """
        SELECT csv_library AS value, COUNT(*) AS count
        FROM journal_meta
        WHERE csv_library IS NOT NULL AND csv_library != ''
        GROUP BY csv_library
        ORDER BY count DESC, value ASC
        """,
        [],
    )
    return [ValueCount(**row) for row in rows]


@app.get("/years", response_model=list[YearSummary])
async def list_years(
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
) -> list[YearSummary]:
    """
    List publication years with issue and journal counts.

    Args:
        db: Database connection.

    Returns:
        Year summary rows.
    """
    rows = await fetch_all(
        db,
        """
        SELECT
            CAST(strftime('%Y', date) AS INTEGER) AS year,
            COUNT(DISTINCT issue_id) AS issue_count,
            COUNT(DISTINCT journal_id) AS journal_count
        FROM issues
        WHERE date IS NOT NULL
        GROUP BY year
        ORDER BY year DESC
        """,
        [],
    )
    return [YearSummary(**row) for row in rows]


@app.get("/journals", response_model=JournalPage)
async def list_journals(
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
    area: str | None = Query(default=None),
    library_id: str | None = Query(default=None),
    available: bool | None = Query(default=None),
    has_articles: bool | None = Query(default=None),
    year: int | None = Query(default=None, ge=0),
    scimago_min: float | None = Query(default=None),
    scimago_max: float | None = Query(default=None),
    sort: str | None = Query(default="scimago_rank:desc"),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> JournalPage:
    """
    List journals with filtering and sorting.

    Args:
        area: Filter by CSV area.
        library_id: Filter by library_id from journals.
        available: Filter by availability flag.
        has_articles: Filter by has_articles flag.
        year: Filter journals with issues in a year.
        scimago_min: Minimum Scimago rank value.
        scimago_max: Maximum Scimago rank value.
        sort: Multi-column sort string.
        limit: Page size.
        offset: Page offset.
        db: Database connection.

    Returns:
        Paginated journal list.
    """
    where_clauses: list[str] = []
    params: list[Any] = []

    if area:
        where_clauses.append("m.area = ?")
        params.append(area)
    if library_id:
        where_clauses.append("j.library_id = ?")
        params.append(library_id)
    if available is not None:
        where_clauses.append("j.available = ?")
        params.append(1 if available else 0)
    if has_articles is not None:
        where_clauses.append("j.has_articles = ?")
        params.append(1 if has_articles else 0)
    if scimago_min is not None:
        where_clauses.append("j.scimago_rank >= ?")
        params.append(scimago_min)
    if scimago_max is not None:
        where_clauses.append("j.scimago_rank <= ?")
        params.append(scimago_max)
    if year is not None:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM issues i WHERE i.journal_id = j.journal_id AND "
            "i.publication_year = ?)"
        )
        params.append(year)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    order_sql = apply_sort(parse_sort(sort, JOURNAL_SORT_FIELDS))

    count_row = await fetch_one(
        db,
        f"""
        SELECT COUNT(*) AS total
        FROM journals j
        LEFT JOIN journal_meta m ON j.journal_id = m.journal_id
        {where_sql}
        """,
        params,
    )
    total = int(count_row["total"]) if count_row else 0

    rows = await fetch_all(
        db,
        f"""
        SELECT
            j.journal_id,
            j.library_id,
            j.title,
            j.issn,
            j.eissn,
            j.scimago_rank,
            j.cover_url,
            j.available,
            j.toc_data_approved_and_live,
            j.has_articles,
            m.source_csv,
            m.area,
            m.csv_title,
            m.csv_issn,
            m.csv_library
        FROM journals j
        LEFT JOIN journal_meta m ON j.journal_id = m.journal_id
        {where_sql}
        {order_sql}
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )

    return JournalPage(
        items=[JournalRecord(**row) for row in rows],
        page=build_page_meta(total, limit, offset),
    )


@app.get("/journals/{journal_id}", response_model=JournalRecord)
async def get_journal(
    journal_id: int,
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
) -> JournalRecord:
    """
    Fetch a single journal record.

    Args:
        journal_id: Journal identifier.
        db: Database connection.

    Returns:
        Journal record.
    """
    row = await fetch_one(
        db,
        """
        SELECT
            j.journal_id,
            j.library_id,
            j.title,
            j.issn,
            j.eissn,
            j.scimago_rank,
            j.cover_url,
            j.available,
            j.toc_data_approved_and_live,
            j.has_articles,
            m.source_csv,
            m.area,
            m.csv_title,
            m.csv_issn,
            m.csv_library
        FROM journals j
        LEFT JOIN journal_meta m ON j.journal_id = m.journal_id
        WHERE j.journal_id = ?
        """,
        [journal_id],
    )
    if not row:
        raise HTTPException(status_code=404, detail="Journal not found")
    return JournalRecord(**row)


@app.get("/issues", response_model=IssuePage)
async def list_issues(
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
    journal_id: int | None = Query(default=None, ge=0),
    year: int | None = Query(default=None, ge=0),
    is_valid_issue: bool | None = Query(default=None),
    suppressed: bool | None = Query(default=None),
    embargoed: bool | None = Query(default=None),
    within_subscription: bool | None = Query(default=None),
    sort: str | None = Query(default="publication_year:desc"),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> IssuePage:
    """
    List issues with filtering and sorting.

    Args:
        journal_id: Filter by journal ID.
        year: Filter by publication year.
        is_valid_issue: Filter by valid issue flag.
        suppressed: Filter by suppressed flag.
        embargoed: Filter by embargoed flag.
        within_subscription: Filter by within_subscription flag.
        sort: Multi-column sort string.
        limit: Page size.
        offset: Page offset.
        db: Database connection.

    Returns:
        Paginated issue list.
    """
    where_clauses: list[str] = []
    params: list[Any] = []

    if journal_id is not None:
        where_clauses.append("i.journal_id = ?")
        params.append(journal_id)
    if year is not None:
        where_clauses.append("i.publication_year = ?")
        params.append(year)
    if is_valid_issue is not None:
        where_clauses.append("i.is_valid_issue = ?")
        params.append(1 if is_valid_issue else 0)
    if suppressed is not None:
        where_clauses.append("i.suppressed = ?")
        params.append(1 if suppressed else 0)
    if embargoed is not None:
        where_clauses.append("i.embargoed = ?")
        params.append(1 if embargoed else 0)
    if within_subscription is not None:
        where_clauses.append("i.within_subscription = ?")
        params.append(1 if within_subscription else 0)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    order_sql = apply_sort(parse_sort(sort, ISSUE_SORT_FIELDS))

    count_row = await fetch_one(
        db,
        f"SELECT COUNT(*) AS total FROM issues i {where_sql}",
        params,
    )
    total = int(count_row["total"]) if count_row else 0

    rows = await fetch_all(
        db,
        f"""
        SELECT
            i.issue_id,
            i.journal_id,
            i.publication_year,
            i.title,
            i.volume,
            i.number,
            i.date,
            i.is_valid_issue,
            i.suppressed,
            i.embargoed,
            i.within_subscription
        FROM issues i
        {where_sql}
        {order_sql}
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )

    return IssuePage(
        items=[IssueRecord(**row) for row in rows],
        page=build_page_meta(total, limit, offset),
    )


@app.get("/issues/{issue_id}", response_model=IssueRecord)
async def get_issue(
    issue_id: int,
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
) -> IssueRecord:
    """
    Fetch a single issue record.

    Args:
        issue_id: Issue identifier.
        db: Database connection.

    Returns:
        Issue record.
    """
    row = await fetch_one(
        db,
        """
        SELECT
            issue_id,
            journal_id,
            publication_year,
            title,
            volume,
            number,
            date,
            is_valid_issue,
            suppressed,
            embargoed,
            within_subscription
        FROM issues
        WHERE issue_id = ?
        """,
        [issue_id],
    )
    if not row:
        raise HTTPException(status_code=404, detail="Issue not found")
    return IssueRecord(**row)


async def is_article_listing_ready(db: aiosqlite.Connection) -> bool:
    """
    Check whether the article listing table is available and populated.

    Args:
        db: Database connection.

    Returns:
        True when the listing table can be used safely.
    """
    try:
        state_row = await fetch_one(
            db, "SELECT status FROM listing_state WHERE id = 1", []
        )
    except aiosqlite.Error:
        return False
    if not state_row or state_row.get("status") != "ready":
        return False
    try:
        await fetch_one(db, "SELECT 1 FROM article_listing LIMIT 1", [])
    except aiosqlite.Error:
        return False
    return True


async def list_articles_from_listing(
    db: aiosqlite.Connection,
    journal_id: int | None,
    issue_id: int | None,
    year: int | None,
    area: list[str] | None,
    in_press: bool | None,
    open_access: bool | None,
    suppressed: bool | None,
    within_library_holdings: bool | None,
    date_from: str | None,
    date_to: str | None,
    doi: str | None,
    pmid: str | None,
    q: str | None,
    use_simple_query: bool,
    sort: str | None,
    limit: int,
    offset: int,
    cursor: str | None,
    include_total: bool,
) -> ArticlePage:
    """
    List articles using the materialized listing table.

    Args:
        db: Database connection.
        journal_id: Filter by journal ID.
        issue_id: Filter by issue ID.
        year: Filter by publication year from issues.
        area: Filter by journal area (multiple allowed).
        in_press: Filter by in_press flag.
        open_access: Filter by open_access flag.
        suppressed: Filter by suppressed flag.
        within_library_holdings: Filter by holdings flag.
        date_from: Minimum article date.
        date_to: Maximum article date.
        doi: Filter by DOI.
        pmid: Filter by PMID.
        q: Full-text search query for FTS5.
        use_simple_query: Whether to wrap queries with simple_query().
        sort: Sort string for articles.
        limit: Page size.
        offset: Page offset.
        cursor: Keyset cursor for pagination.
        include_total: Whether to compute total count.

    Returns:
        Paginated article list.
    """
    where_clauses: list[str] = []
    params: list[Any] = []

    if journal_id is not None:
        where_clauses.append("l.journal_id = ?")
        params.append(journal_id)
    if issue_id is not None:
        where_clauses.append("l.issue_id = ?")
        params.append(issue_id)
    if area:
        placeholders = ", ".join(["?"] * len(area))
        where_clauses.append(f"l.area IN ({placeholders})")
        params.extend(area)
    if in_press is not None:
        where_clauses.append("l.in_press = ?")
        params.append(1 if in_press else 0)
    if open_access is not None:
        where_clauses.append("l.open_access = ?")
        params.append(1 if open_access else 0)
    if suppressed is not None:
        where_clauses.append("l.suppressed = ?")
        params.append(1 if suppressed else 0)
    if within_library_holdings is not None:
        where_clauses.append("l.within_library_holdings = ?")
        params.append(1 if within_library_holdings else 0)
    if date_from:
        where_clauses.append("l.date >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("l.date <= ?")
        params.append(date_to)
    if doi:
        where_clauses.append("l.doi = ?")
        params.append(doi)
    if pmid:
        where_clauses.append("l.pmid = ?")
        params.append(pmid)
    if year is not None:
        where_clauses.append("l.publication_year = ?")
        params.append(year)
    if q and q.strip():
        matcher = "simple_query(?)" if use_simple_query else "?"
        fts_clause = (
            "l.article_id IN ("
            f"SELECT rowid FROM article_search WHERE article_search MATCH {matcher}"
            ")"
        )
        where_clauses.append(fts_clause)
        params.append(q.strip())

    sort_specs = parse_sort(sort, ARTICLE_SORT_FIELDS)
    supports_keyset = len(sort_specs) == 1 and sort_specs[0].column == "l.date"
    if not supports_keyset:
        raise HTTPException(
            status_code=400,
            detail="Articles only support sort=date:desc or date:asc",
        )
    direction = sort_specs[0].direction
    order_sql = f" ORDER BY l.date {direction}, l.article_id {direction}"

    if cursor:
        cursor_date, cursor_id = parse_article_cursor(cursor)
        operator = "<" if direction == "DESC" else ">"
        where_clauses.append(
            f"(l.date {operator} ? OR (l.date = ? AND l.article_id {operator} ?))"
        )
        params.extend([cursor_date, cursor_date, cursor_id])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    total = None
    if include_total:
        count_row = await fetch_one(
            db,
            f"""
            SELECT COUNT(*) AS total
            FROM article_listing l
            {where_sql}
            """,
            params,
        )
        total = int(count_row["total"]) if count_row else 0

    pagination_sql = "LIMIT ?"
    pagination_params: list[Any] = [limit]
    if cursor is None:
        pagination_sql = f"{pagination_sql} OFFSET ?"
        pagination_params.append(offset)

    id_rows = await fetch_all(
        db,
        f"""
        SELECT
            l.article_id,
            l.date
        FROM article_listing l INDEXED BY idx_article_listing_date_id
        {where_sql}
        {order_sql}
        {pagination_sql}
        """,
        params + pagination_params,
    )

    has_more = len(id_rows) == limit
    next_cursor = None
    if id_rows and has_more:
        last_row = id_rows[-1]
        next_cursor = build_article_cursor(
            last_row.get("date"),
            int(last_row["article_id"]),
        )
        if next_cursor is None:
            has_more = False

    article_ids = [int(row["article_id"]) for row in id_rows]
    if not article_ids:
        return ArticlePage(
            items=[],
            page=build_page_meta(
                total=total,
                limit=limit,
                offset=offset,
                next_cursor=next_cursor,
                has_more=has_more,
            ),
        )

    placeholders = ", ".join(["?"] * len(article_ids))
    rows = await fetch_all(
        db,
        f"""
        SELECT
            a.article_id,
            a.journal_id,
            a.issue_id,
            a.sync_id,
            a.title,
            a.date,
            a.authors,
            a.start_page,
            a.end_page,
            a.abstract,
            a.doi,
            a.pmid,
            a.ill_url,
            a.link_resolver_openurl_link,
            a.email_article_request_link,
            a.permalink,
            a.suppressed,
            a.in_press,
            a.open_access,
            a.platform_id,
            a.retraction_doi,
            a.retraction_date,
            a.retraction_related_urls,
            a.unpaywall_data_suppressed,
            a.expression_of_concern_doi,
            a.within_library_holdings,
            a.noodletools_export_link,
            a.avoid_unpaywall_publisher_links,
            a.browzine_web_in_context_link,
            a.content_location,
            a.libkey_content_location,
            a.full_text_file,
            a.libkey_full_text_file,
            a.nomad_fallback_url,
            j.title AS journal_title,
            i.volume,
            i.number
        FROM articles a
        LEFT JOIN issues i ON i.issue_id = a.issue_id
        JOIN journals j ON j.journal_id = a.journal_id
        WHERE a.article_id IN ({placeholders})
        """,
        article_ids,
    )

    row_map = {int(row["article_id"]): row for row in rows}
    ordered_rows = [
        row_map[article_id] for article_id in article_ids if article_id in row_map
    ]

    return ArticlePage(
        items=[ArticleRecord(**row) for row in ordered_rows],
        page=build_page_meta(
            total=total,
            limit=limit,
            offset=offset,
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )


async def list_articles_from_articles(
    db: aiosqlite.Connection,
    journal_id: int | None,
    issue_id: int | None,
    year: int | None,
    area: list[str] | None,
    in_press: bool | None,
    open_access: bool | None,
    suppressed: bool | None,
    within_library_holdings: bool | None,
    date_from: str | None,
    date_to: str | None,
    doi: str | None,
    pmid: str | None,
    q: str | None,
    use_simple_query: bool,
    sort: str | None,
    limit: int,
    offset: int,
    cursor: str | None,
    include_total: bool,
) -> ArticlePage:
    """
    List articles using direct table joins when listing data is unavailable.

    Args:
        db: Database connection.
        journal_id: Filter by journal ID.
        issue_id: Filter by issue ID.
        year: Filter by publication year from issues.
        area: Filter by journal area (multiple allowed).
        in_press: Filter by in_press flag.
        open_access: Filter by open_access flag.
        suppressed: Filter by suppressed flag.
        within_library_holdings: Filter by holdings flag.
        date_from: Minimum article date.
        date_to: Maximum article date.
        doi: Filter by DOI.
        pmid: Filter by PMID.
        q: Full-text search query for FTS5.
        use_simple_query: Whether to wrap queries with simple_query().
        sort: Sort string for articles.
        limit: Page size.
        offset: Page offset.
        cursor: Keyset cursor for pagination.
        include_total: Whether to compute total count.

    Returns:
        Paginated article list.
    """
    where_clauses: list[str] = []
    params: list[Any] = []
    join_meta = area is not None and len(area) > 0
    join_search = q is not None and q.strip() != ""
    join_issues = year is not None

    if journal_id is not None:
        where_clauses.append("a.journal_id = ?")
        params.append(journal_id)
    if issue_id is not None:
        where_clauses.append("a.issue_id = ?")
        params.append(issue_id)
    if area:
        placeholders = ", ".join(["?"] * len(area))
        where_clauses.append(f"m.area IN ({placeholders})")
        params.extend(area)
    if in_press is not None:
        where_clauses.append("a.in_press = ?")
        params.append(1 if in_press else 0)
    if open_access is not None:
        where_clauses.append("a.open_access = ?")
        params.append(1 if open_access else 0)
    if suppressed is not None:
        where_clauses.append("a.suppressed = ?")
        params.append(1 if suppressed else 0)
    if within_library_holdings is not None:
        where_clauses.append("a.within_library_holdings = ?")
        params.append(1 if within_library_holdings else 0)
    if date_from:
        where_clauses.append("a.date >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("a.date <= ?")
        params.append(date_to)
    if doi:
        where_clauses.append("a.doi = ?")
        params.append(doi)
    if pmid:
        where_clauses.append("a.pmid = ?")
        params.append(pmid)
    if year is not None:
        where_clauses.append("i.publication_year = ?")
        params.append(year)
    if q and q.strip():
        matcher = "simple_query(?)" if use_simple_query else "?"
        where_clauses.append(f"article_search MATCH {matcher}")
        params.append(q.strip())

    join_sql = []
    if join_issues:
        join_sql.append("JOIN issues i ON i.issue_id = a.issue_id")
    if join_search:
        join_sql.append(
            "JOIN article_search ON article_search.article_id = a.article_id"
        )
    if join_meta:
        join_sql.append("JOIN journal_meta m ON m.journal_id = a.journal_id")

    filter_joins = " ".join(join_sql)

    sort_specs = parse_sort(sort, {"date": "a.date"})
    supports_keyset = len(sort_specs) == 1 and sort_specs[0].column == "a.date"
    if not supports_keyset:
        raise HTTPException(
            status_code=400,
            detail="Articles only support sort=date:desc or date:asc",
        )
    direction = sort_specs[0].direction
    order_sql = f" ORDER BY a.date {direction}, a.article_id {direction}"

    if cursor:
        cursor_date, cursor_id = parse_article_cursor(cursor)
        operator = "<" if direction == "DESC" else ">"
        where_clauses.append(
            f"(a.date {operator} ? OR (a.date = ? AND a.article_id {operator} ?))"
        )
        params.extend([cursor_date, cursor_date, cursor_id])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    total = None
    if include_total:
        count_row = await fetch_one(
            db,
            f"""
            SELECT COUNT(*) AS total
            FROM articles a
            {filter_joins}
            {where_sql}
            """,
            params,
        )
        total = int(count_row["total"]) if count_row else 0

    pagination_sql = "LIMIT ?"
    pagination_params: list[Any] = [limit]
    if cursor is None:
        pagination_sql = f"{pagination_sql} OFFSET ?"
        pagination_params.append(offset)

    id_rows = await fetch_all(
        db,
        f"""
        SELECT
            a.article_id,
            a.date
        FROM articles a
        {filter_joins}
        {where_sql}
        {order_sql}
        {pagination_sql}
        """,
        params + pagination_params,
    )

    has_more = len(id_rows) == limit
    next_cursor = None
    if id_rows and has_more:
        last_row = id_rows[-1]
        next_cursor = build_article_cursor(
            last_row.get("date"),
            int(last_row["article_id"]),
        )
        if next_cursor is None:
            has_more = False

    article_ids = [int(row["article_id"]) for row in id_rows]
    if not article_ids:
        return ArticlePage(
            items=[],
            page=build_page_meta(
                total=total,
                limit=limit,
                offset=offset,
                next_cursor=next_cursor,
                has_more=has_more,
            ),
        )

    placeholders = ", ".join(["?"] * len(article_ids))
    rows = await fetch_all(
        db,
        f"""
        SELECT
            a.article_id,
            a.journal_id,
            a.issue_id,
            a.sync_id,
            a.title,
            a.date,
            a.authors,
            a.start_page,
            a.end_page,
            a.abstract,
            a.doi,
            a.pmid,
            a.ill_url,
            a.link_resolver_openurl_link,
            a.email_article_request_link,
            a.permalink,
            a.suppressed,
            a.in_press,
            a.open_access,
            a.platform_id,
            a.retraction_doi,
            a.retraction_date,
            a.retraction_related_urls,
            a.unpaywall_data_suppressed,
            a.expression_of_concern_doi,
            a.within_library_holdings,
            a.noodletools_export_link,
            a.avoid_unpaywall_publisher_links,
            a.browzine_web_in_context_link,
            a.content_location,
            a.libkey_content_location,
            a.full_text_file,
            a.libkey_full_text_file,
            a.nomad_fallback_url,
            j.title AS journal_title,
            i.volume,
            i.number
        FROM articles a
        LEFT JOIN issues i ON i.issue_id = a.issue_id
        JOIN journals j ON j.journal_id = a.journal_id
        WHERE a.article_id IN ({placeholders})
        """,
        article_ids,
    )

    row_map = {int(row["article_id"]): row for row in rows}
    ordered_rows = [
        row_map[article_id] for article_id in article_ids if article_id in row_map
    ]

    return ArticlePage(
        items=[ArticleRecord(**row) for row in ordered_rows],
        page=build_page_meta(
            total=total,
            limit=limit,
            offset=offset,
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )


@app.get("/articles", response_model=ArticlePage)
async def list_articles(
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
    journal_id: int | None = Query(default=None, ge=0),
    issue_id: int | None = Query(default=None, ge=0),
    year: int | None = Query(default=None, ge=0),
    area: Annotated[list[str] | None, Query()] = None,
    in_press: bool | None = Query(default=None),
    open_access: bool | None = Query(default=None),
    suppressed: bool | None = Query(default=None),
    within_library_holdings: bool | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    doi: str | None = Query(default=None),
    pmid: str | None = Query(default=None),
    q: str | None = Query(default=None, description="FTS query for article_search"),
    sort: str | None = Query(default="date:desc"),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    include_total: bool = Query(default=True),
) -> ArticlePage:
    """
    List articles with filtering, FTS, and sorting.

    Args:
        journal_id: Filter by journal ID.
        issue_id: Filter by issue ID.
        year: Filter by publication year from issues.
        area: Filter by journal area (multiple allowed).
        in_press: Filter by in_press flag.
        open_access: Filter by open_access flag.
        suppressed: Filter by suppressed flag.
        within_library_holdings: Filter by holdings flag.
        date_from: Minimum article date.
        date_to: Maximum article date.
        doi: Filter by DOI.
        pmid: Filter by PMID.
        q: Full-text search query for FTS5.
        sort: Multi-column sort string.
        limit: Page size.
        offset: Page offset.
        cursor: Keyset cursor for pagination.
        include_total: Whether to compute total count.
        db: Database connection.

    Returns:
        Paginated article list.
    """
    use_simple_search = await is_simple_search_enabled(db)
    use_simple_query = should_use_simple_query(q, use_simple_search)
    if await is_article_listing_ready(db):
        return await list_articles_from_listing(
            db,
            journal_id,
            issue_id,
            year,
            area,
            in_press,
            open_access,
            suppressed,
            within_library_holdings,
            date_from,
            date_to,
            doi,
            pmid,
            q,
            use_simple_query,
            sort,
            limit,
            offset,
            cursor,
            include_total,
        )

    return await list_articles_from_articles(
        db,
        journal_id,
        issue_id,
        year,
        area,
        in_press,
        open_access,
        suppressed,
        within_library_holdings,
        date_from,
        date_to,
        doi,
        pmid,
        q,
        use_simple_query,
        sort,
        limit,
        offset,
        cursor,
        include_total,
    )


@app.get("/articles/{article_id}", response_model=ArticleRecord)
async def get_article(
    article_id: int,
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
) -> ArticleRecord:
    """
    Fetch a single article record.

    Args:
        article_id: Article identifier.
        db: Database connection.

    Returns:
        Article record.
    """
    row = await fetch_one(
        db,
        """
        SELECT
            a.article_id,
            a.journal_id,
            a.issue_id,
            a.sync_id,
            a.title,
            a.date,
            a.authors,
            a.start_page,
            a.end_page,
            a.abstract,
            a.doi,
            a.pmid,
            a.ill_url,
            a.link_resolver_openurl_link,
            a.email_article_request_link,
            a.permalink,
            a.suppressed,
            a.in_press,
            a.open_access,
            a.platform_id,
            a.retraction_doi,
            a.retraction_date,
            a.retraction_related_urls,
            a.unpaywall_data_suppressed,
            a.expression_of_concern_doi,
            a.within_library_holdings,
            a.noodletools_export_link,
            a.avoid_unpaywall_publisher_links,
            a.browzine_web_in_context_link,
            a.content_location,
            a.libkey_content_location,
            a.full_text_file,
            a.libkey_full_text_file,
            a.nomad_fallback_url,
            j.title AS journal_title,
            i.volume,
            i.number
        FROM articles a
        LEFT JOIN issues i ON i.issue_id = a.issue_id
        JOIN journals j ON j.journal_id = a.journal_id
        WHERE a.article_id = ?
        """,
        [article_id],
    )
    if not row:
        raise HTTPException(status_code=404, detail="Article not found")
    return ArticleRecord(**row)


@app.get("/articles/{article_id}/fulltext")
async def redirect_article_fulltext(
    article_id: int,
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
) -> RedirectResponse:
    """
    Redirect to a DOI or signed full text URL for an article.

    Args:
        article_id: Article identifier.
        db: Database connection.

    Returns:
        RedirectResponse to the resolved full text URL.
    """
    row = await fetch_one(
        db,
        """
        SELECT
            a.article_id,
            a.title,
            a.doi,
            a.platform_id,
            a.full_text_file,
            a.libkey_full_text_file,
            i.publication_year,
            i.number,
            j.issn,
            j.title AS journal_title,
            j.library_id
        FROM articles a
        LEFT JOIN issues i ON i.issue_id = a.issue_id
        JOIN journals j ON j.journal_id = a.journal_id
        WHERE a.article_id = ?
        """,
        [article_id],
    )
    if not row:
        raise HTTPException(status_code=404, detail="Article not found")
    doi = row.get("doi")
    if doi:
        doi_text = str(doi).strip()
        if doi_text:
            return RedirectResponse(f"https://doi.org/{doi_text}")
    full_text_file = row.get("full_text_file") or row.get("libkey_full_text_file")
    if full_text_file:
        return RedirectResponse(str(full_text_file))
    if row.get("library_id") == WEIPU_LIBRARY_ID:
        detail_url = await resolve_weipu_detail_url(
            row.get("journal_title"),
            row.get("issn"),
            row.get("publication_year"),
            row.get("number"),
            row.get("platform_id"),
            row.get("title"),
        )
        if detail_url:
            return RedirectResponse(detail_url)
    raise HTTPException(status_code=404, detail="Full text not available")


def main() -> None:
    """
    Run the FastAPI application with Uvicorn.
    """
    uvicorn.run("scripts.api:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
