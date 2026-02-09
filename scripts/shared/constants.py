"""Shared constants used across script modules."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_DIR = PROJECT_ROOT / "data" / "index"
PUSH_STATE_DIR = PROJECT_ROOT / "data" / "push_state"

DEFAULT_LIBRARY_ID = "3050"
WEIPU_LIBRARY_ID = "-1"
FALLBACK_LIBRARIES = ["215", "866", "72", "853", "554", "371", "230"]
BROWZINE_BASE_URL = "https://api.thirdiron.com/v2"
TOKEN_EXPIRY_BUFFER = 300

DB_TIMEOUT_SECONDS = 30
DB_RETRY_ATTEMPTS = 6
DB_RETRY_BASE_DELAY = 0.5
SQLITE_INT_MAX = (1 << 63) - 1
SQLITE_INT_MIN = -(1 << 63)

SIMPLE_TOKENIZER_ENV = "SIMPLE_TOKENIZER_PATH"
NOTIFY_STATE_DIR = "data/push_state"
MAX_LIMIT = 200
API_PREFIX = "/api"
