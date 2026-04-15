from __future__ import annotations

from typing import Any

import httpx


def post_to_sheets_webhook(*, client: httpx.Client, webhook_url: str, payload: dict[str, Any]) -> None:
    res = client.post(webhook_url, json=payload, timeout=10.0)
    res.raise_for_status()

