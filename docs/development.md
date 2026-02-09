# Development Guide

This document covers the architecture, data flow, and development practices for Paper Scanner.

## Architecture Overview

Paper Scanner is a full-stack application with three main subsystems:

```
┌──────────────────────────────────────────────────────────────┐
│                  Next.js Frontend (Port 3000)                │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │  Login Page  │  │  Search Page  │  │  Weekly Updates  │  │
│  └──────┬───────┘  └───────┬───────┘  └────────┬─────────┘  │
│         └──────────────────┼───────────────────┘             │
│                  TanStack React Query                        │
└────────────────────────────┼─────────────────────────────────┘
                             │ HTTP/REST
                             │
┌────────────────────────────┼─────────────────────────────────┐
│              FastAPI Backend (Port 8000)                      │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  Routes: articles, journals, issues, meta, weekly       │ │
│  │  Queries: filtering, FTS5, cursor/offset pagination     │ │
│  │  Middleware: CORS, cache control                        │ │
│  └─────────────────────────┬───────────────────────────────┘ │
│                     aiosqlite                                 │
└────────────────────────────┼─────────────────────────────────┘
                             │
               ┌─────────────┴──────────────┐
               │                            │
         ┌─────▼──────┐         ┌───────────▼───────────┐
         │  *.sqlite   │         │  Index / Notify CLI   │
         │  databases  │         │  - Bulk indexer       │
         └─────────────┘         │  - Incremental sync   │
                                 │  - AI notifications   │
                                 └───────────┬───────────┘
                                             │
                                 ┌───────────▼───────────┐
                                 │    External APIs      │
                                 │  BrowZine  │  Weipu   │
                                 └───────────────────────┘
```

## Backend Architecture

### Module Layout

```
scripts/
├── api/                  # REST API server
│   ├── main.py           # Entrypoint (uvicorn runner)
│   ├── app.py            # FastAPI factory + middleware
│   ├── dependencies.py   # Dependency injection (DB connections)
│   ├── models.py         # Pydantic response models
│   ├── pagination.py     # Cursor/offset pagination utilities
│   ├── routes/           # Endpoint handlers
│   │   ├── __init__.py   # Route registration
│   │   ├── articles.py   # /api/articles
│   │   ├── journals.py   # /api/journals
│   │   ├── issues.py     # /api/issues
│   │   ├── meta.py       # /api/meta/* and /api/years
│   │   ├── weekly.py     # /api/weekly-updates
│   │   └── health.py     # /api/health
│   └── queries/          # SQL query builders per resource
├── index/                # Data indexer
│   ├── main.py           # CLI entrypoint
│   ├── fetcher.py        # Journal/issue/article fetcher
│   ├── changes.py        # Change detection and manifests
│   ├── workers.py        # Multi-process parallel workers
│   └── db/               # Database layer
│       ├── schema.py     # DDL, indexes, init
│       ├── client.py     # Async DB write client
│       ├── operations.py # Listing builder, state ops
│       ├── fts.py        # FTS5 index management
│       └── retry.py      # SQLite retry/backoff logic
├── notify/               # Notification subsystem
│   ├── main.py           # CLI entrypoint
│   ├── workflow.py       # End-to-end notification pipeline
│   ├── models.py         # Config models, defaults
│   ├── selector.py       # SiliconFlow LLM article selector
│   ├── delivery.py       # PushPlus message sender
│   └── state.py          # Deduplication state management
├── browzine/             # BrowZine API client
│   ├── client.py         # Async HTTP client
│   └── resolver.py       # Library fallback resolution
├── weipu/                # WeipuAPI client (Chinese journals)
│   └── client.py         # Playwright + selectolax scraper
└── shared/               # Cross-module utilities
    ├── constants.py      # Global constants
    ├── converters.py     # Type conversion helpers
    └── sqlite_ext.py     # SQLite extension loader
```

### API Server

The API server is built with FastAPI and uses aiosqlite for async database access.

**Application factory** (`scripts/api/app.py`):
- Creates a FastAPI instance with title "Paper Scanner API"
- Adds CORS middleware allowing all origins
- Adds cache control middleware (5-minute public cache for articles and meta endpoints)

**Dependency injection** (`scripts/api/dependencies.py`):
- `get_db()` resolves a database name to a SQLite connection
- Accepts an optional `db` query parameter; when omitted, defaults to the only available database
- Loads the simple tokenizer extension if available (for CJK full-text search)
- Connection cleanup is handled via FastAPI's dependency lifecycle

**Route registration** (`scripts/api/routes/__init__.py`):
- All routers are registered in `register_routes()` with a shared `/api` prefix
- Routes: health, meta, journals, issues, articles, weekly

