# Notification Pipeline

This document explains how to run the weekly AI-driven article notification task.

## Overview

The notification task performs the following steps:

1. Reads the selected SQLite database under `data/index`.
2. Compares current issue and in-press article counts with the last snapshot in `data/push_state/<db>.json`.
3. Builds pending issue and in-press sets for changed groups.
4. Loads subscribers from `data/push/subscriptions.json`.
5. Uses SiliconFlow with the OpenAI Python SDK to rank relevant candidate articles.
6. Sends one digest message per subscriber through PushPlus.
7. Updates the state snapshot and dedupe records.

Each push is capped at 20 articles and 18000 characters. Each article item includes title, journal, date, DOI, and abstract preview.
PushPlus requests use payload fields `token`, `title`, `content`, `channel`, and `template`, plus optional `to`, `topic`, and `option`.
The pipeline no longer applies `excluded_keywords`. It prioritizes articles by AI ranking and keyword/direction phrase matches, then packs as many as possible under the 18000-character limit.

## Prerequisites

- SiliconFlow API key should be configured in the `global` section.
- PushPlus token should be configured per user in each user object.

## Subscription File

Use `data/push/subscriptions.example.json` as a template.

Copy it to `data/push/subscriptions.json` and update user entries.

The file is organized as:

- `global`: shared SiliconFlow key and PushPlus defaults.
- `defaults`: AI selection defaults.
- `users`: per-subscriber preferences, where each user must provide `pushplus_token`.

## Command

Run the notification command:

```bash
uv run notify --db utd24.sqlite
```

Common options:

- `--subscriptions data/push/subscriptions.json`
- `--state-dir data/push_state`
- `--siliconflow-model deepseek-ai/DeepSeek-V3`
- `--max-candidates 120`
- `--timeout 60`
- `--retries 3`
- `--dedupe-retention-days 60`
- `--dry-run`

## Weekly Workflow Suggestion

1. Run index update:

   ```bash
   uv run index --update
   ```

2. Run notification task:

   ```bash
   uv run notify --db utd24.sqlite
   ```

## Trigger Notify from Index Update

You can trigger notification directly from the update task.

```bash
uv run index --update --notify --file utd24.csv
```

When update finishes, `index` writes a change manifest file to:

- `data/push_state/<db_stem>.changes.json`

Then `index` calls:

- `uv run notify --db <db_name> --changes-file <manifest_path>`

This mode uses exact article-level diffs from the update run.

## Notes

- The task is idempotent for delivered articles using `delivery_dedupe`.
- If no issue or in-press group changed, the task exits early.
- `--dry-run` executes selection without sending PushPlus messages.
