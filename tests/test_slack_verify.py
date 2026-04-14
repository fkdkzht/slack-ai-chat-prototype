import hashlib
import hmac

import pytest

from app.slack.verify import SlackVerificationError, verify_slack_request


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return "v0=" + digest


def test_verify_ok() -> None:
    secret = "secret"
    ts = "1700000000"
    body = b'{"type":"url_verification"}'
    sig = _sign(secret, ts, body)
    verify_slack_request(
        signing_secret=secret,
        timestamp=ts,
        signature=sig,
        body=body,
        now_epoch=1700000001,
    )


def test_verify_rejects_invalid_signature() -> None:
    secret = "secret"
    ts = "1700000000"
    body = b'{"type":"url_verification"}'
    with pytest.raises(SlackVerificationError):
        verify_slack_request(
            signing_secret=secret,
            timestamp=ts,
            signature="v0=deadbeef",
            body=body,
            now_epoch=1700000001,
        )


def test_verify_rejects_replay_skew() -> None:
    secret = "secret"
    ts = "1700000000"
    body = b'{"type":"url_verification"}'
    sig = _sign(secret, ts, body)
    with pytest.raises(SlackVerificationError):
        verify_slack_request(
            signing_secret=secret,
            timestamp=ts,
            signature=sig,
            body=body,
            now_epoch=1700000000 + 60 * 10,
        )

