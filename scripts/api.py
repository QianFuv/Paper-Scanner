"""
FastAPI backend for querying BrowZine article index databases.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import aiosqlite
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).parent.parent
INDEX_DIR = PROJECT_ROOT / "data" / "index"
MAX_LIMIT = 200
MAX_REGEX_CANDIDATES = 5000


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
    rank: str | None = None
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


class PageMeta(BaseModel):
    """
    Pagination metadata.
    """

    total: int
    limit: int
    offset: int


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


def compile_regex(pattern: str, ignore_case: bool) -> re.Pattern[str]:
    """
    Compile a regular expression for filtering.

    Args:
        pattern: Regex pattern.
        ignore_case: Whether to ignore case.

    Returns:
        Compiled regex pattern.
    """
    flags = re.IGNORECASE if ignore_case else 0
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}") from exc


def regex_match_any(
    regex: re.Pattern[str],
    fields: list[str],
    record: dict[str, Any],
) -> bool:
    """
    Test whether any field in a record matches the regex.

    Args:
        regex: Compiled regex.
        fields: Record fields to test.
        record: Row dictionary.

    Returns:
        True if any field matches, otherwise False.
    """
    for field in fields:
        value = record.get(field)
        if value and regex.search(str(value)):
            return True
    return False


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


def build_page_meta(total: int, limit: int, offset: int) -> PageMeta:
    """
    Build pagination metadata.

    Args:
        total: Total rows.
        limit: Page size.
        offset: Page offset.

    Returns:
        Page metadata.
    """
    return PageMeta(total=total, limit=limit, offset=offset)


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
    "article_id": "a.article_id",
    "title": "a.title",
    "date": "a.date",
    "journal_id": "a.journal_id",
    "issue_id": "a.issue_id",
    "open_access": "a.open_access",
    "in_press": "a.in_press",
    "doi": "a.doi",
}

ARTICLE_REGEX_FIELDS = {
    "title": "title",
    "abstract": "abstract",
    "authors": "authors",
    "doi": "doi",
    "journal_title": "journal_title",
}


@app.get("/health")
async def health() -> dict[str, str]:
    """
    Health check endpoint.

    Returns:
        Health status payload.
    """
    return {"status": "ok"}


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
        ORDER BY count DESC, value ASC
        """,
        [],
    )
    return [ValueCount(**row) for row in rows]


@app.get("/meta/ranks", response_model=list[ValueCount])
async def list_ranks(
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
) -> list[ValueCount]:
    """
    List distinct journal ranks.

    Args:
        db: Database connection.

    Returns:
        Rank values with counts.
    """
    rows = await fetch_all(
        db,
        """
        SELECT rank AS value, COUNT(*) AS count
        FROM journal_meta
        WHERE rank IS NOT NULL AND rank != ''
        GROUP BY rank
        ORDER BY count DESC, value ASC
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
            publication_year AS year,
            COUNT(DISTINCT issue_id) AS issue_count,
            COUNT(DISTINCT journal_id) AS journal_count
        FROM issues
        WHERE publication_year IS NOT NULL
        GROUP BY publication_year
        ORDER BY publication_year DESC
        """,
        [],
    )
    return [YearSummary(**row) for row in rows]


