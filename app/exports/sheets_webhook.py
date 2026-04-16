from __future__ import annotations

from typing import Any

import httpx


def post_to_sheets_webhook(*, client: httpx.Client, webhook_url: str, payload: dict[str, Any]) -> None:
    # Apps Script `/exec` commonly returns a 302 to a googleusercontent "echo" URL.
    # POSTing to the echo URL is not reliable (often 405), so we:
    # - POST to `/exec` without following redirects
    # - if 302, GET the Location URL to complete execution (this is what browsers effectively do)
    res = client.post(webhook_url, json=payload, timeout=10.0, follow_redirects=False)
    if res.status_code in (301, 302, 303, 307, 308):
        loc = res.headers.get("location")
        if not loc:
            res.raise_for_status()
        get_res = client.get(loc, timeout=10.0, follow_redirects=True)
        get_res.raise_for_status()
        return
    res.raise_for_status()

