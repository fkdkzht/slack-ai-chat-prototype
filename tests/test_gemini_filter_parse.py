import json

import pytest

from app.cleansing.gemini_filter import FilterResult, parse_filter_json


def test_parse_filter_json_ok() -> None:
    raw = {
        "sanitized_text": "Hello <EMAIL_1>",
        "pii_items": [{"type": "EMAIL", "value": "alice@example.com", "token": "<EMAIL_1>"}],
        "summary": {"EMAIL": 1},
    }
    r = parse_filter_json(json.dumps(raw))
    assert isinstance(r, FilterResult)
    assert "<EMAIL_1>" in r.sanitized_text
    assert r.summary["EMAIL"] == 1
    assert r.pii_items[0].value == "alice@example.com"


def test_parse_filter_json_rejects_missing_sanitized_text() -> None:
    with pytest.raises(ValueError):
        parse_filter_json('{"pii_items": [], "summary": {}}')

