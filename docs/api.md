# API Reference

FastAPI backend for querying the BrowZine article index SQLite databases under
`data/index`.

Base URL examples below assume `http://localhost:8000`.

All backend endpoints are exposed under the `/api` prefix.

## Database Selection

All endpoints accept an optional `db` query parameter pointing to a database
filename under `data/index`. If omitted:

- If exactly one `.sqlite` file exists, it will be used.
- If multiple databases exist, the API returns HTTP 400 and asks for `db`.

Examples:

- `?db=utd24.sqlite`
- `?db=utd24`

## Pagination

Collection endpoints support:

- `limit` (default 50, max 200)
- `offset` (default 0)

Responses include:

```json
{
  "items": [],
  "page": { "total": 0, "limit": 50, "offset": 0 }
}
```

## Sorting

Use `sort` with comma-separated fields:

- `field:asc`
- `field:desc`
- `-field` (descending)

Example:

- `sort=publication_year:desc,issue_id:asc`

Supported sort fields are listed per endpoint.

## Full-Text Search (FTS5)

Articles support FTS5 via `q` against `article_search`.

Example:

- `q=earnings OR disclosure`

## Endpoints

### Health

`GET /api/health`

Returns:

```json
{ "status": "ok" }
```

### Metadata

`GET /api/meta/areas`

Returns a list of journal areas with counts.

`GET /api/meta/libraries`

Returns a list of library IDs with counts.

### Years

`GET /api/years`

Returns publication years with issue and journal counts.

### Journals

`GET /api/journals`

Filters:

- `area`
- `library_id`
- `available` (bool)
- `has_articles` (bool)
- `year` (journals with issues in a given year)
- `scimago_min`
- `scimago_max`

Sorting fields:

- `journal_id`
- `title`
- `issn`
- `eissn`
- `scimago_rank`
- `available`
- `has_articles`

Example:

`/api/journals?area=Accounting&available=true&sort=scimago_rank:desc`

`GET /api/journals/{journal_id}`

Returns a single journal record (404 if not found).

### Issues

`GET /api/issues`

Filters:

- `journal_id`
- `year`
- `is_valid_issue` (bool)
- `suppressed` (bool)
- `embargoed` (bool)
- `within_subscription` (bool)

Sorting fields:

- `issue_id`
- `publication_year`
- `title`
- `date`
- `volume`
- `number`

Example:

`/api/issues?journal_id=34781&year=2024&sort=publication_year:desc`

`GET /api/issues/{issue_id}`

Returns a single issue record (404 if not found).

### Articles

`GET /api/articles`

Filters:

- `journal_id`
- `issue_id`
- `year` (via joined issues)
- `in_press` (bool)
- `open_access` (bool)
- `suppressed` (bool)
- `within_library_holdings` (bool)
- `date_from` / `date_to` (ISO strings)
- `doi`
- `pmid`
- `q` (FTS5 query)

Sorting fields:

- `article_id`
- `title`
- `date`
- `journal_id`
- `issue_id`
- `open_access`
- `in_press`
- `doi`

Example:

`/api/articles?journal_id=34781&year=2024&q=earnings OR disclosure&sort=date:desc`

`GET /api/articles/{article_id}`

Returns a single article record (404 if not found).

## Error Responses

- `400 Bad Request`: invalid sort field.
- `404 Not Found`: database, journal, issue, or article not found.
