from datetime import UTC, datetime

from app.session.models import SessionState


def test_session_state_roundtrip() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    s = SessionState(
        session_id="C123:1700000000.0001",
        created_at=now,
        updated_at=now,
        ttl_at=now,
    )
    dumped = s.model_dump(mode="json")
    loaded = SessionState.model_validate(dumped)
    assert loaded.session_id == s.session_id

