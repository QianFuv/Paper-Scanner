# SQLite Database Schema (Article Index)

Each CSV under `data/meta` is exported to one SQLite database under
`data/index/<csv_stem>.sqlite`. The schema is normalized for filtering and
joins between journals, issues, and articles.

## Tables

### `journals`
Core journal metadata from BrowZine.

- `journal_id` INTEGER PRIMARY KEY
- `library_id` TEXT
- `title` TEXT
- `issn` TEXT
- `eissn` TEXT
- `scimago_rank` REAL
- `cover_url` TEXT
- `available` INTEGER (0/1)
- `toc_data_approved_and_live` INTEGER (0/1)
- `has_articles` INTEGER (0/1)

### `journal_meta`
CSV list metadata for filtering (area, rank, etc).

- `journal_id` INTEGER PRIMARY KEY (FK -> `journals.journal_id`)
- `source_csv` TEXT
- `area` TEXT
- `rank` TEXT
- `csv_title` TEXT
- `csv_issn` TEXT
- `csv_library` TEXT

### `issues`
Journal issues and publication years.

- `issue_id` INTEGER PRIMARY KEY
- `journal_id` INTEGER (FK -> `journals.journal_id`)
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
All article attributes returned by BrowZine.

- `article_id` INTEGER PRIMARY KEY
- `journal_id` INTEGER (FK -> `journals.journal_id`)
- `issue_id` INTEGER (FK -> `issues.issue_id`, NULL for in-press articles)
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

- `journal_id` INTEGER
- `year` INTEGER
- `status` TEXT (`done`)
- `updated_at` TEXT (UTC timestamp)

### `journal_state`
Resume and incremental update state per journal.

- `journal_id` INTEGER PRIMARY KEY
- `status` TEXT (`done`)
- `updated_at` TEXT (UTC timestamp)

### `article_search` (FTS5)
Full-text index for article search and filtering.

- `article_id` INTEGER (UNINDEXED)
- `title` TEXT
- `abstract` TEXT
- `doi` TEXT
- `authors` TEXT
- `journal_title` TEXT

## Indexes

- `journals(issn)`
- `journal_meta(area)`
- `issues(journal_id, publication_year)`
- `articles(journal_id)`
- `articles(issue_id)`
- `articles(date)`
- `articles(doi)`
- `articles(open_access)`
- `articles(in_press)`

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