**Pagination** (`scripts/api/pagination.py`):
- **Offset-based**: Standard `limit` + `offset` parameters
- **Keyset cursor**: Date-based cursor with article_id tiebreaker (format: `{date}|{article_id}`)
- **Sorting**: Comma-separated sort string with `-field` or `field:desc` syntax
- Maximum page size: 200 items

### Indexer

The indexer reads journal metadata from CSV files and fetches article data from external APIs.

**Pipeline**:

1. **Load CSV** - Read journal metadata (title, ISSN, ID, area, library)
2. **Validate libraries** - Check each journal's BrowZine library availability, apply fallbacks if needed
3. **Fetch issues** - Retrieve all issues per journal from BrowZine API (or WeipuAPI for Chinese journals)
4. **Fetch articles** - Retrieve article metadata for each issue
5. **Store** - Upsert all records into SQLite with conflict resolution
6. **Optimize** - Run `ANALYZE` and `PRAGMA optimize`
7. **Build listing** - Populate the materialized `article_listing` table
8. **Build FTS** - Populate the `article_search` FTS5 index

**Resume support**: The indexer tracks completion state per journal and per journal-year. On restart, completed items are skipped automatically.

**Multi-process mode**: When `--processes > 1`, journals are distributed across worker processes. A dedicated writer process serializes all database writes to avoid SQLite lock contention.

**Change tracking** (`scripts/index/changes.py`):
- Before an update, the indexer snapshots the set of article IDs per issue and in-press articles
- After the update, it compares snapshots to compute added/removed articles
- Results are written to a JSON change manifest in `data/push_state/`
- The manifest feeds into the notification pipeline

### Notification System

The notification system selects articles relevant to each user and delivers them via PushPlus.

**Pipeline**:

1. **Load candidates** - Read article IDs from change manifest or scan database for recent additions
2. **Fetch details** - Load full article records (title, abstract, authors, DOI) from the database
3. **AI selection** - Send candidate articles to SiliconFlow LLM with user's keywords and research directions
4. **Deduplication** - Filter out articles already delivered within the retention window (default 60 days)
5. **Delivery** - Format selected articles as Markdown and send via PushPlus
6. **State persistence** - Record delivered article IDs with timestamps

**Subscription config** (`data/push/subscriptions.json`):
- `global` - API keys and PushPlus channel settings
- `defaults` - Default LLM model, temperature, max candidates
- `users[]` - Per-user configuration with keywords, research directions, and PushPlus tokens

### BrowZine Client

The BrowZine client (`scripts/browzine/`) wraps the ThirdIron API v2:
- Fetches journal metadata, issues, and articles via async HTTP (httpx)
- Handles token management and request rate limiting
- Supports library fallback resolution when a journal isn't available in the primary library

### WeipuAPI Client

The Weipu client (`scripts/weipu/`) scrapes Chinese journal data:
- Uses Playwright for browser automation to handle JavaScript-rendered pages
- Parses HTML responses with selectolax for performance
- Uses quickjs for executing inline JavaScript when needed

## Frontend Architecture

### Tech Stack

- **Next.js 16** with App Router
- **React 19** with Server Components
- **TypeScript 5** for type safety
- **TailwindCSS 4** for styling
- **Radix UI** for accessible component primitives
- **TanStack React Query** for server state management and caching
- **nuqs** for URL-synced state (search params, filters)
- **lucide-react** for icons
- **next-themes** for dark/light mode

### Page Structure

```
app/app/
├── layout.tsx              # Root layout (fonts, metadata)
├── providers.tsx           # React Query + theme providers
├── login/
│   ├── page.tsx            # Login page (server component)
│   └── login-client.tsx    # Login form (client component)
└── (protected)/
    ├── layout.tsx          # Protected layout with auth check
    ├── page.tsx            # Main search interface
    ├── articles/
    │   └── [id]/
    │       └── page.tsx    # Article detail view
    └── weekly-updates/
        └── page.tsx        # Weekly article updates
```

### Key Components

| Component | Path | Purpose |
|-----------|------|---------|
| SearchBar | `components/feature/search-bar.tsx` | Full-text search input with debouncing |
| ResultsList | `components/feature/results-list.tsx` | Paginated article results with infinite scroll |
| Sidebar | `components/feature/sidebar.tsx` | Filter panel (journals, areas, year, flags) |
| WeeklyUpdatesFab | `components/feature/weekly-updates-fab.tsx` | Floating button linking to weekly view |

### Authentication

Token-based authentication configured in `app/config/auth.yaml`:

```yaml
tokens:
  - "your-token-here"
secret: "your-jwt-secret"
ttl_hours: 168
```

