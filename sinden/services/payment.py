"""Stripe（支払い）を呼ぶコードは、このファイルだけに書く。

views からは current_app.extensions["payment"] 経由で呼ぶ（テストではフェイクに差し替わる）。
返す値はすべて素の dict にして、views が Stripe の型に依存しないようにする。
"""

import json

import stripe
from flask import current_app, url_for

from sinden.models import Purchase, PurchaseKind


class PaymentError(Exception):
    """決済サービスの呼び出しに失敗したとき。メッセージは画面に出せる日本語"""


class WebhookError(Exception):
    """Webhook の署名が正しくないとき"""


def _client() -> stripe.StripeClient:
    return stripe.StripeClient(current_app.config["STRIPE_SECRET_KEY"])


def create_checkout_session(purchase: Purchase) -> tuple[str, str]:
    """決済ページを作り、(session_id, 決済ページの URL) を返す。
    月額プランは毎月の自動課金（subscription）、鏡の追加は1回払い（payment）"""
    user = purchase.user
    is_plan = purchase.kind in PurchaseKind.PLANS
    price_data = {
        "currency": "jpy",
        # 円のまま渡す（日本円に小数は無いので100倍しない）
        "unit_amount": purchase.amount,
        "product_data": {"name": f"Placaの祠 {purchase.label}"},
    }
    if is_plan:
        price_data["recurring"] = {"interval": "month"}
    params = {
        "mode": "subscription" if is_plan else "payment",
        "line_items": [{"quantity": 1, "price_data": price_data}],
        "metadata": {"purchase_id": str(purchase.id)},
        # {CHECKOUT_SESSION_ID} は Stripe が実際の ID に置き換える
        "success_url": url_for("billing.complete", _external=True)
        + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": url_for("billing.index", _external=True),
    }
    if is_plan:
        params["subscription_data"] = {
            "metadata": {"user_id": str(user.id), "plan": purchase.kind}
        }
    if user.stripe_customer_id:
        params["customer"] = user.stripe_customer_id
    else:
        params["customer_email"] = user.email
        if not is_plan:
            # あとで月額プランに入ったとき、同じ顧客として扱えるようにする
            params["customer_creation"] = "always"

    try:
        session = _client().v1.checkout.sessions.create(params)
    except stripe.StripeError as e:
        current_app.logger.warning("Stripe の呼び出しに失敗: %r", e)
        raise PaymentError(
            "決済ページを開けませんでした。時間をおいてもう一度お試しください。"
        ) from e
    return session.id, session.url


def retrieve_session(session_id: str) -> dict:
    """決済ページ（Checkout Session）の状態を dict で返す"""
    try:
        session = _client().v1.checkout.sessions.retrieve(session_id)
    except stripe.StripeError as e:
        current_app.logger.warning("Stripe の呼び出しに失敗: %r", e)
        raise PaymentError(
            "支払いの状況を確認できませんでした。時間をおいてもう一度お試しください。"
        ) from e
    return session.to_dict()


def create_portal_url(customer_id: str) -> str:
    """月額プランの解約・カードの変更ができる Stripe の画面の URL を返す"""
    try:
        portal = _client().v1.billing_portal.sessions.create(
            {
                "customer": customer_id,
                "return_url": url_for("billing.index", _external=True),
            }
        )
    except stripe.StripeError as e:
        current_app.logger.warning("Stripe の呼び出しに失敗: %r", e)
        raise PaymentError("管理画面を開けませんでした。") from e
    return portal.url


def parse_webhook(payload: bytes, signature: str | None) -> dict:
    """署名を確かめてから、イベントを dict で返す"""
    try:
        stripe.Webhook.construct_event(
            payload, signature, current_app.config["STRIPE_WEBHOOK_SECRET"]
        )
    except (ValueError, stripe.SignatureVerificationError) as e:
        raise WebhookError("署名が正しくありません") from e
    return json.loads(payload)
