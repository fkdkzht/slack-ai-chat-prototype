from __future__ import annotations

import json
from dataclasses import dataclass


class _GenAiProxy:
    Client = None


genai = _GenAiProxy()


@dataclass(frozen=True)
class PiiItem:
    type: str
    value: str
    token: str


@dataclass(frozen=True)
class FilterResult:
    sanitized_text: str
    pii_items: list[PiiItem]
    summary: dict[str, int]


def parse_filter_json(text: str) -> FilterResult:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            for i in range(1, len(lines)):
                if lines[i].startswith("```"):
                    text = "\n".join(lines[1:i]).strip()
                    break

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError("filter returned non-json") from e

    if not isinstance(obj, dict):
        raise ValueError("filter returned non-object json")

    sanitized_text = obj.get("sanitized_text")
    if not isinstance(sanitized_text, str) or not sanitized_text:
        raise ValueError("missing sanitized_text")

    summary = obj.get("summary") or {}
    if not isinstance(summary, dict):
        raise ValueError("invalid summary")

    pii_items_raw = obj.get("pii_items") or []
    if not isinstance(pii_items_raw, list):
        raise ValueError("invalid pii_items")

    pii_items: list[PiiItem] = []
    for it in pii_items_raw:
        if not isinstance(it, dict):
            continue
        t = it.get("type")
        v = it.get("value")
        tok = it.get("token")
        if isinstance(t, str) and isinstance(v, str) and isinstance(tok, str):
            pii_items.append(PiiItem(type=t, value=v, token=tok))

    summary_int: dict[str, int] = {}
    for k, v in summary.items():
        if isinstance(k, str) and isinstance(v, int):
            summary_int[k] = v

    return FilterResult(sanitized_text=sanitized_text, pii_items=pii_items, summary=summary_int)


def run_gemini_filter(api_key: str, model: str, raw_text: str) -> FilterResult:
    if genai.Client is None:
        from google import genai as _real_genai

        genai.Client = _real_genai.Client

    client = genai.Client(api_key=api_key)
    prompt = (
        "You are a PII redaction filter.\n"
        "Return ONLY valid JSON with keys: sanitized_text (string), pii_items (array), summary (object).\n"
        "Replace PII with tokens that use Presidio-style type names and a numeric suffix, e.g. "
        "<EMAIL_ADDRESS_1>, <PHONE_NUMBER_1>, <PERSON_1>, <LOCATION_1>.\n"
        "pii_items entries: {type, value, token} where type matches the prefix inside the angle brackets "
        "(e.g. type EMAIL_ADDRESS for token <EMAIL_ADDRESS_1>).\n"
        "summary: map each type string to an integer count.\n"
        "Do not include any extra commentary.\n"
        "Input:\n"
        f"{raw_text}"
    )
    res = client.models.generate_content(model=model, contents=[prompt])
    out = getattr(res, "text", None)
    if not out:
        raise RuntimeError("Gemini filter returned empty text")
    return parse_filter_json(out)

