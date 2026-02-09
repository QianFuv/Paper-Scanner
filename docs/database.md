# Database Schema

Each CSV file under `data/meta/` produces a corresponding SQLite database at `data/index/<csv_stem>.sqlite`. This document describes the complete schema.

## Configuration

SQLite pragmas applied at initialization:

| Pragma | Value | Purpose |
|--------|-------|---------|
| `journal_mode` | WAL | Write-ahead logging for concurrent reads |
| `foreign_keys` | ON | Enforce referential integrity |
| `synchronous` | NORMAL | Balance safety and performance |
| `busy_timeout` | 30000 ms | Wait time for locked databases |

All timestamps are stored as `TEXT` in UTC ISO-8601 format. Boolean values use `INTEGER` with `0/1` convention.

## Entity Relationship

```
journals (1) ──── (1) journal_meta
    │
    └──── (N) issues (1) ──── (N) articles
                                    │
                                    ├── (1) article_listing  (materialized)
                                    └── (1) article_search   (FTS5)
```

## Tables

### `journals`

Core journal metadata from BrowZine.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `journal_id` | INTEGER | PRIMARY KEY | BrowZine journal ID |
| `library_id` | TEXT | NOT NULL | BrowZine library ID |
| `title` | TEXT | | Journal title |
| `issn` | TEXT | | Print ISSN |
| `eissn` | TEXT | | Electronic ISSN |
| `scimago_rank` | REAL | | SJR ranking |
| `cover_url` | TEXT | | Cover image URL |
| `available` | INTEGER | | Availability in library (0/1) |
| `toc_data_approved_and_live` | INTEGER | | TOC data status (0/1) |
| `has_articles` | INTEGER | | Has indexed articles (0/1) |

### `journal_meta`

CSV-sourced metadata for filtering. One row per journal.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `journal_id` | INTEGER | PRIMARY KEY, FK | References `journals.journal_id` ON DELETE CASCADE |
| `source_csv` | TEXT | NOT NULL | Source CSV filename |
| `area` | TEXT | | Research area (e.g., Accounting, Finance) |
| `csv_title` | TEXT | | Title as listed in CSV |
| `csv_issn` | TEXT | | ISSN as listed in CSV |
| `csv_library` | TEXT | | Library ID as listed in CSV |

### `issues`

Journal issues with publication metadata.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `issue_id` | INTEGER | PRIMARY KEY | BrowZine issue ID |
| `journal_id` | INTEGER | NOT NULL, FK | References `journals.journal_id` ON DELETE CASCADE |
| `publication_year` | INTEGER | | Publication year |
| `title` | TEXT | | Issue title (e.g., "Vol. 101 Issue 1") |
| `volume` | TEXT | | Volume number |
| `number` | TEXT | | Issue number |
| `date` | TEXT | | Publication date (ISO-8601) |
| `is_valid_issue` | INTEGER | | Valid issue flag (0/1) |
| `suppressed` | INTEGER | | Suppressed flag (0/1) |
| `embargoed` | INTEGER | | Embargo flag (0/1) |
| `within_subscription` | INTEGER | | Subscription access flag (0/1) |

### `articles`

