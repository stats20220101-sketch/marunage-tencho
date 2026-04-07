# Render 環境変数 設定一覧

Render ダッシュボードの「Environment」から以下を設定してください。

## 必須設定

| 変数名 | 説明 | 取得場所 |
|--------|------|---------|
| `FLASK_ENV` | `production` 固定 | — |
| `SECRET_KEY` | Flaskセッション暗号化キー（ランダムな長い文字列） | 自分で生成 |
| `LINE_CHANNEL_SECRET` | LINE Messaging API のチャンネルシークレット | LINE Developers コンソール |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API のアクセストークン | LINE Developers コンソール |
| `DATABASE_URL` | Supabase の PostgreSQL 接続URL | Supabase > Settings > Database > Connection string (URI) |
| `ANTHROPIC_API_KEY` | Claude API キー | console.anthropic.com |
| `OPENAI_API_KEY` | OpenAI API キー（DALL-E 3用） | platform.openai.com |
| `ENCRYPTION_KEY` | データ暗号化キー（Fernet形式・32バイトbase64） | 自分で生成 ※1 |
| `ADMIN_EMAIL` | 管理者メールアドレス | — |
| `SENDGRID_API_KEY` | SendGrid API キー | app.sendgrid.com |

## Google Drive 連携

| 変数名 | 説明 | 取得場所 |
|--------|------|---------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | サービスアカウントの認証情報（JSON全体を1行で） | Google Cloud Console > IAM > サービスアカウント |
| `GOOGLE_DRIVE_ROOT_FOLDER_ID` | Driveの格納先フォルダID | GoogleドライブのフォルダURL末尾の文字列 |
| `GOOGLE_CLIENT_ID` | OAuth2 クライアントID | Google Cloud Console > 認証情報 |
| `GOOGLE_CLIENT_SECRET` | OAuth2 クライアントシークレット | Google Cloud Console > 認証情報 |
| `GOOGLE_REDIRECT_URI` | OAuth2 リダイレクトURI（例: `https://your-app.onrender.com/oauth/callback`） | Render のデプロイURL確認後に設定 |

## 補足

### DATABASE_URL について
- Supabase の接続URL は `postgresql://postgres:[PASSWORD]@[HOST]:5432/postgres` の形式
- `postgres://` で始まる場合も自動で `postgresql://` に変換されます（コード対応済み）

### SECRET_KEY の生成方法
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### ENCRYPTION_KEY の生成方法 ※1
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### GOOGLE_SERVICE_ACCOUNT_JSON の設定方法
JSON ファイルの内容を1行に圧縮してそのまま貼り付けてください。
```bash
# JSONを1行化するコマンド（PowerShell）
(Get-Content service-account.json -Raw) -replace "`n","" -replace "`r",""
```

## Render の LINE Webhook URL 設定

デプロイ後、LINE Developers コンソールの Webhook URL を以下に変更してください：
```
https://[your-app-name].onrender.com/webhook/line
```
