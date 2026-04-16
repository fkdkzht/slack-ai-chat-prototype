# Demo mode: Web search + mask output cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demo mode で「Gemini内蔵Webサーチ（grounding）」「Masked表示のノイズ除去」「Slack返信本文の全トークン復元」「filter出力の正規化」を実装する。

**Architecture:** LLM由来の不安定さは `app/orchestrator.handle_user_message()` の demo filter 分岐で吸収し、返信整形は `app/slack/reply.py` に閉じ込める。Webサーチは `app/llm/gemini.generate_reply()` にオプションで追加し、demo mode 時にだけ有効化する。

**Tech Stack:** FastAPI, google-genai (Gemini API), pytest

---

## File structure (changes)

- Modify: `app/slack/reply.py`  
  - `format_first_reply()` が `Masked: NONE` を出さない／x0 を列挙しない
- Modify: `app/cleansing/demask.py`  
  - `demask_text_policy_p0()` を「全トークン復元」ポリシーに変更（関数名は維持して差分最小）
- Modify: `app/orchestrator.py`  
  - demo filter の `summary/pii_items` を正規化・検証してから `mask_map/mask_summary` に落とす
- Modify: `app/llm/gemini.py`  
  - `allow_web_search: bool = False` を追加し、true の時は grounding(web search tool) を `config.tools` に付与
- Modify: `app/main.py`  
  - demo mode の `gen_fn()` から `generate_reply(..., allow_web_search=True)` を呼ぶ
- Tests:
  - Modify: `tests/test_reply_formatting.py`
  - Modify: `tests/test_demask_policy_p0.py`
  - Modify: `tests/test_orchestrator_unit.py`
  - Modify/Add: `tests/test_gemini_wrapper.py`（grounding config を渡す分岐のテスト）

---

### Task 1: Masked 表示のノイズ除去

**Files:**
- Modify: `app/slack/reply.py`
- Test: `tests/test_reply_formatting.py`

- [ ] **Step 1: Write the failing test**

`tests/test_reply_formatting.py` に次を追加（既存テストは残す）。

```python
from app.slack.reply import format_first_reply


def test_format_first_reply_omits_masked_line_when_no_items() -> None:
    text = format_first_reply(mask_summary={}, answer_text="hello")
    assert text == "hello"


def test_format_first_reply_omits_zero_counts() -> None:
    text = format_first_reply(mask_summary={"EMAIL_ADDRESS": 0, "PERSON": 2}, answer_text="hello")
    assert "Masked:" in text
    assert "EMAIL_ADDRESS" not in text
    assert "PERSON x2" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reply_formatting.py -v`  
Expected: FAIL（現状 `Masked: NONE` が先頭に付く／0も列挙される）

- [ ] **Step 3: Write minimal implementation**

`app/slack/reply.py` の `format_first_reply()` を次の方針で修正。

```python
def format_first_reply(*, mask_summary: dict[str, int], answer_text: str) -> str:
    items = [(k, v) for k, v in mask_summary.items() if isinstance(v, int) and v > 0]
    if not items:
        return answer_text
    parts = [f"{k} x{v}" for k, v in sorted(items)]
    summary = "Masked: " + ", ".join(parts)
    return f"{summary}\n\n{answer_text}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reply_formatting.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/slack/reply.py tests/test_reply_formatting.py
git commit -m "fix: omit empty/zero mask summary in Slack reply"
```

---

### Task 2: 復元ポリシーを「全トークン復元」に変更

**Files:**
- Modify: `app/cleansing/demask.py`
- Test: `tests/test_demask_policy_p0.py`

- [ ] **Step 1: Write the failing test**

`tests/test_demask_policy_p0.py` を次に置き換える（「全部復元」が要件のため）。

```python
from app.cleansing.demask import demask_text_policy_p0


def test_demask_restores_all_presidio_style_tokens() -> None:
    text = "Hello <PERSON_1>. Your card is <CREDIT_CARD_1>."
    mask_map = {"<PERSON_1>": "Alice", "<CREDIT_CARD_1>": "4111 1111 1111 1111"}
    out = demask_text_policy_p0(text, mask_map)
    assert "Alice" in out
    assert "4111 1111 1111 1111" in out


def test_demask_ignores_non_presidio_tokens() -> None:
    text = "token={{EMAIL}}"
    mask_map = {"{{EMAIL}}": "alice@example.com"}
    out = demask_text_policy_p0(text, mask_map)
    assert out == text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_demask_policy_p0.py -v`  
