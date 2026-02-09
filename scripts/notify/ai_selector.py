"""SiliconFlow selection client."""

from __future__ import annotations

import json
import time
from typing import Any, cast

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam, completion_create_params

from scripts.notify.models import (
    SILICONFLOW_BASE_URL,
    ArticleCandidate,
    NotificationDefaults,
    RankedSelection,
    SelectionResult,
    Subscriber,
)
from scripts.shared.converters import to_float, to_int, truncate_text


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
                "priority_order": [
                    (
                        "First pass: directions-first filtering. "
                        "When directions are provided, only keep candidates "
                        "that clearly match at least one direction."
                    ),
                    (
                        "Second pass: within the direction-matched subset, "
                        "rank by keyword relevance."
                    ),
                    (
                        "Third pass: break ties by methodological rigor, "
                        "recency, and practical or theoretical contribution."
                    ),
                ],
                "must_follow": [
                    (
                        "Directions have higher priority than keywords. "
                        "Do not elevate a keyword-only paper over a weaker "
                        "direction-matched paper."
                    ),
                    (
                        "If directions are non-empty and at least one candidate "
                        "matches directions, do not select direction-mismatched papers."
                    ),
                    (
                        "If directions are empty or no candidate matches directions, "
                        "fallback to keyword relevance."
                    ),
                ],
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
                        "Use two-stage selection: directions-first filtering, "
                        "then keyword-based ranking in the filtered set. "
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