@app.get("/journals", response_model=JournalPage)
async def list_journals(
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
    area: str | None = Query(default=None),
    rank: str | None = Query(default=None),
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
        rank: Filter by CSV rank.
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
    if rank:
        where_clauses.append("m.rank = ?")
        params.append(rank)
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
            m.rank,
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
            m.rank,
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


@app.get("/articles", response_model=ArticlePage)
async def list_articles(
    db: Annotated[aiosqlite.Connection, Depends(get_db_dependency)],
    journal_id: int | None = Query(default=None, ge=0),
    issue_id: int | None = Query(default=None, ge=0),
    year: int | None = Query(default=None, ge=0),
    in_press: bool | None = Query(default=None),
    open_access: bool | None = Query(default=None),
    suppressed: bool | None = Query(default=None),
    within_library_holdings: bool | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    doi: str | None = Query(default=None),
    pmid: str | None = Query(default=None),
    q: str | None = Query(default=None, description="FTS query for article_search"),
    regex: str | None = Query(default=None),
    regex_fields: str | None = Query(
        default=None,
        description="Comma-separated fields for regex filtering",
    ),
    regex_ignore_case: bool = Query(default=True),
    sort: str | None = Query(default="date:desc"),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> ArticlePage:
    """
    List articles with filtering, FTS, regex filtering, and sorting.

    Args:
        journal_id: Filter by journal ID.
        issue_id: Filter by issue ID.
        year: Filter by publication year from issues.
        in_press: Filter by in_press flag.
        open_access: Filter by open_access flag.
        suppressed: Filter by suppressed flag.
        within_library_holdings: Filter by holdings flag.
        date_from: Minimum article date.
        date_to: Maximum article date.
        doi: Filter by DOI.
        pmid: Filter by PMID.
        q: Full-text search query for FTS5.
        regex: Regex to apply after FTS filtering.
        regex_fields: Fields to test for regex matches.
        regex_ignore_case: Whether to ignore case for regex matching.
        sort: Multi-column sort string.
        limit: Page size.
        offset: Page offset.
        db: Database connection.

    Returns:
        Paginated article list.
    """
    where_clauses: list[str] = []
    params: list[Any] = []
    join_issue = year is not None
    join_search = q is not None and q.strip() != ""
    if regex and not join_search:
        raise HTTPException(
            status_code=400, detail="regex requires q for FTS prefilter"
        )

    if journal_id is not None:
        where_clauses.append("a.journal_id = ?")
        params.append(journal_id)
    if issue_id is not None:
        where_clauses.append("a.issue_id = ?")
        params.append(issue_id)
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
        where_clauses.append("article_search MATCH ?")
        params.append(q.strip())

    join_sql = []
    if join_issue:
        join_sql.append("JOIN issues i ON i.issue_id = a.issue_id")
    if join_search:
        join_sql.append(
            "JOIN article_search ON article_search.article_id = a.article_id"
        )
    join_sql.append("JOIN journals j ON j.journal_id = a.journal_id")
    joins = " ".join(join_sql)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    order_sql = apply_sort(parse_sort(sort, ARTICLE_SORT_FIELDS))

    count_row = await fetch_one(
        db,
        f"""
        SELECT COUNT(*) AS total
        FROM articles a
        {joins}
        {where_sql}
        """,
        params,
    )
    total = int(count_row["total"]) if count_row else 0

    if regex:
        if total > MAX_REGEX_CANDIDATES:
            raise HTTPException(
                status_code=400,
                detail="Too many FTS matches for regex filtering; refine q or filters.",
            )
        regex_compiled = compile_regex(regex, regex_ignore_case)
        if regex_fields:
            selected_fields = [
                field.strip() for field in regex_fields.split(",") if field.strip()
            ]
        else:
            selected_fields = list(ARTICLE_REGEX_FIELDS.keys())
        invalid_fields = [
            field for field in selected_fields if field not in ARTICLE_REGEX_FIELDS
        ]
        if invalid_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported regex fields: {', '.join(invalid_fields)}",
            )

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
                j.title AS journal_title
            FROM articles a
            {joins}
            {where_sql}
            {order_sql}
            """,
            params,
        )
        filtered_rows = [
            row for row in rows if regex_match_any(regex_compiled, selected_fields, row)
        ]
        total_filtered = len(filtered_rows)
        page_rows = filtered_rows[offset : offset + limit]
        return ArticlePage(
            items=[ArticleRecord(**row) for row in page_rows],
            page=build_page_meta(total_filtered, limit, offset),
        )

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
            j.title AS journal_title
        FROM articles a
        {joins}
        {where_sql}
        {order_sql}
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )

    return ArticlePage(
        items=[ArticleRecord(**row) for row in rows],
        page=build_page_meta(total, limit, offset),
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
            j.title AS journal_title
        FROM articles a
        JOIN journals j ON j.journal_id = a.journal_id
        WHERE a.article_id = ?
        """,
        [article_id],
    )
    if not row:
        raise HTTPException(status_code=404, detail="Article not found")
    return ArticleRecord(**row)


def main() -> None:
    """
    Run the FastAPI application with Uvicorn.
    """
    uvicorn.run("scripts.api:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
