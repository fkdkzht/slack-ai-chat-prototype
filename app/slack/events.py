from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlackEvent:
    user_id: str
    channel_id: str
    text: str
    ts: str
    thread_ts: str | None

    @property
    def session_id(self) -> str:
        base_ts = self.thread_ts or self.ts
        return f"{self.channel_id}:{base_ts}"


def parse_message_event(payload: dict) -> SlackEvent:
    ev = payload["event"]
    return SlackEvent(
        user_id=ev["user"],
        channel_id=ev["channel"],
        text=ev.get("text", ""),
        ts=ev["ts"],
        thread_ts=ev.get("thread_ts"),
    )