Expected: FAIL（現状は CREDIT_CARD が復元されない）

- [ ] **Step 3: Write minimal implementation**

`app/cleansing/demask.py` の実装を「型制限なし」に変更する。

```python
def _is_presidio_style_token(token: str) -> bool:
    if not (token.startswith("<") and token.endswith(">")):
        return False
    inner = token[1:-1]
    if "_" not in inner:
        return False
    type_part, num_part = inner.rsplit("_", 1)
    return bool(type_part) and num_part.isdigit()


def demask_text_policy_p0(text: str, mask_map: dict[str, str]) -> str:
    out = text
    for token in sorted(mask_map.keys(), key=len, reverse=True):
        if _is_presidio_style_token(token):
            out = out.replace(token, mask_map[token])
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_demask_policy_p0.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/cleansing/demask.py tests/test_demask_policy_p0.py
git commit -m "fix: restore all presidio-style tokens in replies"
```

---

### Task 3: Demo filter 出力の正規化（summaryの0抑制、pii_items検証、type揺れ吸収）

**Files:**
- Modify: `app/orchestrator.py`
- Test: `tests/test_orchestrator_unit.py`

- [ ] **Step 1: Write the failing test**

`tests/test_orchestrator_unit.py` に次を追加。

```python
from datetime import UTC, datetime

from app.orchestrator import handle_user_message
from app.session.models import SessionState


def test_filter_path_normalizes_summary_and_items_and_suppresses_zeros() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = SessionState(session_id="C:1", created_at=now, updated_at=now, ttl_at=now)

    def fake_filter(_raw: str):
        return {
            "sanitized_text": "Email <EMAIL_1> / badtok {{EMAIL}}",
            "pii_items": [
                {"type": "EMAIL", "value": "alice@example.com", "token": "<EMAIL_1>"},
                {"type": "EMAIL", "value": "alice@example.com", "token": "{{EMAIL}}"},
                {"type": "PHONE", "value": "", "token": "<PHONE_1>"},
            ],
            "summary": {"EMAIL": 1, "PHONE": 0, "URL": 0},
        }

    def fake_chat(_messages):
        return "ok <EMAIL_1>"

    _new_state, summary, reply = handle_user_message(
        state=state,
        user_text="my email is alice@example.com",
        user_ts="1",
        generate_reply_fn=fake_chat,
        ttl_hours=24,
        filter_fn=fake_filter,
    )
    # 0は落ちる / keyは正規化される
    assert summary == {"EMAIL_ADDRESS": 1}
    # tokenがpresidio形式のものだけ復元される
    assert "alice@example.com" in reply
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator_unit.py::test_filter_path_normalizes_summary_and_items_and_suppresses_zeros -v`  
Expected: FAIL（現状 summary が {"EMAIL":1,"PHONE":0...} のまま／pii_itemsのtype正規化なし）

- [ ] **Step 3: Write minimal implementation**

`app/orchestrator.py` の demo filter 分岐（`filter_fn` ありの方）に正規化を追加する。  
実装は同ファイル内にローカル関数として置き、責務が膨らむようなら後で `app/cleansing/` に切り出す。

追加するユーティリティ（例）:

```python
def _is_presidio_style_token(token: str) -> bool:
    if not (token.startswith("<") and token.endswith(">")):
        return False
    inner = token[1:-1]
    if "_" not in inner:
        return False
    type_part, num_part = inner.rsplit("_", 1)
    return bool(type_part) and num_part.isdigit()


def _token_type(token: str) -> str | None:
    if not _is_presidio_style_token(token):
        return None
    inner = token[1:-1]
    type_part, _num_part = inner.rsplit("_", 1)
    return type_part


_TYPE_MAP = {
    "EMAIL": "EMAIL_ADDRESS",
    "PHONE": "PHONE_NUMBER",
    "DATE_OF_BIRT": "DATE_OF_BIRTH",
}


def _normalize_type_name(type_name: str) -> str:
    return _TYPE_MAP.get(type_name, type_name)
```

`mask_map` 構築ロジックを次の方針に変更:

