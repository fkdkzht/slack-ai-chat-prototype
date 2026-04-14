# Slack AI Chat + 自動クレンジング（PII/機密）プロトタイプ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slack DM でボットに話しかけると、入力が自動クレンジング（マスク）された状態で Gemini API に送られ、復元ポリシーに従って自然な回答を Slack スレッドに返すプロトタイプを Cloud Run + Firestore(Tokyo) でデモ可能にする。

**Architecture:** Slack Events API で DM/スレッド返信を受信 → 署名検証/リプレイ対策 → Presidio で PII 検出/マスクし `mask_map` を生成 → Firestore(Tokyo) にセッション状態（サニタイズ済み履歴 + `mask_map` + `mask_summary`）を TTL 付きで保存 → Gemini に投入（外部送信はサニタイズ済みのみ）→ 応答へ `mask_map` を適用してポリシー P0 で復元 → Slack スレッドに返信（初回はマスクサマリ付き）。

**Tech Stack:** Python 3.12, FastAPI(Uvicorn), Slack Events API (request signature verification), Presidio (analyzer/anonymizer), Google Cloud Firestore (asia-northeast1), Gemini API (Google GenAI SDK), Cloud Run.

---

## Scope / 前提

- 本計画は `docs/superpowers/specs/2026-04-14-slack-ai-chat-with-pii-cleansing-design.md` の Phase 0（デモ最速）範囲を実装対象とする
- “Step2（疑わしい場合のみローカルLLM判定）” や添付ファイル対応は **実装しない**
- 実装時は **生値をログに出さない**（Slack表示・アプリログとも）
- Firestore は **Native mode / Tokyo** を前提（ロケーションは後から変えられない）

## Repository / File Structure (this plan locks it in)

**Create:**
- `app/main.py` (FastAPI entrypoint + routes)
- `app/settings.py` (env settings loading)
- `app/logging_.py` (PII-safe logging helpers)
- `app/slack/verify.py` (Slack署名検証 + リプレイ対策)
- `app/slack/events.py` (イベント正規化 + 返信ユーティリティ)
- `app/cleansing/presidio.py` (PII検出/マスク、`mask_map`/`mask_summary`生成)
- `app/cleansing/demask.py` (復元ポリシーP0)
- `app/session/models.py` (session schema)
- `app/session/store_firestore.py` (Firestore CRUD + TTL)
- `app/llm/gemini.py` (Gemini呼び出し)
- `tests/test_slack_verify.py`
- `tests/test_cleansing_presidio.py`
- `tests/test_demask_policy_p0.py`
- `tests/test_prompt_assembly.py`
- `tests/test_end_to_end_handler_unit.py` (Slackイベント→返信テキストまでのユニット結合)
- `pyproject.toml`
- `.env.example`
- `Dockerfile`
- `README.md` (実行手順/デプロイ手順の追記)

**Modify:**
- `README.md` (Docsリンクに plan 追加)

## Environment variables (names locked in)

- `SLACK_SIGNING_SECRET` (Slack)
- `SLACK_BOT_TOKEN` (Slack Web API for posting messages)
- `GCP_PROJECT_ID`
- `FIRESTORE_DATABASE` (default: `(default)`; allow override)
- `SESSION_TTL_HOURS` (default: `24`)
- `GEMINI_API_KEY`
- `GEMINI_MODEL` (default: `gemini-2.5-flash`)
- `APP_ENV` (default: `dev`)

---

### Task 1: Python project bootstrap + test runner

**Files:**
- Create: `pyproject.toml`
- Create: `app/main.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "slack-ai-chat-prototype"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.30.0",
  "httpx>=0.27.0",
  "pydantic>=2.8.0",
  "pydantic-settings>=2.4.0",
  "pytest>=8.3.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Add minimal FastAPI app**

```python
# app/main.py
from fastapi import FastAPI

app = FastAPI()


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}
```

- [ ] **Step 3: Add smoke test**

```python
# tests/test_smoke.py
from app.main import app
from fastapi.testclient import TestClient


