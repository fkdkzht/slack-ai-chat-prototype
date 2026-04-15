from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable
import json

from app.cleansing.demask import demask_text_policy_p0
from app.cleansing.presidio import cleanse_text_presidio
from app.llm.prompt import build_messages
from app.session.models import SessionMessage, SessionState


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
        pii_items = list(out.get("pii_items") or [])
        mask_summary = dict(out.get("summary") or {})
        # Demo mode: we do not demask via token->value; keep reply as-is
        mask_map = {}

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
