from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

_logger = logging.getLogger("slack_ai_chat")


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def configure_app_logging(app_env: str | None = None) -> None:
    """Configure root logging once. ``dev`` = verbose (PII-safe fields only). ``prod`` = quieter."""
    env = (app_env or os.environ.get("APP_ENV", "dev")).lower()
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    root.setLevel(logging.INFO)
    _logger.setLevel(logging.DEBUG if env == "dev" else logging.INFO)


def slack_ingest_log(app_env: str, message: str, **fields: Any) -> None:
    """Structured, PII-safe diagnostics for Slack ingestion. In prod, omit most detail."""
    env = (app_env or "dev").lower()
    safe = {k: v for k, v in fields.items() if v is not None}
    if env == "dev":
        parts = " ".join(f"{k}={v}" for k, v in sorted(safe.items()))
        _logger.info("%s | %s", message, parts)
        return
    # prod: keep volume low; no raw user text or channel ids in fields
    outcome = safe.get("outcome")
    if outcome in ("handler_error", "bad_json", "verify_failed"):
        _logger.error("%s | %s", message, " ".join(f"{k}={v}" for k, v in sorted(safe.items())))
    elif outcome == "posted":
        _logger.info("%s | event_id=%s", message, safe.get("event_id"))