def test_healthz() -> None:
    client = TestClient(app)
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/main.py tests/test_smoke.py
git commit -m "chore: bootstrap FastAPI app and pytest"
```

---

### Task 2: Settings + PII-safe logging baseline

**Files:**
- Create: `app/settings.py`
- Create: `app/logging_.py`
- Modify: `app/main.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Add settings model**

```python
# app/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "dev"

    slack_signing_secret: str
    slack_bot_token: str

    gcp_project_id: str
    firestore_database: str = "(default)"
    session_ttl_hours: int = 24

    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 2: Add safe logging helpers (never log raw user text)**

```python
# app/logging_.py
import hashlib


def text_fingerprint(text: str) -> str:
    # PII-safe: hash only, no plaintext storage
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 3: Wire settings into app**

```python
# app/main.py
from fastapi import FastAPI
from app.settings import get_settings

app = FastAPI()


@app.get("/healthz")
def healthz() -> dict:
    _ = get_settings()
    return {"ok": True}
```

- [ ] **Step 4: Add tests for settings import**

```python
# tests/test_settings.py
from app.settings import Settings


def test_settings_has_defaults() -> None:
    s = Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )
    assert s.firestore_database == "(default)"
    assert s.session_ttl_hours == 24
    assert s.gemini_model
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/settings.py app/logging_.py app/main.py tests/test_settings.py
git commit -m "chore: add settings and PII-safe logging helper"
```

---

### Task 3: Slack request verification (signature + replay defense)

**Files:**
- Create: `app/slack/verify.py`
- Test: `tests/test_slack_verify.py`

- [ ] **Step 1: Add verification implementation**

```python
# app/slack/verify.py
import hashlib
import hmac
import time


class SlackVerificationError(Exception):
    pass


def verify_slack_request(
    *,
    signing_secret: str,
    timestamp: str,
    signature: str,
    body: bytes,
    now_epoch: int | None = None,
    max_skew_seconds: int = 60 * 5,
) -> None:
    if now_epoch is None:
        now_epoch = int(time.time())

    try:
        ts_int = int(timestamp)
    except ValueError as e:
        raise SlackVerificationError("invalid timestamp") from e

    if abs(now_epoch - ts_int) > max_skew_seconds:
        raise SlackVerificationError("timestamp skew too large")

    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    expected = "v0=" + digest

    # constant-time compare
    if not hmac.compare_digest(expected, signature):
        raise SlackVerificationError("invalid signature")
```

- [ ] **Step 2: Add tests (happy + invalid signature + replay)**

```python
# tests/test_slack_verify.py
import hashlib
import hmac

import pytest

from app.slack.verify import SlackVerificationError, verify_slack_request


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return "v0=" + digest


def test_verify_ok() -> None:
    secret = "secret"
    ts = "1700000000"
    body = b'{"type":"url_verification"}'
    sig = _sign(secret, ts, body)
    verify_slack_request(
        signing_secret=secret,
        timestamp=ts,
        signature=sig,
        body=body,
        now_epoch=1700000001,
    )


def test_verify_rejects_invalid_signature() -> None:
    secret = "secret"
    ts = "1700000000"
    body = b'{"type":"url_verification"}'
    with pytest.raises(SlackVerificationError):
        verify_slack_request(
            signing_secret=secret,
            timestamp=ts,
            signature="v0=deadbeef",
            body=body,
            now_epoch=1700000001,
        )


def test_verify_rejects_replay_skew() -> None:
    secret = "secret"
    ts = "1700000000"
    body = b'{"type":"url_verification"}'
    sig = _sign(secret, ts, body)
    with pytest.raises(SlackVerificationError):
        verify_slack_request(
            signing_secret=secret,
            timestamp=ts,
            signature=sig,
            body=body,
            now_epoch=1700000000 + 60 * 10,
        )
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_slack_verify.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/slack/verify.py tests/test_slack_verify.py
git commit -m "feat: verify Slack requests with signature and replay defense"
```

---

### Task 4: Presidio cleansing (mask + mask_map + mask_summary)

**Files:**
- Create: `app/cleansing/presidio.py`
- Test: `tests/test_cleansing_presidio.py`