Full article records. In-press articles have `issue_id` set to NULL.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `article_id` | INTEGER | PRIMARY KEY | BrowZine article ID |
| `journal_id` | INTEGER | NOT NULL, FK | References `journals.journal_id` ON DELETE CASCADE |
| `issue_id` | INTEGER | FK | References `issues.issue_id` ON DELETE SET NULL |
| `sync_id` | INTEGER | | BrowZine sync identifier |
| `title` | TEXT | | Article title |
| `date` | TEXT | | Publication date |
| `authors` | TEXT | | Comma-separated author names |
| `start_page` | TEXT | | Start page |
| `end_page` | TEXT | | End page |
| `abstract` | TEXT | | Article abstract |
| `doi` | TEXT | | Digital Object Identifier |
| `pmid` | TEXT | | PubMed ID |
| `ill_url` | TEXT | | Interlibrary loan URL |
| `link_resolver_openurl_link` | TEXT | | OpenURL resolver link |
| `email_article_request_link` | TEXT | | Email request link |
| `permalink` | TEXT | | Permanent link |
| `suppressed` | INTEGER | | Suppression flag (0/1) |
| `in_press` | INTEGER | | In-press flag (0/1) |
| `open_access` | INTEGER | | Open access flag (0/1) |
| `platform_id` | TEXT | | Platform identifier |
| `retraction_doi` | TEXT | | Retraction DOI |
| `retraction_date` | TEXT | | Retraction date |
| `retraction_related_urls` | TEXT | | JSON-encoded retraction URLs |
| `unpaywall_data_suppressed` | INTEGER | | Unpaywall suppression (0/1) |
| `expression_of_concern_doi` | TEXT | | Expression of concern DOI |
| `within_library_holdings` | INTEGER | | Library holdings flag (0/1) |
| `noodletools_export_link` | TEXT | | NoodleTools export link |
| `avoid_unpaywall_publisher_links` | INTEGER | | Unpaywall publisher link flag (0/1) |
| `browzine_web_in_context_link` | TEXT | | BrowZine web context link |
| `content_location` | TEXT | | Content access URL |
| `libkey_content_location` | TEXT | | LibKey content URL |
| `full_text_file` | TEXT | | Full-text PDF URL |
| `libkey_full_text_file` | TEXT | | LibKey full-text URL |
| `nomad_fallback_url` | TEXT | | NOMAD fallback URL |

### `article_listing`

Materialized view for optimized list queries. Populated after the initial index build.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `article_id` | INTEGER | PRIMARY KEY | Article ID |
| `journal_id` | INTEGER | NOT NULL, FK | Journal ID |
| `issue_id` | INTEGER | FK | Issue ID |
| `publication_year` | INTEGER | | Publication year (from issue) |
| `date` | TEXT | | Publication date |
| `open_access` | INTEGER | | Open access flag |
| `in_press` | INTEGER | | In-press flag |
| `suppressed` | INTEGER | | Suppression flag |
| `within_library_holdings` | INTEGER | | Library holdings flag |
| `doi` | TEXT | | DOI |
| `pmid` | TEXT | | PubMed ID |
| `area` | TEXT | | Research area (from journal_meta) |

### `article_search` (FTS5)

Full-text search virtual table. Content is synced from the `articles` table.

```sql
CREATE VIRTUAL TABLE article_search USING fts5(
    article_id UNINDEXED,
    title,
    abstract,
    doi,
    authors,
    journal_title
    [, tokenize = 'simple']
);
```

The optional `simple` tokenizer improves CJK character matching. It is enabled when the `SIMPLE_TOKENIZER_PATH` environment variable points to the SQLite extension binary.

### `listing_state`

Tracks whether the `article_listing` table is ready for queries.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY CHECK (id = 1) | Singleton row |
| `status` | TEXT | | `ready` when populated |
| `updated_at` | TEXT | | Last update timestamp |

### `journal_year_state`

Indexing progress per journal and year. Used for resume support.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `journal_id` | INTEGER | NOT NULL | Journal ID |
| `year` | INTEGER | NOT NULL | Publication year |
| `status` | TEXT | NOT NULL | `done` when complete |
| `updated_at` | TEXT | NOT NULL | Completion timestamp |

Primary key: `(journal_id, year)`

### `journal_state`

Indexing progress per journal.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `journal_id` | INTEGER | PRIMARY KEY | Journal ID |
| `status` | TEXT | NOT NULL | `done` when complete |
| `updated_at` | TEXT | NOT NULL | Completion timestamp |

## Indexes

### Journal indexes

| Index | Columns | Purpose |
|-------|---------|---------|
| `idx_journals_issn` | `journals(issn)` | ISSN lookup |
| `idx_journals_library_id` | `journals(library_id)` | Library filtering |
| `idx_journals_available` | `journals(available)` | Availability filtering |
| `idx_journals_has_articles` | `journals(has_articles)` | Article availability filtering |
| `idx_journals_scimago_rank` | `journals(scimago_rank)` | Ranking sort/filter |

### Journal meta indexes

| Index | Columns | Purpose |
|-------|---------|---------|
| `idx_journal_meta_area` | `journal_meta(area)` | Area filtering |
| `idx_journal_meta_area_journal` | `journal_meta(area, journal_id)` | Area + journal compound queries |

