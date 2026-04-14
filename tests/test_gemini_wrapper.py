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

