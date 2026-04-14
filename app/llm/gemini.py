from __future__ import annotations

from google import genai


def generate_reply(*, api_key: str, model: str, messages: list[dict[str, str]]) -> str:
    client = genai.Client(api_key=api_key)
    res = client.models.generate_content(
        model=model,
        contents=[m["content"] for m in messages],
    )
    text = getattr(res, "text", None)
    if not text:
        raise RuntimeError("Gemini returned empty text")
    return text

