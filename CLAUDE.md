# Placaの祠（sinden-app）

喧嘩したふたり（夫婦・恋人）が、スマホの中の祠で「一人ずつ」訴えるアプリ。キャッチコピーは「喧嘩を、終わりにしないための祠」。

## 設計書（正本）

- 要件（AI 機能の仕様・費用の上限を含む）：`docs/spec/requirements.md`
- 画面一覧・URL・遷移：`docs/design/screens.md`
- ER 図・テーブル定義：`docs/design/database.md`
- 企画の背景・発表の内容：`docs/plan.md`
- 設計書とコードが食い違うときは、設計書を直してからコードを直す

## 技術

- Python 3.14 系（`.python-version` は `3.14`、`requires-python = ">=3.14"`。手元 3.14.9、本番 3.14.10、CI は setup-uv が 3.14 の最新を入れる）、uv
- Flask 3.1、SQLAlchemy 2.1（Flask-SQLAlchemy 3.1、`Mapped` / `mapped_column`）、Flask-Migrate、Flask-Login、Flask-WTF、Flask-Limiter、Jinja2、Pico CSS 2.1.1（CDN、integrity 付き）
- anthropic 2.9、stripe 17、本番は MySQL 8.0 ＋ gunicorn ＋ nginx（Ubuntu 24.04）。正確な版は `uv.lock`
- 版の確かめ方：`uv run python --version`、`uv tree --depth 1`、本番は `ssh` して `cd /var/www/sinden-app && ~/.local/bin/uv run --no-dev python --version`
- DB は開発 SQLite（`instance/sinden.sqlite`、テストはメモリ）、本番 MySQL（PyMySQL）
- Claude API（女神の鏡）、Stripe（月額の個人プラン・ふたりプランと、鏡の追加の1回払い）
- 2人の画面の同期は 3 秒ごとのポーリング（`/shrine/<id>/state`）。WebSocket は使わない

## 構成

- `sinden/__init__.py` の `create_app(config=None)`。拡張は `sinden/extensions.py`
- 画面は Blueprint ごとに `sinden/views/`（auth, home, shrine, records, letters, learn, billing）。テンプレートは `sinden/templates/<blueprint名>/`
- 祠の状態は `Visit.status`：invited → rules → pleading → reconciled → closed（取り消しは cancelled）。テンプレートは `shrine/<status>.html`
- 外部サービスは `sinden/services/`（ai.py = Claude API、payment.py = Stripe）。views からは `current_app.extensions["ai"]` / `["payment"]` 経由で呼ぶ。テストではフェイクを `create_app({"AI_SERVICE": ..., "PAYMENT_SERVICE": ...})` で渡す
- 無料とプランの違いは `sinden/services/plans.py` と config（`MIRROR_FREE_PER_MONTH` など）に集める
- プランは支払った人（User）が持つ。本人だけの機能は `User.is_premium`、ふたりで共有する機能（ローマの朝・記録）は `Pair.is_premium`
- 女神の鏡の回数は1人ずつ数える（`MirrorUse.user_id`）。月の回数を使い切ったら `User.extra_mirrors`（追加購入分）から使う
- 学びの記事は `sinden/content.py`
- 日時は日本時間（Asia/Tokyo）をタイムゾーンなしで保存する。現在時刻は必ず `models.now()` を使い、`datetime.now()` を直接書かない
- 契約の状態は Webhook の中身を信じず、`payment.retrieve_subscription` で取り直す
- 和解は「ふたりの選択」として書く（和解の画面は「ふたりの選択：和解」）。女神は裁かないので、伝説を語る文も含めて「判決」は使わない
- 女神の像・背景は `templates/shrine/_stage.html`。`static/img/` に CC0 写真を置くと差し替わる

## このプロジェクトの決まり

- 文言は日本語。日付は「11月14日(土) 10:00」、金額は「1,200円」
- **女神（AI）は肯定も否定もしない・裁かない・助言しない**。鏡は書いた本人にだけ見せる
- **ことばの灯**（思いやりのある言い方の案）は、女神とは別の機能。案を出すだけで、**相手に届くのは本人が「届ける」を押した言葉だけ**。危険の気配があるときは灯を出さない
- 鏡と灯は1回の AI 呼び出しでまとめて作る（`ai.reflect`）。下書きは `visits.draft_*` に置き、話し手にだけ見せる
- **掟「訴えは一人ずつ」はサーバーで守らせる**：話し手でない人の訴えは受け付けない
- **危険の気配の案内は、書いた本人にだけ出す**（聴く側には出さない）。どちらの判定も完全ではないと伝える。祠は「祠を中断する」でひとりでも終えられる
- 下書き・鏡・灯・危険の気配は、HTML・`/state` の JSON・ログに、本人以外の分を入れない
- 他人のデータ（祠、記録、手紙、支払い）は、取得したあとにペアのメンバーかを必ず確かめ、違えば 403
- 記録は、ふたりとも「残す」を選んだときだけ残す。どちらかが「残さない」なら訴えを削除する
- 金額はサーバー側の config から決める。フォームから来た金額は使わない
- テンプレートで `|safe` と `Markup()` を使わない（訴え・鏡・手紙も自動エスケープのまま）
- SQL は SQLAlchemy の `select()`。SQLite 専用の書き方をしない。文字列のカラムには長さを付ける
- Claude API は `services/ai.py` からだけ呼ぶ。モデルは `ANTHROPIC_MODEL`（既定 `claude-opus-5-5`）。テストで本物の API・Stripe を呼ばない
- テーブルを変えたら `uv run flask db migrate -m "..."` → 内容を読んでから `uv run flask db upgrade`
- 機能を足したら `tests/` にテストを足す（正常系・権限なし・不正な入力）

## コマンド

- 必ず `uv run` を付ける（`uv run flask run --debug`、`uv run pytest -q`、`uv run ruff check .`）
- 開発サーバーはポート 8001（marche-app の 8000 と分ける）

## 作業の進め方

- 変更の前に、何をどのファイルに書くかを短く説明してから実装する
- `.env` を読まない。API キーやパスワードをコード、ログ、コミットに含めない
