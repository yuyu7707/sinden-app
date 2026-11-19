"""プラン（月額の個人プラン・ふたりプラン）と、Stripe からの通知（Webhook）"""

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from sinden.decorators import pair_required
from sinden.extensions import csrf, db
from sinden.models import Purchase, PurchaseKind, User, now
from sinden.services import plans
from sinden.services.payment import PaymentError, WebhookError

bp = Blueprint("billing", __name__)

PAID_STATUSES = ("paid", "no_payment_required")


def apply_purchase(purchase: Purchase, session: dict) -> None:
    """支払いが確定した申し込みを、支払った本人のプランに反映する（何度呼んでも同じ結果）

    完了画面と Webhook が同時に来ても二重に反映しないよう、
    「まだ pending の申し込み」を paid に変えられたときだけ反映する。
    """
    result = db.session.execute(
        db.update(Purchase)
        .where(Purchase.id == purchase.id, Purchase.status == "pending")
        .values(status="paid", paid_at=now())
    )
    if result.rowcount != 1:
        return
    user = purchase.user
    if session.get("customer"):
        user.stripe_customer_id = session["customer"]
    if purchase.kind == PurchaseKind.MIRRORS:
        # 加算は DB の中で計算する（読んだ値に足して書き戻すと、同時の更新が消える）
        db.session.execute(
            db.update(User)
            .where(User.id == user.id)
            .values(
                extra_mirrors=User.extra_mirrors
                + current_app.config["MIRROR_PACK_SIZE"]
            )
        )
        return
    user.plan = purchase.kind
    user.stripe_subscription_id = session.get("subscription")
    user.subscription_status = "active"


def session_is_paid(session: dict) -> bool:
    return (
        session.get("status") == "complete"
        and session.get("payment_status") in PAID_STATUSES
    )


def checkout_block_reason(user: User, kind: str) -> str | None:
    """申し込めない理由。申し込めるなら None"""
    if kind == PurchaseKind.MIRRORS:
        # 鏡の追加は、本人がプランの機能を使える人だけ（何度でも買える）
        if not user.is_premium:
            return "女神の鏡の追加は、プランに入っている方が購入できます"
        return None
    if user.has_subscription:
        return "すでにプランに入っています。変えるときは、いまのプランを解約してから申し込んでください"
    partner = user.partner
    if partner is not None and partner.has_active_plan:
        if partner.plan == PurchaseKind.PAIR:
            return f"{partner.name}さんのふたりプランで、すでにすべて使えます"
        if kind == PurchaseKind.PAIR:
            return (
                f"{partner.name}さんが個人プランに入っています。"
                "ふたりプランにするときは、先に個人プランを解約してください"
            )
    return None


@bp.route("/billing")
@pair_required
def index():
    config = current_app.config
    return render_template(
        "billing/index.html",
        partner=current_user.partner,
        price_solo=config["PRICE_SOLO"],
        price_pair=config["PRICE_PAIR"],
        mirrors_left=plans.mirrors_left_this_month(current_user),
        free_mirrors=config["MIRROR_FREE_PER_MONTH"],
        premium_mirrors=config["MIRROR_PREMIUM_PER_MONTH"],
        free_records=config["RECORDS_FREE"],
        pack_size=config["MIRROR_PACK_SIZE"],
        price_pack=config["PRICE_MIRROR_PACK"],
        block_solo=checkout_block_reason(current_user, PurchaseKind.SOLO),
        block_pair=checkout_block_reason(current_user, PurchaseKind.PAIR),
    )


@bp.route("/billing/checkout/<kind>", methods=["POST"])
@pair_required
def checkout(kind):
    if kind not in PurchaseKind.LABELS:
        abort(404)
    reason = checkout_block_reason(current_user, kind)
    if reason:
        flash(reason)
        return redirect(url_for("billing.index"))

    # 金額はフォームから受け取らず、設定から決める
    purchase = Purchase(
        pair=current_user.pair,
        user=current_user,
        kind=kind,
        amount=current_app.config[PurchaseKind.PRICE_KEYS[kind]],
    )
    db.session.add(purchase)
    db.session.commit()
    try:
        session_id, url = current_app.extensions["payment"].create_checkout_session(
            purchase
        )
    except PaymentError as e:
        db.session.delete(purchase)
        db.session.commit()
        flash(str(e))
        return redirect(url_for("billing.index"))
    purchase.session_id = session_id
    db.session.commit()
    return redirect(url, code=303)


@bp.route("/billing/complete")
@pair_required
def complete():
    session_id = request.args.get("session_id", "")
    purchase = db.session.scalar(db.select(Purchase).filter_by(session_id=session_id))
    if purchase is None:
        abort(404)
    if purchase.user_id != current_user.id:
        abort(403)
    if purchase.status != "paid":
        try:
            session = current_app.extensions["payment"].retrieve_session(session_id)
        except PaymentError as e:
            flash(str(e))
            return redirect(url_for("billing.index"))
        if session_is_paid(session):
            apply_purchase(purchase, session)
            db.session.commit()
    return render_template("billing/complete.html", purchase=purchase)


@bp.route("/billing/portal", methods=["POST"])
@pair_required
def portal():
    if not current_user.stripe_customer_id:
        flash("管理できる支払いがありません")
        return redirect(url_for("billing.index"))
    try:
        url = current_app.extensions["payment"].create_portal_url(
            current_user.stripe_customer_id
        )
    except PaymentError as e:
        flash(str(e))
        return redirect(url_for("billing.index"))
    return redirect(url, code=303)


@bp.route("/webhooks/stripe", methods=["POST"])
@csrf.exempt
def webhook():
    try:
        event = current_app.extensions["payment"].parse_webhook(
            request.get_data(), request.headers.get("Stripe-Signature")
        )
    except WebhookError:
        abort(400)

    kind = event.get("type")
    obj = event.get("data", {}).get("object", {})
    if kind == "checkout.session.completed":
        purchase_id = (obj.get("metadata") or {}).get("purchase_id", "")
        purchase = (
            db.session.get(Purchase, int(purchase_id))
            if purchase_id.isdigit()
            else None
        )
        if (
            purchase is not None
            and purchase.session_id == obj.get("id")
            and session_is_paid(obj)
        ):
            apply_purchase(purchase, obj)
            db.session.commit()
    elif kind in ("customer.subscription.updated", "customer.subscription.deleted"):
        user = db.session.scalar(
            db.select(User).filter_by(stripe_subscription_id=obj.get("id"))
        )
        if user is not None:
            user.subscription_status = (
                "canceled"
                if kind == "customer.subscription.deleted"
                else obj.get("status")
            )
            db.session.commit()
    return {"received": True}
