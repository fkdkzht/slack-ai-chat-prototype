# Demo (Cloud Run): Gemini Filter + Chat LLM Separation + Sheets Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 今日のデモ向けに、(1) フィルター（クレンジング）を Gemini に差し替え、(2) チャットLLMには必ずマスク後のみを投げ、(3) マスク結果を Apps Script Webhook 経由で Spreadsheet に書き出す。

**Architecture:** Slackイベント受信（即 ack）→ DEMO_MODE の場合は「フィルターGemini(raw→sanitized+PII)」→ Sheets Webhook へ `pii_dictionary` / `message_log` 追記 → 「チャットGemini(sanitized history + sanitized text)」→ Slack返信。raw全文は永続化・ログ出力しない。

**Tech Stack:** Python (FastAPI), google-genai, Firestore (既存セッション状態), Slack SDK, httpx（Apps Script Webhook POST）, Cloud Run（デモは `--no-cpu-throttling` 推奨）。

---

## Scope / 前提

- 対象 spec: `docs/superpowers/specs/2026-04-15-demo-gemini-filter-and-sheets-design.md`
- デモでは **フィルターGeminiに raw を送るのは許容**
- **raw全文は保存しない**（Firestore/Sheets/ログすべて）
- Sheets には生値が入る（`pii_dictionary`）。デモの共有範囲は最小化
- 既存の Slack 即 ack / dedupe / bot traffic filter は維持

---

## Repository / File Structure (this plan locks it in)

**Create:**
- `app/cleansing/gemini_filter.py` (raw → sanitized_text + pii_items + summary)
- `app/exports/sheets_webhook.py` (Apps Script Webhook client)
- `app/exports/models.py` (export payload models)
- `tests/test_gemini_filter_parse.py`
- `tests/test_sheets_webhook_client.py`

**Modify:**
- `app/settings.py` (DEMO_MODE + models + webhook URL)
- `app/orchestrator.py` (filter/chat separation + optional export hook)
- `app/main.py` (wire demo mode + models + webhook)
- `pyproject.toml` (httpx dependency already present; verify)
- `README.md` or runbook (デモ手順: `--no-cpu-throttling` 追記)

---

## Environment variables (names locked in)

- `DEMO_MODE` (default: `"false"`)
- `GEMINI_FILTER_MODEL` (default: `gemini-2.5-flash`)
- `GEMINI_CHAT_MODEL` (default: `gemini-2.5-flash`)
- `SHEETS_WEBHOOK_URL` (required when `DEMO_MODE=true`)

Existing:
- `GEMINI_API_KEY`, `SLACK_*`, `FIRESTORE_*`, `APP_ENV`

---

### Task 1: Add demo settings fields

**Files:**
- Modify: `app/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write failing test for new settings defaults**

Add to `tests/test_settings.py`:

```python
from app.settings import Settings


def test_demo_settings_defaults() -> None:
    s = Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )
    assert s.demo_mode is False
    assert s.gemini_filter_model
    assert s.gemini_chat_model
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings.py -q`  
Expected: FAIL (`demo_mode` / new fields missing)

- [ ] **Step 3: Implement settings fields**

Update `app/settings.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "dev"

    slack_signing_secret: str
    slack_bot_token: str

    gcp_project_id: str
    firestore_database: str = "default"
    session_ttl_hours: int = 24

    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"

    # Demo-only switches
    demo_mode: bool = False
    gemini_filter_model: str = "gemini-2.5-flash"
    gemini_chat_model: str = "gemini-2.5-flash"
    sheets_webhook_url: str | None = None


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_settings.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/settings.py tests/test_settings.py
git commit -m "feat: add demo mode settings for filter/chat/sheets"
```

---

### Task 2: Implement Gemini filter wrapper (raw -> JSON)

**Files:**
- Create: `app/cleansing/gemini_filter.py`
- Test: `tests/test_gemini_filter_parse.py`

- [ ] **Step 1: Write failing tests for JSON parsing + minimal validation**

Create `tests/test_gemini_filter_parse.py`:

```python
import json

