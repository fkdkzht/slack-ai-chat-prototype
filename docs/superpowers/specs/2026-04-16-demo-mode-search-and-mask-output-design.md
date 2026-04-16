# Demo mode: Web search + mask output cleanup (Design)

## Goal

Slack AI Chat Prototype（demo mode）において、次を実現する。

- Gemini が必要に応じて Web サーチできるようにする（まずは Gemini の内蔵検索/grounding を利用する）
- Slack 返信の「Masked: ...」表示をノイズなくする（0件なら表示しない、x0 列挙を出さない）
- Slack 返信本文は **マスク情報をすべて復元**して返す
- Gemini filter 由来の「変なマスク情報」（型名揺れ、0件列挙、トークン不正）を吸収して安定化する

## Non-goals

- 検索ソースを外部API（Bing/Serp 等）に切り替える実装はこの段階では行わない（不足が見えたら次段で追加）
- demo mode 以外（Presidio 経路）の挙動変更は最小に留める（必要があれば別Specにする）

## Current behavior (observed)

- `app/slack/reply.format_first_reply()` は `mask_summary` が空でも `Masked: NONE` を必ず出す
- demo mode の Gemini filter は `summary` を「全カテゴリ x0」や型名揺れ（例: EMAIL/PHONE/DATE_OF_BIRT）で返すことがあり、Slack 返信が煩雑になる
- 復元は `app/cleansing/demask.demask_text_policy_p0()` の許可タイプに限定され、demo mode 由来の型名揺れだと復元されないケースがある

## Design

### 1) Web search: Gemini internal search / grounding (first)

#### Approach

- `app/llm/gemini.generate_reply()` に「検索を許可する」オプションを追加し、demo mode のときだけ有効化する。
- 仕組みは **Gemini API の grounding / web search tool** を利用する（SDK `google-genai` の対応機能を使う）。
- 返答に引用（URL）が付く場合は、それを Slack 返信にそのまま含めて良い（まずは整形しない）。引用が無い場合も正常。

#### Safety / control

- デフォルトは **off**。demo mode の時だけ on にする（設定で将来 off に戻せるようにする）。
- タイムアウトや最大トークン等の制御は既存の Gemini 呼び出し設定に合わせて行う。

#### Fallback plan (future)

- 内蔵検索の挙動/再現性/可観測性が不足する場合に限り、アプリ側検索（外部検索API）を別Specで追加する。

### 2) Mask summary output: suppress NONE and x0

#### Behavior

- Slack 返信冒頭の `Masked:` 行は、**count > 0 の項目が1つでもある時だけ表示**する。
- `mask_summary` に 0 が含まれていても表示しない（例の `ADDRESS x0, ...` の列挙を出さない）。
- 出力順は安定させる（現状と同じくキーのソートでOK）。

#### Example

- `{"EMAIL_ADDRESS": 1, "PERSON": 2}` → `Masked: EMAIL_ADDRESS x1, PERSON x2`
- `{}` or `{"EMAIL_ADDRESS": 0, "URL": 0}` → （Masked行なし）→ そのまま回答本文だけ

### 3) Demask policy: restore all tokens

#### Behavior

- `mask_map` に含まれるトークンは、**種別に関係なくすべて復元**する。
- ただし、誤爆を抑えるために、復元対象トークンは「Presidio-style token」だけに限定する。
  - 例: `<EMAIL_ADDRESS_1>` のように `<` と `>` で囲まれ、末尾に `_<number>` がある形式

### 4) Stabilize demo-mode filter outputs (normalize + validate)

#### Motivation

demo mode の Gemini filter は LLM 出力なので、次の揺れがあり得る。

- `summary` が「全カテゴリ x0」形式で返ってくる
- `type` 名が Presidio の型名に揃わない（EMAIL vs EMAIL_ADDRESS 等）
- `pii_items` の token/type/value が欠けていたり、トークン形式が崩れる

#### Proposed normalization

- `summary`:
  - 値が int でないものは捨てる（既に parse は実施）
  - `**<= 0` は捨てる**
  - キーは正規化（下記）
- `pii_items`:
  - `{type, value, token}` が全て文字列で、`token` が Presidio-style token の形式を満たすものだけ採用
  - `type` は token の中身（`<TYPE_N>` の TYPE）から再導出して一致させる（LLMが `type` を間違えても token を優先）
  - value が空の場合は捨てる
- Type name mapping（最低限）:
  - `EMAIL` → `EMAIL_ADDRESS`
  - `PHONE` → `PHONE_NUMBER`
  - `DATE_OF_BIRT` → `DATE_OF_BIRTH`
  - （必要に応じて追加。未知は token から取った TYPE をそのまま使う）

#### Where to apply

- `app/orchestrator.handle_user_message()` の demo mode 分岐（`filter_fn` の結果を `mask_map/mask_summary` に変換するところ）で正規化する。
  - ここを「LLM由来の不安定さを吸収する境界」とする。

## Affected files (expected)

- Modify: `app/llm/gemini.py`（grounding/web search tool の有効化オプション）
- Modify: `app/orchestrator.py`（demo mode filter outputs の正規化、summaryの0抑制、pii_items検証）
- Modify: `app/cleansing/demask.py`（復元ポリシーを all に変更）
- Modify: `app/slack/reply.py`（Masked: NONE を消し、x0を出さない）
- Update tests:
  - `tests/test_reply_formatting.py`
  - `tests/test_demask_policy_p0.py`（名称含め見直し）
  - `tests/test_orchestrator_unit.py`（demo mode filter の正規化が効くこと）

## Test plan

- `python -m pytest`
- demo mode で、以下の Slack 返信を目視確認:
  - PIIが無い文 → Masked行なし、回答のみ
  - PIIがある文 → Masked行あり、回答はすべて復元されている
  - Gemini filter が x0 列挙/型名揺れ/不正token を返しても、表示が崩れず復元が破綻しない