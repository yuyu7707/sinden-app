#!/usr/bin/env bash
# 本番サーバーでの更新手順（サーバーの中で bash /var/www/sinden-app/deploy.sh）
set -euo pipefail

# SSH から呼ばれたときに uv が見つかるようにする
export PATH="$HOME/.local/bin:$PATH"

echo "==> アプリのフォルダーへ移動します"
cd /var/www/sinden-app

echo "==> 最新のコードを取得します（git pull）"
git pull --ff-only origin main

echo "==> 依存パッケージを同期します（uv sync）"
uv sync --frozen --no-dev

echo "==> データベースのマイグレーションを適用します"
uv run --frozen --no-dev flask db upgrade

echo "==> アプリを再起動します"
sudo -n systemctl restart sinden-app

echo "==> 2 秒待って、起動したか確かめます"
sleep 2
systemctl is-active sinden-app

echo "==> トップページが返るか確かめます"
# 設定の誤り（SECRET_KEY や Stripe の鍵の不足）で起動に失敗していたら、ここで止まる
for i in 1 2 3 4 5; do
  if curl -fsS -o /dev/null http://127.0.0.1:8001/; then
    break
  fi
  if [ "$i" = 5 ]; then
    echo "トップページが返りません。sudo journalctl -u sinden-app -n 50 --no-pager で確かめてください"
    exit 1
  fi
  sleep 2
done

echo "==> 更新が終わりました"