import pytest

from app.cleansing.gemini_filter import FilterResult, parse_filter_json


def test_parse_filter_json_ok() -> None:
    raw = {
        "sanitized_text": "Hello <EMAIL_1>",
        "pii_items": [{"type": "EMAIL", "value": "alice@example.com", "token": "<EMAIL_1>"}],
        "summary": {"EMAIL": 1},
    }
    r = parse_filter_json(json.dumps(raw))
    assert isinstance(r, FilterResult)
    assert "<EMAIL_1>" in r.sanitized_text
    assert r.summary["EMAIL"] == 1
    assert r.pii_items[0].value == "alice@example.com"


def test_parse_filter_json_rejects_missing_sanitized_text() -> None:
    with pytest.raises(ValueError):
        parse_filter_json('{"pii_items": [], "summary": {}}')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gemini_filter_parse.py -q`  
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `app/cleansing/gemini_filter.py`**

Create `app/cleansing/gemini_filter.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass

from google import genai


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
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError("filter returned non-json") from e

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

    # cast summary values to int where possible
    summary_int: dict[str, int] = {}
    for k, v in summary.items():
        if isinstance(k, str) and isinstance(v, int):
            summary_int[k] = v

    return FilterResult(sanitized_text=sanitized_text, pii_items=pii_items, summary=summary_int)


def run_gemini_filter(*, api_key: str, model: str, raw_text: str) -> FilterResult:
    client = genai.Client(api_key=api_key)
    prompt = (
        "You are a PII redaction filter.\n"
        "Return ONLY valid JSON with keys: sanitized_text (string), pii_items (array), summary (object).\n"
        "Replace PII with tokens like <EMAIL_1>, <PHONE_1>, <PERSON_1>.\n"
        "pii_items entries: {type, value, token}. summary: {TYPE: count}.\n"
        "Do not include any extra commentary.\n"
        "Input:\n"
        f"{raw_text}"
    )
    res = client.models.generate_content(model=model, contents=[prompt])
    out = getattr(res, "text", None)
    if not out:
        raise RuntimeError("Gemini filter returned empty text")
    return parse_filter_json(out)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_gemini_filter_parse.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/cleansing/gemini_filter.py tests/test_gemini_filter_parse.py
git commit -m "feat: add Gemini-based demo filter returning sanitized JSON"
```

---

### Task 3: Implement Sheets webhook client + payload models

**Files:**
- Create: `app/exports/models.py`
- Create: `app/exports/sheets_webhook.py`
- Test: `tests/test_sheets_webhook_client.py`

- [ ] **Step 1: Write failing test for webhook client request shape**

Create `tests/test_sheets_webhook_client.py`:

```python
import json

import httpx
import pytest

from app.exports.sheets_webhook import post_to_sheets_webhook


class DummyTransport(httpx.BaseTransport):
    def __init__(self):
        self.requests = []

    def handle_request(self, request):  # type: ignore[override]
        self.requests.append(request)
        return httpx.Response(200, text="ok")


def test_post_to_sheets_webhook_posts_json() -> None:
    t = DummyTransport()
    client = httpx.Client(transport=t)
    post_to_sheets_webhook(
        client=client,
        webhook_url="https://example.com/webhook",
        payload={"hello": "world"},
    )
    assert len(t.requests) == 1
    req = t.requests[0]
    assert req.method == "POST"
    assert req.url.host == "example.com"
    body = json.loads(req.content.decode("utf-8"))
    assert body["hello"] == "world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sheets_webhook_client.py -q`  
Expected: FAIL (module missing)

- [ ] **Step 3: Add export models**

Create `app/exports/models.py`:

```python
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
```

- [ ] **Step 4: Implement webhook client**

Create `app/exports/sheets_webhook.py`:

```python
from __future__ import annotations

from typing import Any

import httpx


def post_to_sheets_webhook(*, client: httpx.Client, webhook_url: str, payload: dict[str, Any]) -> None:
    res = client.post(webhook_url, json=payload, timeout=10.0)
    res.raise_for_status()
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_sheets_webhook_client.py -q`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/exports/models.py app/exports/sheets_webhook.py tests/test_sheets_webhook_client.py
git commit -m "feat: add Sheets webhook exporter client"
```

---

### Task 4: Refactor orchestrator for filter/chat separation + optional Sheets export

**Files:**
- Modify: `app/orchestrator.py`
- Test: `tests/test_orchestrator_unit.py`

- [ ] **Step 1: Write failing test for demo pipeline hook**

Add to `tests/test_orchestrator_unit.py`:

```python
from datetime import UTC, datetime
import json

from app.orchestrator import handle_user_message
from app.session.models import SessionState


def test_orchestrator_accepts_custom_filter_and_export_hook() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = SessionState(session_id="C:1", created_at=now, updated_at=now, ttl_at=now)

    def fake_filter(raw_text: str):
        return {
            "sanitized_text": "Hello <EMAIL_1>",
            "pii_items": [{"type": "EMAIL", "value": "alice@example.com", "token": "<EMAIL_1>"}],
            "summary": {"EMAIL": 1},
        }

    exported = {}

    def export_hook(payload: dict):
        exported.update(payload)

    def fake_chat(messages):
        # ensure chat only sees sanitized content
        assert any("<EMAIL_1>" in m["content"] for m in messages)
        assert not any("alice@example.com" in m["content"] for m in messages)
        return "ok"

    new_state, summary, reply = handle_user_message(
        state=state,
        user_text="my email is alice@example.com",
        user_ts="1",
        generate_reply_fn=fake_chat,
        ttl_hours=24,
        filter_fn=fake_filter,
        export_hook=export_hook,
    )
    assert reply
    assert summary["EMAIL"] == 1
    assert "sanitized_text" in exported
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator_unit.py -q`  
Expected: FAIL (`handle_user_message` signature mismatch)

- [ ] **Step 3: Implement orchestrator changes**

Update `app/orchestrator.py` to:
- accept `filter_fn` and `export_hook` (both optional)
- when `filter_fn` is provided:
  - use it to produce `sanitized_text`, `pii_items`, `summary`
  - do not persist raw text
  - call `export_hook` with only sanitized + pii items + summary (no raw)
- otherwise keep current Presidio path
- keep history as sanitized only

Concrete code (replace function body accordingly):

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Callable, Any
import json

from app.cleansing.demask import demask_text_policy_p0
from app.cleansing.presidio import cleanse_text_presidio
from app.llm.prompt import build_messages
from app.session.models import SessionMessage, SessionState


def handle_user_message(
    *,
    state: SessionState,
    user_text: str,
    user_ts: str,
    generate_reply_fn,
    ttl_hours: int,
    filter_fn: Callable[[str], dict[str, Any]] | None = None,
    export_hook: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[SessionState, dict[str, int], str]:
    if filter_fn is None:
        cleansing = cleanse_text_presidio(user_text)
        sanitized_text = cleansing.sanitized_text
        mask_map = cleansing.mask_map
        mask_summary = cleansing.mask_summary
        pii_items: list[dict[str, str]] = []
    else:
        out = filter_fn(user_text)
        sanitized_text = str(out.get("sanitized_text") or "")
        pii_items = list(out.get("pii_items") or [])
        mask_summary = dict(out.get("summary") or {})
        # Demo mode: we do not demask via token->value; keep reply as-is
        mask_map = {}

        if export_hook is not None:
            export_hook(
                {
                    "ts": user_ts,
                    "sanitized_text": sanitized_text,
                    "pii_items": pii_items,
                    "summary": mask_summary,
                    "pii_summary_json": json.dumps(mask_summary, ensure_ascii=False),
                }
            )

    messages = build_messages(state.history, sanitized_text)
    assistant_sanitized = generate_reply_fn(messages)
    combined_mask = {**state.mask_map, **mask_map}
    assistant_restored = demask_text_policy_p0(assistant_sanitized, combined_mask)

    state.history.append(SessionMessage(role="user", text=sanitized_text, ts=user_ts))
    state.history.append(SessionMessage(role="assistant", text=assistant_sanitized, ts=user_ts))
    state.mask_map.update(mask_map)
    state.mask_summary = mask_summary
    now = datetime.now(UTC)
    state.updated_at = now
    state.ttl_at = now + timedelta(hours=ttl_hours)
    return state, mask_summary, assistant_restored
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_orchestrator_unit.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator_unit.py
git commit -m "refactor: split filter vs chat and add optional export hook"
```