- [ ] **Step 1: Add dependencies**

Update `pyproject.toml` dependencies to include:

```toml
"presidio-analyzer>=2.2.0",
"presidio-anonymizer>=2.2.0",
```

- [ ] **Step 2: Implement masking (token format `<TYPE_N>`)**

```python
# app/cleansing/presidio.py
from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine


@dataclass(frozen=True)
class CleansingResult:
    sanitized_text: str
    mask_map: dict[str, str]
    mask_summary: dict[str, int]


def cleanse_text_presidio(text: str) -> CleansingResult:
    analyzer = AnalyzerEngine()
    results = analyzer.analyze(text=text, language="en")

    # Build replacements from back to front so indexes remain valid.
    # Use deterministic numbering per entity type in appearance order.
    counters: dict[str, int] = {}
    mask_map: dict[str, str] = {}
    mask_summary: dict[str, int] = {}

    # Presidio returns spans in original text coordinates
    sorted_results = sorted(results, key=lambda r: (r.start, r.end))

    # assign tokens
    token_assignments: list[tuple[int, int, str, str]] = []
    for r in sorted_results:
        entity = str(r.entity_type)
        counters[entity] = counters.get(entity, 0) + 1
        token = f"<{entity}_{counters[entity]}>"
        original = text[r.start : r.end]
        token_assignments.append((r.start, r.end, token, original))

        mask_map[token] = original
        mask_summary[entity] = mask_summary.get(entity, 0) + 1

    out = text
    for start, end, token, _original in reversed(token_assignments):
        out = out[:start] + token + out[end:]

    return CleansingResult(sanitized_text=out, mask_map=mask_map, mask_summary=mask_summary)
```

- [ ] **Step 3: Tests with representative inputs**

```python
# tests/test_cleansing_presidio.py
from app.cleansing.presidio import cleanse_text_presidio


def test_cleansing_masks_email_and_phone() -> None:
    text = "Email me at alice@example.com or call +1 415 555 2671."
    r = cleanse_text_presidio(text)

    assert "<EMAIL_ADDRESS_1>" in r.sanitized_text or "<EMAIL_1>" in r.sanitized_text
    # PHONE_NUMBER is the typical Presidio type name
    assert "<PHONE_NUMBER_1>" in r.sanitized_text
    assert any("@" in v for v in r.mask_map.values())
    assert any(any(c.isdigit() for c in v) for v in r.mask_map.values())
    assert r.mask_summary
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cleansing_presidio.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/cleansing/presidio.py tests/test_cleansing_presidio.py
git commit -m "feat: add Presidio-based masking with mask_map and mask_summary"
```

---

### Task 5: De-mask policy P0 (restore some types, keep others masked)

**Files:**
- Create: `app/cleansing/demask.py`
- Test: `tests/test_demask_policy_p0.py`

- [ ] **Step 1: Implement policy P0**

Policy P0:
- restore: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION`
- do not restore: `CREDIT_CARD`, `IBAN_CODE`, `CRYPTO`, and anything unknown

```python
# app/cleansing/demask.py
from __future__ import annotations


RESTORE_TYPES_P0: set[str] = {
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "LOCATION",
}


def demask_text_policy_p0(text: str, mask_map: dict[str, str]) -> str:
    out = text
    # Replace longer tokens first to avoid accidental partial overlaps.
    for token in sorted(mask_map.keys(), key=len, reverse=True):
        # Token format: <TYPE_N>
        if token.startswith("<") and token.endswith(">") and "_" in token:
            type_name = token[1 : token.rfind("_")]
            if type_name in RESTORE_TYPES_P0:
                out = out.replace(token, mask_map[token])
    return out
```

- [ ] **Step 2: Tests**

```python
# tests/test_demask_policy_p0.py
from app.cleansing.demask import demask_text_policy_p0


