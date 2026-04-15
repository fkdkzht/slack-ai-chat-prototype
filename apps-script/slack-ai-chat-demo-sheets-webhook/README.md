## Apps Script: Sheets Webhook (clasp)

Cloud Run から `SHEETS_WEBHOOK_URL` に JSON を POST すると、Spreadsheet を自動作成して 2 シートに追記する Webhook。

### 1) 初回セットアップ（新規作成）

このフォルダで実行。

```bash
clasp login
clasp create --type standalone --title "slack-ai-chat-demo-sheets-webhook"
```

すると `.clasp.json`（`scriptId`）が生成される。**このファイルは gitignore 済み**。

### 2) push → version → deploy

```bash
clasp push
clasp version "v1"
clasp deploy -V 1 -d "webhook v1"
clasp deployments
```

`clasp deployments` の出力に Web App の URL が出るので、それを Cloud Run 側の `SHEETS_WEBHOOK_URL` に設定する。

### 3) 同じ URL のまま更新（redeploy）

```bash
clasp push
clasp version "v2"
clasp redeploy <DEPLOYMENT_ID> -V 2
```

### 4) 疎通確認（curl）

```bash
curl -sS -X POST "$SHEETS_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{"message_log":{"ts":"1","event_id":"E1","sanitized_text":"hi <EMAIL_1>","pii_summary_json":"{\"EMAIL\":1}"},"pii_dictionary":[{"ts":"1","event_id":"E1","pii_type":"EMAIL","token":"<EMAIL_1>","value":"alice@example.com"}]}'
```

### 注意

- `webapp.access` を `ANYONE` にしているので、**URL を知っている第三者が叩ける**。デモ用途に限定し、必要なら `DOMAIN` へ変更する。
- Spreadsheet は Apps Script 側で自動作成し、Script Properties に `SPREADSHEET_ID` を保存して使い回す。

