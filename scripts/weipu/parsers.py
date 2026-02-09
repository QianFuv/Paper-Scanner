"""WeiPu payload parsing and normalization helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

BASE_URL = "https://www.cqvip.com"


def normalize_issn(value: str) -> str:
    """
    Normalize ISSN by stripping non-alphanumeric characters and uppercasing.

    Args:
        value: Raw ISSN value.

    Returns:
        Normalized ISSN string.
    """
    if not value:
        return ""
    cleaned = re.sub(r"[^0-9A-Za-z]", "", value)
    return cleaned.upper()


def pick_first(data: dict[str, Any], *keys: str) -> Any:
    """
    Pick the first non-empty value from a dictionary by key order.

    Args:
        data: Source dictionary.
        keys: Keys to search in order.

    Returns:
        First non-empty value or None.
    """
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None


def normalize_doi(value: Any) -> str | None:
    """
    Normalize DOI values by stripping prefixes and URLs.

    Args:
        value: Raw DOI value.

    Returns:
        Normalized DOI string or None.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    return text or None


def normalize_keyword(value: str) -> str:
    """
    Normalize a keyword for comparison.

    Args:
        value: Raw keyword string.

    Returns:
        Normalized keyword string.
    """
    return value.strip().lower()


def normalize_detail_url(value: Any) -> str | None:
    """
    Normalize a detail URL value to an absolute URL.

    Args:
        value: Raw URL value.

    Returns:
        Absolute URL string or None.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith("/"):
        return f"{BASE_URL}{text}"
    return text


def iter_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    """
    Yield all dictionaries found in a nested structure.

    Args:
        obj: Arbitrary nested data structure.

    Returns:
        Iterable of dictionaries.
    """
    stack = [obj]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def iter_lists(obj: Any) -> Iterable[list[Any]]:
    """
    Yield all lists found in a nested structure.

    Args:
        obj: Arbitrary nested data structure.

    Returns:
        Iterable of lists.
    """
    stack = [obj]
    while stack:
        current = stack.pop()
        if isinstance(current, list):
            yield current
            stack.extend(current)
        elif isinstance(current, dict):
            stack.extend(current.values())


def is_article_payload(item: dict[str, Any]) -> bool:
    """
    Determine whether a dictionary looks like an article payload.

    Args:
        item: Dictionary to inspect.

    Returns:
        True when the dictionary resembles an article.
    """
    keys = (
        "title",
        "titleCn",
        "titleCN",
        "name",
        "authors",
        "author",
        "abstract",
        "summary",
        "abstr",
        "keywords",
        "keyWords",
        "keyword",
        "pages",
    )
    return any(key in item for key in keys)


def extract_doi_map(payload: dict[str, Any]) -> dict[str, str]:
    """
    Extract DOI values keyed by article ID from a payload.

    Args:
        payload: Parsed Nuxt payload.

    Returns:
        Mapping of article ID to DOI.
    """
    doi_map: dict[str, str] = {}
    for item in iter_dicts(payload):
        if not isinstance(item, dict):
            continue
        if not is_article_payload(item):
            continue
        article_id = pick_first(item, "id", "articleId", "article_id")
        if article_id is None:
            continue
        doi = normalize_doi(pick_first(item, "doi", "DOI"))
        if doi:
            doi_map[str(article_id)] = doi
    return doi_map


def collect_detail_links(
    articles: list[dict[str, Any]], seed_links: dict[str, str]
) -> dict[str, str]:
    """
    Collect article detail URLs from normalized articles and existing links.

    Args:
        articles: Normalized article list.
        seed_links: Existing detail links from HTML.

    Returns:
        Mapping of article ID to detail URL.
    """
    links = dict(seed_links)
    for article in articles:
        article_id = article.get("id")
        if article_id is None:
            continue
        article_key = str(article_id)
        if article_key in links:
            detail_url = normalize_detail_url(links[article_key])
            if detail_url:
                article["detailUrl"] = detail_url
            continue
        detail_url = normalize_detail_url(article.get("detailUrl"))
        if detail_url:
            links[article_key] = detail_url
            article["detailUrl"] = detail_url
    return links


def normalize_string_list(value: Any) -> list[str]:
    """
    Normalize a value into a list of non-empty strings.

    Args:
        value: Raw value to normalize.

    Returns:
        List of string values.
    """
    if value is None:
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = pick_first(item, "name", "keyword", "word", "label", "title")
                if text:
                    items.append(str(text).strip())
                continue
            text = str(item).strip()
            if text:
                items.append(text)
        return items
    if isinstance(value, str):
        tokens = re.split(r"[;；,、|/]", value)
        return [token.strip() for token in tokens if token.strip()]
    text = str(value).strip()
    return [text] if text else []


def normalize_authors(value: Any) -> list[dict[str, Any]]:
    """
    Normalize author data to a list of dictionaries.

    Args:
        value: Raw author value.

    Returns:
        Normalized list of author dictionaries.
    """
    if value is None:
        return []
    if isinstance(value, list):
        authors: list[dict[str, Any]] = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, dict):
                name = pick_first(item, "name", "authorName", "author", "name_cn")
                name_en = pick_first(item, "name_en", "nameEn", "nameEnUS")
                if not name_en and isinstance(item.get("nameAlt"), list):
                    for alt in item["nameAlt"]:
                        if not isinstance(alt, dict):
                            continue
                        if alt.get("lang") == "en":
                            alt_values = alt.get("_v")
                            if isinstance(alt_values, list) and alt_values:
                                name_en = alt_values[0]
                                break
                is_corresponding = bool(
                    pick_first(
                        item,
                        "is_corresponding",
                        "isCorresponding",
                        "corresponding",
                        "isCorrespondingAuthor",
                        "iscorr",
                    )
                )
                order = pick_first(item, "order", "orderNo", "seq", "sequence")
                order_value = index
                if order is not None:
                    try:
                        order_value = int(order)
                    except (TypeError, ValueError):
                        order_value = index
                authors.append(
                    {
                        "name": str(name) if name is not None else "",
                        "name_en": str(name_en) if name_en is not None else None,
                        "is_corresponding": is_corresponding,
                        "order": order_value,
                    }
                )
            else:
                text = str(item).strip()
                if text:
                    authors.append(
                        {
                            "name": text,
                            "name_en": None,
                            "is_corresponding": False,
                            "order": index,
                        }
                    )
        return authors
    if isinstance(value, str):
        names = normalize_string_list(value)
        return [
            {
                "name": name,
                "name_en": None,
                "is_corresponding": False,
                "order": index,
            }
            for index, name in enumerate(names, start=1)
        ]
    return []


def normalize_pages(article: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize page information from an article payload.

    Args:
        article: Article dictionary.

    Returns:
        Normalized page dictionary.
    """
    pages = article.get("pages")
    if isinstance(pages, dict):
        begin = pick_first(pages, "begin", "start", "startPage")
        end = pick_first(pages, "end", "endPage")
        count = pick_first(pages, "count", "pageCount")
        return {
            "begin": str(begin) if begin is not None else "",
            "end": str(end) if end is not None else "",
            "count": int(count) if isinstance(count, (int, float)) else None,
        }

    begin = pick_first(
        article, "begin", "startPage", "start_page", "pageStart", "beginPage"
    )
    end = pick_first(article, "end", "endPage", "end_page", "pageEnd", "endPage")
    count = pick_first(article, "pageCnt", "pageCount")

    begin_text = str(begin) if begin is not None else ""
    end_text = str(end) if end is not None else ""
    if count is not None:
        try:
            count_value = int(count)
        except (TypeError, ValueError):
            count_value = None
    else:
        count_value = None
    count = count_value
    if count is None:
        try:
            if begin is not None and end is not None:
                begin_num = int(begin)
                end_num = int(end)
                if end_num >= begin_num:
                    count = end_num - begin_num + 1
        except (TypeError, ValueError):
            count = None

    return {"begin": begin_text, "end": end_text, "count": count}


