from datetime import UTC, datetime

from app.orchestrator import handle_user_message
from app.session.models import SessionState


def test_orchestrator_restores_allowed_entities() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = SessionState(session_id="C:1", created_at=now, updated_at=now, ttl_at=now)

    def stub(messages: list[dict[str, str]]) -> str:
        return messages[-1]["content"]

    new_state, summary, reply = handle_user_message(
        state=state,
        user_text="Email alice@example.com",
        user_ts="1",
        generate_reply_fn=stub,
        ttl_hours=24,
    )
    assert new_state.history
    assert summary
    assert "alice@example.com" in reply


def test_orchestrator_accepts_custom_filter_and_export_hook() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = SessionState(session_id="C:1", created_at=now, updated_at=now, ttl_at=now)

    def fake_filter(raw_text: str):
        return {
            "sanitized_text": "Hello <EMAIL_1>",
            "pii_items": [{"type": "EMAIL", "value": "alice@example.com", "token": "<EMAIL_1>"}],
            "summary": {"EMAIL": 1},
        }

    exported = {}

    def export_hook(payload: dict):
        exported.update(payload)

    def fake_chat(messages):
        # ensure chat only sees sanitized content
        assert any("<EMAIL_1>" in m["content"] for m in messages)
        assert not any("alice@example.com" in m["content"] for m in messages)
        return "ok"

    new_state, summary, reply = handle_user_message(
        state=state,
        user_text="my email is alice@example.com",
        user_ts="1",
        generate_reply_fn=fake_chat,
        ttl_hours=24,
        filter_fn=fake_filter,
        export_hook=export_hook,
    )
    assert reply
    assert summary["EMAIL"] == 1
    assert "sanitized_text" in exported
