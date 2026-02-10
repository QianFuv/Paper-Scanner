# Development Guide

This document covers the architecture, data flow, and development practices for Paper Scanner.

For detailed reference on specific subsystems, see:
- [API Reference](api.md) - REST API endpoints and query parameters
- [Database Schema](database.md) - SQLite tables, indexes, and query examples
- [BrowZine API](browzine_api.md) - BrowZine API integration
- [WeipuAPI](weipu_api.md) - CQVIP data extraction
- [Notification Pipeline](notify.md) - AI-powered article notifications
- [Docker Deployment](docker.md) - Container build, configuration, and CI/CD

## Architecture Overview

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

## Backend Module Layout

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
│   ├── ai_selector.py    # SiliconFlow LLM article selector
│   ├── selection.py      # Multi-round selection logic
│   ├── delivery.py       # Manifest loading, dedup pruning
│   └── state.py          # JSON state persistence
├── browzine/             # BrowZine API client
│   ├── client.py         # Async HTTP client with token caching
│   └── validation.py     # Journal availability + library fallback
├── weipu/                # WeipuAPI client (Chinese journals)
│   ├── client.py         # Nuxt payload extraction via QuickJS
│   ├── des.py            # Pure Python DES-ECB for request signing
│   └── parsers.py        # Payload normalization helpers
└── shared/               # Cross-module utilities
    ├── constants.py      # Global constants
    ├── converters.py     # Type conversion helpers
    └── sqlite_ext.py     # SQLite extension loader
```

## API Server

The API server is built with FastAPI and uses aiosqlite for async database access.

**Application factory** (`app.py`): Creates a FastAPI instance with CORS (all origins) and cache control middleware (5-minute public cache for articles and meta endpoints).

**Dependency injection** (`dependencies.py`): The `get_db()` function resolves a database name to a SQLite connection. It accepts an optional `db` query parameter; when omitted, defaults to the only available database. Connection cleanup is handled via FastAPI's dependency lifecycle.

**Route registration** (`routes/__init__.py`): All routers are registered with the `/api` prefix. Routes: health, meta, journals, issues, articles, weekly.

**Pagination** (`pagination.py`):
- Offset-based: `limit` + `offset` parameters
- Keyset cursor: Date-based with article_id tiebreaker (format: `{date}|{article_id}`)
- Sorting: Comma-separated string with `-field` or `field:desc` syntax
- Max page size: 200

**Query strategy**: Article listing uses the `article_listing` materialized table when available (checked via `listing_state`), falling back to direct table joins otherwise.

## Indexer

The indexer reads journal metadata from CSV files and fetches article data from external APIs.

**Pipeline**:
1. Load CSV with journal metadata (title, ISSN, ID, area, library)
2. Validate libraries via BrowZine API, apply fallbacks if needed
3. Fetch issues per journal per year
4. Fetch articles per issue
5. Upsert all records into SQLite
6. Build `article_listing` materialized table
7. Build `article_search` FTS5 index
8. Run `ANALYZE` and `PRAGMA optimize`

**Resume support**: Tracks completion state per journal and per journal-year in `journal_state` and `journal_year_state` tables. On restart, completed items are skipped.

**Multi-process mode**: When `--processes > 1`, journals are distributed across worker processes. A dedicated writer process serializes all database writes to avoid SQLite lock contention.

**Change tracking** (`changes.py`): Takes before/after snapshots of article ID sets per issue. The diff produces a JSON change manifest that feeds into the notification pipeline.

## Notification System

See [Notification Pipeline](notify.md) for full details.

Key components:
- **AI selector** (`ai_selector.py`): SiliconFlow LLM client with structured JSON output and multi-round selection
- **Selection logic** (`selection.py`): Score aggregation, dedup filtering, keyword-based supplementation
- **State management** (`state.py`): Atomic JSON persistence with delivery dedup records

## Frontend Architecture

### Tech Stack

- **Next.js 16** with App Router
- **React 19** with Server Components
- **TypeScript 5**
- **TailwindCSS 4**
- **Radix UI** for accessible component primitives
- **TanStack React Query** for server state management
- **nuqs** for URL-synced filter state
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
| SearchBar | `components/feature/search-bar.tsx` | Full-text search input |
| ResultsList | `components/feature/results-list.tsx` | Paginated article results with infinite scroll |
| Sidebar | `components/feature/sidebar.tsx` | Filter panel (journals, areas, year, flags) |
| WeeklyUpdatesFab | `components/feature/weekly-updates-fab.tsx` | Floating button to weekly view |

### Authentication

Token-based authentication configured in `app/config/auth.yaml`:

```yaml
tokens:
  - "your-token-here"
