from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
) -> tuple[SessionState, dict[str, int], str]:
    cleansing = cleanse_text_presidio(user_text)
    messages = build_messages(state.history, cleansing.sanitized_text)
    assistant_sanitized = generate_reply_fn(messages)
    combined_mask = {**state.mask_map, **cleansing.mask_map}
    assistant_restored = demask_text_policy_p0(assistant_sanitized, combined_mask)
    state.history.append(SessionMessage(role="user", text=cleansing.sanitized_text, ts=user_ts))
    state.history.append(SessionMessage(role="assistant", text=assistant_sanitized, ts=user_ts))
    state.mask_map.update(cleansing.mask_map)
    state.mask_summary = cleansing.mask_summary
    now = datetime.now(UTC)
    state.updated_at = now
    state.ttl_at = now + timedelta(hours=ttl_hours)
    return state, cleansing.mask_summary, assistant_restored
