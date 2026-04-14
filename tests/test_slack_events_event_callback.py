import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from app.settings import Settings, get_settings


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return "v0=" + digest


def test_slack_events_event_callback_message_returns_debug_reply() -> None:
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )

    client = TestClient(app)
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "text": "Email me at alice@example.com",
            "ts": "1700000000.0001",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    sig = _sign("x", ts, body)

    import app.main as main_mod

    posted = {}

    def fake_post_thread_reply(*, bot_token: str, channel_id: str, thread_ts: str, text: str) -> None:
        posted["bot_token"] = bot_token
        posted["channel_id"] = channel_id
        posted["thread_ts"] = thread_ts
        posted["text"] = text

    main_mod.post_thread_reply = fake_post_thread_reply

    res = client.post(
        "/slack/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
        },
    )
    assert res.status_code == 200
    j = res.json()
    assert j["ok"] is True
    assert j["debug"]["session_id"] == "C1:1700000000.0001"
    assert j["debug"]["mask_summary"]["EMAIL_ADDRESS"] == 1
    assert "Masked:" in j["debug"]["mask_summary_text"]
    assert "alice@example.com" in j["debug"]["reply_text"]
    assert posted["channel_id"] == "C1"
    assert posted["thread_ts"] == "1700000000.0001"
    assert "Masked:" in posted["text"]
    assert "alice@example.com" in posted["text"]

