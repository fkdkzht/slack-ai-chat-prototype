from app.llm.prompt import build_messages
from app.session.models import SessionMessage


def test_build_messages_includes_history_and_user() -> None:
    history = [
        SessionMessage(role="user", text="hello <EMAIL_ADDRESS_1>", ts="1"),
        SessionMessage(role="assistant", text="ok", ts="2"),
    ]
    messages = build_messages(history, "next <PHONE_NUMBER_1>")
    assert messages[0]["role"] == "system"
    sys = messages[0]["content"]
    assert "placeholder" in sys.lower() or "プレース" in sys or "<PERSON_1>" in sys
    assert messages[-1]["role"] == "user"
    assert "next" in messages[-1]["content"]

