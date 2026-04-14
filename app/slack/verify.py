import hashlib
import hmac
import time


class SlackVerificationError(Exception):
    pass


def verify_slack_request(
    *,
    signing_secret: str,
    timestamp: str,
    signature: str,
    body: bytes,
    now_epoch: int | None = None,
    max_skew_seconds: int = 60 * 5,
) -> None:
    if now_epoch is None:
        now_epoch = int(time.time())

    try:
        ts_int = int(timestamp)
    except ValueError as e:
        raise SlackVerificationError("invalid timestamp") from e

    if abs(now_epoch - ts_int) > max_skew_seconds:
        raise SlackVerificationError("timestamp skew too large")

    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    expected = "v0=" + digest

    if not hmac.compare_digest(expected, signature):
        raise SlackVerificationError("invalid signature")

