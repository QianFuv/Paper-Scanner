"""API response models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


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


class JournalOption(BaseModel):
    """
    Journal option for selection lists.
    """

    journal_id: int
    title: str | None = None


class WeeklyArticleRecord(BaseModel):
    """
    Weekly update article record.
    """

    article_id: int
    journal_id: int
    issue_id: int | None = None
    title: str | None = None
    date: str | None = None
    doi: str | None = None
    journal_title: str | None = None
    open_access: int | None = None
    in_press: int | None = None


class WeeklyJournalUpdate(BaseModel):
    """
    Weekly update summary for one journal.
    """

    journal_id: int
    journal_title: str | None = None
    new_article_count: int
    articles: list[WeeklyArticleRecord]


class WeeklyDatabaseUpdate(BaseModel):
    """
    Weekly update summary for one database.
    """

    db_name: str
    run_id: str | None = None
    generated_at: str
    new_article_count: int
    journals: list[WeeklyJournalUpdate]


class WeeklyUpdatesResponse(BaseModel):
    """
    Weekly updates grouped by database and journal.
    """

    generated_at: str
    window_start: str
    window_end: str
    databases: list[WeeklyDatabaseUpdate]


@dataclass(frozen=True)
class WeeklyManifestSummary:
    """
    Parsed weekly changes manifest summary.
    """

    db_name: str
    run_id: str | None
    generated_at: datetime
    article_ids: list[int]
