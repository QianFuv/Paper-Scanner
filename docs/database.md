# SQLite Database Schema (Article Index)

Each CSV under `data/meta` is exported to one SQLite database at
`data/index/<csv_stem>.sqlite`. The schema below is derived directly from
`scripts/index.py`.

## Initialization Notes

- SQLite pragmas are set to `journal_mode=WAL`, `foreign_keys=ON`,
  `synchronous=NORMAL`, and `busy_timeout=30000` milliseconds.
- All timestamps are stored as `TEXT` (UTC ISO-8601 style strings).
- Boolean values are stored as `INTEGER` with `0/1` convention.

## Tables

### `journals`
Core journal metadata from BrowZine.

- `journal_id` INTEGER PRIMARY KEY
- `library_id` TEXT NOT NULL
- `title` TEXT
- `issn` TEXT
- `eissn` TEXT
- `scimago_rank` REAL
- `cover_url` TEXT
- `available` INTEGER (0/1)
- `toc_data_approved_and_live` INTEGER (0/1)
- `has_articles` INTEGER (0/1)

### `journal_meta`
CSV list metadata for filtering (area, rank, etc). One row per journal.

- `journal_id` INTEGER PRIMARY KEY (FK -> `journals.journal_id`, ON DELETE CASCADE)
- `source_csv` TEXT NOT NULL
- `area` TEXT
- `rank` TEXT
- `csv_title` TEXT
- `csv_issn` TEXT
- `csv_library` TEXT

### `issues`
Journal issues and publication years.

- `issue_id` INTEGER PRIMARY KEY
- `journal_id` INTEGER NOT NULL (FK -> `journals.journal_id`, ON DELETE CASCADE)
- `publication_year` INTEGER
- `title` TEXT
- `volume` TEXT
- `number` TEXT
- `date` TEXT
- `is_valid_issue` INTEGER (0/1)
- `suppressed` INTEGER (0/1)
- `embargoed` INTEGER (0/1)
- `within_subscription` INTEGER (0/1)

### `articles`
Article attributes returned by BrowZine. In-press items have `issue_id` set to NULL.

- `article_id` INTEGER PRIMARY KEY
- `journal_id` INTEGER NOT NULL (FK -> `journals.journal_id`, ON DELETE CASCADE)
- `issue_id` INTEGER (FK -> `issues.issue_id`, ON DELETE SET NULL)
- `sync_id` INTEGER
- `title` TEXT
- `date` TEXT
- `authors` TEXT
- `start_page` TEXT
- `end_page` TEXT
- `abstract` TEXT
- `doi` TEXT
- `pmid` TEXT
- `ill_url` TEXT
- `link_resolver_openurl_link` TEXT
- `email_article_request_link` TEXT
- `permalink` TEXT
- `suppressed` INTEGER (0/1)
- `in_press` INTEGER (0/1)
- `open_access` INTEGER (0/1)
- `platform_id` TEXT
- `retraction_doi` TEXT
- `retraction_date` TEXT
- `retraction_related_urls` TEXT (JSON-encoded array when present)
- `unpaywall_data_suppressed` INTEGER (0/1)
- `expression_of_concern_doi` TEXT
- `within_library_holdings` INTEGER (0/1)
- `noodletools_export_link` TEXT
- `avoid_unpaywall_publisher_links` INTEGER (0/1)
- `browzine_web_in_context_link` TEXT
- `content_location` TEXT
- `libkey_content_location` TEXT
- `full_text_file` TEXT
- `libkey_full_text_file` TEXT
- `nomad_fallback_url` TEXT

### `journal_year_state`
Resume and incremental update state per journal year.

- `journal_id` INTEGER NOT NULL
- `year` INTEGER NOT NULL
- `status` TEXT NOT NULL (currently `done`)
- `updated_at` TEXT NOT NULL
- PRIMARY KEY (`journal_id`, `year`)

### `journal_state`
Resume and incremental update state per journal.

- `journal_id` INTEGER PRIMARY KEY
- `status` TEXT NOT NULL (currently `done`)
- `updated_at` TEXT NOT NULL

### `article_search` (FTS5)
Full-text index for article search and filtering.

- `article_id` INTEGER (UNINDEXED)
- `title` TEXT
- `abstract` TEXT
- `doi` TEXT
- `authors` TEXT
- `journal_title` TEXT

Note: `rowid` is set to `article_id` when inserting into this table.

## Indexes

- `idx_journals_issn` on `journals(issn)`
- `idx_journal_meta_area` on `journal_meta(area)`
- `idx_issues_journal_year` on `issues(journal_id, publication_year)`
- `idx_articles_journal` on `articles(journal_id)`
- `idx_articles_issue` on `articles(issue_id)`
- `idx_articles_date` on `articles(date)`
- `idx_articles_doi` on `articles(doi)`
- `idx_articles_open_access` on `articles(open_access)`
- `idx_articles_in_press` on `articles(in_press)`

## Query Examples

Filter by list area and rank:

```sql
SELECT j.title, m.area, m.rank
FROM journals j
JOIN journal_meta m ON j.journal_id = m.journal_id
WHERE m.area = 'Accounting' AND m.rank = 'utd24';
```

Find open-access articles for a journal in a year:

```sql
SELECT a.title, a.date, a.doi
FROM articles a
JOIN issues i ON a.issue_id = i.issue_id
WHERE a.journal_id = 34781
  AND i.publication_year = 2024
  AND a.open_access = 1;
```

Find in-press articles (no issue assigned yet):

```sql
SELECT title, date, authors
FROM articles
WHERE in_press = 1 AND issue_id IS NULL;
```

Full-text search by keywords with optional filters:

```sql
SELECT a.title, a.authors, a.doi, j.title
FROM article_search s
JOIN articles a ON a.article_id = s.article_id
JOIN journals j ON j.journal_id = a.journal_id
WHERE s MATCH 'earnings OR disclosure'
  AND j.title LIKE '%Accounting%';
```
