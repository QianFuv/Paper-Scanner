# API Reference

FastAPI backend for querying the BrowZine article index SQLite databases under
`data/index`.

Base URL examples below assume `http://localhost:8000`.

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

## Regex Filtering

Articles support regex filtering applied after FTS:

- `regex` is required to enable regex filtering.
- `q` must be supplied to prefilter via FTS5.
- Regex is applied in application code after FTS.
- If the FTS prefilter matches more than 5,000 rows, the API returns HTTP 400.

Parameters:

- `regex`: Regex pattern.
- `regex_fields`: Comma-separated fields to match.
- `regex_ignore_case`: default `true`.

Allowed `regex_fields`:

- `title`
- `abstract`
- `authors`
- `doi`
- `journal_title`

Example:

- `/articles?q=machine AND learning&regex=transformer&regex_fields=title,abstract`

## Endpoints

### Health

`GET /health`

Returns:

```json
{ "status": "ok" }
```

### Metadata

`GET /meta/areas`

Returns a list of journal areas with counts.

`GET /meta/ranks`

Returns a list of journal ranks with counts.

`GET /meta/libraries`

Returns a list of library IDs with counts.

### Years

`GET /years`

Returns publication years with issue and journal counts.

### Journals

`GET /journals`

Filters:

- `area`
- `rank`
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

`/journals?area=Accounting&rank=utd24&available=true&sort=scimago_rank:desc`

`GET /journals/{journal_id}`

Returns a single journal record (404 if not found).

### Issues

`GET /issues`

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

`/issues?journal_id=34781&year=2024&sort=publication_year:desc`

`GET /issues/{issue_id}`

Returns a single issue record (404 if not found).

### Articles

`GET /articles`

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
- `regex` (regex applied after FTS)
- `regex_fields`
- `regex_ignore_case`

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

`/articles?journal_id=34781&year=2024&q=earnings OR disclosure&sort=date:desc`

Regex example:

`/articles?q=machine AND learning&regex=transformer&regex_fields=title,abstract`

`GET /articles/{article_id}`

Returns a single article record (404 if not found).

## Error Responses

- `400 Bad Request`: invalid sort field, invalid regex, regex without `q`,
  or too many FTS matches for regex filtering.
- `404 Not Found`: database, journal, issue, or article not found.