def test_demask_restores_person_but_not_credit_card() -> None:
    text = "Hello <PERSON_1>. Your card is <CREDIT_CARD_1>."
    mask_map = {"<PERSON_1>": "Alice", "<CREDIT_CARD_1>": "4111 1111 1111 1111"}
    out = demask_text_policy_p0(text, mask_map)
    assert "Alice" in out
    assert "<CREDIT_CARD_1>" in out
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_demask_policy_p0.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/cleansing/demask.py tests/test_demask_policy_p0.py
git commit -m "feat: add demask policy P0"
```

---

### Task 6: Session model + Firestore store (Tokyo) with TTL

**Files:**
- Create: `app/session/models.py`
- Create: `app/session/store_firestore.py`
- Test: `tests/test_session_models.py`

- [ ] **Step 1: Add dependency**

Update `pyproject.toml` dependencies:

```toml
"google-cloud-firestore>=2.16.0",
```

- [ ] **Step 2: Define session schema**

```python
# app/session/models.py
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
```

- [ ] **Step 3: Implement Firestore CRUD**

```python
# app/session/store_firestore.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from google.cloud import firestore

from app.session.models import SessionState


def _now() -> datetime:
    return datetime.now(UTC)


class FirestoreSessionStore:
    def __init__(self, *, project_id: str, database: str, ttl_hours: int) -> None:
        self._client = firestore.Client(project=project_id, database=database)
        self._ttl_hours = ttl_hours

    def get(self, session_id: str) -> SessionState | None:
        doc = self._client.collection("sessions").document(session_id).get()
        if not doc.exists:
            return None
        return SessionState.model_validate(doc.to_dict())

    def upsert(self, state: SessionState) -> None:
        self._client.collection("sessions").document(state.session_id).set(
            state.model_dump(mode="json"),
            merge=True,
        )

    def new_state(self, session_id: str) -> SessionState:
        now = _now()
        return SessionState(
            session_id=session_id,
            created_at=now,
            updated_at=now,
            ttl_at=now + timedelta(hours=self._ttl_hours),
        )
```

- [ ] **Step 4: Tests for model serialization (no Firestore network)**

```python
# tests/test_session_models.py
from datetime import UTC, datetime

from app.session.models import SessionState


def test_session_state_roundtrip() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    s = SessionState(
        session_id="C123:1700000000.0001",
        created_at=now,
        updated_at=now,
        ttl_at=now,
    )
    dumped = s.model_dump(mode="json")
    loaded = SessionState.model_validate(dumped)
    assert loaded.session_id == s.session_id
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_session_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/session/models.py app/session/store_firestore.py tests/test_session_models.py
git commit -m "feat: add Firestore session store model and TTL fields"
```

---

### Task 7: Gemini client + prompt assembly (sanitized only)

**Files:**
- Create: `app/llm/gemini.py`
- Create: `app/llm/prompt.py`
- Test: `tests/test_prompt_assembly.py`

- [ ] **Step 1: Add dependency**

Update `pyproject.toml` dependencies:

```toml
"google-genai>=0.5.0",
```

- [ ] **Step 2: Implement prompt assembly**

```python
# app/llm/prompt.py
from __future__ import annotations

from app.session.models import SessionMessage


