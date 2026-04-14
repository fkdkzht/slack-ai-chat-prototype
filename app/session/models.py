from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SessionMessage(BaseModel):
    role: str  # "user" | "assistant"
    text: str  # sanitized text only
    ts: str


class SessionState(BaseModel):
    session_id: str
    mask_map: dict[str, str] = Field(default_factory=dict)
    mask_summary: dict[str, int] = Field(default_factory=dict)
    history: list[SessionMessage] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    ttl_at: datetime

