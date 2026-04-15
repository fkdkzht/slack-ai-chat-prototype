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