def build_messages(history: list[SessionMessage], user_sanitized_text: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    messages.append(
        {
            "role": "system",
            "content": "You are a helpful assistant. Never ask for or reveal masked secrets. Respond concisely in Japanese.",
        }
    )
    for m in history:
        role = "user" if m.role == "user" else "assistant"
        messages.append({"role": role, "content": m.text})
    messages.append({"role": "user", "content": user_sanitized_text})
    return messages
```

- [ ] **Step 3: Implement Gemini call**

```python
# app/llm/gemini.py
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
```

- [ ] **Step 4: Tests for prompt shape**

```python
# tests/test_prompt_assembly.py
from datetime import UTC, datetime

from app.llm.prompt import build_messages
from app.session.models import SessionMessage


def test_build_messages_includes_history_and_user() -> None:
    history = [
        SessionMessage(role="user", text="hello <EMAIL_ADDRESS_1>", ts="1"),
        SessionMessage(role="assistant", text="ok", ts="2"),
    ]
    messages = build_messages(history, "next <PHONE_NUMBER_1>")
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert "next" in messages[-1]["content"]
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_prompt_assembly.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/llm/gemini.py app/llm/prompt.py tests/test_prompt_assembly.py pyproject.toml
git commit -m "feat: add Gemini client wrapper and prompt assembly"
```

---

### Task 8: Slack Events handler (DM parent vs thread reply) + session semantics

**Files:**
- Create: `app/slack/events.py`
- Modify: `app/main.py`
- Test: `tests/test_end_to_end_handler_unit.py`

- [ ] **Step 1: Implement Slack event normalization**

```python
# app/slack/events.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlackEvent:
    user_id: str
    channel_id: str
    text: str
    ts: str
    thread_ts: str | None

    @property
    def session_id(self) -> str:
        # session_id = "<channel_id>:<thread_ts>"
        base_ts = self.thread_ts or self.ts
        return f"{self.channel_id}:{base_ts}"


def parse_message_event(payload: dict) -> SlackEvent:
    ev = payload["event"]
    return SlackEvent(
        user_id=ev["user"],
        channel_id=ev["channel"],
        text=ev.get("text", ""),
        ts=ev["ts"],
        thread_ts=ev.get("thread_ts"),
    )
```

- [ ] **Step 2: Implement unit-level orchestrator (no Slack Web API yet)**

```python
# app/main.py (add below healthz)
from fastapi import Header, HTTPException, Request

from app.settings import get_settings
from app.slack.verify import SlackVerificationError, verify_slack_request
from app.slack.events import parse_message_event
from app.cleansing.presidio import cleanse_text_presidio
from app.cleansing.demask import demask_text_policy_p0


@app.post("/slack/events")
async def slack_events(
    request: Request,
    x_slack_request_timestamp: str = Header(alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str = Header(alias="X-Slack-Signature"),
) -> dict:
    settings = get_settings()
    body = await request.body()
    try:
        verify_slack_request(
            signing_secret=settings.slack_signing_secret,
            timestamp=x_slack_request_timestamp,
            signature=x_slack_signature,
            body=body,
        )
    except SlackVerificationError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    payload = await request.json()

    # URL verification handshake
    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}

    if payload.get("type") != "event_callback":
        return {"ok": True}

    if payload.get("event", {}).get("type") != "message":
        return {"ok": True}

    ev = parse_message_event(payload)
    cleansing = cleanse_text_presidio(ev.text)

    # Prototype: for now, echo back as if LLM said the sanitized text
    # (Gemini + Firestore wiring is in later tasks)
    llm_text = f"(sanitized) {cleansing.sanitized_text}"
    restored = demask_text_policy_p0(llm_text, cleansing.mask_map)

    summary_parts = [f"{k} x{v}" for k, v in sorted(cleansing.mask_summary.items())]
    summary = "Masked: " + (", ".join(summary_parts) if summary_parts else "NONE")

    return {
        "ok": True,
        "debug": {
            "session_id": ev.session_id,
            "mask_summary": cleansing.mask_summary,
            "mask_summary_text": summary,
            "reply_text": restored,
        },
    }
```

- [ ] **Step 3: Add unit-style test with fixed signature**

```python
# tests/test_end_to_end_handler_unit.py
import os
import json
import hashlib
import hmac

from fastapi.testclient import TestClient


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return "v0=" + digest


def test_slack_events_url_verification() -> None:
    os.environ["SLACK_SIGNING_SECRET"] = "x"
    os.environ["SLACK_BOT_TOKEN"] = "x"
    os.environ["GCP_PROJECT_ID"] = "x"
    os.environ["GEMINI_API_KEY"] = "x"

    from app.main import app  # import after env injection

    client = TestClient(app)
    body = json.dumps({"type": "url_verification", "challenge": "abc"}).encode("utf-8")
    ts = "1700000000"
    secret = "x"
    sig = _sign(secret, ts, body)

    res = client.post(
        "/slack/events",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
        },
    )
    assert res.status_code == 200
    assert res.json() == {"challenge": "abc"}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_end_to_end_handler_unit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/slack/events.py app/main.py tests/test_end_to_end_handler_unit.py
