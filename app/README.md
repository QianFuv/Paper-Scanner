# Paper Scanner Frontend

Next.js web application for searching and browsing academic journal articles indexed by the Paper Scanner backend.

## Tech Stack

- **Next.js 16** - App Router with Server Components
- **React 19** - UI library
- **TypeScript 5** - Type safety
- **TailwindCSS 4** - Utility-first styling
- **Radix UI** - Accessible component primitives (dialog, select, checkbox, popover, slider, switch, scroll-area)
- **TanStack React Query** - Server state management and caching
- **nuqs** - URL-synced search parameter state
- **next-themes** - Dark/light mode support
- **lucide-react** - Icon set
- **Geist** - Font family (sans + mono)

## Getting Started

### Prerequisites

- Node.js 20+
- Backend API server running at `http://localhost:8000` (see root README)

### Install and Run

```bash
npm install
npm run dev
```

Open http://localhost:3000 in your browser.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API base URL |

## Project Structure

```
app/
├── app/                         # Next.js App Router
│   ├── layout.tsx               # Root layout (fonts, metadata, providers)
│   ├── globals.css              # Global styles
│   ├── providers.tsx            # TanStack Query + theme providers
│   ├── login/
│   │   ├── page.tsx             # Login page
│   │   └── login-client.tsx     # Login form component
│   └── (protected)/             # Auth-protected route group
│       ├── layout.tsx           # Auth check layout
│       ├── page.tsx             # Main search page
│       ├── articles/
│       │   └── [id]/
│       │       └── page.tsx     # Article detail page
│       └── weekly-updates/
│           └── page.tsx         # Weekly new articles page
├── components/
│   ├── feature/                 # Business components
│   │   ├── search-bar.tsx       # Full-text search input
│   │   ├── results-list.tsx     # Article results with infinite scroll
│   │   ├── sidebar.tsx          # Filter panel (journals, areas, year)
│   │   └── weekly-updates-fab.tsx # Floating action button
│   └── ui/                      # Radix UI primitives
│       ├── button.tsx
│       ├── input.tsx
│       ├── card.tsx
│       ├── badge.tsx
│       ├── dialog.tsx
│       ├── select.tsx
│       ├── popover.tsx
│       ├── checkbox.tsx
│       ├── label.tsx
│       ├── slider.tsx
│       ├── switch.tsx
│       ├── skeleton.tsx
│       └── scroll-area.tsx
├── lib/
│   ├── api.ts                   # API client (fetch wrappers, types)
│   ├── auth.ts                  # Authentication logic
│   ├── auth-config.ts           # Auth config loader
│   ├── citation.ts              # Citation formatting
│   └── utils.ts                 # Utility functions (cn, etc.)
├── config/
│   └── auth.yaml                # Authentication tokens and settings
├── assets/                      # Static assets
├── next.config.ts               # Next.js configuration
├── tailwind.config.ts           # Tailwind configuration
└── tsconfig.json                # TypeScript configuration
```

## Pages

### Login (`/login`)

Token-based authentication. Users enter a pre-configured token to access protected routes. Tokens and JWT settings are defined in `config/auth.yaml`.

### Search (`/`)

Main interface with three sections:
- **Search bar** - Full-text search across article titles, abstracts, authors
- **Sidebar filters** - Journal, research area, publication year, open access / in-press flags
- **Results list** - Cursor-based infinite scroll with article cards

All filter state is synced to URL parameters via nuqs, making search results shareable as links.

### Article Detail (`/articles/[id]`)

Full article metadata view with links to full-text (DOI, PDF) and citation information.

### Weekly Updates (`/weekly-updates`)

Displays recently added articles from index updates, grouped by database and journal. Configurable lookback window (1-31 days).

## API Client

The API client (`lib/api.ts`) provides typed fetch wrappers for all backend endpoints:

| Function | Endpoint | Description |
|----------|----------|-------------|
| `getArticles()` | `GET /api/articles` | Paginated article search with filters |
| `getArticleById()` | `GET /api/articles/{id}` | Single article detail |
| `getFullTextUrl()` | `GET /api/articles/{id}/fulltext` | Full-text redirect URL |
| `getAreas()` | `GET /api/meta/areas` | Research area list |
| `getYears()` | `GET /api/years` | Publication year summaries |
| `getJournalOptions()` | `GET /api/meta/journals` | Journal dropdown options |
| `getDatabases()` | `GET /api/meta/databases` | Available databases |
| `getWeeklyUpdates()` | `GET /api/weekly-updates` | Recent article updates |

Database selection is managed via `localStorage` with `setDatabase()` / `getCurrentDatabase()`.

## Authentication

Configured in `config/auth.yaml`:

```yaml
tokens:
  - "your-auth-token"
secret: "your-jwt-secret"
ttl_hours: 168
```

- `tokens` - List of valid authentication tokens
- `secret` - JWT signing secret for session cookies
- `ttl_hours` - Session validity period (default: 7 days)

## Scripts

```bash
npm run dev      # Start dev server with hot reload
npm run build    # Production build
npm run start    # Start production server
npm run lint     # Run ESLint
```
