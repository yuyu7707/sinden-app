# 本番環境

- URL：https://sinden-34-146-71-44.sslip.io
- サーバー：Google Cloud の VM（Ubuntu 24.04）。marche-app と同じサーバーに、別のアプリとして置く

## 構成

| | sinden-app | （参考）marche-app |
|-|-|-|
| 置き場所 | `/var/www/sinden-app` | `/var/www/marche-app` |
| アプリ | gunicorn（`127.0.0.1:8001`、worker 2） | `127.0.0.1:8000` |
| サービス | systemd `sinden-app.service` | `marche-app.service` |
| データベース | MySQL 8.0 の `sinden`（ユーザー `sinden`、utf8mb4） | `marche` |
| Web サーバー | nginx `sites-available/sinden-app`（`/static/` は nginx が直接返す） | `sites-available/marche-app` |
| https | Let's Encrypt（certbot。自動更新） | なし |

- ドメインは [sslip.io](https://sslip.io)（IP アドレスをそのまま名前にする無料のサービス）。https は音声入力（ブラウザの音声認識）に必要
- `.env` はサーバーにだけ置く（`chmod 600`）。DB のパスワードと `SECRET_KEY` はサーバーの中で作り、外に出していない
- `SESSION_COOKIE_SECURE=1`（https だけでログインの Cookie を送る）

## 初めて公開したときの手順（2026-11-18）

1. ディスクの空きを作る：`sudo apt-get clean`、`sudo journalctl --vacuum-size=100M`、古い snap の削除
2. `cd /var/www && git clone https://github.com/yuyu7707/sinden-app.git`
3. MySQL に DB とユーザーを作る
   ```sql
   CREATE DATABASE sinden CHARACTER SET utf8mb4 COLLATE utf8mb4_ja_0900_as_cs;
   CREATE USER 'sinden'@'localhost' IDENTIFIED BY '（openssl rand -hex 24 で作った値）';
   GRANT ALL PRIVILEGES ON sinden.* TO 'sinden'@'localhost';
   ```
4. `.env` を作る（項目は `.env.example`。`DATABASE_URL=mysql+pymysql://sinden:...@localhost/sinden?charset=utf8mb4`）
5. `uv sync --frozen --no-dev` → `uv run --frozen --no-dev flask db upgrade`（`Context impl MySQLImpl.` と表示される）
6. `/etc/systemd/system/sinden-app.service` を作り、`sudo systemctl enable --now sinden-app`
7. nginx の設定を作り、`sites-enabled` にリンクして `sudo nginx -t && sudo systemctl reload nginx`
8. `sudo certbot --nginx -d sinden-34-146-71-44.sslip.io --redirect`

## 更新するとき

手元で main に push したあと、サーバーで次を実行する。

```
bash /var/www/sinden-app/deploy.sh
```

## API キーを入れるとき

サーバーで `nano /var/www/sinden-app/.env` を開き、`ANTHROPIC_API_KEY`、`STRIPE_SECRET_KEY`、`STRIPE_WEBHOOK_SECRET` を書いて、`sudo systemctl restart sinden-app`。
Stripe の Webhook の送り先は `https://sinden-34-146-71-44.sslip.io/webhooks/stripe`。

## 困ったとき

```
systemctl status sinden-app
sudo journalctl -u sinden-app -n 50 --no-pager
df -h /        # ディスクの空き
```
