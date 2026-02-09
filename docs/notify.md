# Notification Pipeline

This document describes the AI-driven article notification system that selects and delivers relevant articles to subscribers.

## Overview

The notification pipeline:

1. Identifies newly added or changed articles from index updates
2. Uses SiliconFlow LLM to rank articles by relevance to each subscriber's research interests
3. Delivers personalized digests via PushPlus
4. Tracks delivery state to prevent duplicate notifications

## Architecture

```
Change Manifest (JSON)
    │
    ▼
Load candidate articles from SQLite
    │
    ▼
For each subscriber:
    ├── Send candidates to SiliconFlow LLM
    ├── Score by keywords + research directions
    ├── Deduplicate against delivery history
    ├── Format as Markdown digest
    └── Send via PushPlus
    │
    ▼
Persist delivery state
```

## Prerequisites

- **SiliconFlow API key**: Configured in `global.siliconflow_api_key`
- **PushPlus token**: Configured per user in `users[].pushplus_token`

## Subscription Configuration

### Setup

```bash
cp data/push/subscriptions.example.json data/push/subscriptions.json
```

### File Structure

```json
{
  "global": {
    "siliconflow_api_key": "sk-your-siliconflow-key",
    "pushplus_channel": "mail",
    "pushplus_template": "markdown",
    "pushplus_topic": "",
    "pushplus_option": ""
  },
  "defaults": {
    "max_candidates": 120,
    "siliconflow_model": "deepseek-ai/DeepSeek-V3",
    "temperature": 0.2
  },
  "users": [
    {
      "id": "alice",
      "name": "Alice",
      "enabled": true,
      "pushplus_token": "your-pushplus-token",
      "to": "",
      "keywords": ["earnings management", "disclosure quality"],
      "directions": ["accounting research", "capital markets"],
      "template": "markdown",
      "topic": ""
    }
  ]
}
```

### Configuration Fields

**`global`**: Shared service credentials and PushPlus defaults.

| Field | Description |
|-------|-------------|
| `siliconflow_api_key` | SiliconFlow API key for LLM access |
| `pushplus_channel` | Delivery channel (`mail`, `wechat`, etc.) |
| `pushplus_template` | Message format (`markdown`, `html`, `txt`) |
| `pushplus_topic` | PushPlus topic (optional) |
| `pushplus_option` | PushPlus option (optional) |

**`defaults`**: AI selection parameters.

| Field | Default | Description |
|-------|---------|-------------|
| `max_candidates` | 120 | Max articles sent to the LLM per run |
| `siliconflow_model` | `deepseek-ai/DeepSeek-V3` | LLM model ID |
| `temperature` | 0.2 | LLM sampling temperature |

**`users[]`**: Per-subscriber preferences.

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique subscriber identifier |
| `name` | Yes | Display name |
| `enabled` | Yes | Whether notifications are active |
| `pushplus_token` | Yes | PushPlus delivery token |
| `to` | No | PushPlus recipient override |
| `keywords` | Yes | Research keywords for article matching |
| `directions` | Yes | Research directions (higher priority than keywords) |
| `template` | No | Override message template |
| `topic` | No | Override PushPlus topic |

## Commands

### Standalone notification

```bash
uv run notify --db utd24.sqlite
```

### Triggered from index update

```bash
uv run index --update --notify --file utd24.csv
```

When `--notify` is used with `--update`, the indexer:
1. Computes a change manifest (`data/push_state/<db_stem>.changes.json`)
2. Passes the manifest to the notification pipeline
3. Only newly added articles are considered as candidates

### Dry run (no delivery)

```bash
uv run notify --db utd24.sqlite --dry-run
```

### All CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | auto-detect | Database file under `data/index/` |
| `--subscriptions` | `data/push/subscriptions.json` | Subscription config path |
| `--state-dir` | `data/push_state` | Directory for persisted state files |
| `--changes-file` | - | Change manifest from index update |
| `--siliconflow-model` | config default | Override LLM model ID |
| `--max-candidates` | config default (120) | Max articles sent to LLM |
| `--timeout` | 60 | HTTP timeout in seconds |
| `--retries` | 3 | Retry count for API calls |
| `--dedupe-retention-days` | 60 | Days to keep delivery dedup records |
| `--dry-run` | disabled | Run selection without sending messages |

