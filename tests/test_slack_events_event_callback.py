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

