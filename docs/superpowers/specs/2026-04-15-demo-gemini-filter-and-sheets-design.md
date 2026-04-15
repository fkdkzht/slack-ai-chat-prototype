## デモ: Geminiフィルター + チャットLLM分離 + Spreadsheet可視化 設計（Design Spec）

- **作成日**: 2026-04-15
- **目的**: 「外部LLMへはマスク後のみ送る」ことをデモで分かりやすく示しつつ、**本番は常駐ワーカー（GCE/GKE等）**へ移行しやすい形で境界を切る。

---

## 1. ゴール / 非ゴール

### ゴール（今日のデモで必ず満たす）

- **フィルター（クレンジング）**は Presidio ではなく **Gemini** を使う
  - 入力は **raw（マスク前）**を送る（デモ許容）
  - 出力は **サニタイズ済みテキスト** + **検出PIIのリスト** + **サマリ**
- **チャットLLM**はフィルターとは別として扱い、必ず **サニタイズ済みテキストのみ**を送る
  - デモではチャットLLMも **Gemini** を利用（モデルは分けられる）
- **ログ可視化**として Google Spreadsheet に以下を書き出す
  - **PII辞書（生値あり）**と、**メッセージログ（サニタイズ済みのみ）**を別シートに分ける
  - **raw全文は保存しない**

### 非ゴール（デモではやらない）

- Presidio を使ったローカル検出の最適化（本番で対応）
- 会社導入を見据えた監査・権限・DLP厳密対応
- 完全な重複排除・高信頼な非同期基盤（本番で対応）

---

## 2. 環境方針（デモ vs 本番）

### 2.1 デモ（Cloud Run / アプローチB）

- Slack の 3 秒制約のため **即 ack** し、後続処理をバックグラウンドで進める
- Cloud Run は **CPU 常時割り当て（推奨: `--no-cpu-throttling`）**でデモ安定性を上げる

### 2.2 本番（常駐ワーカー / アプローチC）

- Slack受信は軽量な入口（HTTP）として維持しつつ、重い処理（フィルター/チャット/その他常駐処理）は **常駐ワーカー**に寄せる
- 常駐の利点（初期化の保持、同一プロセス内キャッシュ、バッチ/定期処理）が必要な前提のため、GCE/GKE 等を第一候補とする

---

## 3. 全体データフロー（デモ）

1. Slack Events API でメッセージイベント受信
2. 署名検証・簡易フィルタ（bot/subtype）・イベント重複排除
3. **フィルターGemini**に raw テキストを送る
4. 返ってきた **sanitized_text / pii_items / pii_summary** を Spreadsheet に書き出す（Apps Script Webhook）
5. **チャットLLM**に sanitized_text と sanitized 履歴のみを投げて応答を生成する
6. Slack に返信（初回はサマリも添える）

重要:

- **チャットLLMに raw は投げない**
- **Spreadsheet に raw 全文は書かない**

---

## 4. フィルターGemini（クレンジング）仕様

### 4.1 入出力

- 入力: raw user text（デモ許容）
- 出力: JSON（Gemini の自由文ではなく、JSON だけ返すようにプロンプト制約）

### 4.2 JSON スキーマ（案）

```json
{
  "sanitized_text": "Hello <EMAIL_1>, call me at <PHONE_1>.",
  "pii_items": [
    {"type": "EMAIL", "value": "alice@example.com", "token": "<EMAIL_1>"},
    {"type": "PHONE", "value": "+81-90-1234-5678", "token": "<PHONE_1>"}
  ],
  "summary": {
    "EMAIL": 1,
    "PHONE": 1
  }
}
```

### 4.3 ルール（デモ用）

- `sanitized_text` は必ず元文と同じ言語で、意味が通るように置換する
- `token` は種別+連番（`<EMAIL_1>` など）
- `pii_items[].value` は **検出した生値**（デモ用に保存するが raw全文は保存しない）

---

## 5. チャットLLM（応答生成）仕様（デモ）

- フィルターとは独立したコンポーネントとして実装し、入力は以下のみ:
  - `sanitized_text`
  - `sanitized history`（セッション履歴がある場合）
- デモでは Gemini を使用（モデルは `GEMINI_CHAT_MODEL` のように分離可能）

---

## 6. Spreadsheet 可視化（Apps Script Webhook）

### 6.1 方式（Bを採用）

- Apps Script を Web App としてデプロイし、Cloud Run は **Webhook URL に POST** するだけにする
- Cloud Run 側に Google API の資格情報を持たせない（デモの事故率を下げる）

### 6.2 シート構成

- `pii_dictionary`（生値あり、辞書）
  - `ts`, `event_id`, `pii_type`, `token`, `value`
- `message_log`（サニタイズ済みのみ）
  - `ts`, `event_id`, `sanitized_text`, `pii_summary_json`

### 6.3 保存ルール（重要）

- raw全文は **保存しない**
- `pii_dictionary` に値（email/phone等）が入るため、デモ環境・共有範囲は最小化する

---

## 7. 設定（環境変数）

- `DEMO_MODE=true`（デモ挙動のスイッチ）
- `GEMINI_FILTER_MODEL`（フィルター用モデル。例: `gemini-2.5-flash`）
- `GEMINI_CHAT_MODEL`（チャット用モデル）
- `SHEETS_WEBHOOK_URL`（Apps Script Web App URL）

---

## 8. オープンクエスチョン（必要なら後で詰める）

- PII 辞書シートの生値を、値そのものではなく fingerprint（hash）にするか（デモ後に再検討）
- 本番（常駐ワーカー）での可視化は Sheets か、別の監査ストア（BigQuery等）か