## Pipeline Details

### 1. Change Detection

When running with `--update`, the indexer takes before/after snapshots of article IDs per issue and in-press articles. The diff produces a change manifest:

```json
{
  "db_name": "utd24",
  "db_path": "data/index/utd24.sqlite",
  "generated_at": "2026-02-10T08:00:00Z",
  "pending_issue_keys": ["34781:641161731"],
  "pending_inpress_keys": ["34781"],
  "notifiable_article_ids": [685706566, 685706567],
  "summary": {
    "added_article_count": 2,
    "removed_article_count": 0
  }
}
```

### 2. Candidate Loading

Articles are loaded from the database using the change manifest's `notifiable_article_ids`. Each candidate includes: title, abstract (truncated to 1200 chars), authors, date, DOI, journal title, and access flags.

### 3. AI Selection

The `SiliconFlowSelector` sends candidates to the LLM with a structured prompt:

- **Directions** have higher priority than keywords
- The LLM returns a JSON array of `{article_id, score}` pairs
- Multi-round selection: if results are sparse, additional rounds are run (up to 5)
- Scores are aggregated across rounds (highest score wins)
- The system uses JSON schema enforcement for structured output

### 4. Selection Rules

After AI selection:
1. Filter out articles already delivered within the dedup retention window
2. Supplement with keyword-matched articles if the AI selection is below the limit
3. Cap at 20 articles per push message
4. Cap message content at 18,000 characters

### 5. Delivery

Each subscriber receives a Markdown digest via PushPlus containing:
- Article title
- Journal name
- Publication date
- DOI link
- Abstract preview

PushPlus payload fields: `token`, `title`, `content`, `channel`, `template`, plus optional `to`, `topic`, `option`.

### 6. Deduplication

Delivery records are keyed as `{subscriber_id}:{article_id}` with ISO-8601 timestamps. Records older than `--dedupe-retention-days` (default 60) are pruned on each run.

## State File

State is persisted at `data/push_state/<db_stem>.json` with atomic writes (write to `.tmp`, then rename).

```json
{
  "db_name": "utd24",
  "status": "idle",
  "last_completed_run_at": "2026-02-10T08:00:00Z",
  "snapshot": {
    "issue_article_counts": { "34781:641161731": 18 },
    "inpress_article_counts": { "34781": 5 }
  },
  "run": {
    "run_id": "...",
    "status": "completed",
    "started_at": "...",
    "completed_at": "...",
    "pending_issue_keys": [...],
    "done_issue_keys": [...],
    "pending_inpress_keys": [...],
    "done_inpress_keys": [...],
    "user_results": [...],
    "errors": []
  },
  "delivery_dedupe": {
    "alice:685706566": "2026-02-10T08:00:00Z"
  },
  "updated_at": "2026-02-10T08:00:00Z"
}
```

## Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `SILICONFLOW_BASE_URL` | `https://api.siliconflow.cn/v1` | SiliconFlow API endpoint |
| `PUSHPLUS_ENDPOINT` | `https://www.pushplus.plus/send` | PushPlus send endpoint |
| `MAX_ARTICLES_PER_PUSH` | 20 | Max articles per message |
| `MAX_PUSH_CONTENT_LENGTH` | 18000 | Max message content length |
| `MAX_AI_SELECTION_ROUNDS` | 5 | Max LLM query rounds per subscriber |

## Weekly Workflow

1. Run the index update:

   ```bash
   uv run index --update
   ```

2. Run the notification pipeline:

   ```bash
   uv run notify --db utd24.sqlite
   ```

Or combine both in a single command:

```bash
uv run index --update --notify --file utd24.csv
```

## Notes

- The pipeline is idempotent for delivered articles via the dedup mechanism
- If no articles changed since the last run, the pipeline exits early
- `--dry-run` executes the full selection pipeline without sending PushPlus messages
- The SiliconFlow client uses the OpenAI Python SDK for compatibility