---

### Task 5: Wire demo mode into Slack processing (main)

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_slack_events_event_callback.py`

- [ ] **Step 1: Add failing test for demo mode path (unit)**

In `tests/test_slack_events_event_callback.py`, add a test that:
- sets `Settings(demo_mode=True, sheets_webhook_url="https://example.com")`
- monkeypatches filter function to return sanitized JSON
- monkeypatches `httpx.Client.post` to capture payload
- ensures `generate_reply` gets sanitized text (not raw)

Test skeleton (minimal, keep with existing patterns):

```python
import httpx


def test_event_callback_demo_mode_exports_to_sheets_and_uses_sanitized(monkeypatch) -> None:
    import app.main as main_mod

    posted_payloads = []

    class DummyClient:
        def post(self, url, json=None, timeout=None):
            posted_payloads.append({"url": url, "json": json})
            return httpx.Response(200, text="ok")

    monkeypatch.setattr(main_mod.httpx, "Client", lambda **kwargs: DummyClient())

    def fake_filter(*, api_key: str, model: str, raw_text: str):
        from app.cleansing.gemini_filter import FilterResult, PiiItem
        return FilterResult(
            sanitized_text="hi <EMAIL_1>",
            pii_items=[PiiItem(type="EMAIL", value="alice@example.com", token="<EMAIL_1>")],
            summary={"EMAIL": 1},
        )

    monkeypatch.setattr(main_mod, "run_gemini_filter", fake_filter)

    seen = {"contents": None}

    def fake_generate_reply(*, api_key: str, model: str, messages: list[dict[str, str]]) -> str:
        seen["contents"] = [m["content"] for m in messages]
        return "ok"

    main_mod.generate_reply = fake_generate_reply
    # ... then call main_mod._process_slack_message_event with demo settings and a payload containing raw email ...
    assert posted_payloads
    assert any("<EMAIL_1>" in c for c in (seen["contents"] or []))
    assert not any("alice@example.com" in c for c in (seen["contents"] or []))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_slack_events_event_callback.py -q`  
Expected: FAIL (demo mode not wired / missing imports)

- [ ] **Step 3: Implement wiring in `app/main.py`**

Changes:
- import `httpx`
- import `run_gemini_filter`, `FilterResult`
- in `_process_slack_message_event`:
  - if `settings.demo_mode`:
    - run filter: `run_gemini_filter(api_key=settings.gemini_api_key, model=settings.gemini_filter_model, raw_text=ev.text)`
    - define `export_hook` that posts to `settings.sheets_webhook_url` (required) with:
      - one payload containing `message_log` row data and `pii_dictionary` rows (both)
    - chat LLM call uses `settings.gemini_chat_model`
    - call orchestrator with `filter_fn` that returns dict in orchestrator expected format, and export hook
  - else: current Presidio path stays

Export payload shape (single POST):

```json
{
  "message_log": {"ts":"...", "event_id":"...", "sanitized_text":"...", "pii_summary_json":"..."},
  "pii_dictionary": [{"ts":"...", "event_id":"...", "pii_type":"EMAIL", "token":"<EMAIL_1>", "value":"alice@example.com"}]
}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_slack_events_event_callback.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_slack_events_event_callback.py
git commit -m "feat: demo mode Gemini filter + Sheets export + chat model separation"
```

---

### Task 6: Apps Script Web App (manual step, but scripted content)

**Files:**
- (No repo files required for deployment, but include snippet in runbook/README)

- [ ] **Step 1: Create Apps Script project**

In Google Drive → Apps Script:
- Create new project: `slack-ai-chat-demo-sheets-webhook`
- Add `Code.gs`:

```javascript
const PROP_KEY = "SPREADSHEET_ID";

