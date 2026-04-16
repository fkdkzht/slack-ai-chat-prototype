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
            "sanitized_text": "Hello <EMAIL_ADDRESS_1>",
            "pii_items": [
                {"type": "EMAIL_ADDRESS", "value": "alice@example.com", "token": "<EMAIL_ADDRESS_1>"},
            ],
            "summary": {"EMAIL_ADDRESS": 1},
        }

    exported = {}

    def export_hook(payload: dict):
        exported.update(payload)

    def fake_chat(messages):
        # ensure chat only sees sanitized content
        assert any("<EMAIL_ADDRESS_1>" in m["content"] for m in messages)
        assert not any("alice@example.com" in m["content"] for m in messages)
        return "ok <EMAIL_ADDRESS_1>"

    new_state, summary, reply = handle_user_message(
        state=state,
        user_text="my email is alice@example.com",
        user_ts="1",
        generate_reply_fn=fake_chat,
        ttl_hours=24,
        filter_fn=fake_filter,
        export_hook=export_hook,
    )
    assert "alice@example.com" in reply
    assert summary["EMAIL_ADDRESS"] == 1
    assert "sanitized_text" in exported


def test_filter_path_chat_never_sees_raw_secret_and_history_is_sanitized() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = SessionState(session_id="C:1", created_at=now, updated_at=now, ttl_at=now)
    secret = "alice@example.com"

    def fake_filter(_raw: str):
        return {
            "sanitized_text": f"Hello <EMAIL_ADDRESS_1>",
            "pii_items": [
                {"type": "EMAIL_ADDRESS", "value": secret, "token": "<EMAIL_ADDRESS_1>"},
            ],
            "summary": {"EMAIL_ADDRESS": 1},
        }

    seen_messages: list[list[dict[str, str]]] = []

    def fake_chat(messages: list[dict[str, str]]) -> str:
        seen_messages.append(messages)
        joined = "\n".join(m["content"] for m in messages)
        assert secret not in joined
        assert "<EMAIL_ADDRESS_1>" in joined
        return "received"

    new_state, _, reply = handle_user_message(
        state=state,
        user_text=f"my email is {secret}",
        user_ts="1",
        generate_reply_fn=fake_chat,
        ttl_hours=24,
        filter_fn=fake_filter,
    )
    assert new_state.history[0].text == "Hello <EMAIL_ADDRESS_1>"
    assert new_state.history[0].role == "user"
    assert secret not in new_state.history[0].text
    assert new_state.history[1].text == "received"
    assert secret not in reply


def test_filter_path_restores_person_token_in_slack_reply() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = SessionState(session_id="C:1", created_at=now, updated_at=now, ttl_at=now)
    name = "山田太郎"

    def fake_filter(_raw: str):
        return {
            "sanitized_text": f"私の名前は <PERSON_1> です。",
            "pii_items": [{"type": "PERSON", "value": name, "token": "<PERSON_1>"}],
            "summary": {"PERSON": 1},
        }

    def fake_chat(messages: list[dict[str, str]]) -> str:
        assert name not in "\n".join(m["content"] for m in messages)
        assert "<PERSON_1>" in messages[-1]["content"]
        return "こんにちは、<PERSON_1>さん。"

    _new_state, _summary, reply = handle_user_message(
        state=state,
        user_text=f"私の名前は {name} です。",
        user_ts="1",
        generate_reply_fn=fake_chat,
        ttl_hours=24,
        filter_fn=fake_filter,
    )
    assert name in reply
    assert "<PERSON_1>" not in reply
