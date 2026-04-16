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
    items = [(k, v) for k, v in mask_summary.items() if v > 0]
    if not items:
        return answer_text

    parts = [f"{k} x{v}" for k, v in sorted(items)]
    summary = "Masked: " + ", ".join(parts)
    return f"{summary}\n\n{answer_text}"

