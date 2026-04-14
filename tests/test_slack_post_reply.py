import app.slack.reply as reply


def test_post_thread_reply_calls_chat_postMessage(monkeypatch) -> None:
    calls = {}

    class DummyClient:
        def __init__(self, token: str):
            calls["token"] = token

        def chat_postMessage(self, *, channel: str, thread_ts: str, text: str):
            calls["channel"] = channel
            calls["thread_ts"] = thread_ts
            calls["text"] = text

    monkeypatch.setattr(reply, "WebClient", DummyClient)

    reply.post_thread_reply(
        bot_token="xoxb-123",
        channel_id="C1",
        thread_ts="1700000000.0001",
        text="hello",
    )

    assert calls == {
        "token": "xoxb-123",
        "channel": "C1",
        "thread_ts": "1700000000.0001",
        "text": "hello",
    }

