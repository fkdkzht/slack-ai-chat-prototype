import pytest


def test_generate_reply_raises_on_empty_text(monkeypatch) -> None:
    import app.llm.gemini as mod

    class DummyRes:
        text = ""

    class DummyModels:
        def generate_content(self, **_kwargs):
            return DummyRes()

    class DummyClient:
        def __init__(self, **_kwargs):
            self.models = DummyModels()

    monkeypatch.setattr(mod.genai, "Client", DummyClient)

    with pytest.raises(RuntimeError):
        mod.generate_reply(
            api_key="x",
            model="x",
            messages=[{"role": "user", "content": "hi"}],
        )


def test_generate_reply_web_search_adds_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.llm.gemini as gem

    captured: dict[str, object] = {}

    class _DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config=None):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config

            class _Res:
                text = "ok"

            return _Res()

    class _DummyClient:
        def __init__(self, *, api_key: str):
            self.models = _DummyModels()

    monkeypatch.setattr(gem.genai, "Client", _DummyClient)

    out = gem.generate_reply(
        api_key="k",
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        allow_web_search=True,
    )
    assert out == "ok"
    assert captured["config"] is not None
    assert getattr(captured["config"], "tools", None)

