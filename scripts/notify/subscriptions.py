"""Subscription parsing utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.notify.models import (
    DEFAULT_SILICONFLOW_MODEL,
    PUSHPLUS_CHANNEL,
    NotificationDefaults,
    NotificationGlobal,
    Subscriber,
)
from scripts.notify.state import load_json
from scripts.shared.converters import to_float, to_int, to_string_list


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