- `pii_items` は token を優先し、`token` から TYPE を再導出して正規化
- `value` が空は捨てる
- `mask_summary` は `summary` と `pii_items` の両方を元に作って良いが、最小は「summaryを正規化して `<=0` を落とす」でOK

最小実装案（pii_items由来でmask_mapとsummaryを作る）:

```python
mask_map = {}
mask_summary = {}
for item in pii_items:
    if not isinstance(item, dict):
        continue
    tok = str(item.get("token") or "")
    val = str(item.get("value") or "")
    t0 = _token_type(tok)
    if not t0 or not val:
        continue
    t = _normalize_type_name(t0)
    mask_map[tok] = val
    mask_summary[t] = mask_summary.get(t, 0) + 1
```

`summary` があればそれを使う場合は、必ず:

- key を `_normalize_type_name`
- value が int かつ `> 0` のみ採用

- [ ] **Step 4: Run test to verify it passes**

Run:
- `pytest tests/test_orchestrator_unit.py::test_filter_path_normalizes_summary_and_items_and_suppresses_zeros -v`
- `pytest tests/test_orchestrator_unit.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator_unit.py
git commit -m "fix: normalize demo filter outputs and drop noisy mask summary"
```

---

### Task 4: Gemini内蔵Webサーチ（grounding）を demo mode で有効化

**Files:**
- Modify: `app/llm/gemini.py`
- Modify: `app/main.py`
- Test: `tests/test_gemini_wrapper.py`

- [ ] **Step 1: Write the failing test**

`tests/test_gemini_wrapper.py` に、web search を許可した場合に `config.tools` が付与されることをテストする。  
（既存があるので追記でOK。`genai.Client` を monkeypatch して `generate_content` の引数を捕捉する）

例:

```python
import pytest

import app.llm.gemini as gem


def test_generate_reply_web_search_adds_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class _DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config=None):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
            class _Res:
                text = "ok"
            return _Res()

    class _DummyClient:
        def __init__(self, *, api_key: str):
            self.models = _DummyModels()

    monkeypatch.setattr(gem.genai, "Client", _DummyClient)

    out = gem.generate_reply(api_key="k", model="m", messages=[{"role": "user", "content": "hi"}], allow_web_search=True)
    assert out == "ok"
    assert captured["config"] is not None
    # config.tools が入っていること（型はSDK依存なので「存在」だけを見る）
    assert getattr(captured["config"], "tools", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gemini_wrapper.py::test_generate_reply_web_search_adds_tools -v`  
Expected: FAIL（現状 `allow_web_search` 引数も `config` もない）

- [ ] **Step 3: Write minimal implementation**

`app/llm/gemini.py` を次の方針で更新:

- `allow_web_search: bool = False` を追加
- true の場合だけ `google.genai.types` を使って grounding tool を追加

実装例（SDKドキュメント準拠）:

```python
from google import genai


def generate_reply(*, api_key: str, model: str, messages: list[dict[str, str]], allow_web_search: bool = False) -> str:
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
```

次に `app/main.py` の demo mode の `gen_fn()` を `allow_web_search=True` で呼ぶ:

```python
return generate_reply(api_key=settings.gemini_api_key, model=chat_model, messages=messages, allow_web_search=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
- `pytest tests/test_gemini_wrapper.py::test_generate_reply_web_search_adds_tools -v`
- `pytest tests/test_gemini_wrapper.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/llm/gemini.py app/main.py tests/test_gemini_wrapper.py
git commit -m "feat: enable Gemini grounding web search in demo mode"
```

---

### Task 5: Full regression run

**Files:**
- (No code changes; verification only)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest`  
Expected: PASS

- [ ] **Step 2: Smoke check locally (optional)**

Run: `uvicorn app.main:app --reload --port 8080`  
Expected:
- `GET /health` returns `{"ok": true}`
- demo mode で Slack の返しが:
  - PII無し → Masked行無し
  - PII有り → Masked行あり、本文は全トークン復元

---

## Self-review

- **Spec coverage:** `docs/superpowers/specs/2026-04-16-demo-mode-search-and-mask-output-design.md` の Goal 4点にそれぞれ Task 1-4 が対応していることを確認済み。
- **Placeholder scan:** “TBD/TODO/edge cases” などの曖昧表現は無し。コード断片・コマンド・期待結果は明示。
- **Type consistency:** `allow_web_search` の命名を `generate_reply()` → `app/main.py` まで統一。

