# Placaの祠（sinden-app）

**喧嘩を、終わりにしないための祠。**
ひとりずつ話して、最後まで聴く。2000年前のローマの仲直りの知恵を、スマホに。
企画と設計は [docs/plan.md](docs/plan.md)。

- **公開中**：https://sinden-34-146-71-44.sslip.io
- 設計書：[要件](docs/spec/requirements.md) / [画面](docs/design/screens.md) / [データベース](docs/design/database.md) / [本番環境](docs/deploy.md)

## 動かし方

### 1. `.env` を作る

プロジェクトの直下に `.env` を作り、次の内容を書きます（`.env` は Git に入れません）。

```
FLASK_DEBUG=1
SECRET_KEY=（長いランダムな文字列）
DATABASE_URL=sqlite:///sinden.sqlite
ANTHROPIC_API_KEY=（Claude API キー。空なら女神の鏡は「いまは使えません」になる）
ANTHROPIC_MODEL=claude-opus-5-5
STRIPE_SECRET_KEY=（Stripe のテスト用シークレットキー sk_test_...）
STRIPE_WEBHOOK_SECRET=（stripe listen が表示する whsec_...）
PRICE_SOLO=500
PRICE_PAIR=800
PRICE_MIRROR_PACK=100
SESSION_COOKIE_SECURE=0
```

`SECRET_KEY` は `uv run python -c "import secrets; print(secrets.token_hex(32))"` で作れます。

`STRIPE_SECRET_KEY` と `STRIPE_WEBHOOK_SECRET` は、**両方書くか、両方空**にします。片方だけだと、Webhook の署名を確かめられないため、アプリは起動しません。支払いを試さないなら両方空で動きます（プランの申し込みだけが使えません）。

### 2. 起動する

```
uv sync
uv run flask db upgrade
uv run flask seed               # 開発用の初期データ（全データを消して入れ直す）
uv run flask run --debug        # http://127.0.0.1:8001
```

初期データのユーザー（パスワードはすべて `password`）

| メール | 名前 | |
|---|---|---|
| a@example.com | あおい | ひかるとペア |
| b@example.com | ひかる | あおいとペア |
| c@example.com | ひとり | ペアなし |

2人の動きを試すときは、**通常のウィンドウとシークレットウィンドウ**で別々にログインします。

`uv run flask set-premium a@example.com` で、Stripe を通さずにペアを特別プラン（ふたりとも全機能）にできます（`--off` で戻す）。

### 3. 支払い（Stripe）を試す（任意）

Stripe のテスト用のキーで、手元のパソコンで支払いを試す手順です。試さなくても、ほかの機能はすべて動きます。

1. Stripe のダッシュボードを**テストモード**にして、シークレットキーを `.env` の `STRIPE_SECRET_KEY` に書く（まだ再起動しない。`STRIPE_WEBHOOK_SECRET` が空のままだと起動しないため）
2. 月額プランの解約画面を使うため、ダッシュボードの「設定 → Billing → カスタマーポータル」を有効にする
3. 別のターミナルで Webhook を転送する（Stripe CLI）
   ```
   stripe listen --forward-to localhost:8001/webhooks/stripe
   ```
   表示された `whsec_...` を `STRIPE_WEBHOOK_SECRET` に書き、アプリを再起動する
4. テスト用カード `4242 4242 4242 4242`（期限は未来の日付、CVC は任意）で支払う

### 4. 女神の像と背景を写真にする（任意）

`sinden/static/img/` に次の名前で画像を置くと、図の代わりに写真を使います。
**CC0（パブリックドメイン）の画像**を使ってください（例：メトロポリタン美術館 Open Access のローマ時代の女性像）。

| ファイル | 使う場所 |
|---|---|
| `img/goddess.png` | 女神の像（背景を透明にした PNG がおすすめ） |
| `img/bg-night.jpg` | 夜の祠の背景 |
| `img/bg-morning.jpg` | ローマの朝の背景 |
| `img/bg-learn.jpg` | 学び（ふたりの書庫）の帯。ケルスス図書館、撮影 Jona Lendering / Livius.org（CC0） |

ヴィリプラカの像は現存しないため、発表や画面では「ローマ時代の女性像を女神のイメージとして使用」と明記します。

## テストと検査

```
uv run pytest -q
uv run ruff check .
uv run ruff format .
```

## 無料とプランの違い

| | 無料 | 個人プラン 500円/月 | ふたりプラン 800円/月 |
|---|---|---|---|
| 一人ずつ訴える・夜の祠・和解 | ○ | ○ | ○ |
| 女神の鏡（AI） | 1人 月1回 | 本人が月30回 | ふたりとも月30回 |
| 声で訴える・学び（全記事） | － | 本人 | ふたりとも |
| 手紙 | 読むだけ | 本人が書ける | ふたりとも書ける |
| 記録の振り返り（共有） | 記録は直近3件 | ふたりとも | ふたりとも |

- 共有する機能は、どちらかがプランに入れば、ふたりで使えます
- 女神の鏡を使い切ったら、**追加10回 100円**（1回払い・期限なし）で買い足せます。追加購入はプランの方だけです
- 1回の祠で、1人が鏡を使えるのは10回まで