def score_article_list(items: list[Any]) -> int:
    """
    Score a candidate list of article dictionaries.

    Args:
        items: Candidate list.

    Returns:
        Integer score for the list.
    """
    score = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        if any(key in item for key in ("title", "titleCn", "titleCN", "name")):
            score += 3
        if any(
            key in item for key in ("authors", "author", "authorList", "author_name")
        ):
            score += 2
        if any(key in item for key in ("id", "articleId", "article_id")):
            score += 2
        if any(key in item for key in ("abstract", "summary")):
            score += 1
        if "doi" in item:
            score += 1
    return score


def select_best_article_list(payload: Any) -> list[dict[str, Any]]:
    """
    Select the most likely article list from the payload.

    Args:
        payload: Parsed Nuxt payload.

    Returns:
        List of article dictionaries.
    """
    best_list: list[dict[str, Any]] = []
    best_score = 0
    for candidate in iter_lists(payload):
        if not candidate or not all(isinstance(item, dict) for item in candidate):
            continue
        candidate_score = score_article_list(candidate)
        if candidate_score > best_score:
            best_score = candidate_score
            best_list = candidate
    return best_list


def select_best_year_list(payload: Any) -> list[dict[str, Any]]:
    """
    Select the most likely year list from the payload.

    Args:
        payload: Parsed Nuxt payload.

    Returns:
        List of year dictionaries.
    """
    best_list: list[dict[str, Any]] = []
    best_score = 0
    for candidate in iter_lists(payload):
        if not candidate or not all(isinstance(item, dict) for item in candidate):
            continue
        score = 0
        for item in candidate:
            if "year" in item:
                score += 2
            if any(key in item for key in ("issues", "issueList", "issue_list")):
                score += 1
        if score > best_score:
            best_score = score
            best_list = candidate
    return best_list


