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


def test_slack_events_url_verification() -> None:
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )

    client = TestClient(app)
    body = json.dumps({"type": "url_verification", "challenge": "abc"}).encode("utf-8")
    ts = str(int(time.time()))
    sig = _sign("x", ts, body)

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
    assert res.json() == {"challenge": "abc"}

