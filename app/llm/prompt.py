from __future__ import annotations

from app.session.models import SessionMessage


def build_messages(history: list[SessionMessage], user_sanitized_text: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    messages.append(
        {
            "role": "system",
            "content": "You are a helpful assistant. Never ask for or reveal masked secrets. Respond concisely in Japanese.",
        }
    )
    for m in history:
        role = "user" if m.role == "user" else "assistant"
        messages.append({"role": role, "content": m.text})
    messages.append({"role": "user", "content": user_sanitized_text})
    return messages