Flow:
1. User enters token on `/login`
2. Token is validated against the config
3. A session cookie is set
4. Protected routes check the session in the layout component

### Data Fetching

All API calls use TanStack React Query with the backend at `http://127.0.0.1:8000/api`:
- Queries are cached and deduplicated automatically
- Infinite scrolling uses cursor-based pagination
- Filter state is synced to URL params via nuqs for shareable links

## Database Schema

### Entity Relationship

```
journals (1) ──── (N) issues (1) ──── (N) articles
    │                                        │
    │                                        │
journal_meta (1:1)              article_listing (1:1, materialized)
                                article_search (FTS5 index)
```

### Tables

**journals**
```sql
CREATE TABLE journals (
    journal_id INTEGER PRIMARY KEY,
    library_id TEXT NOT NULL,
    title TEXT,
    issn TEXT,
    eissn TEXT,
    scimago_rank REAL,
    cover_url TEXT,
    available INTEGER,
    toc_data_approved_and_live INTEGER,
    has_articles INTEGER
);
```

**journal_meta**
```sql
CREATE TABLE journal_meta (
    journal_id INTEGER PRIMARY KEY,
    source_csv TEXT NOT NULL,
    area TEXT,
    csv_title TEXT,
    csv_issn TEXT,
    csv_library TEXT,
    FOREIGN KEY (journal_id) REFERENCES journals(journal_id) ON DELETE CASCADE
);
```

**issues**
```sql
CREATE TABLE issues (
    issue_id INTEGER PRIMARY KEY,
    journal_id INTEGER NOT NULL,
    publication_year INTEGER,
    title TEXT,
    volume TEXT,
    number TEXT,
    date TEXT,
    is_valid_issue INTEGER,
    suppressed INTEGER,
    embargoed INTEGER,
    within_subscription INTEGER,
    FOREIGN KEY (journal_id) REFERENCES journals(journal_id) ON DELETE CASCADE
);
```

**articles**
```sql
CREATE TABLE articles (
    article_id INTEGER PRIMARY KEY,
    journal_id INTEGER NOT NULL,
    issue_id INTEGER,
    sync_id INTEGER,
    title TEXT,
    date TEXT,
    authors TEXT,
    start_page TEXT,
    end_page TEXT,
    abstract TEXT,
    doi TEXT,
    pmid TEXT,
    -- ... URL and metadata fields ...
    suppressed INTEGER,
    in_press INTEGER,
    open_access INTEGER,
    FOREIGN KEY (journal_id) REFERENCES journals(journal_id) ON DELETE CASCADE,
    FOREIGN KEY (issue_id) REFERENCES issues(issue_id) ON DELETE SET NULL
);
```

**article_listing** (materialized view for optimized queries)
```sql
CREATE TABLE article_listing (
    article_id INTEGER PRIMARY KEY,
    journal_id INTEGER NOT NULL,
    issue_id INTEGER,
    publication_year INTEGER,
    date TEXT,
    open_access INTEGER,
    in_press INTEGER,
    suppressed INTEGER,
    within_library_holdings INTEGER,
    doi TEXT,
    pmid TEXT,
    area TEXT
);
```

**article_search** (FTS5 virtual table)
```sql
CREATE VIRTUAL TABLE article_search USING fts5(
    title, abstract, content=articles, content_rowid=article_id
);
```

### SQLite Configuration

- **WAL mode** - Write-ahead logging for concurrent reads during writes
- **Foreign keys enabled** - Cascading deletes from journals to issues/articles
- **Busy timeout** - 30 seconds to handle lock contention
- **Simple tokenizer** - Optional extension for improved CJK text search

### Key Indexes

The schema creates indexes optimized for the most common query patterns:

- **Keyset pagination**: `(date, article_id)` composite indexes
- **Filtering**: Separate indexes on `open_access`, `in_press`, `suppressed`, `area`, `journal_id`
- **Combined filter + pagination**: `(open_access, date, article_id)` and similar composites
- **Lookup**: `doi`, `pmid`, `issn` indexes
- **Journal-level queries**: `(journal_id, publication_year)` on issues

## Data Flow

### Indexing Pipeline

```
CSV files (data/meta/)
    │
    ▼
Load journal metadata
    │
    ▼
Validate libraries (BrowZine availability check)
    │
    ├── Available → fetch via BrowZine API
    │   ├── Fetch issues per journal
    │   └── Fetch articles per issue
    │
    └── Weipu library → fetch via WeipuAPI
        └── Playwright scraper + selectolax parser
    │
    ▼
Upsert into SQLite (ON CONFLICT DO UPDATE)
    │
    ▼
Build article_listing (materialized view)
    │
    ▼
Build article_search (FTS5 index)
    │
    ▼
ANALYZE + PRAGMA optimize
```

