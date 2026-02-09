# API Reference

FastAPI REST API for querying the article index databases.

**Base URL**: `http://localhost:8000`

All endpoints are prefixed with `/api`.

## Database Selection

All endpoints accept an optional `db` query parameter specifying which SQLite database to query under `data/index/`.

- If exactly one `.sqlite` file exists, it is used automatically
- If multiple databases exist and `db` is omitted, returns HTTP 400
- Accepts filenames with or without the `.sqlite` extension

Examples: `?db=utd24.sqlite`, `?db=utd24`

## Pagination

Collection endpoints support offset-based and cursor-based pagination.

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Page size (max 200) |
| `offset` | int | 0 | Number of items to skip |
| `cursor` | string | - | Keyset cursor (articles only) |

**Response format**:

```json
{
  "items": [...],
  "page": {
    "total": 1234,
    "limit": 50,
    "offset": 0,
    "next_cursor": "2024-06-01|685706566",
    "has_more": true
  }
}
```

### Cursor Pagination (Articles)

For article listings sorted by date, keyset cursor pagination is available. The cursor format is `{date}|{article_id}`. Pass the `next_cursor` value from the response as the `cursor` parameter to fetch the next page.

## Sorting

Use the `sort` parameter with comma-separated field names:

- `field` or `field:asc` for ascending
- `-field` or `field:desc` for descending

Example: `sort=-date`, `sort=scimago_rank:desc,title:asc`

Invalid sort fields return HTTP 400.

## Full-Text Search

Article listing supports FTS5 full-text search via the `q` parameter:

```
GET /api/articles?q=earnings OR disclosure
```

The query is matched against `title`, `abstract`, `doi`, `authors`, and `journal_title`. When the simple tokenizer is enabled (CJK support), non-CJK queries are wrapped in `simple_query()` automatically.

## Endpoints

### Health

```
GET /api/health
```

Returns `{"status": "ok"}`.

---

### Articles

#### List Articles

```
GET /api/articles
```

**Query parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `db` | string | Database name |
| `q` | string | Full-text search query |
| `journal_id` | int (multi) | Filter by journal ID(s) |
| `issue_id` | int | Filter by issue ID |
| `year` | int | Filter by publication year |
| `area` | string (multi) | Filter by research area(s) |
| `in_press` | bool | Filter by in-press status |
| `open_access` | bool | Filter by open access |
| `suppressed` | bool | Filter by suppression |
| `within_library_holdings` | bool | Filter by library holdings |
| `date_from` | string | Start date (ISO-8601) |
| `date_to` | string | End date (ISO-8601) |
| `doi` | string | Filter by DOI |
| `pmid` | string | Filter by PubMed ID |
| `sort` | string | Sort field |
| `limit` | int | Page size (default 50, max 200) |
| `offset` | int | Offset for pagination |
| `cursor` | string | Keyset cursor |
| `include_total` | bool | Include total count (default true) |

**Sort fields**: `date`

**Response model**: `ArticlePage`

The endpoint uses the `article_listing` materialized table when available, falling back to direct `articles` table joins.

#### Get Article

```
GET /api/articles/{article_id}
```

Returns a single `ArticleRecord` with full metadata including journal title, volume, and number from joined tables.

Returns 404 if not found.

#### Redirect to Full Text

```
GET /api/articles/{article_id}/fulltext
```

Redirects (HTTP 302) to the article's full-text URL. Priority order:

1. DOI URL (`https://doi.org/{doi}`)
2. `full_text_file`
3. `libkey_full_text_file`
4. CQVIP detail URL (for Weipu journals, identified by `library_id = "-1"`)

Returns 404 if no full-text URL is available.

---

### Journals

#### List Journals

```
GET /api/journals
```

**Query parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `db` | string | Database name |
| `area` | string | Filter by research area |
| `library_id` | string | Filter by BrowZine library ID |
| `available` | bool | Filter by availability |
| `has_articles` | bool | Filter by article availability |
| `year` | int | Filter by journals with issues in a given year |
| `scimago_min` | float | Minimum SJR ranking |
| `scimago_max` | float | Maximum SJR ranking |
| `sort` | string | Sort fields |
| `limit` | int | Page size |
| `offset` | int | Offset |

**Sort fields**: `journal_id`, `title`, `issn`, `eissn`, `scimago_rank`, `available`, `has_articles`

**Response model**: `JournalPage`

#### Get Journal

```
GET /api/journals/{journal_id}
```

Returns a single `JournalRecord`. Returns 404 if not found.

---

### Issues

#### List Issues

```
GET /api/issues
```

