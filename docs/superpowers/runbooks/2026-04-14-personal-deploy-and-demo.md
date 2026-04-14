# 個人GCP + 個人Slackでの低コストデプロイ & デモ手順（Runbook）

**目的:** あなた個人の Google アカウントと Slack ワークスペースで、なるべく料金をかけずに本プロトタイプをデプロイし、ボスに動作デモできる状態にする。

**想定構成:** Cloud Run（scale to zero） + Firestore（Tokyo, TTL） + Secret Manager + Slack Events API + Gemini API

---

## 0. 料金を抑える基本方針（重要）

- **Cloud Run**: `min-instances=0`（アイドル時はゼロ） + 最小のCPU/メモリから開始
- **Firestore**: セッション状態のみ保存し **TTLで自動削除**（例: 24h）
- **Secret Manager**: Slack/Gemini の秘匿値はすべて Secret Manager（コードやログに出さない）

---

## 1. 事前準備（ローカル/CLI）

### 1.1 Google Cloud CLI（必須）

1) `gcloud` をインストール  
2) ログイン

```bash
gcloud auth login
gcloud auth application-default login
```

3) 課金アカウントとプロジェクト確認

```bash
gcloud billing accounts list
gcloud projects list
```

### 1.2 Slack CLI（任意）

Slack CLI（`slack`）は **App Manifest をコード管理したい**場合に便利。最短で進めるなら、SlackのWeb UIで App を作る方が早いことも多い（本RunbookはUI手順を主体にする）。

---

## 2. GCP プロジェクト作成（デモ用）

> 既存プロジェクトを使う場合は読み替え。**Firestoreのロケーションは後から変更できない**ので注意。

### 2.1 プロジェクト作成 & 選択

```bash
export PROJECT_ID="slack-ai-chat-demo-$(date +%Y%m%d)-$RANDOM"
gcloud projects create "$PROJECT_ID"
gcloud config set project "$PROJECT_ID"
```

### 2.2 課金の紐付け

```bash
export BILLING_ACCOUNT_ID="XXXXXX-XXXXXX-XXXXXX"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID"
```

### 2.3 必要APIを有効化

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com
```

---

## 3. Firestore（Tokyo）セットアップ + TTL

### 3.1 Firestoreデータベース作成（Native mode / Tokyo）

UI（推奨）:
- Google Cloud Console → Firestore → データベースを作成
- **Native mode**
- **Location: `asia-northeast1 (Tokyo)`**

### 3.2 TTLポリシーの方針

アプリ側でセッションドキュメントに `ttl_at`（timestamp）を保存し、Firestore TTL で削除する。

制約メモ:
- TTL削除は即時ではなく、期限後に遅延があり得る
- TTLはサブコレクションを自動削除しない（本プロトタイプはサブコレクションを作らない設計にする）

CLI（可能なら）:

```bash
gcloud firestore fields ttls update ttl_at \
  --collection-group="sessions" \
  --enable-ttl
```

---

## 4. Secret Manager にシークレット登録

登録するシークレット:
- `slack_signing_secret`
- `slack_bot_token`
- `gemini_api_key`

作成例（`latest` を使う運用）:

```bash
printf "%s" "YOUR_SLACK_SIGNING_SECRET" | gcloud secrets create slack_signing_secret --data-file=-
printf "%s" "xoxb-..." | gcloud secrets create slack_bot_token --data-file=-
printf "%s" "YOUR_GEMINI_API_KEY" | gcloud secrets create gemini_api_key --data-file=-
```

既に存在する場合は「作成」ではなく「新しいバージョン追加」:

```bash
printf "%s" "NEW_VALUE" | gcloud secrets versions add slack_signing_secret --data-file=-
```

---

## 5. Cloud Run デプロイ（低コスト設定）

### 5.1 リージョンを Tokyo にする

```bash
export REGION="asia-northeast1"
```

### 5.2 デプロイ（ソースから）

> アプリ実装が入ったら、リポジトリルートで実行。

```bash
gcloud run deploy slack-ai-chat-prototype \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=2 \
  --set-env-vars="APP_ENV=prod,GCP_PROJECT_ID=$PROJECT_ID,FIRESTORE_DATABASE=(default),SESSION_TTL_HOURS=24,GEMINI_MODEL=gemini-2.5-flash" \
  --set-secrets="SLACK_SIGNING_SECRET=slack_signing_secret:latest,SLACK_BOT_TOKEN=slack_bot_token:latest,GEMINI_API_KEY=gemini_api_key:latest"
```

デプロイ後、表示される **Service URL**（例: `https://...run.app`）をメモする。

---

## 6. Slack App 作成（Events API / DM）

UI（最短）:
1) Slack API → “Create New App”
2) **Bot Token Scopes** を追加（最低限）
   - `chat:write`
   - `im:history`（DM受信に必要。実際に必要なイベントに応じて調整）
3) “Event Subscriptions” を Enable
4) Request URL に Cloud Run の URL を入れる
   - 例: `https://<service-url>/slack/events`
5) Subscribe to bot events
   - `message.im`（DMメッセージ）
6) “Install to Workspace”
7) “Basic Information” から **Signing Secret** を取得
8) “OAuth & Permissions” から **Bot User OAuth Token**（`xoxb-...`）を取得

上記 7) 8) を Secret Manager に登録（Runbook 4章）

---

## 7. 動作確認（デモ当日チェックリスト）

- Cloud Run の `/healthz` が 200 を返す
- Slack でボットにDMを送る
  - スレッドが作られ、ボットが返信する
  - 返信の先頭に **Masked: ...** サマリが出る
  - PIIが含まれるDM（メール/電話）でも、外部送信はサニタイズのみである説明ができる
- Firestore に `sessions/<channel:thread_ts>` ができ、`ttl_at` が将来時刻で入っている

---

## 8. Cursor から操作できるもの（整理）

- **できる（CLIで完結）**
  - `gcloud` による API有効化 / Secret Manager 登録 / Cloud Run デプロイ
  - `gcloud firestore fields ttls ...` による TTL 設定（利用可能なら）
- **UIが確実**
  - Firestore DB 作成（Tokyo指定）
  - Slack App作成・インストール（最初はUI推奨）