### Query Pipeline

```
HTTP Request
    │
    ▼
FastAPI Dependency Injection → resolve DB connection
    │
    ▼
Build WHERE clause from query params
    │
    ├── Full-text search? → FTS5 MATCH clause
    ├── Filters? → AND conditions
    └── Pagination? → cursor or offset
    │
    ▼
Execute query (aiosqlite)
    │
    ▼
Map rows to Pydantic models
    │
    ▼
JSON Response with PageMeta
```

### Notification Pipeline

```
Change manifest (JSON)
    │
    ▼
Load candidate articles from DB
    │
    ▼
For each user:
    ├── Filter by keywords/directions
    ├── Send to SiliconFlow LLM for scoring
    ├── Deduplicate against delivery history
    ├── Format as Markdown
    └── Send via PushPlus
    │
    ▼
Persist delivery state
```

## Configuration Reference

### Constants (`scripts/shared/constants.py`)

| Constant | Value | Description |
|----------|-------|-------------|
| `DEFAULT_LIBRARY_ID` | `"3050"` | Primary BrowZine library |
| `WEIPU_LIBRARY_ID` | `"-1"` | Marker for Chinese journals |
| `FALLBACK_LIBRARIES` | `["215", "866", ...]` | Backup libraries for unavailable journals |
| `BROWZINE_BASE_URL` | `https://api.thirdiron.com/v2` | BrowZine API base URL |
| `DB_TIMEOUT_SECONDS` | `30` | SQLite connection timeout |
| `DB_RETRY_ATTEMPTS` | `6` | Max retry attempts for DB operations |
| `MAX_LIMIT` | `200` | Maximum API page size |
| `API_PREFIX` | `"/api"` | API route prefix |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SIMPLE_TOKENIZER_PATH` | Path to the SQLite simple tokenizer extension for CJK support |

### Frontend Auth (`app/config/auth.yaml`)

| Field | Description |
|-------|-------------|
| `tokens` | List of valid authentication tokens |
| `secret` | JWT signing secret |
| `ttl_hours` | Token validity period in hours |

### Subscription Config (`data/push/subscriptions.json`)

| Section | Field | Description |
|---------|-------|-------------|
| `global` | `siliconflow_api_key` | SiliconFlow API key |
| `global` | `pushplus_channel` | Delivery channel (e.g., `mail`) |
| `defaults` | `siliconflow_model` | Default LLM model ID |
| `defaults` | `max_candidates` | Max articles sent to LLM per run |
| `defaults` | `temperature` | LLM temperature |
| `users[]` | `id` | Unique user identifier |
| `users[]` | `pushplus_token` | User's PushPlus token |
| `users[]` | `keywords` | Research keywords for article matching |
| `users[]` | `directions` | Research directions for article matching |

## Code Style

- **Language**: English for all code, comments, and documentation
- **No inline comments**: Use docstrings for documentation
- **Docstrings**: Standard Python format with Args/Returns sections
- **Linting**: `uv run ruff check` (rules: E, F, UP, B, SIM, I)
- **Formatting**: `uv run ruff format`
- **Type checking**: `uv run mypy` (untyped imports allowed)

## Adding a New Data Source

To add a new journal data source:

1. Create a new client module under `scripts/` (e.g., `scripts/newapi/client.py`)
2. Implement an async client class with methods to fetch journals, issues, and articles
3. Return data in the same dict format used by the BrowZine client
4. Add a library ID constant in `scripts/shared/constants.py`
5. Update `scripts/index/fetcher.py` to route journals with the new library ID to your client
6. Update `scripts/shared/converters.py` with a helper to detect the new library type

## Adding a New API Endpoint

1. Create a query builder in `scripts/api/queries/` if needed
2. Create a route handler in `scripts/api/routes/`
3. Define Pydantic response models in `scripts/api/models.py`
4. Register the router in `scripts/api/routes/__init__.py`

## Troubleshooting

### SQLite lock errors during indexing

The indexer uses WAL mode and retry logic with exponential backoff. If you still see lock errors:
- Reduce `--processes` to 1
- Ensure no other process has the database open
- Check that the database file is not on a network drive

### FTS search returns no results

- Verify that `article_search` is populated: check the `listing_state` table for `status = 'ready'`
- For CJK text, ensure the simple tokenizer extension is available and `SIMPLE_TOKENIZER_PATH` is set

### BrowZine API fetch failures

- Check network connectivity to `api.thirdiron.com`
- The indexer retries failed requests automatically
- Use `--resume` (enabled by default) to restart from where it left off
- Try different fallback libraries by updating the CSV's `library` column
