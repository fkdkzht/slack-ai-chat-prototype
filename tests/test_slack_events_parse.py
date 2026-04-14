from app.slack.events import parse_message_event


def test_parse_message_event_and_session_id_prefers_thread_ts() -> None:
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "text": "hi",
            "ts": "1700000000.0001",
            "thread_ts": "1699999999.0009",
        },
    }
    ev = parse_message_event(payload)
    assert ev.user_id == "U1"
    assert ev.channel_id == "C1"
    assert ev.text == "hi"
    assert ev.session_id == "C1:1699999999.0009"


def test_session_id_uses_ts_when_no_thread_ts() -> None:
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "text": "hi",
            "ts": "1700000000.0001",
        },
    }
    ev = parse_message_event(payload)
    assert ev.session_id == "C1:1700000000.0001"