function _getOrCreateSpreadsheetId_() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty(PROP_KEY);
  if (id) return id;

  const ss = SpreadsheetApp.create("slack-ai-chat demo export");
  const dict = ss.getActiveSheet();
  dict.setName("pii_dictionary");
  dict.appendRow(["ts", "event_id", "pii_type", "token", "value"]);

  const log = ss.insertSheet("message_log");
  log.appendRow(["ts", "event_id", "sanitized_text", "pii_summary_json"]);

  props.setProperty(PROP_KEY, ss.getId());
  return ss.getId();
}

function doPost(e) {
  const ssId = _getOrCreateSpreadsheetId_();
  const ss = SpreadsheetApp.openById(ssId);

  const payload = JSON.parse(e.postData.contents || "{}");
  const messageLog = payload.message_log;
  const piiDict = payload.pii_dictionary || [];

  if (messageLog) {
    const sheet = ss.getSheetByName("message_log");
    sheet.appendRow([
      messageLog.ts || "",
      messageLog.event_id || "",
      messageLog.sanitized_text || "",
      messageLog.pii_summary_json || "",
    ]);
  }

  if (Array.isArray(piiDict) && piiDict.length) {
    const sheet = ss.getSheetByName("pii_dictionary");
    piiDict.forEach((r) => {
      sheet.appendRow([r.ts || "", r.event_id || "", r.pii_type || "", r.token || "", r.value || ""]);
    });
  }

  return ContentService.createTextOutput("ok").setMimeType(ContentService.MimeType.TEXT);
}
```

- [ ] **Step 2: Deploy as Web App**

Deploy → New deployment:
- Type: Web app
- Execute as: Me
- Who has access: Anyone (for demo) **or** Anyone within domain (if available)

Copy the Web App URL and set it to `SHEETS_WEBHOOK_URL`.

- [ ] **Step 3: Verify it works (manual curl)**

Run locally:

```bash
curl -sS -X POST "$SHEETS_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{"message_log":{"ts":"1","event_id":"E1","sanitized_text":"hi <EMAIL_1>","pii_summary_json":"{\"EMAIL\":1}"},"pii_dictionary":[{"ts":"1","event_id":"E1","pii_type":"EMAIL","token":"<EMAIL_1>","value":"alice@example.com"}]}'
```

Expected: `ok` and the spreadsheet gets created with 2 sheets and 2 rows.

---

### Task 7: Docs + Cloud Run deploy flags for demo stability

**Files:**
- Modify: `docs/superpowers/runbooks/2026-04-14-personal-deploy-and-demo.md` (or `README.md`)

- [ ] **Step 1: Add `--no-cpu-throttling` note for demo**

Add a short paragraph + sample deploy flag:

```bash
gcloud run deploy slack-ai-chat-prototype \
  ... \
  --no-cpu-throttling
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/runbooks/2026-04-14-personal-deploy-and-demo.md README.md
git commit -m "docs: note Cloud Run no-cpu-throttling for demo"
```

---

## Self-Review Checklist (run now)

- [ ] **Spec coverage:** spec のゴール（Geminiフィルター、チャットLLM分離、Sheets2シート、raw保存しない、Cloud Runデモ安定化）に対応する Task がある
- [ ] **Placeholder scan:** “TBD/TODO/適切に〜” の曖昧記述が無い（手動作業はコードを全提示）
- [ ] **Type consistency:** `SHEETS_WEBHOOK_URL` payload keys と Apps Script の参照名が一致している

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-04-15-demo-gemini-filter-sheets-implementation-plan.md`.

Two execution options:
- **1. Subagent-Driven (recommended)**: タスクごとに実装→レビュー→次へ
- **2. Inline Execution**: このセッションで順に実装（チェックポイントあり）

Which approach?