git commit -m "feat: add Slack events endpoint with verification and cleansing (prototype response)"
```

---

### Task 9: Refactor app wiring for testability (dependency injection) + make Task 8 test green

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_end_to_end_handler_unit.py`
- Test: `tests/test_end_to_end_handler_unit.py`

- [ ] **Step 1: Introduce FastAPI dependency for settings**

```python
# app/main.py (top-level)
from fastapi import Depends
from app.settings import Settings, get_settings

# In handler signature: settings: Settings = Depends(get_settings)
```

- [ ] **Step 2: Update handler to accept injected settings**

```python
# app/main.py (handler signature)
@app.post("/slack/events")
async def slack_events(
    request: Request,
    settings: Settings = Depends(get_settings),
    x_slack_request_timestamp: str = Header(alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str = Header(alias="X-Slack-Signature"),
) -> dict:
    ...
```

- [ ] **Step 3: In tests, override dependency**

```python
# tests/test_end_to_end_handler_unit.py
from app.settings import Settings, get_settings

def test_slack_events_url_verification() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )
    ...
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_end_to_end_handler_unit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_end_to_end_handler_unit.py
git commit -m "test: inject settings via FastAPI dependencies"
```

---

### Task 10: Slack Web API reply + thread semantics (real responses in Slack)

**Files:**
- Create: `app/slack/reply.py`
- Modify: `app/main.py`
- Test: `tests/test_reply_formatting.py`

- [ ] **Step 1: Add dependency**

Update `pyproject.toml`:

```toml
"slack-sdk>=3.33.0",
```

- [ ] **Step 2: Implement reply helper**

```python
# app/slack/reply.py
from __future__ import annotations

from slack_sdk import WebClient


def post_thread_reply(
    *,
    bot_token: str,
    channel_id: str,
    thread_ts: str,
    text: str,
) -> None:
    client = WebClient(token=bot_token)
    client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=text)
```

- [ ] **Step 3: Format first reply with mask summary**

```python
# app/slack/reply.py (add)
def format_first_reply(*, mask_summary: dict[str, int], answer_text: str) -> str:
    parts = [f"{k} x{v}" for k, v in sorted(mask_summary.items())]
    summary = "Masked: " + (", ".join(parts) if parts else "NONE")
    return f"{summary}\n\n{answer_text}"
```

- [ ] **Step 4: Add unit test**

```python
# tests/test_reply_formatting.py
from app.slack.reply import format_first_reply


def test_format_first_reply_includes_summary_and_answer() -> None:
    text = format_first_reply(mask_summary={"EMAIL_ADDRESS": 1}, answer_text="hello")
    assert "Masked:" in text
    assert "hello" in text
```

- [ ] **Step 5: Wire into `/slack/events`**

In `app/main.py`, after parsing event:
- Determine `thread_ts`:
  - If event has `thread_ts`: use it
  - Else (DM parent): use its own `ts` as `thread_ts` for replies
- Post reply into that thread with `post_thread_reply(...)`
- Return `{"ok": True}` quickly (Slack expects timely ack; heavy work should be bounded)

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_reply_formatting.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml app/slack/reply.py tests/test_reply_formatting.py app/main.py
git commit -m "feat: post Slack thread replies and format first reply summary"
```

---

### Task 11: Wire Firestore sessions + Gemini + demask end-to-end

**Files:**
- Modify: `app/main.py`
- Modify: `app/session/store_firestore.py`
- Modify: `app/llm/gemini.py`
- Create: `tests/test_orchestrator_unit.py`

- [ ] **Step 1: Implement orchestrator function (pure-ish for unit tests)**

Create `app/orchestrator.py`:

```python
from __future__ import annotations

from app.cleansing.presidio import cleanse_text_presidio
from app.cleansing.demask import demask_text_policy_p0
from app.llm.prompt import build_messages
from app.session.models import SessionMessage, SessionState


