"""WeiPu URL resolution helpers."""

from __future__ import annotations

import re
from typing import Any

from scripts.weipu import WeipuAPISelectolax, normalize_years


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
