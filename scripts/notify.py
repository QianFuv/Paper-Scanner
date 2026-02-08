"""
Select and push updated articles with SiliconFlow and PushPlus.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
from openai import OpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    completion_create_params,
)

PROJECT_ROOT = Path(__file__).parent.parent
INDEX_DIR = PROJECT_ROOT / "data" / "index"
DEFAULT_SUBSCRIPTIONS_PATH = PROJECT_ROOT / "data" / "push" / "subscriptions.json"
DEFAULT_STATE_DIR = PROJECT_ROOT / "data" / "push_state"
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
PUSHPLUS_ENDPOINT = "https://www.pushplus.plus/send"
PUSHPLUS_CHANNEL = "mail"
DEFAULT_SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V3"
MAX_ARTICLES_PER_PUSH = 20
MAX_PUSH_CONTENT_LENGTH = 18000
MAX_AI_SELECTION_ROUNDS = 5

SUMMARY_STOPWORDS = {
    "about",
    "after",
    "against",
    "among",
    "analysis",
    "article",
    "based",
    "between",
    "can",
    "data",
    "effects",
    "from",
    "into",
    "journal",
    "more",
    "paper",
    "papers",
    "results",
    "research",
    "shows",
    "study",
    "their",
    "these",
    "this",
    "using",
    "with",
}


@dataclass(frozen=True)
class ArticleCandidate:
    """
    Candidate article for recommendation and push delivery.

    Args:
        article_id: Unique article identifier.
        journal_id: Journal identifier.
        issue_id: Issue identifier when available.
        title: Article title.
        abstract: Article abstract.
        date: Publication date string.
        journal_title: Journal title.
        doi: DOI value.
        full_text_file: Full text file link.
        permalink: External permalink.
        open_access: Open access flag.
        in_press: In-press flag.
        within_library_holdings: Library holdings flag.
    """

    article_id: int
    journal_id: int
    issue_id: int | None
    title: str
    abstract: str
    date: str | None
    journal_title: str
    doi: str | None
    full_text_file: str | None
    permalink: str | None
    open_access: bool
    in_press: bool
    within_library_holdings: bool


@dataclass(frozen=True)
class Subscriber:
    """
    Subscriber configuration for AI selection and PushPlus delivery.

    Args:
        subscriber_id: Stable subscriber identifier.
        name: Display name.
        pushplus_token: PushPlus token for this user.
        to: Optional recipient value for channels that support it.
        keywords: Keyword preferences.
        directions: Direction preferences.
        topic: Optional per-user PushPlus topic override.
        template: Optional per-user PushPlus template override.
    """

    subscriber_id: str
    name: str
    pushplus_token: str
    to: str | None
    keywords: list[str]
    directions: list[str]
    topic: str | None
    template: str | None


@dataclass(frozen=True)
class NotificationGlobal:
    """
    Global notification configuration loaded from subscriptions file.

    Args:
        siliconflow_api_key: SiliconFlow API key used for AI selection.
        pushplus_channel: PushPlus channel name.
        pushplus_template: Default PushPlus template.
        pushplus_topic: Optional default PushPlus topic.
        pushplus_option: Optional PushPlus option value.
    """

    siliconflow_api_key: str
    pushplus_channel: str
    pushplus_template: str
    pushplus_topic: str | None
    pushplus_option: str | None


@dataclass(frozen=True)
class NotificationDefaults:
    """
    Global defaults loaded from subscription configuration.

    Args:
        max_candidates: Maximum candidates sent to model.
        siliconflow_model: SiliconFlow model identifier.
        temperature: Model temperature.
    """

    max_candidates: int
    siliconflow_model: str
    temperature: float


@dataclass(frozen=True)
class RankedSelection:
    """
    One model-selected article result.

    Args:
        article_id: Selected article identifier.
        score: Recommendation score from 0 to 100.
    """

    article_id: int
    score: float


@dataclass(frozen=True)
class SelectionResult:
    """
    Structured model selection output.

    Args:
        summary: Short run summary for this subscriber.
        selections: Selected items.
    """

    summary: str
    selections: list[RankedSelection]


class SiliconFlowSelector:
    """
    SiliconFlow client for structured article selection.

    Args:
        api_key: SiliconFlow API key.
        model: SiliconFlow model identifier.
        timeout_seconds: Request timeout.
        retries: Retry attempts for transient failures.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: int,
        retries: int,
        temperature: float,
    ) -> None:
        """
        Initialize selector client.

        Args:
            api_key: SiliconFlow API key.
            model: SiliconFlow model identifier.
            timeout_seconds: Request timeout.
            retries: Retry attempts.
            temperature: Model temperature.

        Returns:
            None.
        """
        self.api_key = api_key
        self.model = model
        self.retries = max(0, retries)
        self.temperature = temperature
        self.client = OpenAI(
            api_key=api_key,
            base_url=SILICONFLOW_BASE_URL,
            timeout=timeout_seconds,
            max_retries=self.retries,
        )

    def close(self) -> None:
        """
        Close HTTP resources.

        Args:
            None.

        Returns:
            None.
        """
        return None

    def select_articles(
        self,
        subscriber: Subscriber,
        defaults: NotificationDefaults,
        candidates: list[ArticleCandidate],
    ) -> SelectionResult:
        """
        Select and rank relevant articles for one subscriber.

        Args:
            subscriber: Subscriber configuration.
            defaults: Global defaults.
            candidates: Candidate article list.

        Returns:
            Structured selection result.
        """
        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "selected": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "article_id": {"type": "integer"},
                            "score": {"type": "number"},
                        },
                        "required": [
                            "article_id",
                            "score",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["summary", "selected"],
            "additionalProperties": False,
        }

        user_payload = {
            "subscriber": {
                "id": subscriber.subscriber_id,
                "name": subscriber.name,
                "keywords": subscriber.keywords,
                "directions": subscriber.directions,
            },
            "summary_requirement": (
                "Summary must focus on the content of selected papers. "
                "Describe major research themes, methods, or findings "
                "in 2-4 sentences. "
                "Avoid generic recommendation language."
            ),
            "selection_rules": {
                "goal": "Return ranked relevant candidates for this subscriber",
                "score_definition": "0 to 100, higher means better match and quality",
                "prefer": [
                    "Article quality and methodological rigor",
                    "Recent papers",
                    "High conceptual overlap with subscriber goals",
                    "Clear practical or theoretical contribution",
                ],
                "avoid": [
                    "Low topical relevance",
                    "Any preference based on journal prestige or ranking",
                ],
            },
            "limits": {
                "max_candidates_input": defaults.max_candidates,
            },
            "candidates": [
                {
                    "article_id": item.article_id,
                    "journal_id": item.journal_id,
                    "issue_id": item.issue_id,
                    "title": item.title,
                    "abstract": truncate_text(item.abstract, 1200),
                    "date": item.date,
                    "journal_title": item.journal_title,
                    "open_access": item.open_access,
                    "in_press": item.in_press,
                    "within_library_holdings": item.within_library_holdings,
                }
                for item in candidates
            ],
            "output_instruction": "Return JSON only and strictly follow schema.",
        }

        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a precise academic recommender. "
                        "Return relevant candidates ranked by score. "
                        "Order selected items from highest to lowest. "
                        "Judge by article content quality and topic relevance only. "
                        "Ignore journal quality, prestige, and ranking completely. "
                        "Do not invent article ids."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "paper_selection",
                    "strict": True,
                    "schema": schema,
                },
            },
        }

        response_json = self._create_completion(body)
        response_payload = extract_response_payload(response_json)
        selected_items = []

        for item in response_payload.get("selected", []):
            article_id = to_int(item.get("article_id"))
            score = to_float(item.get("score"))
            if article_id is None or score is None:
                continue
            selected_items.append(
                RankedSelection(
                    article_id=article_id,
                    score=score,
                )
            )

        selected_items.sort(key=lambda value: value.score, reverse=True)

        summary = str(response_payload.get("summary") or "")
        return SelectionResult(summary=summary, selections=selected_items)

    def summarize_selected_articles(
        self,
        subscriber: Subscriber,
        selected_candidates: list[ArticleCandidate],
    ) -> str:
        """
        Build a content-focused summary for the finalized selected papers.

        Args:
            subscriber: Subscriber configuration.
            selected_candidates: Final selected candidate list.

        Returns:
            Summary text generated by the model.
        """
        if not selected_candidates:
            return ""

        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
            },
            "required": ["summary"],
            "additionalProperties": False,
        }

        payload = {
            "subscriber": {
                "id": subscriber.subscriber_id,
                "name": subscriber.name,
                "keywords": subscriber.keywords,
                "directions": subscriber.directions,
            },
            "selected_articles": [
                {
                    "article_id": item.article_id,
                    "title": item.title,
                    "abstract": truncate_text(item.abstract, 1200),
                    "journal_title": item.journal_title,
                    "date": item.date,
                }
                for item in selected_candidates
            ],
            "instruction": (
                "Summarize the content of these selected papers in 2-4 sentences. "
                "Focus on major research themes, methods, and findings. "
                "Avoid generic recommendation language."
            ),
        }

        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a precise academic summarizer. "
                        "Only summarize the supplied selected papers."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "selected_paper_summary",
                    "strict": True,
                    "schema": schema,
                },
            },
        }

        response_json = self._create_completion(body)
        response_payload = extract_response_payload(response_json)
        summary = str(response_payload.get("summary") or "").strip()
        return summary

    def _create_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        """
        Create chat completion through OpenAI SDK.

        Args:
            body: Chat completion payload.

        Returns:
            JSON response payload.
        """
        last_error: Exception | None = None
        extra_headers = {
            "HTTP-Referer": "https://github.com/openai/codex",
            "X-Title": "Paper Scanner",
        }
        response_format = body.get("response_format")
        if not isinstance(response_format, dict):
            raise ValueError("response_format must be a JSON object")
        raw_messages = body.get("messages")
        if not isinstance(raw_messages, list):
            raise ValueError("messages must be a list")
        messages = cast(list[ChatCompletionMessageParam], raw_messages)
        typed_response_format = cast(
            completion_create_params.ResponseFormat,
            response_format,
        )
        for attempt in range(self.retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=str(body.get("model") or self.model),
                    messages=messages,
                    temperature=float(body.get("temperature") or self.temperature),
                    response_format=typed_response_format,
                    extra_headers=extra_headers,
                )
                payload = response.model_dump(mode="json")
                if not isinstance(payload, dict):
                    raise ValueError("SiliconFlow response is not a JSON object")
                return payload
            except Exception as error:
                last_error = error
                if attempt < self.retries:
                    time.sleep(2**attempt)
                    continue
                break
        raise RuntimeError(f"SiliconFlow request failed: {last_error}")


