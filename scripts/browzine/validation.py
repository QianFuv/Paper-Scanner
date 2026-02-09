"""Validation helpers for BrowZine journal availability."""

from __future__ import annotations

from scripts.browzine.client import BrowZineAPIClient
from scripts.shared.constants import FALLBACK_LIBRARIES
from scripts.shared.converters import to_int


async def validate_single_journal(
    client: BrowZineAPIClient, journal_id: int, library_id: str
) -> tuple[bool, str]:
    """
    Validate a single journal for availability and content.

    Args:
        client: BrowZine API client instance.
        journal_id: BrowZine journal ID.
        library_id: Library ID to validate in.

    Returns:
        Tuple of (is_valid, reason).
    """
    journal_info = await client.get_journal_info(journal_id, library_id)
    if not journal_info:
        return False, "Journal not found"

    attributes = journal_info.get("attributes", {})
    available = attributes.get("available", False)
    if not available:
        return False, "Journal not available"

    current_issue = await client.get_current_issue(journal_id, library_id)
    if not current_issue:
        return False, "No current issue found"

    issue_id = to_int(current_issue.get("id"))
    if not issue_id:
        return False, "Issue has no ID"

    articles = await client.get_articles_from_issue(issue_id, library_id)
    if not articles:
        return False, "No articles found in current issue"

    has_actual_content = any(
        article.get("attributes", {}).get("abstract")
        or article.get("attributes", {}).get("fullTextFile")
        for article in articles
    )
    if not has_actual_content:
        return False, "Articles have no actual content"

    return True, "Valid"


async def resolve_working_library(
    client: BrowZineAPIClient,
    journal_id: int,
    issn: str | None,
    library_id: str,
) -> tuple[int, str, str]:
    """
    Resolve a working library for a journal using fallback libraries when needed.

    Args:
        client: BrowZine API client instance.
        journal_id: BrowZine journal ID.
        issn: Journal ISSN for fallback search.
        library_id: Library ID to try first.

    Returns:
        Tuple of (resolved_journal_id, resolved_library_id, reason).
    """
    is_valid, reason = await validate_single_journal(client, journal_id, library_id)
    if is_valid:
        return journal_id, library_id, reason

    if not issn:
        return journal_id, library_id, reason

    for fallback_lib in FALLBACK_LIBRARIES:
        if fallback_lib == library_id:
            continue
        journal = await client.search_by_issn(issn, fallback_lib)
        if not journal:
            continue
        fallback_id = to_int(journal.get("id"))
        if not fallback_id:
            continue
        is_valid, fallback_reason = await validate_single_journal(
            client, fallback_id, fallback_lib
        )
        if is_valid:
            return fallback_id, fallback_lib, fallback_reason

    return journal_id, library_id, reason
