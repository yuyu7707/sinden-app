import logging
import os

from flask import Flask, render_template, request
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from sinden.extensions import csrf, db, limiter, login_manager, migrate
from sinden.services import ai, payment, plans
from sinden.services.safety import MIND_LINES

WEEKDAYS = "月火水木金土日"


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or "dev",
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///sinden.sqlite"
        ),
        # 本番（https）では Secure を既定にする。開発・テストでは下で外す
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "1") == "1",
        # 他のサイトからの POST に、ログインの Cookie を付けない
        SESSION_COOKIE_SAMESITE="Lax",
        ANTHROPIC_API_KEY=os.environ.get("ANTHROPIC_API_KEY", ""),
        ANTHROPIC_MODEL=os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5"),
        # 女神の鏡を待つ上限（秒。再試行はしない）と、1回の応答の長さの上限。
        # サーバーの待ち時間（gunicorn の timeout）より短くすること（docs/deploy.md）
        AI_TIMEOUT_SECONDS=30,
        AI_MAX_TOKENS=4000,
        STRIPE_SECRET_KEY=os.environ.get("STRIPE_SECRET_KEY", ""),
        STRIPE_WEBHOOK_SECRET=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        # 月額プランの料金（円）。個人は入った本人だけ、ふたりは2人とも使える
        PRICE_SOLO=int(os.environ.get("PRICE_SOLO", "500")),
        PRICE_PAIR=int(os.environ.get("PRICE_PAIR", "800")),
        # 1回の訴えの持ち時間（秒）。途中で自分から終えてもよい
        TURN_SECONDS=300,
        # 訴えの最大文字数（5分で話せる量より少し多め）
        PLEA_MAX_CHARS=3000,
        # 女神の鏡を1人が月に使える回数。プランの30回は、3日に1回喧嘩しても足りる量。
        # 1回 約4.5円（Opus 5.5、5分の訴え。鏡と灯をまとめて作る）なので、使い切っても黒字になる
        MIRROR_FREE_PER_MONTH=1,
        MIRROR_PREMIUM_PER_MONTH=30,
        # 使い切ったときの追加購入（1回払い）。10回 100円なら、AI の費用 約45円で黒字
        MIRROR_PACK_SIZE=10,
        PRICE_MIRROR_PACK=int(os.environ.get("PRICE_MIRROR_PACK", "100")),
        # 1回の祠で、1人が使える上限
        MIRROR_PER_VISIT=10,
        # 無料プランで振り返れる記録の数
        RECORDS_FREE=3,
        # 送信できる大きさの上限（バイト）。訴え・手紙・Stripe の通知には十分な大きさ
        MAX_CONTENT_LENGTH=1_000_000,
        # テストではフェイクを渡す。None なら本物のモジュールを使う
        AI_SERVICE=None,
        PAYMENT_SERVICE=None,
    )
    if config is not None:
        app.config.update(config)
    # http://localhost の開発サーバーとテストでは、Secure だとログインが続かない。
    # 環境変数か config で明示したときは、その値を使う
    secure_given = "SESSION_COOKIE_SECURE" in os.environ or (
        config is not None and "SESSION_COOKIE_SECURE" in config
    )
    if (app.debug or app.testing) and not secure_given:
        app.config["SESSION_COOKIE_SECURE"] = False
    if app.config["SECRET_KEY"] == "dev" and not (app.debug or app.testing):
        raise RuntimeError(
            "SECRET_KEY を .env（本番は EnvironmentFile）に設定してください"
        )
    # Stripe を使うのに Webhook の秘密鍵が空だと、署名の確認が意味をなさない
    if app.config["STRIPE_SECRET_KEY"] and not app.config["STRIPE_WEBHOOK_SECRET"]:
        raise RuntimeError(
            "STRIPE_SECRET_KEY を使うときは STRIPE_WEBHOOK_SECRET も設定してください"
        )

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "ログインしてください"

    app.extensions["ai"] = app.config["AI_SERVICE"] or ai
    app.extensions["payment"] = app.config["PAYMENT_SERVICE"] or payment

    from sinden.views import auth, billing, home, learn, letters, records, shrine

    for module in (auth, home, shrine, records, letters, learn, billing):
        app.register_blueprint(module.bp)

    from sinden import commands

    commands.init_app(app)

    # 相談窓口（気持ちがつらいとき）と、鏡の追加購入のリンクを出すかの判定を、テンプレートから使う
    app.jinja_env.globals["mind_lines"] = MIND_LINES
    app.jinja_env.globals["offers_purchase"] = plans.offers_purchase

    @app.template_filter("yen")
    def yen(value: int) -> str:
        return f"{value:,}円"

    @app.template_filter("jdate")
    def jdate(value) -> str:
        if value is None:
            return ""
        return (
            f"{value.month}月{value.day}日({WEEKDAYS[value.weekday()]}) {value:%H:%M}"
        )

    @app.template_filter("jday")
    def jday(value) -> str:
        if value is None:
            return ""
        return f"{value.year}年{value.month}月{value.day}日"

    @app.template_global()
    def static_exists(filename: str) -> bool:
        """static/ にファイルがあるか（CC0 の写真を置いたら、図の代わりに使う）"""
        return os.path.isfile(os.path.join(app.static_folder, filename))

    @app.url_defaults
    def static_version(endpoint, values):
        """static の URL にファイルの更新時刻を付ける（直したら、ブラウザが古いものを使わない）"""
        if endpoint == "static" and "filename" in values and "v" not in values:
            path = os.path.join(app.static_folder, values["filename"])
            if os.path.isfile(path):
                values["v"] = int(os.path.getmtime(path))

    @app.after_request
    def security_headers(response):
        # 他のサイトの枠（iframe）に入れさせない。種類の推測をさせない。
        # 外のサイトへ移るとき、URL（祠の番号など）を渡さない
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        # ログイン中の画面（訴え・鏡・手紙）をブラウザに残さない。
        # スマホを共有していても、ログアウト後に「戻る」で見られないように
        if current_user.is_authenticated and request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(429)
    def too_many_requests(error):
        return render_template("errors/429.html"), 429

    logging.basicConfig(level=logging.INFO)
    return app