class PushPlusClient:
    """
    PushPlus delivery client with retries.

    Args:
        timeout_seconds: Request timeout.
        retries: Retry attempts for transient failures.
    """

    def __init__(self, timeout_seconds: int, retries: int) -> None:
        """
        Initialize PushPlus client.

        Args:
            timeout_seconds: Request timeout.
            retries: Retry attempts.

        Returns:
            None.
        """
        self.retries = max(0, retries)
        self.client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        """
        Close HTTP resources.

        Args:
            None.

        Returns:
            None.
        """
        self.client.close()

    def send(
        self,
        token: str,
        title: str,
        content: str,
        channel: str,
        template: str,
        topic: str | None,
        option: str | None,
        to: str | None,
    ) -> str:
        """
        Send PushPlus message and return message id.

        Args:
            token: PushPlus token.
            title: Message title.
            content: Message content.
            channel: PushPlus channel.
            template: PushPlus template.
            topic: Optional topic.
            option: Optional channel option value.
            to: Optional recipient value.

        Returns:
            PushPlus message id.
        """
        payload: dict[str, Any] = {
            "token": token,
            "title": title,
            "content": content,
            "channel": channel,
            "template": template,
        }
        if to:
            payload["to"] = to
        if topic:
            payload["topic"] = topic
        if option:
            payload["option"] = option

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.post(PUSHPLUS_ENDPOINT, json=payload)
                if (
                    response.status_code in {429, 500, 502, 503, 504}
                    and attempt < self.retries
                ):
                    time.sleep(2**attempt)
                    continue
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("PushPlus response is not a JSON object")
                code = to_int(result.get("code"))
                if code != 200:
                    message = str(result.get("msg") or "Unknown PushPlus error")
                    raise RuntimeError(f"PushPlus failed with code {code}: {message}")
                return str(result.get("data") or "")
            except Exception as error:
                last_error = error
                if attempt < self.retries:
                    time.sleep(2**attempt)
                    continue
                break
        raise RuntimeError(f"PushPlus request failed: {last_error}")