def handle_user_message(
    *,
    state: SessionState,
    user_text: str,
    user_ts: str,
    generate_reply_fn,
) -> tuple[SessionState, dict[str, int], str]:
    cleansing = cleanse_text_presidio(user_text)
    state.history.append(SessionMessage(role="user", text=cleansing.sanitized_text, ts=user_ts))
    messages = build_messages(state.history, cleansing.sanitized_text)
    assistant_sanitized = generate_reply_fn(messages)
    assistant_restored = demask_text_policy_p0(assistant_sanitized, cleansing.mask_map)
    state.history.append(SessionMessage(role="assistant", text=assistant_sanitized, ts=user_ts))
    state.mask_map.update(cleansing.mask_map)
    state.mask_summary = cleansing.mask_summary
    return state, cleansing.mask_summary, assistant_restored
```

- [ ] **Step 2: Unit test orchestrator with stubbed LLM**

```python
# tests/test_orchestrator_unit.py
from datetime import UTC, datetime

from app.orchestrator import handle_user_message
from app.session.models import SessionState


def test_orchestrator_restores_allowed_entities() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = SessionState(session_id="C:1", created_at=now, updated_at=now, ttl_at=now)

    def stub(messages):
        # echo back last user message
        return messages[-1]["content"]

    new_state, summary, reply = handle_user_message(
        state=state,
        user_text="Email alice@example.com",
        user_ts="1",
        generate_reply_fn=stub,
    )
    assert new_state.history
    assert summary
    assert "alice@example.com" in reply  # restored by policy P0
```

- [ ] **Step 3: Wire `/slack/events` to use Firestore store**

In `app/main.py`:
- create store with `FirestoreSessionStore(project_id=..., database=..., ttl_hours=...)`
- `state = store.get(session_id) or store.new_state(session_id)`
- call orchestrator with real Gemini `generate_reply(...)`
- `store.upsert(state)`
- reply to Slack

- [ ] **Step 4: Run tests**

Run: `python -m pytest`
Expected: PASS (unit tests)

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator_unit.py app/main.py
git commit -m "feat: wire Firestore session, Gemini, and demask end-to-end"
```

---

### Task 12: Dockerfile + Cloud Run deploy docs + .env.example

**Files:**
- Create: `Dockerfile`
- Create: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Add `.env.example`**

```dotenv
APP_ENV=dev
SLACK_SIGNING_SECRET=...
SLACK_BOT_TOKEN=xoxb-...
GCP_PROJECT_ID=...
FIRESTORE_DATABASE=(default)
SESSION_TTL_HOURS=24
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

- [ ] **Step 2: Add Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

COPY app /app/app

ENV PORT=8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 3: Update README with run + deploy commands**

Add sections:
- local run: `uvicorn app.main:app --reload --port 8080`
- tests: `python -m pytest`
- Cloud Run build/deploy (example):

```bash
gcloud run deploy slack-ai-chat-prototype \
  --source . \
  --region asia-northeast1 \
  --set-env-vars APP_ENV=prod,GCP_PROJECT_ID=... \
  --set-secrets SLACK_SIGNING_SECRET=slack_signing_secret:latest,SLACK_BOT_TOKEN=slack_bot_token:latest,GEMINI_API_KEY=gemini_api_key:latest
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .env.example README.md
git commit -m "docs: add env example, Dockerfile, and Cloud Run deployment guide"
```

---

## Self-Review Checklist (run now)

- [ ] **Spec coverage:** `docs/superpowers/specs/2026-04-14-slack-ai-chat-with-pii-cleansing-design.md` のゴール（Slack DM/スレッド=セッション、マスク可視化、復元P0、Firestore Tokyo TTL、外部送信はサニタイズのみ、署名検証/リプレイ対策）に対応する Task がある
- [ ] **Placeholder scan:** 「TBD/TODO/適切に〜」のような曖昧記述が無い
- [ ] **Type consistency:** token 形式 `<TYPE_N>`、`session_id="<channel_id>:<thread_ts>"`、`mask_map`/`mask_summary` の取り扱いが全タスクで一致している

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-04-14-slack-ai-chat-with-pii-cleansing-implementation-plan.md`.

Two execution options:
- **1. Subagent-Driven (recommended)**: タスクごとに実装→レビュー→次へ
- **2. Inline Execution**: このセッションで順に実装（チェックポイントあり）