**Query parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `db` | string | Database name |
| `journal_id` | int | Filter by journal ID |
| `year` | int | Filter by publication year |
| `is_valid_issue` | bool | Filter by valid issue flag |
| `suppressed` | bool | Filter by suppression |
| `embargoed` | bool | Filter by embargo |
| `within_subscription` | bool | Filter by subscription access |
| `sort` | string | Sort fields |
| `limit` | int | Page size |
| `offset` | int | Offset |

**Sort fields**: `issue_id`, `publication_year`, `title`, `date`, `volume`, `number`

**Response model**: `IssuePage`

#### Get Issue

```
GET /api/issues/{issue_id}
```

Returns a single `IssueRecord`. Returns 404 if not found.

---

### Metadata

#### List Databases

```
GET /api/meta/databases
```

Returns a list of available database filenames (`list[str]`).

#### List Areas

```
GET /api/meta/areas
```

Returns research areas with article counts, sorted alphabetically.

```json
[
  { "value": "Accounting", "count": 12345 },
  { "value": "Finance", "count": 8901 }
]
```

#### List Journal Options

```
GET /api/meta/journals
```

Returns journal ID and title pairs for building filter dropdowns.

```json
[
  { "journal_id": 34781, "title": "The Accounting Review" }
]
```

#### List Libraries

```
GET /api/meta/libraries
```

Returns library IDs with journal counts, sorted by ID.

```json
[
  { "value": "3050", "count": 24 }
]
```

#### List Years

```
GET /api/years
```

Returns publication years with issue and journal counts.

```json
[
  { "year": 2024, "issue_count": 350, "journal_count": 24 }
]
```

---

### Weekly Updates

```
GET /api/weekly-updates
```

**Query parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `window_days` | int | 7 | Lookback window in days (1-31) |

Returns recently added articles grouped by database and journal, sourced from change manifests in `data/push_state/*.changes.json`.

**Response**:

```json
{
  "generated_at": "2026-02-10T08:00:00Z",
  "window_start": "2026-02-03T08:00:00Z",
  "window_end": "2026-02-10T08:00:00Z",
  "databases": [
    {
      "db_name": "utd24",
      "run_id": "...",
      "generated_at": "2026-02-10T08:00:00Z",
      "new_article_count": 15,
      "journals": [
        {
          "journal_id": 34781,
          "journal_title": "The Accounting Review",
          "new_article_count": 5,
          "articles": [
            {
              "article_id": 685706566,
              "journal_id": 34781,
              "title": "Risk Choice and Voluntary Disclosure",
              "date": "2025-12-08",
              "doi": "10.2308/TAR-2021-0123",
              "journal_title": "The Accounting Review",
              "open_access": 0,
              "in_press": 0
            }
          ]
        }
      ]
    }
  ]
}
```

---

## Response Models

### ArticleRecord

| Field | Type |
|-------|------|
| `article_id` | int |
| `journal_id` | int |
| `issue_id` | int or null |
| `sync_id` | int or null |
| `title` | string or null |
| `date` | string or null |
| `authors` | string or null |
| `start_page` | string or null |
| `end_page` | string or null |
| `abstract` | string or null |
| `doi` | string or null |
| `pmid` | string or null |
| `permalink` | string or null |
| `suppressed` | int or null |
| `in_press` | int or null |
| `open_access` | int or null |
| `journal_title` | string or null |
| `volume` | string or null |
| `number` | string or null |
| *(plus all URL and metadata fields)* | |

### JournalRecord

| Field | Type |
|-------|------|
| `journal_id` | int |
| `library_id` | string |
| `title` | string or null |
| `issn` | string or null |
| `eissn` | string or null |
| `scimago_rank` | float or null |
| `cover_url` | string or null |
| `available` | int or null |
| `source_csv` | string or null |
| `area` | string or null |

### IssueRecord

| Field | Type |
|-------|------|
| `issue_id` | int |
| `journal_id` | int |
| `publication_year` | int or null |
| `title` | string or null |
| `volume` | string or null |
| `number` | string or null |
| `date` | string or null |

### PageMeta

| Field | Type | Description |
|-------|------|-------------|
| `total` | int or null | Total matching items |
| `limit` | int | Page size |
| `offset` | int | Current offset |
| `next_cursor` | string or null | Cursor for next page |
| `has_more` | bool or null | Whether more pages exist |

## Middleware

- **CORS**: All origins allowed
- **Cache Control**: 5-minute public cache with 10-minute stale-while-revalidate for `/api/articles` and `/api/meta/*`

## Error Responses

| Status | Cause |
|--------|-------|
| 400 | Invalid sort field, missing `db` when multiple databases exist |
| 404 | Database, journal, issue, or article not found |
