from __future__ import annotations

from google import genai


def generate_reply(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    allow_web_search: bool = False,
) -> str:
    client = genai.Client(api_key=api_key)
    config = None
    if allow_web_search:
        from google.genai import types

        google_search_tool = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(tools=[google_search_tool])
    res = client.models.generate_content(
        model=model,
        contents=[m["content"] for m in messages],
        config=config,
    )
    text = getattr(res, "text", None)
    if not text:
        raise RuntimeError("Gemini returned empty text")
    return text

