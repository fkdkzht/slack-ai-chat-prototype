import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.session.models import SessionState
from app.settings import Settings, get_settings


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return "v0=" + digest


class _FakeSessionStore:
    def __init__(self) -> None:
        self._docs: dict[str, SessionState] = {}
        self._claimed: set[str] = set()

    def get(self, session_id: str) -> SessionState | None:
        return self._docs.get(session_id)

    def upsert(self, state: SessionState) -> None:
        self._docs[state.session_id] = state

    def new_state(self, session_id: str) -> SessionState:
        now = datetime.now(UTC)
        return SessionState(
            session_id=session_id,
            created_at=now,
            updated_at=now,
            ttl_at=now + timedelta(hours=24),
        )

    def try_claim_slack_event_delivery(self, event_id: str) -> bool:
        if not event_id:
            return True
        if event_id in self._claimed:
            return False
        self._claimed.add(event_id)
        return True


def test_slack_events_event_callback_message_returns_debug_reply() -> None:
    from app.main import app, get_session_store

    app.dependency_overrides[get_settings] = lambda: Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )
    fake_store = _FakeSessionStore()
    app.dependency_overrides[get_session_store] = lambda: fake_store

    client = TestClient(app)
    payload = {
        "type": "event_callback",
        "event_id": "Ev0001",
        "authorizations": [{"user_id": "UBOT", "is_bot": True}],
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

    def fake_generate_reply(*, api_key: str, model: str, messages: list[dict[str, str]]) -> str:
        return f"(sanitized) {messages[-1]['content']}"

    main_mod.post_thread_reply = fake_post_thread_reply
    main_mod.generate_reply = fake_generate_reply

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
    assert j == {"ok": True}
    assert posted["channel_id"] == "C1"
    assert posted["thread_ts"] == "1700000000.0001"
    assert "Masked:" in posted["text"]
    assert "alice@example.com" in posted["text"]
    session_id = "C1:1700000000.0001"
    saved = fake_store.get(session_id)
    assert saved is not None
    assert saved.history
    joined = "\n".join(m.text for m in saved.history)
    assert "alice@example.com" not in joined


def test_slack_duplicate_event_id_does_not_post_twice() -> None:
    from app.main import app, get_session_store

    app.dependency_overrides[get_settings] = lambda: Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )
    fake_store = _FakeSessionStore()
    app.dependency_overrides[get_session_store] = lambda: fake_store

    client = TestClient(app)
    payload = {
        "type": "event_callback",
        "event_id": "EvDEDUP",
        "authorizations": [{"user_id": "UBOT", "is_bot": True}],
        "event": {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "text": "hi",
            "ts": "1700000000.0001",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    sig = _sign("x", ts, body)

    import app.main as main_mod

    posted: list[str] = []

    def fake_post_thread_reply(*, bot_token: str, channel_id: str, thread_ts: str, text: str) -> None:
        posted.append(text)

    main_mod.post_thread_reply = fake_post_thread_reply
    main_mod.generate_reply = lambda **kwargs: "ok"

    for _ in range(2):
        ts2 = str(int(time.time()))
        sig2 = _sign("x", ts2, body)
        res = client.post(
            "/slack/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": ts2,
                "X-Slack-Signature": sig2,
            },
        )
        assert res.status_code == 200
        assert res.json() == {"ok": True}

    assert len(posted) == 1


def test_slack_events_demo_mode_filters_and_exports_and_chat_sees_sanitized_only() -> None:
    from app.main import app, get_session_store
    from app.cleansing.gemini_filter import FilterResult, PiiItem

    app.dependency_overrides[get_settings] = lambda: Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
        demo_mode=True,
        gemini_filter_model="filter-model",
        gemini_chat_model="chat-model",
        sheets_webhook_url="https://example.invalid/webhook",
    )
    fake_store = _FakeSessionStore()
    app.dependency_overrides[get_session_store] = lambda: fake_store

    client = TestClient(app)
    payload = {
        "type": "event_callback",
        "event_id": "EvDEMO1",
        "authorizations": [{"user_id": "UBOT", "is_bot": True}],
        "event": {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "text": "Email me at alice@example.com",
            "ts": "1700000000.0002",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    sig = _sign("x", ts, body)

    import app.main as main_mod

    sheets_posts: list[dict] = []
    chat_calls: list[dict] = []

    def fake_run_gemini_filter(*, api_key: str, model: str, raw_text: str):
        assert raw_text == "Email me at alice@example.com"
        return FilterResult(
            sanitized_text="hi <EMAIL_1>",
            pii_items=[PiiItem(type="EMAIL", value="alice@example.com", token="<EMAIL_1>")],
            summary={"EMAIL": 1},
        )

    def fake_post_to_sheets_webhook(*, client, webhook_url: str, payload: dict) -> None:
        sheets_posts.append({"webhook_url": webhook_url, "payload": payload})

    def fake_generate_reply(*, api_key: str, model: str, messages: list[dict[str, str]]) -> str:
        chat_calls.append({"api_key": api_key, "model": model, "messages": messages})
        return "ok"

    main_mod.run_gemini_filter = fake_run_gemini_filter
    main_mod.post_to_sheets_webhook = fake_post_to_sheets_webhook
    main_mod.generate_reply = fake_generate_reply
    main_mod.post_thread_reply = lambda **kwargs: None

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
    assert res.json() == {"ok": True}

    assert len(sheets_posts) == 1
    posted_payload = sheets_posts[0]["payload"]
    assert "message_log" in posted_payload
    assert "pii_dictionary" in posted_payload
    assert posted_payload["message_log"]["event_id"] == "EvDEMO1"
    assert posted_payload["message_log"]["sanitized_text"] == "hi <EMAIL_1>"
    assert posted_payload["pii_dictionary"] == [
        {
            "ts": "1700000000.0002",
            "event_id": "EvDEMO1",
            "pii_type": "EMAIL",
            "token": "<EMAIL_1>",
            "value": "alice@example.com",
        }
    ]

    assert len(chat_calls) == 1
    msg_texts = " ".join(m.get("content", "") for m in chat_calls[0]["messages"])
    assert "<EMAIL_1>" in msg_texts
    assert "alice@example.com" not in msg_texts
    assert chat_calls[0]["model"] == "chat-model"
    session_id = "C1:1700000000.0002"
    saved = fake_store.get(session_id)
    assert saved is not None
    assert saved.history
    joined = "\n".join(m.text for m in saved.history)
    assert "alice@example.com" not in joined
    assert "<EMAIL_1>" in joined


def test_slack_skips_message_from_bot_user() -> None:
    from app.main import app, get_session_store

    app.dependency_overrides[get_settings] = lambda: Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )
    fake_store = _FakeSessionStore()
    app.dependency_overrides[get_session_store] = lambda: fake_store

    client = TestClient(app)
    payload = {
        "type": "event_callback",
        "event_id": "EvBOT",
        "authorizations": [{"user_id": "UBOT", "is_bot": True}],
        "event": {
            "type": "message",
            "user": "UBOT",
            "channel": "C1",
            "text": "hello",
            "ts": "1700000000.0001",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    sig = _sign("x", ts, body)

    import app.main as main_mod

    posted: list[str] = []

    def fake_post_thread_reply(*, bot_token: str, channel_id: str, thread_ts: str, text: str) -> None:
        posted.append(text)

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
    assert res.json() == {"ok": True}
    assert posted == []

