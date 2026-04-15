## Slack AI Chat Prototype

Slack から投げた内容を AI チャットに接続し、個人情報・機密情報を自動クレンジングした上で応答するプロトタイプ。

### Status

- Prototype (WIP)

### 開発・リリース方針（一人開発）

- **Pull Request は運用しない。** レビュー用の PR フローは設けず、`python -m pytest` が通ることを確認したうえで `main` に直接マージしてデプロイに進む。
- 作業用ブランチは任意。マージ後の正は常に `main` とする。

### Docs

- `docs/superpowers/specs/2026-04-14-slack-ai-chat-with-pii-cleansing-design.md`
- `docs/superpowers/plans/2026-04-14-slack-ai-chat-with-pii-cleansing-implementation-plan.md`
- `docs/superpowers/runbooks/2026-04-14-personal-deploy-and-demo.md`

### 必要環境

- Python 3.12 以上（ローカル実行・テスト用）
- GCP プロジェクト（Firestore Native / Tokyo、Cloud Run デプロイ時）
- Slack App（Events API、Bot Token）
- Gemini API キー

### ローカル実行

1. 依存関係を入れる（例: 仮想環境を作ってから）

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. `.env.example` を `.env` にコピーし、値を埋める。

```bash
cp .env.example .env
```

3. アプリ起動。

```bash
uvicorn app.main:app --reload --port 8080
```

- ヘルスチェック: `GET http://127.0.0.1:8080/healthz`
- Slack Events URL は `POST /slack/events`（署名検証あり）。外向き URL が必要なので、開発時は ngrok 等で公開する。

### テスト

```bash
python -m pytest
```

### Docker

```bash
docker build -t slack-ai-chat-prototype:local .
docker run --rm -p 8080:8080 --env-file .env slack-ai-chat-prototype:local
```

Cloud Run はコンテナ起動時に `PORT` を渡す。上記 `Dockerfile` は `PORT` が無いとき `8080` を使う。

### Cloud Run へのデプロイ例

Secret Manager に秘匿値を置いたうえで、例として次のようにデプロイできる（プロジェクト・シークレット名は置き換える）。

```bash
gcloud run deploy slack-ai-chat-prototype \
  --source . \
  --region asia-northeast1 \
  --set-env-vars "APP_ENV=prod,GCP_PROJECT_ID=YOUR_PROJECT,FIRESTORE_DATABASE=(default),SESSION_TTL_HOURS=24,GEMINI_MODEL=gemini-2.5-flash" \
  --set-secrets "SLACK_SIGNING_SECRET=slack_signing_secret:latest,SLACK_BOT_TOKEN=slack_bot_token:latest,GEMINI_API_KEY=gemini_api_key:latest"
```

詳細な GCP / Slack の手順は `docs/superpowers/runbooks/2026-04-14-personal-deploy-and-demo.md` を参照。

### あなたが手動でやること（チェックリスト）

- `.env`（または Cloud Run のシークレット）に **実値** を入れる: Slack Signing Secret / Bot Token、GCP プロジェクト ID、Gemini API キー。
- Firestore を **Native / asia-northeast1** で作成済みにする（ロケーションは後から変えられない）。
- Slack アプリで **Events API の Request URL** を Cloud Run の `https://.../slack/events` に向け、必要スコープ・イベント（`message` など）を有効化する。
- ローカルから Slack に届ける場合は **ngrok 等で HTTPS 公開**し、その URL を Slack に登録する。
- 本番では **Secret Manager** と最小権限のサービスアカウントを使う（Runbook 参照）。
