from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable
import json
import re

from app.cleansing.demask import demask_text_policy_p0
from app.cleansing.presidio import cleanse_text_presidio
from app.llm.prompt import build_messages
from app.session.models import SessionMessage, SessionState


_PRESIDIO_STYLE_TOKEN_RE = re.compile(r"^<(?P<type>[A-Z0-9_]+)_(?P<idx>\d+)>$")

_PII_TYPE_ALIASES: dict[str, str] = {
    "EMAIL": "EMAIL_ADDRESS",
    "PHONE": "PHONE_NUMBER",
    "DATE_OF_BIRT": "DATE_OF_BIRTH",
}


def _normalize_pii_type(token_type: str) -> str:
    return _PII_TYPE_ALIASES.get(token_type, token_type)


def _normalize_filter_pii_items(
    pii_items: Any,
) -> tuple[list[dict[str, str]], dict[str, str], dict[str, int]]:
    normalized_items: list[dict[str, str]] = []
    mask_map: dict[str, str] = {}
    counts: dict[str, int] = {}

    if not isinstance(pii_items, list):
        return normalized_items, mask_map, {}

    for item in pii_items:
        if not isinstance(item, dict):
            continue
        tok = item.get("token")
        val = item.get("value")
        if not isinstance(tok, str) or not isinstance(val, str):
            continue
        if not val:
            continue
        m = _PRESIDIO_STYLE_TOKEN_RE.match(tok)
        if m is None:
            continue
        pii_type = _normalize_pii_type(m.group("type"))

        normalized_items.append({"type": pii_type, "value": val, "token": tok})
        mask_map[tok] = val
        counts[pii_type] = counts.get(pii_type, 0) + 1

    mask_summary = {k: v for k, v in counts.items() if v > 0}
    return normalized_items, mask_map, mask_summary


def handle_user_message(
    *,
    state: SessionState,
    user_text: str,
    user_ts: str,
    generate_reply_fn,
    ttl_hours: int,
    filter_fn: Callable[[str], dict[str, Any]] | None = None,
    export_hook: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[SessionState, dict[str, int], str]:
    if filter_fn is None:
        cleansing = cleanse_text_presidio(user_text)
        sanitized_text = cleansing.sanitized_text
        mask_map = cleansing.mask_map
        mask_summary = cleansing.mask_summary
        pii_items: list[dict[str, str]] = []
    else:
        out = filter_fn(user_text)
        sanitized_text = str(out.get("sanitized_text") or "")
        pii_items, mask_map, mask_summary = _normalize_filter_pii_items(out.get("pii_items"))

        if export_hook is not None:
            export_hook(
                {
                    "ts": user_ts,
                    "sanitized_text": sanitized_text,
                    "pii_items": pii_items,
                    "summary": mask_summary,
                    "pii_summary_json": json.dumps(mask_summary, ensure_ascii=False),
                }
            )

    messages = build_messages(state.history, sanitized_text)
    assistant_sanitized = generate_reply_fn(messages)
    combined_mask = {**state.mask_map, **mask_map}
    assistant_restored = demask_text_policy_p0(assistant_sanitized, combined_mask)
    state.history.append(SessionMessage(role="user", text=sanitized_text, ts=user_ts))
    state.history.append(SessionMessage(role="assistant", text=assistant_sanitized, ts=user_ts))
    state.mask_map.update(mask_map)
    state.mask_summary = mask_summary
    now = datetime.now(UTC)
    state.updated_at = now
    state.ttl_at = now + timedelta(hours=ttl_hours)
    return state, mask_summary, assistant_restored
