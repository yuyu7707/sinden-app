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

echo "==> 更新が終わりました"
