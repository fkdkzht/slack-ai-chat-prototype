from __future__ import annotations

from app.session.models import SessionMessage


def build_messages(history: list[SessionMessage], user_sanitized_text: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    messages.append(
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. Respond concisely in Japanese.\n"
                "User messages may contain placeholder tokens like <PERSON_1> or <EMAIL_ADDRESS_1>. "
                "Those tokens stand in for information the user already shared in this Slack thread; "
                "reply naturally and you may reuse the same tokens when referring to that information.\n"
                "Do not guess or invent new personal details beyond what appears in the conversation "
                "(including placeholders). Do not output raw secrets as plain text; use the given tokens instead."
            ),
        }
    )
    for m in history:
        role = "user" if m.role == "user" else "assistant"
        messages.append({"role": role, "content": m.text})
    messages.append({"role": "user", "content": user_sanitized_text})
    return messages