def normalize_issue_list(value: Any) -> list[dict[str, Any]]:
    """
    Normalize a list of issue dictionaries into the expected schema.

    Args:
        value: Raw issue list value.

    Returns:
        List of normalized issue dictionaries.
    """
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for issue in value:
        if not isinstance(issue, dict):
            continue
        issue_id = pick_first(issue, "id", "issueId", "issue_id", "issueID")
        if issue_id is None:
            continue
        name = pick_first(issue, "name", "issueName", "issue", "title", "no")
        cover = pick_first(
            issue, "coverImage", "coverUrl", "coverURL", "cover", "image"
        )
        if isinstance(cover, dict):
            cover = pick_first(cover, "path", "url", "src")
        normalized.append(
            {
                "id": str(issue_id),
                "name": str(name) if name is not None else str(issue_id),
                "coverImage": cover,
            }
        )
    return normalized


def normalize_years(payload: Any) -> list[dict[str, Any]]:
    """
    Normalize year and issue data from a payload.

    Args:
        payload: Parsed Nuxt payload.

    Returns:
        List of normalized year dictionaries.
    """
    time_list = None
    if isinstance(payload, dict):
        data_items = payload.get("data")
        if isinstance(data_items, list) and len(data_items) > 1:
            second = data_items[1]
            if isinstance(second, dict):
                summary = second.get("summaryList")
                if isinstance(summary, dict):
                    time_list = summary.get("timeList")

    if isinstance(time_list, list):
        years: list[dict[str, Any]] = []
        for entry in time_list:
            if not isinstance(entry, dict):
                continue
            year_value = entry.get("year")
            try:
                if year_value is None:
                    continue
                year_int = int(str(year_value))
            except (TypeError, ValueError):
                continue
            issues_raw = entry.get("periodical") or []
            issues = normalize_issue_list(issues_raw)
            if not issues:
                continue
            years.append(
                {
                    "year": year_int,
                    "issueCount": len(issues),
                    "issues": issues,
                }
            )
        if years:
            return years

    year_candidates = select_best_year_list(payload)
    fallback_years: list[dict[str, Any]] = []
    for entry in year_candidates:
        year_value = pick_first(entry, "year", "publishYear", "pubYear")
        try:
            year_int = int(year_value)
        except (TypeError, ValueError):
            continue
        issues_raw = pick_first(entry, "issues", "issueList", "issue_list")
        issues = normalize_issue_list(issues_raw)
        fallback_years.append(
            {
                "year": year_int,
                "issueCount": len(issues),
                "issues": issues,
            }
        )
    return fallback_years


def extract_periodical(payload: Any) -> dict[str, Any] | None:
    """
    Extract periodical information from a payload.

    Args:
        payload: Parsed Nuxt payload.

    Returns:
        Periodical dictionary or None.
    """
    candidates: list[dict[str, Any]] = []
    for item in iter_dicts(payload):
        if "periodical" in item and isinstance(item["periodical"], dict):
            candidates.append(item["periodical"])
        if any(key in item for key in ("journalId", "journalID")):
            candidates.append(item)

    if not candidates:
        return None

    def score(candidate: dict[str, Any]) -> int:
        score_value = 0
        if any(key in candidate for key in ("journalId", "journalID")):
            score_value += 2
        if any(key in candidate for key in ("journalName", "name", "title")):
            score_value += 2
        if "issn" in candidate:
            score_value += 1
        return score_value

    best = max(candidates, key=score)
    journal_id = pick_first(best, "journalId", "journalID", "id")
    journal_name = pick_first(best, "journalName", "name", "title")
    issn = pick_first(best, "issn", "ISSN")
    cnno = pick_first(best, "cnno", "cnNo", "cn")
    return {
        "journalId": str(journal_id) if journal_id is not None else "",
        "journalName": str(journal_name) if journal_name is not None else "",
        "issn": str(issn) if issn is not None else "",
        "cnno": str(cnno) if cnno is not None else "",
    }


def extract_available_years(payload: dict[str, Any]) -> list[int]:
    """
    Extract available publication years from a Nuxt payload.

    Args:
        payload: Parsed Nuxt payload.

    Returns:
        List of available years in descending order when possible.
    """
    years: list[int] = []
    data_items = payload.get("data")
    if isinstance(data_items, list) and len(data_items) > 1:
        second = data_items[1]
        if isinstance(second, dict):
            pyear = second.get("pYear")
            if isinstance(pyear, list):
                for value in pyear:
                    try:
                        year_int = int(str(value))
                    except (TypeError, ValueError):
                        continue
                    years.append(year_int)
            summary = second.get("summaryList")
            if isinstance(summary, dict):
                time_list = summary.get("timeList")
                if isinstance(time_list, list):
                    for entry in time_list:
                        if not isinstance(entry, dict):
                            continue
                        try:
                            year_int = int(str(entry.get("year")))
                        except (TypeError, ValueError):
                            continue
                        if year_int not in years:
                            years.append(year_int)
    return years


def extract_res_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Extract resData from a Nuxt payload if present.

    Args:
        payload: Parsed Nuxt payload.

    Returns:
        resData dictionary or None.
    """
    data_items = payload.get("data")
    if isinstance(data_items, list):
        for item in data_items:
            if isinstance(item, dict) and isinstance(item.get("resData"), dict):
                return item["resData"]
    for item in iter_dicts(payload):
        if isinstance(item.get("resData"), dict):
            return item["resData"]
    return None
