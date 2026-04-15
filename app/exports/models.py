from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SheetsPiiDictionaryRow:
    ts: str
    event_id: str
    pii_type: str
    token: str
    value: str


@dataclass(frozen=True)
class SheetsMessageLogRow:
    ts: str
    event_id: str
    sanitized_text: str
    pii_summary_json: str

