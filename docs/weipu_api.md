# WeipuAPI (CQVIP) Reference

This document describes the WeipuAPI client used by Paper Scanner to extract Chinese journal article metadata from the CQVIP website (https://www.cqvip.com/).

## Overview

CQVIP (China Science Periodical Database) uses Nuxt.js server-side rendering. Article data is embedded in HTML as an obfuscated JavaScript function (`window.__NUXT__`) that cannot be parsed as plain JSON. The client extracts this data using HTTP requests, HTML parsing, and JavaScript execution.

## Architecture

```
HTTP Request (httpx)
    │
    ▼
HTML Parsing (selectolax)
    │
    ▼
Extract <script> containing window.__NUXT__
    │
    ▼
Execute obfuscated JS (QuickJS)
    │
    ▼
Parse JSON & extract article metadata
```

For endpoints requiring authentication, the client computes:
- **HMAC-SHA1 signatures** for HTTP headers (timestamp + app ID)
- **DES-ECB encryption** for request body signing (via pure Python implementation)

## URL Structure

| Resource | URL Pattern |
|----------|-------------|
| Journal search | `https://www.cqvip.com/journal/search?k={issn}` |
| Journal details | `https://www.cqvip.com/journal/{journal_id}/{journal_id}` |
| Issue articles | `https://www.cqvip.com/journal/{journal_id}/{issue_id}` |
| Article detail | `https://www.cqvip.com/doc/journal/{article_id}?sign=...` |
| API: Get years | `https://www.cqvip.com/newsite/journal/getYears` |
| API: Get issues | `https://www.cqvip.com/newsite/journal/getNums` |

## Client API

### Class: `WeipuAPISelectolax`

```python
from scripts.weipu import WeipuAPISelectolax

client = WeipuAPISelectolax(timeout=20.0)
```

### `search_journal_by_issn(issn)`

Search for a journal by ISSN.

```python
async def search_journal_by_issn(issn: str) -> dict[str, Any] | None
```

**Returns**:

```python
{
    "journalId": "95499X",
    "name": "管理世界",
    "issn": "1002-5502",
    "cnno": "11-1235/F",
    "publisher": "...",
    "url": "https://www.cqvip.com/journal/95499X/95499X"
}
```

### `search_journal_by_title(title)`

Search for a journal by title keyword.

```python
async def search_journal_by_title(title: str) -> dict[str, Any] | None
```

### `get_journal_details(journal_id)`

Get complete journal metadata including all years and issues.

```python
async def get_journal_details(journal_id: str) -> dict[str, Any] | None
```

The HTML page typically only embeds the most recent year's issues. The client automatically falls back to the signed `/newsite` API endpoints to retrieve all years and issue IDs.

**Returns**:

```python
{
    "journalId": "95499X",
    "journalName": "管理世界",
    "issn": "1002-5502",
    "cnno": "11-1235/F",
    "years": [
        {
            "year": 2025,
            "issueCount": 12,
            "issues": [
                {
                    "id": "8687909",
                    "name": "12",
                    "coverImage": "https://..."
                }
            ]
        }
    ],
    "totalYears": 41,
    "totalIssues": 492
}
```

### `get_issue_articles(journal_id, issue_id, enrich=True)`

Extract all articles from a specific issue.

```python
async def get_issue_articles(
    journal_id: str,
    issue_id: str,
    enrich: bool = True
) -> dict[str, Any] | None
```

When `enrich=True`, the client follows individual article detail links to merge `abstract`, `doi`, and `pubDate` into each article record (with a concurrency limit of 5).

**Returns**:

```python
{
    "journal": {
        "journalId": "95499X",
        "journalName": "管理世界",
        "issn": "1002-5502",
        "cnno": "11-1235/F"
    },
    "issueId": "8687909",
    "totalArticles": 20,
    "totalPages": 223,
    "articles": [
        {
            "id": "7202582565",
            "title": "美欧关税与全球新能源汽车供应链的重构",
            "category": "重大选题征文",
            "detailUrl": "https://www.cqvip.com/doc/journal/7202582565?sign=...",
            "authors": [
                {
                    "name": "李坤望",
                    "name_en": "Li Kunwang",
                    "is_corresponding": false,
                    "order": 1
                },
                {
                    "name": "王方",
                    "name_en": "Wang Fang",
                    "is_corresponding": true,
                    "order": 2
                }
            ],
            "firstAuthor": { "name": "李坤望", "id": 3759 },
            "keywords": ["关税", "新能源汽车", "供应链"],
            "abstract": "文章摘要内容...",
            "pages": { "begin": "1", "end": "20", "count": 20 },
            "language": "zh",
            "isPdf": true,
            "doi": "10.19744/j...",
            "funds": ["国家自然科学基金", "教育部人文社会科学研究项目"],
            "organizations": ["浙江大学经济学院", "中国人民大学商学院"]
        }
    ]
}
```

### `fetch_years_via_api(journal_id)`

Get available publication years via the signed API endpoint.

```python
async def fetch_years_via_api(journal_id: str) -> list[int]
```

### `fetch_issues_via_api(journal_id, year)`

Get issues for a specific year via the signed API endpoint.

```python
async def fetch_issues_via_api(journal_id: str, year: int) -> list[dict[str, Any]]
```

### `aclose()`

Close the HTTP client and release resources.

```python
async def aclose() -> None
```

## Data Types

### Article

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Article ID |
| `title` | str | Article title |
| `category` | str | Section/category name |
| `authors` | list[Author] | Author list |
| `firstAuthor` | dict | First author name and ID |
| `keywords` | list[str] | Keywords |
| `abstract` | str or None | Abstract text |
| `pages` | PageInfo | Page range |
| `language` | str | Language code (`zh`, `en`, `zh_en`) |
| `isPdf` | bool | PDF availability |
| `doi` | str or None | DOI |
| `funds` | list[str] | Funding sources |
| `organizations` | list[str] | Author affiliations |

### Author

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Chinese name |
| `name_en` | str or None | English name |
| `is_corresponding` | bool | Corresponding author flag |
| `order` | int | Author order (1-indexed) |

### PageInfo

| Field | Type | Description |
|-------|------|-------------|
| `begin` | str | Start page |
| `end` | str | End page |
| `count` | int or None | Total pages |

## Implementation Details

### Nuxt Payload Extraction

CQVIP embeds page data as an obfuscated JavaScript IIFE:

```javascript
window.__NUXT__=(function(a,b,c,d,...){
  return {layout:"default",data:[...],state:{...}}
})(null,1,"正常","龙猫",...)
```

The client:
1. Parses HTML with selectolax to find the `<script>` tag
2. Executes the JavaScript using QuickJS (not Node.js subprocess)
3. Parses the resulting JSON

### Signed API Requests

The `/newsite` API endpoints require request signing:

1. **HMAC-SHA1 header**: Computed from timestamp and `CQVIP_APP_ID`
2. **DES-ECB body signature**: Computed using `CQVIP_SIGNATURE_SECRET` with a pure Python DES implementation (`scripts/weipu/des.py`)
3. **Server time synchronization**: The client tracks server time offset from Nuxt payloads

### Article Enrichment

The issue page often lacks abstracts, DOIs, and publication dates. The client:
1. Extracts article detail URLs from the issue HTML using regex
2. Fetches each detail page concurrently (semaphore limit: 5)
3. Merges `abstract`, `doi`, and `pubDate` into the article records

### Retry Logic

- Default retry attempts: 3
- Base delay: 0.75 seconds with exponential backoff
- HTTP errors and timeouts trigger retries

## Performance

| Metric | Value |
|--------|-------|
| Speed per issue | 2-4 seconds |
| Memory usage | ~60 MB |
| Success rate | ~90% (with rate limiting) |

### Rate Limiting Recommendations

- Sequential requests: 2-4 second delay
- Concurrent requests: max 3-5 simultaneous, 1-2 second delay each
- High concurrency increases the risk of being blocked

## Common ISSN Numbers

| ISSN | Journal Name | Field |
|------|-------------|-------|
| 1002-5502 | 管理世界 | Management |
| 1000-6788 | 会计研究 | Accounting |
| 1002-0241 | 经济学动态 | Economics |
| 1000-596X | 中国工业经济 | Industrial Economics |

## Troubleshooting

### QuickJS execution fails

Verify the `quickjs` Python package is installed. Unlike the older implementation, the current client uses QuickJS via Python bindings, not a Node.js subprocess.

### No data returned

Possible causes:
- Invalid journal or issue ID
- Rate limiting (add delays between requests)
- Website structure changed (check if CQVIP updated their frontend)

### Encoding errors

Always use UTF-8 encoding. For CSV export, use `utf-8-sig` to include BOM for Excel compatibility.
