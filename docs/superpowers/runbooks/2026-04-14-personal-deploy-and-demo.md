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

1. `gcloud` をインストール  
2. ログイン

```bash
gcloud auth login
gcloud auth application-default login
```

1. 課金アカウントとプロジェクト確認

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

**デモ安定化メモ（重要）:** 本アプリは Slack の再送を避けるために **イベント受信を即 2xx で ack** し、重い処理は **バックグラウンド**で継続する。Cloud Run はアイドル時に CPU が絞られることがあるため、**デモでは `--no-cpu-throttling` を付ける**と、返信作成などの処理が **待機中でも継続しやすく**なる（その分、アイドル時も CPU 課金が発生しやすいので、デモ用途に限定して使う）。

```bash
gcloud run deploy slack-ai-chat-prototype \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory=512Mi \
  --cpu=1 \
  --no-cpu-throttling \
  --min-instances=0 \
  --max-instances=2 \
  --set-env-vars="APP_ENV=prod,GCP_PROJECT_ID=$PROJECT_ID,FIRESTORE_DATABASE=default,SESSION_TTL_HOURS=24,GEMINI_MODEL=gemini-2.5-flash" \
  --set-secrets="SLACK_SIGNING_SECRET=slack_signing_secret:latest,SLACK_BOT_TOKEN=slack_bot_token:latest,GEMINI_API_KEY=gemini_api_key:latest"
```

デプロイ後、表示される **Service URL**（例: `https://...run.app`）をメモする。

**Slack Events の注意:** Slack は **数秒以内に HTTP 2xx** が返らないと **同じイベントを再送**し、結果として **同じ DM に返信が複数**出ることがある。本アプリは **`event_callback` を即 `{"ok":true}` で応答**し、重い処理はバックグラウンドで実行する。

**緊急停止（返信が止まらないとき）:** Slack API の **App 管理 → Event Subscriptions をオフ**にすると、Cloud Run へイベントが飛ばなくなり即座に止まる（アプリ設定側のスイッチ）。

---

## 6. Slack App 作成（Events API / DM）

UI（最短）:

1. Slack API → “Create New App”
2. **Bot Token Scopes** を追加（最低限）
  - `chat:write`
  - `im:history`（DM受信に必要。実際に必要なイベントに応じて調整）
3. “Event Subscriptions” を Enable
4. Request URL に Cloud Run の URL を入れる
  - 例: `https://<service-url>/slack/events`
5. Subscribe to bot events
  - `message.im`（DMメッセージ）
6. “Install to Workspace”
7. “Basic Information” から **Signing Secret** を取得
8. “OAuth & Permissions” から **Bot User OAuth Token**（`xoxb-...`）を取得

上記 7) 8) を Secret Manager に登録（Runbook 4章）

---

## 7. 動作確認（デモ当日チェックリスト）

### 7.0 （デモ用）Spreadsheet ログ可視化の準備（Apps Script Webhook）

> Cloud Run 側に Google API の資格情報を持たせずに、Apps Script を Webhook として使う。

1. Google Drive で Apps Script を新規作成（例: `slack-ai-chat-demo-sheets-webhook`）
2. `Code.gs` に以下を貼り付けて保存

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

  const payload = JSON.parse((e && e.postData && e.postData.contents) || "{}");
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

3. Deploy → New deployment → Type: Web app
   - Execute as: Me
   - Who has access: Anyone（デモ用途。可能なら domain 内に限定）
4. Web app URL を控えて、Cloud Run の環境変数 `SHEETS_WEBHOOK_URL` に設定する
5. `curl` で疎通確認（レスポンスが `ok` になり、Spreadsheet が自動作成される）

```bash
curl -sS -X POST "$SHEETS_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{"message_log":{"ts":"1","event_id":"E1","sanitized_text":"hi <EMAIL_1>","pii_summary_json":"{\"EMAIL\":1}"},"pii_dictionary":[{"ts":"1","event_id":"E1","pii_type":"EMAIL","token":"<EMAIL_1>","value":"alice@example.com"}]}'
```

- Cloud Run の **`/health`** が 200 を返す（`*.run.app` では小文字の `/healthz` が Google フロントで 404 になることがあるため）
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

---

## 9. Secret Manager: グローバル vs リージョン（プロトタイプと本番の方針メモ）

### 9.1 リージョンシークレットの仕様（別リソース構成）

