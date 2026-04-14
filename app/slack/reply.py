from __future__ import annotations

from slack_sdk import WebClient


def post_thread_reply(
    *,
    bot_token: str,
    channel_id: str,
    thread_ts: str,
    text: str,
) -> None:
    client = WebClient(token=bot_token)
    client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=text)


def format_first_reply(*, mask_summary: dict[str, int], answer_text: str) -> str:
    parts = [f"{k} x{v}" for k, v in sorted(mask_summary.items())]
    summary = "Masked: " + (", ".join(parts) if parts else "NONE")
    return f"{summary}\n\n{answer_text}"