def utc_now_iso() -> str:
    """
    Build current UTC ISO-8601 timestamp.

    Args:
        None.

    Returns:
        Timestamp string.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def to_int(value: Any) -> int | None:
    """
    Convert value to int safely.

    Args:
        value: Any value.

    Returns:
        Converted integer or None.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def to_float(value: Any) -> float | None:
    """
    Convert value to float safely.

    Args:
        value: Any value.

    Returns:
        Converted float or None.
    """
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def to_string_list(value: Any) -> list[str]:
    """
    Normalize list-like values into non-empty strings.

    Args:
        value: Any value.

    Returns:
        String list.
    """
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def truncate_text(value: str | None, max_length: int) -> str:
    """
    Truncate text for prompt compactness.

    Args:
        value: Source text.
        max_length: Maximum length.

    Returns:
        Truncated text.
    """
    text = (value or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 1)].rstrip() + "..."


def build_issue_key(journal_id: int, issue_id: int) -> str:
    """
    Build issue key string.

    Args:
        journal_id: Journal identifier.
        issue_id: Issue identifier.

    Returns:
        Serialized issue key.
    """
    return f"{journal_id}:{issue_id}"


def parse_issue_key(key: str) -> tuple[int, int]:
    """
    Parse serialized issue key.

    Args:
        key: Issue key string.

    Returns:
        Journal and issue ids.
    """
    parts = key.split(":", maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"Invalid issue key: {key}")
    journal_id = int(parts[0])
    issue_id = int(parts[1])
    return journal_id, issue_id