Secret Manager の **リージョンシークレット**は、グローバル（自動レプリケーション）のシークレットとは **リソース階層が異なる**（例: `projects/<番号>/locations/<リージョン>/secrets/<ID>`）。仕様の一次情報は次を参照する。

- [リージョン シークレットの作成（公式）](https://docs.cloud.google.com/secret-manager/regional-secrets/create-regional-secret?hl=ja)

### 9.2 プロトタイプ（この Runbook の範囲）

- **グローバルシークレット（自動レプリケーション）**でよい。CLI から `gcloud secrets describe <id>` で確認しやすく、Cloud Run の **`--set-secrets`（環境変数としてマウント）**とも整合しやすい。
- **注意:** Cloud Run のサービス設定としては、公式ドキュメントの制限に **「Regional secrets はサポートしない」** とある（[Configure secrets for services](https://cloud.google.com/run/docs/configuring/services/secrets) の Limitations）。そのため、プロトタイプのデプロイは **リージョンシークレットに依存しない**前提が安全。

### 9.3 本番（実運用）で「東京リージョンに閉じたい」場合の未決事項（要実装）

実運用では **データ所在地を東京に寄せたい**要件が出ることが多く、その場合 **東京のリージョンシークレット**を使いたくなる。ただし現状は少なくとも **Cloud Run のネイティブな `--set-secrets` だけではリージョンシークレットを前提にできない**（上記公式制限）ため、本番向けには例えば次のような **別実装**が必要になる可能性が高い（要調査・設計）。

- アプリ起動時または実行時に **リージョンエンドポイントの Secret Manager API** でシークレットを取得し、環境変数へ載せ替える（Workload Identity / サービスアカウント権限の設計が別途必要）
- あるいは **Cloud Run 側の機能拡張・制限緩和**を待つ、など

**記録用の結論:** プロトタイプは **グローバルシークレットで進める**。本番では **東京リージョン要件を満たすためのシークレット取得経路をアプリ／インフラ側で実装する**タスクを別途起こす（この Runbook だけでは完結しない）。

---

## 10. Cloud Run の稼働確認・ログ・Slack 挙動まわりの修正プラン

### 10.1 いま動いているか（確認の仕方）

- **サービスは常に「存在」**し、URL は有効。リクエストが無いときは **インスタンス数は 0 に近い**（スケールトゥゼロ）。
- **直近にリクエストがあったか**は Cloud Logging で `resource.type="cloud_run_revision"` かつサービス名でフィルタし、**タイムスタンプが更新されているか**を見る。
- **Slack の Event Subscriptions をオフ**にしても、**再送キューや別経路**でしばらく `POST /slack/events` が続くことがある。また **429** が出ていると Slack 側は失敗扱いになり **再送が増えやすい**。

### 10.2 ログ（開発 vs 運用）

- アプリは **`APP_ENV=dev`** のとき **`slack_ai_chat` ロガーに詳細**（`event_id`・`outcome`・`subtype` 等。**本文やチャンネル生値は出さない**）。
- **`APP_ENV=prod`**（Cloud Run デプロイ例どおり）のときは **本番向けに抑制**（主に `posted` と `handler_error` / 検証失敗など高シグナルだけ）。
- Uvicorn の標準アクセスログは Cloud Logging に乗る（`/slack/events` の HTTP ステータス確認用）。

### 10.3 Slack 挙動に合わせた「まだやるとよい」修正プラン（優先度順）

1. **（済）即応 `{"ok":true}` + バックグラウンド処理** … Slack の 3 秒ルールと再送の緩和。
2. **（済）ボット自身／subtype／`event_id` デデュープ** … 返信嵐の主因を抑止。
3. **429 の原因切り分け** … Cloud Run の同時実行・クォータ・上流レート制限を Console / Metrics で確認。Slack に **2xx を返し続ける**ことが再送抑制の基本。
4. **緊急停止の標準手順** … Event Subscriptions オフに加え、必要なら **`allUsers` の `run.invoker` を外す**と URL 経由の到達を物理的に止められる（Runbook 緊急停止節を参照）。
5. **（任意）Cloud Pub/Sub 経由の Events** … 高負荷時は公式推奨の非同期配信パターンを検討。
6. **（任意）`event_id` 以外の重複キー** … 極端な再送対策として `x-slack-retry-num` 等の扱いをドキュメント化。

