import json

import pytest

from app.cleansing.gemini_filter import FilterResult, parse_filter_json, run_gemini_filter


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


def test_run_gemini_filter_accepts_positional_args(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DummyResponse:
        def __init__(self, text: str) -> None:
            self.text = text

    class _DummyModels:
        def generate_content(self, *, model: str, contents: list[str]) -> _DummyResponse:
            _ = model
            _ = contents
            return _DummyResponse(
                json.dumps(
                    {
                        "sanitized_text": "Hello <EMAIL_1>",
                        "pii_items": [
                            {"type": "EMAIL", "value": "alice@example.com", "token": "<EMAIL_1>"}
                        ],
                        "summary": {"EMAIL": 1},
                    }
                )
            )

    class _DummyClient:
        def __init__(self, *, api_key: str) -> None:
            _ = api_key
            self.models = _DummyModels()

    monkeypatch.setattr("app.cleansing.gemini_filter.genai.Client", _DummyClient)

    r = run_gemini_filter("fake-key", "fake-model", "hi alice@example.com")
    assert r.sanitized_text == "Hello <EMAIL_1>"
    assert r.summary["EMAIL"] == 1
    assert r.pii_items[0].value == "alice@example.com"