def load_json(path: Path, default: Any) -> Any:
    """
    Load JSON payload from disk.

    Args:
        path: Source path.
        default: Default value when file is missing.

    Returns:
        Loaded payload.
    """
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_json_atomic(path: Path, payload: Any) -> None:
    """
    Save JSON payload atomically.

    Args:
        path: Output path.
        payload: Payload object.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    temp_path.replace(path)


def resolve_db_path(db_name: str | None) -> Path:
    """
    Resolve database path from optional name.

    Args:
        db_name: Database filename or stem.

    Returns:
        Absolute database path.
    """
    if not INDEX_DIR.exists():
        raise FileNotFoundError(f"Index directory not found: {INDEX_DIR}")

    if db_name:
        candidate = INDEX_DIR / db_name
        if not candidate.suffix:
            candidate = candidate.with_suffix(".sqlite")
        if not candidate.exists():
            raise FileNotFoundError(f"Database not found: {candidate}")
        return candidate

    db_files = sorted(INDEX_DIR.glob("*.sqlite"))
    if not db_files:
        raise FileNotFoundError(f"No sqlite database found under {INDEX_DIR}")
    if len(db_files) > 1:
        names = ", ".join(file.name for file in db_files)
        raise ValueError(f"Multiple databases found. Please pass --db. Found: {names}")
    return db_files[0]


def collect_issue_article_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """
    Collect article counts grouped by journal and issue.

    Args:
        connection: SQLite connection.

    Returns:
        Snapshot map keyed by issue key.
    """
    rows = connection.execute(
        """
        SELECT journal_id, issue_id, COUNT(*)
        FROM articles
        WHERE issue_id IS NOT NULL
        GROUP BY journal_id, issue_id
        """
    ).fetchall()
    snapshot: dict[str, int] = {}
    for journal_id, issue_id, count in rows:
        snapshot[build_issue_key(int(journal_id), int(issue_id))] = int(count)
    return snapshot


def collect_inpress_article_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """
    Collect in-press article counts grouped by journal.

    Args:
        connection: SQLite connection.

    Returns:
        Snapshot map keyed by journal id.
    """
    rows = connection.execute(
        """
        SELECT journal_id, COUNT(*)
        FROM articles
        WHERE issue_id IS NULL AND COALESCE(in_press, 0) = 1
        GROUP BY journal_id
        """
    ).fetchall()
    return {str(int(journal_id)): int(count) for journal_id, count in rows}


def compute_changed_issue_keys(
    previous_counts: dict[str, int],
    current_counts: dict[str, int],
) -> list[str]:
    """
    Compute issue keys whose counts changed.

    Args:
        previous_counts: Previous snapshot map.
        current_counts: Current snapshot map.

    Returns:
        Sorted changed issue keys.
    """
    changed = [
        key
        for key, current_count in current_counts.items()
        if previous_counts.get(key) != current_count
    ]
    return sorted(changed, key=lambda item: parse_issue_key(item))


def compute_changed_inpress_keys(
    previous_counts: dict[str, int],
    current_counts: dict[str, int],
) -> list[str]:
    """
    Compute in-press keys whose counts changed.

    Args:
        previous_counts: Previous snapshot map.
        current_counts: Current snapshot map.

    Returns:
        Sorted changed in-press keys.
    """
    changed = [
        key
        for key, current_count in current_counts.items()
        if previous_counts.get(key) != current_count
    ]
    return sorted(changed, key=lambda item: int(item))


def build_default_state(db_name: str) -> dict[str, Any]:
    """
    Build default state payload.

    Args:
        db_name: Database filename.

    Returns:
        Initialized state dictionary.
    """
    now = utc_now_iso()
    return {
        "db_name": db_name,
        "status": "idle",
        "last_completed_run_at": None,
        "snapshot": {
            "issue_article_counts": {},
            "inpress_article_counts": {},
        },
        "run": None,
        "delivery_dedupe": {},
        "updated_at": now,
    }


def load_state(path: Path, db_name: str) -> dict[str, Any]:
    """
    Load and normalize persisted state.

    Args:
        path: State path.
        db_name: Database filename.

    Returns:
        Normalized state dictionary.
    """
    state = load_json(path, build_default_state(db_name))
    if not isinstance(state, dict):
        raise ValueError("State file must be a JSON object")

    if state.get("db_name") not in {None, db_name}:
        raise ValueError("State file does not match selected database")

    state["db_name"] = db_name
    state.setdefault("status", "idle")
    state.setdefault("last_completed_run_at", None)
    snapshot = state.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
    snapshot.setdefault("issue_article_counts", {})
    snapshot.setdefault("inpress_article_counts", {})
    if not isinstance(snapshot["issue_article_counts"], dict):
        snapshot["issue_article_counts"] = {}
    if not isinstance(snapshot["inpress_article_counts"], dict):
        snapshot["inpress_article_counts"] = {}
    state["snapshot"] = snapshot

    delivery_dedupe = state.get("delivery_dedupe")
    if not isinstance(delivery_dedupe, dict):
        delivery_dedupe = {}
    state["delivery_dedupe"] = delivery_dedupe
    if state.get("run") is not None and not isinstance(state.get("run"), dict):
        state["run"] = None
    state.setdefault("updated_at", utc_now_iso())
    return state


def create_run_state(
    run_id: str,
    pending_issue_keys: list[str],
    pending_inpress_keys: list[str],
) -> dict[str, Any]:
    """
    Build run payload for current execution.

    Args:
        run_id: Stable run id.
        pending_issue_keys: Pending issue keys.
        pending_inpress_keys: Pending in-press keys.

    Returns:
        Run dictionary.
    """
    now = utc_now_iso()
    return {
        "run_id": run_id,
        "status": "running",
        "started_at": now,
        "completed_at": None,
        "updated_at": now,
        "pending_issue_keys": pending_issue_keys,
        "done_issue_keys": [],
        "pending_inpress_keys": pending_inpress_keys,
        "done_inpress_keys": [],
        "errors": [],
        "user_results": [],
    }


def parse_subscriber(item: dict[str, Any]) -> Subscriber:
    """
    Parse one subscriber from JSON payload.

    Args:
        item: Subscriber object.

    Returns:
        Parsed subscriber.
    """
    subscriber_id = str(item.get("id") or "").strip()
    if not subscriber_id:
        raise ValueError("Subscriber id is required")

    name = str(item.get("name") or subscriber_id).strip()
    pushplus_token = str(item.get("pushplus_token") or "").strip()
    if not pushplus_token:
        raise ValueError(f"Subscriber {subscriber_id} missing pushplus_token")

    to_value = str(item.get("to") or "").strip()
    to = to_value or None

    topic_value = str(item.get("topic") or "").strip()
    topic = topic_value if topic_value else None

    template = None
    raw_template = item.get("template")
    if raw_template is not None:
        template_text = str(raw_template).strip()
        template = template_text or None

    return Subscriber(
        subscriber_id=subscriber_id,
        name=name,
        pushplus_token=pushplus_token,
        to=to,
        keywords=to_string_list(item.get("keywords")),
        directions=to_string_list(item.get("directions")),
        topic=topic,
        template=template,
    )


def load_subscriptions(
    path: Path,
) -> tuple[NotificationGlobal, NotificationDefaults, list[Subscriber]]:
    """
    Load subscription configuration.

    Args:
        path: Subscription JSON path.

    Returns:
        Global config, defaults, and subscribers list.
    """
    payload = load_json(path, None)
    if not isinstance(payload, dict):
        raise FileNotFoundError(f"Subscription file missing or invalid: {path}")

    global_obj = payload.get("global")
    if not isinstance(global_obj, dict):
        global_obj = {}

    siliconflow_api_key = str(global_obj.get("siliconflow_api_key") or "").strip()
    if not siliconflow_api_key:
        raise ValueError("Global SiliconFlow API key is required")

    pushplus_channel = str(
        global_obj.get("pushplus_channel") or PUSHPLUS_CHANNEL
    ).strip()
    if not pushplus_channel:
        pushplus_channel = PUSHPLUS_CHANNEL
    pushplus_template = str(global_obj.get("pushplus_template") or "markdown").strip()
    if not pushplus_template:
        pushplus_template = "markdown"
    pushplus_topic_value = str(global_obj.get("pushplus_topic") or "").strip()
    pushplus_topic = pushplus_topic_value or None
    pushplus_option_value = str(global_obj.get("pushplus_option") or "").strip()
    pushplus_option = pushplus_option_value or None

    global_config = NotificationGlobal(
        siliconflow_api_key=siliconflow_api_key,
        pushplus_channel=pushplus_channel,
        pushplus_template=pushplus_template,
        pushplus_topic=pushplus_topic,
        pushplus_option=pushplus_option,
    )

    defaults_obj = payload.get("defaults")
    if not isinstance(defaults_obj, dict):
        defaults_obj = {}

    max_candidates = to_int(defaults_obj.get("max_candidates")) or 120
    temperature = to_float(defaults_obj.get("temperature")) or 0.2

    siliconflow_model = str(defaults_obj.get("siliconflow_model") or "").strip()
    if not siliconflow_model:
        siliconflow_model = DEFAULT_SILICONFLOW_MODEL

    defaults = NotificationDefaults(
        max_candidates=max(1, max_candidates),
        siliconflow_model=siliconflow_model,
        temperature=max(0.0, min(1.0, temperature)),
    )

    raw_users = payload.get("users")
    if not isinstance(raw_users, list):
        raise ValueError("Subscription file requires a users array")

    subscribers: list[Subscriber] = []
    for user_item in raw_users:
        if not isinstance(user_item, dict):
            continue
        enabled = user_item.get("enabled", True)
        if isinstance(enabled, bool) and not enabled:
            continue
        subscribers.append(parse_subscriber(user_item))

    if not subscribers:
        raise ValueError("No enabled subscribers found")
    return global_config, defaults, subscribers


def fetch_candidates_for_issue_keys(
    connection: sqlite3.Connection,
    issue_keys: list[str],
) -> list[ArticleCandidate]:
    """
    Fetch candidate articles for pending issue keys.

    Args:
        connection: SQLite connection.
        issue_keys: Pending issue keys.

    Returns:
        Candidate list.
    """
    if not issue_keys:
        return []

    issue_ids = sorted({parse_issue_key(key)[1] for key in issue_keys})
    placeholders = ", ".join(["?"] * len(issue_ids))

    rows = connection.execute(
        f"""
        SELECT
            a.article_id,
            a.journal_id,
            a.issue_id,
            a.title,
            a.abstract,
            a.date,
            a.open_access,
            a.in_press,
            a.within_library_holdings,
            a.doi,
            a.full_text_file,
            a.permalink,
            j.title AS journal_title
        FROM articles a
        JOIN journals j ON j.journal_id = a.journal_id
        WHERE a.issue_id IN ({placeholders})
          AND COALESCE(a.suppressed, 0) = 0
        ORDER BY a.date DESC, a.article_id DESC
        """,
        issue_ids,
    ).fetchall()

    return [row_to_candidate(row) for row in rows]


def fetch_candidates_for_inpress_keys(
    connection: sqlite3.Connection,
    inpress_keys: list[str],
) -> list[ArticleCandidate]:
    """
    Fetch candidate in-press articles for pending journals.

    Args:
        connection: SQLite connection.
        inpress_keys: Pending journal keys.

    Returns:
        Candidate list.
    """
    if not inpress_keys:
        return []

    journal_ids = sorted({int(key) for key in inpress_keys})
    placeholders = ", ".join(["?"] * len(journal_ids))

    rows = connection.execute(
        f"""
        SELECT
            a.article_id,
            a.journal_id,
            a.issue_id,
            a.title,
            a.abstract,
            a.date,
            a.open_access,
            a.in_press,
            a.within_library_holdings,
            a.doi,
            a.full_text_file,
            a.permalink,
            j.title AS journal_title
        FROM articles a
        JOIN journals j ON j.journal_id = a.journal_id
        WHERE a.issue_id IS NULL
          AND COALESCE(a.in_press, 0) = 1
          AND a.journal_id IN ({placeholders})
          AND COALESCE(a.suppressed, 0) = 0
        ORDER BY a.date DESC, a.article_id DESC
        """,
        journal_ids,
    ).fetchall()

    return [row_to_candidate(row) for row in rows]


def row_to_candidate(row: sqlite3.Row | tuple[Any, ...]) -> ArticleCandidate:
    """
    Convert SQL row to candidate object.

    Args:
        row: SQLite row.

    Returns:
        Candidate instance.
    """
    row_data = dict(row)
    title = str(row_data.get("title") or "Untitled article").strip()
    abstract = str(row_data.get("abstract") or "").strip()
    journal_title = str(row_data.get("journal_title") or "Unknown journal").strip()

    return ArticleCandidate(
        article_id=int(row_data["article_id"]),
        journal_id=int(row_data["journal_id"]),
        issue_id=to_int(row_data.get("issue_id")),
        title=title,
        abstract=abstract,
        date=str(row_data.get("date") or "").strip() or None,
        journal_title=journal_title,
        doi=str(row_data.get("doi") or "").strip() or None,
        full_text_file=str(row_data.get("full_text_file") or "").strip() or None,
        permalink=str(row_data.get("permalink") or "").strip() or None,
        open_access=bool(to_int(row_data.get("open_access")) or 0),
        in_press=bool(to_int(row_data.get("in_press")) or 0),
        within_library_holdings=bool(
            to_int(row_data.get("within_library_holdings")) or 0
        ),
    )


def deduplicate_candidates(
    candidates: list[ArticleCandidate],
) -> list[ArticleCandidate]:
    """
    Deduplicate candidates by article id while preserving order.

    Args:
        candidates: Candidate list.

    Returns:
        Deduplicated list.
    """
    deduped: list[ArticleCandidate] = []
    seen_ids: set[int] = set()
    for item in candidates:
        if item.article_id in seen_ids:
            continue
        seen_ids.add(item.article_id)
        deduped.append(item)
    return deduped


def extract_response_payload(response_json: dict[str, Any]) -> dict[str, Any]:
    """
    Extract structured payload from SiliconFlow response.

    Args:
        response_json: SiliconFlow response JSON.

    Returns:
        Parsed payload object.
    """
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("SiliconFlow response missing choices")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ValueError("SiliconFlow response has invalid choice item")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("SiliconFlow response missing message")

    content = message.get("content")
    if isinstance(content, dict):
        return content

    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_text = block.get("text")
            if isinstance(block_text, str):
                text_parts.append(block_text)
        content = "".join(text_parts)

    if not isinstance(content, str):
        raise ValueError("SiliconFlow message content is invalid")

    normalized = content.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()

    payload = json.loads(normalized)
    if not isinstance(payload, dict):
        raise ValueError("Structured response is not a JSON object")
    return payload


def candidate_match_score(candidate: ArticleCandidate, subscriber: Subscriber) -> int:
    """
    Compute keyword and direction match count for one candidate.

    Args:
        candidate: Candidate article.
        subscriber: Subscriber profile.

    Returns:
        Number of matched keyword and direction phrases.
    """
    source_text = f"{candidate.title} {candidate.abstract}".lower()
    phrases: list[str] = []
    phrases.extend(subscriber.keywords)
    phrases.extend(subscriber.directions)

    score = 0
    for phrase in phrases:
        normalized = phrase.lower().strip()
        if normalized and normalized in source_text:
            score += 1
    return score


def select_articles_with_retries(
    selector: SiliconFlowSelector,
    subscriber: Subscriber,
    defaults: NotificationDefaults,
    candidates_for_model: list[ArticleCandidate],
    candidates_by_id: dict[int, ArticleCandidate],
    delivery_dedupe: dict[str, str],
    max_rounds: int,
) -> SelectionResult:
    """
    Query model multiple times on remaining candidates when results are sparse.

    Args:
        selector: SiliconFlow selector client.
        subscriber: Subscriber profile.
        defaults: Notification defaults.
        candidates_for_model: Candidates sent to model.
        candidates_by_id: Candidate lookup map.
        delivery_dedupe: Delivery dedupe map.
        max_rounds: Maximum model query rounds.

    Returns:
        Aggregated selection result across rounds.
    """
    rounds = max(1, max_rounds)
    remaining_candidates = [*candidates_for_model]
    aggregated: dict[int, RankedSelection] = {}
    summary = ""

    for _ in range(rounds):
        if not remaining_candidates:
            break

        round_result = selector.select_articles(
            subscriber,
            defaults,
            remaining_candidates,
        )
        if not summary and round_result.summary:
            summary = round_result.summary

        for item in round_result.selections:
            existing = aggregated.get(item.article_id)
            if existing is None or item.score > existing.score:
                aggregated[item.article_id] = item

        merged = SelectionResult(
            summary=summary,
            selections=sorted(
                aggregated.values(),
                key=lambda item: item.score,
                reverse=True,
            ),
        )

        accepted = apply_selection_rules(
            merged,
            subscriber,
            candidates_by_id,
            delivery_dedupe,
        )
        if len(accepted) >= MAX_ARTICLES_PER_PUSH:
            return merged

        selected_ids = {item.article_id for item in aggregated.values()}
        remaining_candidates = [
            item for item in remaining_candidates if item.article_id not in selected_ids
        ]

    return SelectionResult(
        summary=summary,
        selections=sorted(
            aggregated.values(),
            key=lambda item: item.score,
            reverse=True,
        ),
    )


def apply_selection_rules(
    selection_result: SelectionResult,
    subscriber: Subscriber,
    candidates_by_id: dict[int, ArticleCandidate],
    delivery_dedupe: dict[str, str],
) -> list[RankedSelection]:
    """
    Apply local rules to model output.

    Args:
        selection_result: Model output.
        subscriber: Subscriber configuration.
        candidates_by_id: Candidate map.
        delivery_dedupe: Delivery dedupe map.

    Returns:
        Filtered selection list.
    """
    eligible: list[RankedSelection] = []
    selected_ids: set[int] = set()

    for selection in selection_result.selections:
        candidate = candidates_by_id.get(selection.article_id)
        if candidate is None:
            continue
        dedupe_key = f"{subscriber.subscriber_id}:{candidate.article_id}"
        if dedupe_key in delivery_dedupe:
            continue
        eligible.append(selection)
        selected_ids.add(selection.article_id)

    supplemental: list[RankedSelection] = []
    if len(eligible) < MAX_ARTICLES_PER_PUSH:
        for candidate in candidates_by_id.values():
            if candidate.article_id in selected_ids:
                continue
            dedupe_key = f"{subscriber.subscriber_id}:{candidate.article_id}"
            if dedupe_key in delivery_dedupe:
                continue
            if candidate_match_score(candidate, subscriber) <= 0:
                continue
            supplemental.append(
                RankedSelection(
                    article_id=candidate.article_id,
                    score=0.0,
                )
            )

        supplemental.sort(
            key=lambda item: (
                candidate_match_score(candidates_by_id[item.article_id], subscriber),
                candidates_by_id[item.article_id].article_id,
            ),
            reverse=True,
        )

    merged = [*eligible, *supplemental]

    if not merged:
        return []

    match_sorted = sorted(
        merged,
        key=lambda item: (
            candidate_match_score(candidates_by_id[item.article_id], subscriber),
            item.score,
        ),
        reverse=True,
    )
    return match_sorted[:MAX_ARTICLES_PER_PUSH]


def build_message_title(db_name: str, run_id: str) -> str:
    """
    Build push title.

    Args:
        db_name: Database name.
        run_id: Run identifier.

    Returns:
        Push title string.
    """
    return f"Paper Scanner Weekly Update [{db_name}] {run_id[:10]}"


def build_content_focused_intro(
    summary: str,
    selections: list[RankedSelection],
    candidates_by_id: dict[int, ArticleCandidate],
) -> str:
    """
    Build a content-focused intro paragraph for selected papers.

    Args:
        summary: Model-provided summary.
        selections: Accepted selections.
        candidates_by_id: Candidate map.

    Returns:
        Intro paragraph text.
    """
    cleaned_summary = summary.strip()
    if cleaned_summary:
        return cleaned_summary

    focus_candidates = [
        candidates_by_id[item.article_id]
        for item in selections[:MAX_ARTICLES_PER_PUSH]
        if item.article_id in candidates_by_id
    ]
    if not focus_candidates:
        return (
            "This digest highlights newly selected papers aligned with your interests."
        )

    token_counter: dict[str, int] = {}
    for candidate in focus_candidates:
        source = f"{candidate.title} {candidate.abstract}".lower()
        for token in re.findall(r"[a-z][a-z0-9\-]{2,}", source):
            if token in SUMMARY_STOPWORDS:
                continue
            token_counter[token] = token_counter.get(token, 0) + 1

    top_terms = [
        token
        for token, _ in sorted(
            token_counter.items(),
            key=lambda item: (-item[1], item[0]),
        )[:6]
    ]

    journal_titles = sorted(
        {
            candidate.journal_title.strip()
            for candidate in focus_candidates
            if candidate.journal_title.strip()
        }
    )
    journals_text = ", ".join(journal_titles[:3])
    terms_text = ", ".join(top_terms) if top_terms else "core topic themes"
    return (
        f"This digest focuses on {len(focus_candidates)} selected papers. "
        f"The main content themes include {terms_text}. "
        f"The selected work is concentrated in journals such as {journals_text}."
    )


def build_markdown_content(
    db_name: str,
    run_id: str,
    subscriber: Subscriber,
    summary: str,
    selections: list[RankedSelection],
    candidates_by_id: dict[int, ArticleCandidate],
) -> str:
    """
    Build markdown push content.

    Args:
        db_name: Database name.
        run_id: Run id.
        subscriber: Subscriber profile.
        summary: AI summary text.
        selections: Accepted selections.
        candidates_by_id: Candidate map.

    Returns:
        Markdown message.
    """
    base_lines = [
        f"## Weekly Digest for {subscriber.name}",
        "",
        f"- Database: `{db_name}`",
        f"- Run ID: `{run_id}`",
    ]
    intro_text = build_content_focused_intro(summary, selections, candidates_by_id)
    if intro_text:
        base_lines.extend(["", f"{intro_text}"])

    ranked_sections: list[tuple[RankedSelection, str]] = []
    for item in selections[:MAX_ARTICLES_PER_PUSH]:
        candidate = candidates_by_id[item.article_id]
        display_doi = (candidate.doi or "").strip() or "N/A"
        section = "\n".join(
            [
                f"### {len(ranked_sections) + 1}. {candidate.title}",
                f"- Journal: {candidate.journal_title}",
                f"- Date: {candidate.date or 'Unknown'}",
                f"- DOI: {display_doi}",
                f"- Abstract: {candidate.abstract or 'N/A'}",
            ]
        )
        ranked_sections.append((item, section))

    def render_content(sections: list[str], total_selected: int) -> str:
        """
        Render markdown content from base and article sections.

        Args:
            sections: Article section blocks.
            total_selected: Number of selected sections.

        Returns:
            Rendered markdown content.
        """
        header_lines = [*base_lines, f"- Selected Articles: {total_selected}"]
        content_parts: list[str] = ["\n".join(header_lines).strip()]
        content_parts.extend(sections)
        return "\n\n".join(part for part in content_parts if part).strip()

    kept_sections: list[str] = []
    for _, section in ranked_sections:
        trial_sections = [*kept_sections, section]
        trial_content = render_content(trial_sections, len(trial_sections))
        if len(trial_content) <= MAX_PUSH_CONTENT_LENGTH:
            kept_sections.append(section)

    content = render_content(kept_sections, len(kept_sections))
    if len(content) <= MAX_PUSH_CONTENT_LENGTH:
        return content

    base_content = render_content([], 0)
    return truncate_text(base_content, MAX_PUSH_CONTENT_LENGTH)


def prune_delivery_dedupe(
    delivery_dedupe: dict[str, str],
    retention_days: int,
) -> dict[str, str]:
    """
    Prune old dedupe records.

    Args:
        delivery_dedupe: Dedupe map.
        retention_days: Retention day count.

    Returns:
        Pruned map.
    """
    if retention_days <= 0:
        return {}

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    kept: dict[str, str] = {}
    for key, value in delivery_dedupe.items():
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if parsed >= cutoff:
            kept[key] = value
    return kept


def resolve_path(path_value: str, project_root: Path) -> Path:
    """
    Resolve path relative to project root.

    Args:
        path_value: Raw path argument.
        project_root: Project root path.

    Returns:
        Resolved path.
    """
    path = Path(path_value)
    if path.is_absolute():
        return path
    return project_root / path


def load_change_manifest(
    path: Path,
    db_name: str,
) -> tuple[list[str], list[str], str | None]:
    """
    Load a change manifest generated by the index update task.

    Args:
        path: Change manifest path.
        db_name: Active database file name.

    Returns:
        Pending issue keys, pending in-press journal ids, and run id.
    """
    payload = load_json(path, None)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid change manifest file: {path}")

    manifest_db = str(payload.get("db_name") or "").strip()
    if manifest_db and manifest_db != db_name:
        raise ValueError(
            f"Change manifest database mismatch: expected {db_name}, got {manifest_db}"
        )

    raw_issue_keys = to_string_list(payload.get("changed_issue_keys"))
    pending_issue_keys = sorted(
        {
            issue_key
            for issue_key in raw_issue_keys
            if ":" in issue_key and len(issue_key.split(":", maxsplit=1)) == 2
        },
        key=lambda item: parse_issue_key(item),
    )

    pending_inpress_keys: list[str] = []
    seen_inpress_keys: set[str] = set()
    raw_inpress_values = payload.get("changed_inpress_journal_ids")
    if isinstance(raw_inpress_values, list):
        for value in raw_inpress_values:
            journal_id = to_int(value)
            if journal_id is None:
                continue
            journal_key = str(journal_id)
            if journal_key in seen_inpress_keys:
                continue
            seen_inpress_keys.add(journal_key)
            pending_inpress_keys.append(journal_key)
    pending_inpress_keys.sort(key=lambda item: int(item))

    run_id_value = str(payload.get("run_id") or "").strip()
    run_id = run_id_value or None
    return pending_issue_keys, pending_inpress_keys, run_id


def run_notification(args: argparse.Namespace) -> int:
    """
    Execute notification pipeline.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process exit code.
    """
    db_path = resolve_db_path(args.db)
    subscriptions_path = resolve_path(args.subscriptions, PROJECT_ROOT)
    state_dir = resolve_path(args.state_dir, PROJECT_ROOT)
    state_file = state_dir / f"{db_path.stem}.json"
    changes_file_value = str(getattr(args, "changes_file", "") or "").strip()
    changes_file = (
        resolve_path(changes_file_value, PROJECT_ROOT) if changes_file_value else None
    )

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        current_issue_counts = collect_issue_article_counts(connection)
        current_inpress_counts = collect_inpress_article_counts(connection)

        state = load_state(state_file, db_path.name)
        manifest_run_id: str | None = None
        if changes_file is not None:
            (
                pending_issue_keys,
                pending_inpress_keys,
                manifest_run_id,
            ) = load_change_manifest(changes_file, db_path.name)
        else:
            previous_issue_counts = {
                key: int(value)
                for key, value in state["snapshot"]["issue_article_counts"].items()
                if to_int(value) is not None
            }
            previous_inpress_counts = {
                key: int(value)
                for key, value in state["snapshot"]["inpress_article_counts"].items()
                if to_int(value) is not None
            }

            pending_issue_keys = compute_changed_issue_keys(
                previous_issue_counts,
                current_issue_counts,
            )
            pending_inpress_keys = compute_changed_inpress_keys(
                previous_inpress_counts,
                current_inpress_counts,
            )

        if not pending_issue_keys and not pending_inpress_keys:
            state["status"] = "idle"
            state["run"] = None
            state["updated_at"] = utc_now_iso()
            save_json_atomic(state_file, state)
            print("No updated issues or in-press entries to notify.")
            return 0

        run_id = manifest_run_id or utc_now_iso()
        run_state = create_run_state(run_id, pending_issue_keys, pending_inpress_keys)
        state["status"] = "running"
        state["run"] = run_state
        state["updated_at"] = utc_now_iso()
        save_json_atomic(state_file, state)

        issue_candidates = fetch_candidates_for_issue_keys(
            connection,
            pending_issue_keys,
        )
        inpress_candidates = fetch_candidates_for_inpress_keys(
            connection,
            pending_inpress_keys,
        )
        all_candidates = deduplicate_candidates(issue_candidates + inpress_candidates)

        if not all_candidates:
            run_state["status"] = "completed"
            run_state["completed_at"] = utc_now_iso()
            run_state["updated_at"] = utc_now_iso()
            run_state["done_issue_keys"] = pending_issue_keys
            run_state["done_inpress_keys"] = pending_inpress_keys
            run_state["pending_issue_keys"] = []
            run_state["pending_inpress_keys"] = []
            state["snapshot"] = {
                "issue_article_counts": current_issue_counts,
                "inpress_article_counts": current_inpress_counts,
            }
            state["status"] = "completed"
            state["last_completed_run_at"] = utc_now_iso()
            state["updated_at"] = utc_now_iso()
            save_json_atomic(state_file, state)
            print("No visible article candidates found for pending issues.")
            return 0

        global_config, defaults, subscribers = load_subscriptions(subscriptions_path)

        model = str(args.siliconflow_model or "").strip() or defaults.siliconflow_model
        max_candidates = args.max_candidates or defaults.max_candidates
        max_candidates = max(1, max_candidates)
        candidates_for_model = all_candidates[:max_candidates]
        candidates_by_id = {item.article_id: item for item in all_candidates}

        selector = SiliconFlowSelector(
            api_key=global_config.siliconflow_api_key,
            model=model,
            timeout_seconds=args.timeout,
            retries=args.retries,
            temperature=defaults.temperature,
        )
        push_client = PushPlusClient(timeout_seconds=args.timeout, retries=args.retries)

        delivery_dedupe = state.get("delivery_dedupe")
        if not isinstance(delivery_dedupe, dict):
            delivery_dedupe = {}
        state["delivery_dedupe"] = delivery_dedupe

        errors: list[str] = []

        try:
            for subscriber in subscribers:
                try:
                    selection_result = select_articles_with_retries(
                        selector,
                        subscriber,
                        defaults,
                        candidates_for_model,
                        candidates_by_id,
                        delivery_dedupe,
                        MAX_AI_SELECTION_ROUNDS,
                    )
                    accepted = apply_selection_rules(
                        selection_result,
                        subscriber,
                        candidates_by_id,
                        delivery_dedupe,
                    )

                    selected_candidates = [
                        candidates_by_id[item.article_id]
                        for item in accepted
                        if item.article_id in candidates_by_id
                    ]

                    final_summary = selection_result.summary
                    if selected_candidates:
                        try:
                            summarized = selector.summarize_selected_articles(
                                subscriber,
                                selected_candidates,
                            )
                            if summarized:
                                final_summary = summarized
                        except Exception:
                            final_summary = selection_result.summary

                    if not accepted:
                        run_state["user_results"].append(
                            {
                                "subscriber_id": subscriber.subscriber_id,
                                "selected_count": 0,
                                "pushed_count": 0,
                                "message_id": None,
                                "status": "skipped",
                                "error": None,
                            }
                        )
                        run_state["updated_at"] = utc_now_iso()
                        state["updated_at"] = utc_now_iso()
                        save_json_atomic(state_file, state)
                        continue

                    message_title = build_message_title(db_path.name, run_id)
                    content = build_markdown_content(
                        db_path.name,
                        run_id,
                        subscriber,
                        final_summary,
                        accepted,
                        candidates_by_id,
                    )

                    message_id = ""
                    if args.dry_run:
                        print(
                            "DRY RUN",
                            subscriber.subscriber_id,
                            f"selected={len(accepted)}",
                        )
                    else:
                        message_id = push_client.send(
                            token=subscriber.pushplus_token,
                            title=message_title,
                            content=content,
                            channel=global_config.pushplus_channel,
                            template=subscriber.template
                            or global_config.pushplus_template,
                            topic=subscriber.topic or global_config.pushplus_topic,
                            option=global_config.pushplus_option,
                            to=subscriber.to,
                        )
                        sent_at = utc_now_iso()
                        for item in accepted:
                            delivery_key = (
                                f"{subscriber.subscriber_id}:{item.article_id}"
                            )
                            delivery_dedupe[delivery_key] = sent_at

                    run_state["user_results"].append(
                        {
                            "subscriber_id": subscriber.subscriber_id,
                            "selected_count": len(accepted),
                            "pushed_count": len(accepted),
                            "message_id": message_id or None,
                            "status": "ok",
                            "error": None,
                        }
                    )
                except Exception as error:
                    error_message = f"{subscriber.subscriber_id}: {error}"
                    errors.append(error_message)
                    run_state["user_results"].append(
                        {
                            "subscriber_id": subscriber.subscriber_id,
                            "selected_count": 0,
                            "pushed_count": 0,
                            "message_id": None,
                            "status": "error",
                            "error": str(error),
                        }
                    )
                finally:
                    run_state["updated_at"] = utc_now_iso()
                    state["updated_at"] = utc_now_iso()
                    save_json_atomic(state_file, state)
        finally:
            selector.close()
            push_client.close()

        if errors:
            run_state["status"] = "failed"
            run_state["errors"] = errors
            run_state["updated_at"] = utc_now_iso()
            state["status"] = "failed"
            state["updated_at"] = utc_now_iso()
            save_json_atomic(state_file, state)
            print("Notification run failed.")
            for message in errors:
                print(message)
            return 1

        state["delivery_dedupe"] = prune_delivery_dedupe(
            delivery_dedupe,
            args.dedupe_retention_days,
        )
        run_state["status"] = "completed"
        run_state["completed_at"] = utc_now_iso()
        run_state["updated_at"] = utc_now_iso()
        run_state["done_issue_keys"] = pending_issue_keys
        run_state["done_inpress_keys"] = pending_inpress_keys
        run_state["pending_issue_keys"] = []
        run_state["pending_inpress_keys"] = []
        state["status"] = "completed"
        state["last_completed_run_at"] = utc_now_iso()
        state["snapshot"] = {
            "issue_article_counts": current_issue_counts,
            "inpress_article_counts": current_inpress_counts,
        }
        state["updated_at"] = utc_now_iso()
        save_json_atomic(state_file, state)
        print("Notification run completed successfully.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """
    Build CLI parser.

    Args:
        None.

    Returns:
        Argument parser.
    """
    parser = argparse.ArgumentParser(
        description="Select and push updated articles with SiliconFlow and PushPlus"
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Database file under data/index. Defaults to the only sqlite file.",
    )
    parser.add_argument(
        "--subscriptions",
        type=str,
        default=str(DEFAULT_SUBSCRIPTIONS_PATH.relative_to(PROJECT_ROOT)),
        help="Path to subscriptions JSON file.",
    )
    parser.add_argument(
        "--state-dir",
        type=str,
        default=str(DEFAULT_STATE_DIR.relative_to(PROJECT_ROOT)),
        help="Directory for persisted push state files.",
    )
    parser.add_argument(
        "--changes-file",
        type=str,
        default="",
        help=(
            "Optional change manifest from index update. "
            "When provided, notification uses this exact change set."
        ),
    )
    parser.add_argument(
        "--siliconflow-model",
        type=str,
        default="",
        help="Override SiliconFlow model id.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=0,
        help="Maximum candidates sent to model per run. 0 uses config default.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retry count for SiliconFlow and PushPlus calls.",
    )
    parser.add_argument(
        "--dedupe-retention-days",
        type=int,
        default=60,
        help="Days to keep delivery dedupe records.",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run selection without sending PushPlus messages.",
    )
    return parser


def main() -> None:
    """
    Parse CLI arguments and run notification pipeline.

    Args:
        None.

    Returns:
        None.
    """
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run_notification(args))


if __name__ == "__main__":
    main()