### Issue indexes

| Index | Columns | Purpose |
|-------|---------|---------|
| `idx_issues_journal_year` | `issues(journal_id, publication_year)` | Journal + year compound queries |
| `idx_issues_publication_year` | `issues(publication_year)` | Year filtering |

### Article indexes

| Index | Columns | Purpose |
|-------|---------|---------|
| `idx_articles_journal` | `articles(journal_id)` | Journal filtering |
| `idx_articles_issue` | `articles(issue_id)` | Issue filtering |
| `idx_articles_date` | `articles(date)` | Date filtering |
| `idx_articles_date_id` | `articles(date, article_id)` | Keyset pagination |
| `idx_articles_journal_date_id` | `articles(journal_id, date, article_id)` | Journal + pagination |
| `idx_articles_issue_date_id` | `articles(issue_id, date, article_id)` | Issue + pagination |
| `idx_articles_doi` | `articles(doi)` | DOI lookup |
| `idx_articles_pmid` | `articles(pmid)` | PubMed ID lookup |
| `idx_articles_open_access` | `articles(open_access)` | OA filtering |
| `idx_articles_in_press` | `articles(in_press)` | In-press filtering |
| `idx_articles_suppressed` | `articles(suppressed)` | Suppression filtering |
| `idx_articles_within_holdings` | `articles(within_library_holdings)` | Holdings filtering |
| `idx_articles_open_access_date_id` | `articles(open_access, date, article_id)` | OA + pagination |
| `idx_articles_in_press_date_id` | `articles(in_press, date, article_id)` | In-press + pagination |
| `idx_articles_suppressed_date_id` | `articles(suppressed, date, article_id)` | Suppression + pagination |
| `idx_articles_within_holdings_date_id` | `articles(within_library_holdings, date, article_id)` | Holdings + pagination |

### Article listing indexes

| Index | Columns | Purpose |
|-------|---------|---------|
| `idx_article_listing_date_id` | `article_listing(date, article_id)` | Keyset pagination |
| `idx_article_listing_area` | `article_listing(area)` | Area filtering |
| `idx_article_listing_publication_year` | `article_listing(publication_year)` | Year filtering |
| `idx_article_listing_journal` | `article_listing(journal_id)` | Journal filtering |
| `idx_article_listing_issue` | `article_listing(issue_id)` | Issue filtering |

## Write Semantics

All insert operations use `ON CONFLICT DO UPDATE` (upsert) semantics:
- Journals: conflict on `journal_id`, update all fields
- Journal meta: conflict on `journal_id`, update all fields
- Issues: conflict on `issue_id`, update all fields
- Articles: conflict on `article_id`, update all fields

Foreign key cascades:
- Deleting a journal cascades to `journal_meta`, `issues`, and `articles`
- Deleting an issue sets `articles.issue_id` to NULL

## Optimization

After data loading, the indexer runs:

```sql
ANALYZE;
PRAGMA optimize;
```

This updates query planner statistics for optimal index usage.

## Query Examples

Filter by research area:

```sql
SELECT j.title, m.area
FROM journals j
JOIN journal_meta m ON j.journal_id = m.journal_id
WHERE m.area = 'Accounting';
```

Open-access articles for a journal in a year:

```sql
SELECT a.title, a.date, a.doi
FROM articles a
JOIN issues i ON a.issue_id = i.issue_id
WHERE a.journal_id = 34781
  AND i.publication_year = 2024
  AND a.open_access = 1;
```

In-press articles (no issue assigned):

```sql
SELECT title, date, authors
FROM articles
WHERE in_press = 1 AND issue_id IS NULL;
```

Full-text search:

```sql
SELECT a.title, a.authors, a.doi
FROM article_search s
JOIN articles a ON a.article_id = s.rowid
WHERE s MATCH 'earnings OR disclosure';
```

Keyset pagination (articles by date descending):

```sql
SELECT a.article_id, a.title, a.date
FROM article_listing l
JOIN articles a ON a.article_id = l.article_id
WHERE (l.date, l.article_id) < ('2024-06-01', 999999)
ORDER BY l.date DESC, l.article_id DESC
LIMIT 50;
```