secret: "your-jwt-secret"
ttl_hours: 168
```

### Data Fetching

All API calls use TanStack React Query:
- Queries are cached and deduplicated
- Infinite scrolling uses cursor-based pagination
- Filter state is synced to URL params via nuqs for shareable links

## Data Flow

### Indexing

```
CSV files (data/meta/)
    │
    ▼
Validate libraries (BrowZine availability check)
    │
    ├── BrowZine journals → BrowZine API
    └── Weipu journals → CQVIP website scraper
    │
    ▼
Upsert into SQLite (ON CONFLICT DO UPDATE)
    │
    ▼
Build article_listing + article_search
    │
    ▼
ANALYZE + PRAGMA optimize
```

### API Queries

```
HTTP Request → FastAPI DI → resolve DB connection
    │
    ▼
Build WHERE clause from query params
    ├── FTS5 MATCH (if search query)
    ├── Filter conditions
    └── Keyset cursor or offset
    │
    ▼
Execute query → Map to Pydantic models → JSON Response
```

### Notifications

```
Change manifest → Load candidates → AI selection → Dedup → PushPlus delivery → Save state
```

## Configuration

### Constants (`scripts/shared/constants.py`)

| Constant | Value | Description |
|----------|-------|-------------|
| `DEFAULT_LIBRARY_ID` | `"3050"` | Primary BrowZine library |
| `WEIPU_LIBRARY_ID` | `"-1"` | Marker for Chinese journals |
| `FALLBACK_LIBRARIES` | `["215", "866", ...]` | Backup libraries |
| `BROWZINE_BASE_URL` | `https://api.thirdiron.com/v2` | BrowZine API base |
| `DB_TIMEOUT_SECONDS` | `30` | SQLite connection timeout |
| `DB_RETRY_ATTEMPTS` | `6` | Max DB retry attempts |
| `MAX_LIMIT` | `200` | Maximum API page size |
| `API_PREFIX` | `"/api"` | API route prefix |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SIMPLE_TOKENIZER_PATH` | Path to SQLite simple tokenizer extension for CJK support |

## Code Style

- **Language**: English for all code, comments, and documentation
- **No inline comments**: Use docstrings for documentation
- **Docstrings**: Standard Python format with Args/Returns sections
- **Linting**: `uv run ruff check` (rules: E, F, UP, B, SIM, I)
- **Formatting**: `uv run ruff format`
- **Type checking**: `uv run mypy` (untyped imports allowed)

## Adding a New Data Source

1. Create a client module under `scripts/` (e.g., `scripts/newapi/client.py`)
2. Implement an async client with methods for journals, issues, and articles
3. Return data in the same dict format used by the BrowZine client
4. Add a library ID constant in `scripts/shared/constants.py`
5. Update `scripts/index/fetcher.py` to route journals with the new library ID
6. Update `scripts/shared/converters.py` with a detection helper

## Adding a New API Endpoint

1. Create a query builder in `scripts/api/queries/`
2. Create a route handler in `scripts/api/routes/`
3. Define Pydantic response models in `scripts/api/models.py`
4. Register the router in `scripts/api/routes/__init__.py`

## Troubleshooting

### SQLite lock errors during indexing

The indexer uses WAL mode and retry logic with exponential backoff. If lock errors persist:
- Reduce `--processes` to 1
- Ensure no other process has the database open
- Avoid network drives for database files

### FTS search returns no results

- Check `listing_state` table: status should be `ready`
- For CJK text, ensure `SIMPLE_TOKENIZER_PATH` is set and the extension exists

### BrowZine API fetch failures

- Check connectivity to `api.thirdiron.com`
- The indexer retries automatically and supports `--resume` (on by default)
- Try updating the CSV's `library` column to a different fallback library
