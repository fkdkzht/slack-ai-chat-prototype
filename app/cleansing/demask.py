from __future__ import annotations

RESTORE_TYPES_P0: set[str] = {
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "LOCATION",
}


def demask_text_policy_p0(text: str, mask_map: dict[str, str]) -> str:
    out = text
    for token in sorted(mask_map.keys(), key=len, reverse=True):
        if token.startswith("<") and token.endswith(">") and "_" in token:
            type_name = token[1 : token.rfind("_")]
            if type_name in RESTORE_TYPES_P0:
                out = out.replace(token, mask_map[token])
    return out

