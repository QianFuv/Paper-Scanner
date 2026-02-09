# BrowZine API Reference

This document describes the BrowZine API (Third Iron API v2) used by Paper Scanner to fetch journal and article metadata.

**Base URL**: `https://api.thirdiron.com/v2`

## Authentication

All requests require a Bearer token obtained from the token endpoint.

### Get API Token

```
POST /v2/api-tokens
```

**Headers**:

| Header | Value |
|--------|-------|
| `Accept` | `application/json, text/javascript, */*; q=0.01` |
| `Content-Type` | `application/json; charset=UTF-8` |
| `Referer` | `https://browzine.com/` |

**Body**:

```json
{
  "libraryId": "3050",
  "returnPreproxy": true,
  "client": "bzweb",
  "forceAuth": false
}
```

**Response**:

```json
{
  "api-tokens": [
    {
      "id": "1ebc4969-d577-410a-9a72-7c1b56b94ecb",
      "expires_at": "2026-02-18T05:10:30.933Z",
      "links": {
        "library": { "type": "libraries", "id": "3050" }
      },
      "type": "api-tokens"
    }
  ]
}
```

Token expiry is approximately 30 days. The client caches tokens per library and refreshes them automatically when they expire (with a 300-second buffer).

## Request Format

All data endpoints use the following headers:

| Header | Value |
|--------|-------|
| `Accept` | `application/vnd.api+json` |
| `Authorization` | `Bearer {token}` |
| `Referer` | `https://browzine.com/` |

All endpoints require `client=bzweb` as a query parameter.

## Endpoints

### Get Library Information

```
GET /v2/libraries/{library_id}?client=bzweb
```

Returns library metadata including name, logo, and available services.

### Get Journal Information

```
GET /v2/libraries/{library_id}/journals/{journal_id}?client=bzweb
```

Returns journal metadata.

**Response fields**:

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Journal ID |
| `title` | string | Journal title |
| `scimagoRank` | string | SJR ranking |
| `coverURL` | string | Cover image URL |
| `available` | bool | Whether journal is available in this library |
| `tocDataApprovedAndLive` | bool | TOC data availability |
| `hasArticles` | bool | Whether articles are indexed |

### Search Journals by ISSN

```
GET /v2/libraries/{library_id}/search?client=bzweb&query={issn}
```

**Accept header**: `application/json, text/javascript, */*; q=0.01`

Returns matching journals. ISSN can be provided with or without hyphens.

**Response**:

```json
{
  "data": [
    {
      "id": 34781,
      "title": "The Accounting Review (00014826)",
      "name": "The Accounting Review",
      "scimago_rank": "4.045",
      "has_articles": true,
      "issn_no_hyphen": "00014826",
      "eissn_no_hyphen": "15587967",
      "toc_data_approved_and_live": true,
      "type": "journals"
    }
  ]
}
```

### Get Publication Years

```
GET /v2/libraries/{library_id}/journals/{journal_id}/publication-years?client=bzweb
```

Returns all available publication years for a journal.

**Response**:

```json
{
  "publicationYears": [
    { "id": 2026, "type": "publicationYears" },
    { "id": 2025, "type": "publicationYears" }
  ]
}
```

### Get Issues by Year

```
GET /v2/libraries/{library_id}/journals/{journal_id}/issues?client=bzweb&publication-year={year}
```

Returns all issues for a journal in a specific year. Omit `publication-year` for the current year.

**Response**:

```json
{
  "issues": [
    {
      "id": 641161731,
      "type": "issues",
      "attributes": {
        "isValidIssue": true,
        "title": "Vol. 101 Issue 1",
        "volume": "101",
        "number": "1",
        "date": "2026-01-01",
        "journal": 34781,
        "suppressed": false,
        "embargoed": false,
        "withinSubscription": true
      }
    }
  ]
}
```

### Get Current Issue

```
GET /v2/libraries/{library_id}/journals/{journal_id}/issues/current?client=bzweb
```

Returns the latest issue. Same response format as issue listing.

### Get Articles from Issue

```
GET /v2/libraries/{library_id}/issues/{issue_id}/articles?client=bzweb
```

Returns all articles in an issue with full metadata.

**Response**:

```json
{
  "data": [
    {
      "id": 685706566,
      "type": "articles",
      "attributes": {
        "syncId": 675149355,
        "title": "Risk Choice and Voluntary Disclosure",
        "date": "2025-12-08",
        "authors": "An, Byeong-Je; Pae, Suil",
        "startPage": "1",
        "endPage": "26",
        "abstract": "This paper presents a model...",
        "doi": "10.2308/TAR-2021-0123",
        "openAccess": false,
        "inPress": false,
        "suppressed": false
      }
    }
  ]
}
```

**Article attributes** (30 fields):

| Field | Description |
|-------|-------------|
| `syncId` | Internal sync identifier |
| `title` | Article title |
| `date` | Publication date |
| `authors` | Comma-separated author names |
| `startPage` / `endPage` | Page range |
| `abstract` | Article abstract (always included) |
| `doi` | Digital Object Identifier |
| `pmid` | PubMed ID |
| `ILLURL` | Interlibrary loan URL |
| `linkResolverOpenurlLink` | OpenURL link |
| `permalink` | Permanent link |
| `openAccess` | Open access flag |
| `inPress` | In-press flag |
| `suppressed` | Suppression status |
| `fullTextFile` | Full-text PDF URL |
| `libkeyFullTextFile` | LibKey full-text URL |
| `contentLocation` | Content access URL |
| `libkeyContentLocation` | LibKey content URL |
| `retractionDoi` | Retraction DOI (if retracted) |
| `retractionDate` | Retraction date |
| `withinLibraryHoldings` | Library holdings flag |
| `browzineWebInContextLink` | BrowZine web link |
| `nomadFallbackURL` | NOMAD fallback URL |

### Get Articles in Press

```
GET /v2/libraries/{library_id}/journals/{journal_id}/articles-in-press?client=bzweb
```

Returns articles published ahead of print. Supports cursor-based pagination.

**Response**:

```json
{
  "data": [...],
  "meta": {
    "cursor": {
      "next": "eyJwYWdlU2l6ZSI6MjU..."
    }
  }
}
```

Pass `cursor` as a query parameter to fetch the next page. The client follows cursors automatically until all pages are retrieved.

## Client Implementation

Paper Scanner wraps the BrowZine API in `scripts/browzine/client.py`:

| Method | Description |
|--------|-------------|
| `get_journal_info(journal_id, library_id)` | Fetch journal metadata |
| `search_by_issn(issn, library_id)` | Search journal by ISSN |
| `get_current_issue(journal_id, library_id)` | Get latest issue |
| `get_publication_years(journal_id, library_id)` | List available years |
| `get_issues_by_year(journal_id, library_id, year)` | Fetch issues for a year |
| `get_articles_from_issue(issue_id, library_id)` | Get articles in an issue |
| `get_articles_in_press(journal_id, library_id)` | Fetch in-press articles (all pages) |

Features:
- Token caching per library with automatic refresh
- Retry logic for transient errors (429, 500, 502, 503, 504)
- Automatic token refresh on 401 responses
- Cursor-based pagination with loop detection for in-press articles

## Library Fallback Resolution

When a journal isn't available in the primary library (`3050`), the system attempts fallback libraries defined in `FALLBACK_LIBRARIES`:

```python
FALLBACK_LIBRARIES = ["215", "866", "72", "853", "554", "371", "230"]
```

The validation process (`scripts/browzine/validation.py`):

1. Check if the journal is available in the target library
2. Verify that the current issue exists and contains articles with content (abstract or full-text)
3. If validation fails, try each fallback library in order
4. If a fallback works, update the CSV with the new library ID and journal ID
5. Search by ISSN is used to find the journal in alternate libraries

## Error Handling

| Status | Meaning | Client Behavior |
|--------|---------|-----------------|
| 200 | Success | Process response |
| 401 | Token expired | Refresh token and retry |
| 404 | Not found | Return `None` |
| 429 | Rate limited | Retry with backoff |
| 500-504 | Server error | Retry up to 2 times |

## Notes

- All requests require `client=bzweb` as a query parameter
- Responses follow the JSON:API specification
- Token expiry is approximately 30 days
- No official rate limit is documented; the client uses retry logic with backoff
- Library ID `3050` corresponds to CEIBS (China Europe International Business School)
