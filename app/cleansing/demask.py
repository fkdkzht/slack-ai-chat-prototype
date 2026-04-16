from __future__ import annotations

def _is_presidio_style_token(token: str) -> bool:
    if not (token.startswith("<") and token.endswith(">")):
        return False

    body = token[1:-1]
    if "_" not in body:
        return False

    prefix, suffix = body.rsplit("_", 1)
    return bool(prefix) and bool(suffix) and suffix.isdigit()


def demask_text_policy_p0(text: str, mask_map: dict[str, str]) -> str:
    out = text
    for token in sorted(mask_map.keys(), key=len, reverse=True):
        if _is_presidio_style_token(token):
            replacement = mask_map.get(token)
            if replacement is not None:
                out = out.replace(token, replacement)
    return out

