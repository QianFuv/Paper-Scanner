"""
Weipu (CQVIP) API client using selectolax and QuickJS.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import re
import time
from collections.abc import Iterable
from typing import Any

import httpx
import quickjs
from selectolax.parser import HTMLParser

BASE_URL = "https://www.cqvip.com"
API_BASE_URL = "https://www.cqvip.com/newsite"
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY = 0.75
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.cqvip.com/",
}
CQVIP_APP_ID = "f0de4ab08fbe4ca2afd1708d160d33a4"
CQVIP_SIGNATURE_SECRET = "06925E8A-CBB9-4A95-A738-B1C9156B9D06"

DES_IP_TABLE = [
    58,
    50,
    42,
    34,
    26,
    18,
    10,
    2,
    60,
    52,
    44,
    36,
    28,
    20,
    12,
    4,
    62,
    54,
    46,
    38,
    30,
    22,
    14,
    6,
    64,
    56,
    48,
    40,
    32,
    24,
    16,
    8,
    57,
    49,
    41,
    33,
    25,
    17,
    9,
    1,
    59,
    51,
    43,
    35,
    27,
    19,
    11,
    3,
    61,
    53,
    45,
    37,
    29,
    21,
    13,
    5,
    63,
    55,
    47,
    39,
    31,
    23,
    15,
    7,
]
DES_FP_TABLE = [
    40,
    8,
    48,
    16,
    56,
    24,
    64,
    32,
    39,
    7,
    47,
    15,
    55,
    23,
    63,
    31,
    38,
    6,
    46,
    14,
    54,
    22,
    62,
    30,
    37,
    5,
    45,
    13,
    53,
    21,
    61,
    29,
    36,
    4,
    44,
    12,
    52,
    20,
    60,
    28,
    35,
    3,
    43,
    11,
    51,
    19,
    59,
    27,
    34,
    2,
    42,
    10,
    50,
    18,
    58,
    26,
    33,
    1,
    41,
    9,
    49,
    17,
    57,
    25,
]
DES_E_TABLE = [
    32,
    1,
    2,
    3,
    4,
    5,
    4,
    5,
    6,
    7,
    8,
    9,
    8,
    9,
    10,
    11,
    12,
    13,
    12,
    13,
    14,
    15,
    16,
    17,
    16,
    17,
    18,
    19,
    20,
    21,
    20,
    21,
    22,
    23,
    24,
    25,
    24,
    25,
    26,
    27,
    28,
    29,
    28,
    29,
    30,
    31,
    32,
    1,
]
DES_P_TABLE = [
    16,
    7,
    20,
    21,
    29,
    12,
    28,
    17,
    1,
    15,
    23,
    26,
    5,
    18,
    31,
    10,
    2,
    8,
    24,
    14,
    32,
    27,
    3,
    9,
    19,
    13,
    30,
    6,
    22,
    11,
    4,
    25,
]
DES_PC1_TABLE = [
    57,
    49,
    41,
    33,
    25,
    17,
    9,
    1,
    58,
    50,
    42,
    34,
    26,
    18,
    10,
    2,
    59,
    51,
    43,
    35,
    27,
    19,
    11,
    3,
    60,
    52,
    44,
    36,
    63,
    55,
    47,
    39,
    31,
    23,
    15,
    7,
    62,
    54,
    46,
    38,
    30,
    22,
    14,
    6,
    61,
    53,
    45,
    37,
    29,
    21,
    13,
    5,
    28,
    20,
    12,
    4,
]
DES_PC2_TABLE = [
    14,
    17,
    11,
    24,
    1,
    5,
    3,
    28,
    15,
    6,
    21,
    10,
    23,
    19,
    12,
    4,
    26,
    8,
    16,
    7,
    27,
    20,
    13,
    2,
    41,
    52,
    31,
    37,
    47,
    55,
    30,
    40,
    51,
    45,
    33,
    48,
    44,
    49,
    39,
    56,
    34,
    53,
    46,
    42,
    50,
    36,
    29,
    32,
]
DES_SHIFTS = [1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1]
DES_SBOXES = [
    [
        [14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7],
        [0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8],
        [4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0],
        [15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13],
    ],
    [
        [15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10],
        [3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5],
        [0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15],
        [13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9],
    ],
    [
        [10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8],
        [13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1],
        [13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7],
        [1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12],
    ],
    [
        [7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15],
        [13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9],
        [10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4],
        [3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14],
    ],
    [
        [2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9],
        [14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6],
        [4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14],
        [11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3],
    ],
    [
        [12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11],
        [10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8],
        [9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6],
        [4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13],
    ],
    [
        [4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1],
        [13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6],
        [1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2],
        [6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12],
    ],
    [
        [13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7],
        [1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2],
        [7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8],
        [2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11],
    ],
]


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


def permute_bits(value: int, table: list[int], bits: int) -> int:
    """
    Permute bits according to a 1-based table.

    Args:
        value: Source integer.
        table: 1-based permutation table.
        bits: Bit width of the source value.

    Returns:
        Permuted integer.
    """
    result = 0
    for position in table:
        result = (result << 1) | ((value >> (bits - position)) & 1)
    return result


def rotate_left(value: int, shift: int, bits: int) -> int:
    """
    Rotate a value left within a fixed bit width.

    Args:
        value: Source integer.
        shift: Rotation count.
        bits: Bit width of the value.

    Returns:
        Rotated integer.
    """
    mask = (1 << bits) - 1
    shift %= bits
    return ((value << shift) & mask) | (value >> (bits - shift))


def build_des_subkeys(key: bytes) -> list[int]:
    """
    Build DES round subkeys from a raw 8-byte key.

    Args:
        key: Raw key bytes.

    Returns:
        List of 16 round subkeys.
    """
    if len(key) != 8:
        return []
    key_value = int.from_bytes(key, "big")
    permuted = permute_bits(key_value, DES_PC1_TABLE, 64)
    left = permuted >> 28
    right = permuted & ((1 << 28) - 1)
    subkeys: list[int] = []
    for shift in DES_SHIFTS:
        left = rotate_left(left, shift, 28)
        right = rotate_left(right, shift, 28)
        combined = (left << 28) | right
        subkeys.append(permute_bits(combined, DES_PC2_TABLE, 56))
    return subkeys


def sbox_substitute(value: int) -> int:
    """
    Apply DES S-box substitution to a 48-bit value.

    Args:
        value: 48-bit integer value.

    Returns:
        32-bit substitution output.
    """
    output = 0
    for index in range(8):
        shift = 42 - (index * 6)
        chunk = (value >> shift) & 0x3F
        row = ((chunk & 0x20) >> 4) | (chunk & 0x01)
        col = (chunk >> 1) & 0x0F
        output = (output << 4) | DES_SBOXES[index][row][col]
    return output


def des_encrypt_block(block: int, subkeys: list[int]) -> int:
    """
    Encrypt a single 64-bit block using DES in ECB mode.

    Args:
        block: 64-bit block value.
        subkeys: Round subkeys.

    Returns:
        Encrypted 64-bit block.
    """
    permuted = permute_bits(block, DES_IP_TABLE, 64)
    left = permuted >> 32
    right = permuted & ((1 << 32) - 1)
    for subkey in subkeys:
        expanded = permute_bits(right, DES_E_TABLE, 32)
        mixed = expanded ^ subkey
        substituted = sbox_substitute(mixed)
        permuted_round = permute_bits(substituted, DES_P_TABLE, 32)
        left, right = right, left ^ permuted_round
    combined = (right << 32) | left
    return permute_bits(combined, DES_FP_TABLE, 64)


def des_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    """
    Encrypt data using DES ECB with zero padding.

    Args:
        data: Plaintext bytes.
        key: Raw 8-byte key.

    Returns:
        Encrypted bytes.
    """
    subkeys = build_des_subkeys(key)
    if not subkeys:
        return b""
    pad_len = (8 - (len(data) % 8)) % 8
    if pad_len:
        data = data + (b"\x00" * pad_len)
    encrypted = bytearray()
    for offset in range(0, len(data), 8):
        block = int.from_bytes(data[offset : offset + 8], "big")
        encrypted_block = des_encrypt_block(block, subkeys)
        encrypted.extend(encrypted_block.to_bytes(8, "big"))
    return bytes(encrypted)


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


class WeipuAPISelectolax:
    """
    Client for extracting CQVIP journal metadata using selectolax and Node.js.
    """

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """
        Initialize the API client.

        Args:
            timeout: HTTP request timeout in seconds.
        """
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
        )
        self._uuid: str | None = None
        self._env: str | None = None
        self._server_time_offset_ms: int | None = None
        self._retry_attempts = DEFAULT_RETRY_ATTEMPTS
        self._retry_base_delay = DEFAULT_RETRY_BASE_DELAY

    async def _sleep_backoff(self, attempt: int) -> None:
        """
        Sleep for an exponential backoff interval.

        Args:
            attempt: Retry attempt index starting at 0.

        Returns:
            None.
        """
        delay = self._retry_base_delay * (2**attempt)
        await asyncio.sleep(delay)

    async def _request_with_retry(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response | None:
        """
        Send an HTTP request with retries on transient failures.

        Args:
            method: HTTP method.
            url: Target URL.
            kwargs: Additional httpx request arguments.

        Returns:
            httpx.Response or None when all retries fail.
        """
        for attempt in range(self._retry_attempts):
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.RequestError:
                response = None
            if response is None:
                await self._sleep_backoff(attempt)
                continue
            if (
                response.status_code in {429, 500, 502, 503, 504}
                and attempt < self._retry_attempts - 1
            ):
                await self._sleep_backoff(attempt)
                continue
            return response
        return None

    async def __aenter__(self) -> WeipuAPISelectolax:
        """
        Enter async context and return self.

        Returns:
            WeipuAPISelectolax instance.
        """
        return self

    async def __aexit__(self, exc_type, exc, exc_tb) -> None:
        """
        Exit async context and close the HTTP client.

        Args:
            exc_type: Exception type.
            exc: Exception instance.
            exc_tb: Exception traceback.

        Returns:
            None.
        """
        await self.aclose()

    async def aclose(self) -> None:
        """
        Close the underlying HTTP client.

        Returns:
            None.
        """
        await self._client.aclose()

    def _update_state_from_payload(self, payload: dict[str, Any]) -> None:
        """
        Update stored state values from a Nuxt payload.

        Args:
            payload: Parsed Nuxt payload.

        Returns:
            None.
        """
        state = payload.get("state")
        if not isinstance(state, dict):
            return
        uuid = state.get("uuid")
        env = state.get("env")
        server_time = state.get("serverTime")
        if uuid:
            self._uuid = str(uuid)
        if env:
            self._env = str(env)
        if server_time is not None:
            try:
                server_time_int = int(server_time)
            except (TypeError, ValueError):
                server_time_int = None
            if server_time_int is not None:
                local_time = int(time.time() * 1000)
                self._server_time_offset_ms = server_time_int - local_time

    def _current_timestamp_ms(self) -> int:
        """
        Get a timestamp in milliseconds aligned with server time when possible.

        Returns:
            Timestamp in milliseconds.
        """
        ts_ms = int(time.time() * 1000)
        if self._server_time_offset_ms is None:
            return ts_ms
        return ts_ms + self._server_time_offset_ms

    def _compute_signature(self, ts_sec: int) -> str:
        """
        Compute the signature header value for CQVIP requests.

        Args:
            ts_sec: Timestamp in seconds.

        Returns:
            Base64-encoded signature string.
        """
        data = f"{CQVIP_APP_ID}\n{CQVIP_SIGNATURE_SECRET}\n{ts_sec}"
        digest = hmac.new(
            CQVIP_SIGNATURE_SECRET.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _compute_cqvip_sign(self, data: str, key: str) -> str | None:
        """
        Compute the CQVIP DES signature using DES-ECB with zero padding.

        Args:
            data: Payload string for signing.
            key: DES key string.

        Returns:
            Hex-encoded signature string or None when computation fails.
        """
        key_bytes = key.encode("utf-8")
        payload = data.encode("utf-8")
        encrypted = des_ecb_encrypt(payload, key_bytes)
        if not encrypted:
            return None
        return encrypted.hex()

    def _build_signed_headers(self, path: str) -> dict[str, str] | None:
        """
        Build signed headers for CQVIP API requests.

        Args:
            path: API path without base URL.

        Returns:
            Headers dictionary or None when signing cannot be performed.
        """
        if not self._uuid:
            return None
        ts_ms = self._current_timestamp_ms()
        signature = self._compute_signature(ts_ms // 1000)
        sign = self._compute_cqvip_sign(f"{path}-{ts_ms}", self._uuid)
        if not sign:
            return None
        headers = {
            "User-Agent": DEFAULT_HEADERS["User-Agent"],
            "Referer": DEFAULT_HEADERS["Referer"],
            "Content-Type": "application/json;charset=UTF-8",
            "dt": "pc",
            "cqvipenv": self._env or "",
            "cqvip-type": "sm",
            "path": path,
            "cqvip-ts": str(ts_ms),
            "cqvip-sign": sign,
            "appId": CQVIP_APP_ID,
            "timestamp": str(ts_ms // 1000),
            "signature": signature,
        }
        return headers

    async def _post_signed(self, path: str, payload: dict[str, Any]) -> Any | None:
        """
        Send a signed POST request to the CQVIP API.

        Args:
            path: API path without base URL.
            payload: JSON payload.

        Returns:
            Response data or None when request fails.
        """
        headers = self._build_signed_headers(path)
        if headers is None:
            return None
        url = f"{API_BASE_URL}{path}"
        response = await self._request_with_retry(
            "POST", url, headers=headers, json=payload
        )
        if response is None or response.status_code != 200:
            return None
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            return None
        code = data.get("code")
        if code in {200, 25, 26}:
            return data.get("data")
        return None

    async def fetch_years_via_api(self, journal_id: str) -> list[int]:
        """
        Fetch available years for a journal using the CQVIP API.

        Args:
            journal_id: CQVIP journal identifier.

        Returns:
            List of publication years.
        """
        data = await self._post_signed("/journal/getYears", {"id": journal_id})
        if not isinstance(data, list):
            return []
        years: list[int] = []
        for item in data:
            try:
                year_int = int(str(item))
            except (TypeError, ValueError):
                continue
            years.append(year_int)
        return years

    async def fetch_issues_via_api(
        self, journal_id: str, year: int
    ) -> list[dict[str, Any]]:
        """
        Fetch issue list for a given year using the CQVIP API.

        Args:
            journal_id: CQVIP journal identifier.
            year: Target publication year.

        Returns:
            List of issue dictionaries.
        """
        data = await self._post_signed(
            "/journal/getNums", {"id": journal_id, "year": str(year)}
        )
        if not isinstance(data, list):
            return []
        return normalize_issue_list(data)

    async def fetch_page_payload(self, url: str) -> tuple[str, dict[str, Any]] | None:
        """
        Fetch HTML and parse the Nuxt payload for a CQVIP page.

        Args:
            url: Target URL.

        Returns:
            Tuple of (html, payload) or None.
        """
        response = await self._request_with_retry("GET", url)
        if response is None or response.status_code != 200:
            return None
        html_text = response.text
        script = self.extract_nuxt_script(html_text)
        if not script:
            return None
        payload = await asyncio.to_thread(self.execute_nuxt_script, script)
        if payload is None:
            return None
        return html_text, payload

    async def fetch_html(self, url: str) -> str | None:
        """
        Fetch HTML for a CQVIP page without parsing the Nuxt payload.

        Args:
            url: Target URL.

        Returns:
            HTML string or None.
        """
        response = await self._request_with_retry("GET", url)
        if response is None or response.status_code != 200:
            return None
        return response.text

    def extract_doc_links(self, html_text: str) -> dict[str, str]:
        """
        Extract article detail URLs from an issue page HTML.

        Args:
            html_text: Raw HTML content.

        Returns:
            Mapping of article ID to detail URL.
        """
        links: dict[str, str] = {}
        search_text = html_text.replace("\\/", "/")
        for match in re.finditer(r'/doc/journal/[^"\'<>\s]+', search_text):
            raw_path = html.unescape(match.group(0))
            path = raw_path.split("#", 1)[0]
            article_path = path.split("/doc/journal/")[-1].split("?", 1)[0].strip("/")
            if not article_path:
                continue
            article_id = article_path.split("/")[-1]
            if not article_id:
                continue
            url = path if path.startswith("http") else f"{BASE_URL}{path}"
            if article_id not in links:
                links[article_id] = url
        return links

    async def fetch_article_detail(self, url: str) -> dict[str, Any] | None:
        """
        Fetch a detail page and extract resData.

        Args:
            url: Article detail URL.

        Returns:
            resData dictionary or None.
        """
        payload = await self.fetch_nuxt_payload(url)
        if payload is None:
            return None
        return extract_res_data(payload)

    async def enrich_articles_with_details(
        self, articles: list[dict[str, Any]], doc_links: dict[str, str]
    ) -> None:
        """
        Enrich articles with abstract, DOI, and publish date from detail pages.

        Args:
            articles: List of normalized article dictionaries.
            doc_links: Mapping of article ID to detail URL.

        Returns:
            None.
        """
        if not articles or not doc_links:
            return
        semaphore = asyncio.Semaphore(5)

        async def fetch_and_update(article: dict[str, Any]) -> None:
            article_id = article.get("id")
            if article_id is None:
                return
            article_key = str(article_id)
            url = doc_links.get(article_key)
            if not url:
                return
            if (
                article.get("abstract")
                and article.get("doi")
                and article.get("publishDate")
            ):
                return
            detail = None
            for attempt in range(3):
                async with semaphore:
                    detail = await self.fetch_article_detail(url)
                if isinstance(detail, dict):
                    break
                await asyncio.sleep(0.5 * (attempt + 1))
            if not isinstance(detail, dict):
                return
            if not article.get("abstract"):
                article["abstract"] = pick_first(detail, "abstr", "abstract", "summary")
            if not article.get("doi"):
                article["doi"] = normalize_doi(pick_first(detail, "doi", "DOI"))
            if not article.get("publishDate"):
                article["publishDate"] = pick_first(
                    detail, "pubDate", "publishDate", "publishTime", "date"
                )

        tasks = [fetch_and_update(article) for article in articles]
        if tasks:
            await asyncio.gather(*tasks)

    async def search_journal_by_issn(self, issn: str) -> dict[str, Any] | None:
        """
        Search for a journal by ISSN.

        Args:
            issn: ISSN string.

        Returns:
            Journal dictionary or None.
        """
        if not issn:
            return None
        normalized = normalize_issn(issn)
        url = f"{BASE_URL}/journal/search?k={issn}"
        payload = await self.fetch_nuxt_payload(url)
        if payload is None:
            return None
        records = self.extract_search_records(payload)
        for record in records:
            item_issn = pick_first(record, "issn", "ISSN", "journalIssn")
            if not item_issn:
                continue
            if normalize_issn(str(item_issn)) != normalized:
                continue
            return self.normalize_search_record(record)
        return None

    async def search_journal_by_title(self, title: str) -> dict[str, Any] | None:
        """
        Search for a journal by title keyword.

        Args:
            title: Journal title keyword.

        Returns:
            Journal dictionary or None.
        """
        keyword = title.strip()
        if not keyword:
            return None
        url = f"{BASE_URL}/journal/search?k={keyword}"
        payload = await self.fetch_nuxt_payload(url)
        if payload is None:
            return None
        records = self.extract_search_records(payload)
        if not records:
            return None
        normalized = normalize_keyword(keyword)
        for record in records:
            name = pick_first(record, "journalName", "name", "title")
            if name and normalize_keyword(str(name)) == normalized:
                return self.normalize_search_record(record)
        return self.normalize_search_record(records[0])

    def extract_search_records(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract journal search records from a Nuxt payload.

        Args:
            payload: Parsed Nuxt payload.

        Returns:
            List of journal record dictionaries.
        """
        data_items = payload.get("data")
        if not isinstance(data_items, list) or not data_items:
            return []
        first = data_items[0]
        if not isinstance(first, dict):
            return []
        list_data = first.get("listData")
        if not isinstance(list_data, dict):
            return []
        records = list_data.get("records")
        if not isinstance(records, list):
            return []
        return [record for record in records if isinstance(record, dict)]

    def normalize_search_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize a journal search record into a consistent schema.

        Args:
            record: Raw journal record dictionary.

        Returns:
            Normalized journal dictionary.
        """
        journal_id = pick_first(record, "journalId", "journalID", "id", "gch", "code")
        journal_name = pick_first(record, "journalName", "name", "title")
        issn = pick_first(record, "issn", "ISSN", "journalIssn")
        cnno = pick_first(record, "cnno", "cnNo", "cn")
        publisher = pick_first(record, "publisher", "press", "publisherName")
        url_value = pick_first(record, "url")
        if journal_id and not url_value:
            url_value = f"{BASE_URL}/journal/{journal_id}/{journal_id}"
        return {
            "journalId": str(journal_id) if journal_id is not None else "",
            "name": str(journal_name) if journal_name is not None else "",
            "issn": str(issn) if issn is not None else "",
            "cnno": str(cnno) if cnno is not None else "",
            "publisher": str(publisher) if publisher is not None else "",
            "url": str(url_value) if url_value is not None else "",
        }

    async def get_journal_details(self, journal_id: str) -> dict[str, Any] | None:
        """
        Get journal details including years and issues.

        Args:
            journal_id: CQVIP journal identifier.

        Returns:
            Journal details dictionary or None.
        """
        if not journal_id:
            return None
        url = f"{BASE_URL}/journal/{journal_id}/{journal_id}"
        payload = await self.fetch_nuxt_payload(url)
        if payload is None:
            return None
        self._update_state_from_payload(payload)
        periodical = extract_periodical(payload)
        years = normalize_years(payload)
        available_years = extract_available_years(payload)
        if not years or (available_years and len(years) < len(available_years)):
            api_years = await self.fetch_years_via_api(journal_id)
            if api_years:
                api_years = sorted(api_years, reverse=True)
                existing_by_year = {
                    year.get("year"): year
                    for year in years
                    if isinstance(year.get("year"), int)
                }
                merged_years: list[dict[str, Any]] = []
                for year_value in api_years:
                    existing = existing_by_year.get(year_value)
                    if existing and existing.get("issues"):
                        merged_years.append(existing)
                        continue
                    issues = await self.fetch_issues_via_api(journal_id, year_value)
                    merged_years.append(
                        {
                            "year": year_value,
                            "issueCount": len(issues),
                            "issues": issues,
                        }
                    )
                years = merged_years
        total_years = len(years)
        total_issues = sum(year.get("issueCount", 0) for year in years)
        info = periodical or {}
        return {
            "journalId": info.get("journalId") or str(journal_id),
            "journalName": info.get("journalName") or "",
            "issn": info.get("issn") or "",
            "cnno": info.get("cnno") or "",
            "years": years,
            "totalYears": total_years,
            "totalIssues": total_issues,
        }

    async def get_issue_articles(
        self, journal_id: str, issue_id: str, enrich: bool = True
    ) -> dict[str, Any] | None:
        """
        Get articles for a journal issue.

        Args:
            journal_id: CQVIP journal identifier.
            issue_id: CQVIP issue identifier.
            enrich: Whether to enrich articles with detail pages.

        Returns:
            Issue article dictionary or None.
        """
        if not journal_id or not issue_id:
            return None
        url = f"{BASE_URL}/journal/{journal_id}/{issue_id}"
        page_payload = await self.fetch_page_payload(url)
        if page_payload is None:
            return None
        html_text, payload = page_payload
        self._update_state_from_payload(payload)
        periodical: dict[str, Any] = extract_periodical(payload) or {}
        raw_articles = self.extract_catalog_articles(payload)
        if not raw_articles:
            raw_articles = select_best_article_list(payload)
        articles: list[dict[str, Any]] = []
        for item in raw_articles:
            normalized = self.normalize_article(item)
            if normalized:
                articles.append(normalized)
        if enrich:
            doi_map = extract_doi_map(payload)
            if doi_map:
                for article in articles:
                    article_id = article.get("id")
                    if article_id is None:
                        continue
                    if article.get("doi"):
                        continue
                    doi = doi_map.get(str(article_id))
                    if doi:
                        article["doi"] = doi
        doc_links = self.extract_doc_links(html_text)
        detail_links = collect_detail_links(articles, doc_links)
        if enrich and detail_links:
            await self.enrich_articles_with_details(articles, detail_links)
        total_pages = 0
        pages_available = False
        for article in articles:
            count = article.get("pages", {}).get("count")
            if isinstance(count, int):
                total_pages += count
                pages_available = True
        return {
            "journal": {
                "journalId": periodical.get("journalId") or str(journal_id),
                "journalName": periodical.get("journalName") or "",
                "issn": periodical.get("issn") or "",
                "cnno": periodical.get("cnno") or "",
            },
            "issueId": str(issue_id),
            "totalArticles": len(articles),
            "totalPages": total_pages if pages_available else 0,
            "articles": articles,
        }

    async def fetch_nuxt_payload(self, url: str) -> dict[str, Any] | None:
        """
        Fetch and parse the Nuxt payload from a CQVIP page.

        Args:
            url: Target URL.

        Returns:
            Parsed payload dictionary or None.
        """
        response = await self._request_with_retry("GET", url)
        if response is None or response.status_code != 200:
            return None
        script = self.extract_nuxt_script(response.text)
        if not script:
            return None
        return await asyncio.to_thread(self.execute_nuxt_script, script)

    def extract_catalog_articles(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract article items from the catalog section of a payload.

        Args:
            payload: Parsed Nuxt payload.

        Returns:
            List of article dictionaries.
        """
        data_items = payload.get("data")
        if not isinstance(data_items, list) or len(data_items) < 2:
            return []
        second = data_items[1]
        if not isinstance(second, dict):
            return []
        catalog = second.get("catalog")
        if not isinstance(catalog, dict):
            return []
        records = catalog.get("records")
        if not isinstance(records, list):
            return []
        articles: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            category = pick_first(record, "name", "title")
            children = record.get("children") or []
            if not isinstance(children, list):
                continue
            for child in children:
                if not isinstance(child, dict):
                    continue
                item = dict(child)
                if category and "category" not in item:
                    item["category"] = category
                articles.append(item)
        return articles

    def extract_nuxt_script(self, html: str) -> str | None:
        """
        Extract the script content containing window.__NUXT__.

        Args:
            html: HTML response text.

        Returns:
            JavaScript content or None.
        """
        tree = HTMLParser(html)
        for node in tree.css("script"):
            text = node.text()
            if text and "window.__NUXT__" in text:
                return text
        return None

    def execute_nuxt_script(self, script: str) -> dict[str, Any] | None:
        """
        Execute a Nuxt script in QuickJS and parse the JSON output.

        Args:
            script: JavaScript content.

        Returns:
            Parsed JSON payload or None.
        """
        try:
            ctx = quickjs.Context()
            ctx.eval(
                "var window = {}; "
                "var self = window; "
                "if (typeof globalThis !== 'undefined') { "
                "globalThis.window = window; "
                "globalThis.self = window; "
                "}"
            )
            ctx.eval(script)
            payload_text = ctx.eval("JSON.stringify(window.__NUXT__)")
            if not payload_text:
                return None
            if not isinstance(payload_text, str):
                payload_text = str(payload_text)
            return json.loads(payload_text)
        except (quickjs.JSException, json.JSONDecodeError, TypeError, ValueError):
            return None

    def normalize_article(self, article: dict[str, Any]) -> dict[str, Any] | None:
        """
        Normalize a raw article dictionary.

        Args:
            article: Raw article dictionary.

        Returns:
            Normalized article dictionary or None.
        """
        if not isinstance(article, dict):
            return None
        article_id = pick_first(article, "id", "articleId", "article_id")
        title = pick_first(article, "title", "titleCn", "titleCN", "name")
        if article_id is None or title is None:
            return None
        authors_raw = pick_first(
            article, "authors", "author", "authorList", "authorInfo"
        )
        authors = normalize_authors(authors_raw)
        keywords_raw = pick_first(
            article, "keywords", "keyWords", "keyword", "keywordInfo"
        )
        keywords = normalize_string_list(keywords_raw)
        funds_raw = pick_first(
            article, "funds", "funding", "fund", "fundInfo", "fundProjectInfo"
        )
        funds = normalize_string_list(funds_raw)
        organizations_raw = pick_first(
            article, "organizations", "orgs", "organization", "organInfo"
        )
        organizations = normalize_string_list(organizations_raw)
        pages = normalize_pages(article)
        category = pick_first(article, "category", "catalogName", "sectionName")
        if not category and isinstance(article.get("journalColumnInfo"), list):
            for item in article["journalColumnInfo"]:
                if isinstance(item, dict):
                    category = pick_first(item, "name", "title")
                    if category:
                        break
        first_author = article.get("firstAuthor")
        if isinstance(first_author, dict):
            raw_id = pick_first(first_author, "id")
            try:
                author_id = int(raw_id) if raw_id is not None else 0
            except (TypeError, ValueError):
                author_id = 0
            first_author_entry = {
                "name": str(pick_first(first_author, "name", "authorName") or ""),
                "id": author_id,
            }
        else:
            first_author_entry = None
        doi = normalize_doi(pick_first(article, "doi", "DOI"))
        detail_url = normalize_detail_url(
            pick_first(
                article,
                "detailUrl",
                "detailURL",
                "docUrl",
                "docurl",
                "url",
                "href",
                "link",
            )
        )
        return {
            "id": str(article_id),
            "title": str(title),
            "category": category or "",
            "authors": authors,
            "firstAuthor": first_author_entry,
            "keywords": keywords,
            "abstract": pick_first(article, "abstract", "summary", "abstr"),
            "pages": pages,
            "language": pick_first(article, "language", "lang", "paperLanguage")
            or "zh",
            "isPdf": bool(pick_first(article, "isPdf", "pdf", "hasPdf", "pdfFlag")),
            "doi": doi,
            "publishDate": pick_first(
                article, "publishDate", "pubDate", "publishTime", "date"
            ),
            "funds": funds,
            "organizations": organizations,
            "detailUrl": detail_url,
        }
