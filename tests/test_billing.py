from sinden.extensions import db
from sinden.models import Plea, Purchase
from sinden.services import plans
from tests.test_shrine import open_shrine, speak, use_mirrors


def paid_session(**extra):
    return {"status": "complete", "payment_status": "paid", **extra}


def buy(client, user, kind, fake_payment):
    """kind を申し込み、支払いを済ませて完了画面まで進める"""
    client.post(f"/billing/checkout/{kind}")
    purchase = db.session.scalars(
        db.select(Purchase).filter_by(user_id=user.id).order_by(Purchase.id.desc())
    ).first()
    fake_payment.sessions[purchase.session_id] = paid_session(
        customer=f"cus_{user.id}", subscription=f"sub_{user.id}"
    )
    res = client.get(f"/billing/complete?session_id={purchase.session_id}")
    db.session.refresh(user)
    return purchase, res


def test_checkout_redirects_to_stripe(aoi, hikaru, login_as):
    res = login_as(aoi).post("/billing/checkout/pair")
    assert res.status_code == 303
    assert res.headers["Location"].startswith("https://checkout.stripe.test/")
    purchase = db.session.scalar(db.select(Purchase))
    assert purchase.amount == 800
    assert purchase.kind == "pair"


def test_unknown_plan_is_404(aoi, hikaru, login_as):
    assert login_as(aoi).post("/billing/checkout/lifetime").status_code == 404


def test_solo_plan_is_only_for_payer(aoi, hikaru, login_as, fake_payment):
    purchase, res = buy(login_as(aoi), aoi, "solo", fake_payment)
    assert purchase.amount == 500
    assert "ありがとうございます" in res.get_data(as_text=True)
    assert aoi.is_premium
    assert not hikaru.is_premium  # 本人だけの機能は、相手には使えない
    assert hikaru.pair.is_premium  # ふたりで共有する機能は使える


def test_pair_plan_is_for_both(aoi, hikaru, login_as, fake_payment):
    buy(login_as(aoi), aoi, "pair", fake_payment)
    assert aoi.is_premium
    assert hikaru.is_premium
    assert hikaru.plan_source == "あおいさんのふたりプラン"


def test_partner_cannot_buy_when_pair_plan(aoi, hikaru, login_as, fake_payment):
    buy(login_as(aoi), aoi, "pair", fake_payment)
    login_as(hikaru).post("/billing/checkout/solo")
    assert db.session.scalar(db.select(Purchase).filter_by(user_id=hikaru.id)) is None


def test_cannot_buy_pair_when_partner_has_solo(aoi, hikaru, login_as, fake_payment):
    buy(login_as(aoi), aoi, "solo", fake_payment)
    login_as(hikaru).post("/billing/checkout/pair")
    assert db.session.scalar(db.select(Purchase).filter_by(user_id=hikaru.id)) is None
    # 個人プランなら、相手も自分で入れる
    buy(login_as(hikaru), hikaru, "solo", fake_payment)
    assert hikaru.is_premium


def test_cannot_buy_plan_twice(aoi, hikaru, login_as, fake_payment):
    a = login_as(aoi)
    buy(a, aoi, "solo", fake_payment)
    a.post("/billing/checkout/pair")
    assert fake_payment.created == ["solo"]


def test_complete_unpaid_does_not_apply(aoi, hikaru, login_as, fake_payment):
    a = login_as(aoi)
    a.post("/billing/checkout/solo")
    purchase = db.session.scalar(db.select(Purchase))
    fake_payment.sessions[purchase.session_id] = {
        "status": "open",
        "payment_status": "unpaid",
    }
    a.get(f"/billing/complete?session_id={purchase.session_id}")
    db.session.refresh(aoi)
    assert not aoi.is_premium


def test_other_user_cannot_complete(aoi, hikaru, login_as):
    login_as(aoi).post("/billing/checkout/solo")
    purchase = db.session.scalar(db.select(Purchase))
    # 同じペアの相手でも、他人の申し込みは完了させられない
    res = login_as(hikaru).get(f"/billing/complete?session_id={purchase.session_id}")
    assert res.status_code == 403


def test_webhook_subscription_flow(aoi, hikaru, login_as, app, fake_payment):
    login_as(aoi).post("/billing/checkout/pair")
    purchase = db.session.scalar(db.select(Purchase))
    client = app.test_client()
    fake_payment.event = {
        "type": "checkout.session.completed",
        "data": {
            "object": paid_session(
                id=purchase.session_id,
                customer="cus_1",
                subscription="sub_1",
                metadata={"purchase_id": str(purchase.id)},
            )
        },
    }
    res = client.post("/webhooks/stripe", headers={"Stripe-Signature": "ok"})
    assert res.status_code == 200
    db.session.refresh(aoi)
    assert hikaru.is_premium
    assert aoi.stripe_subscription_id == "sub_1"

    fake_payment.event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_1", "status": "canceled"}},
    }
    client.post("/webhooks/stripe", headers={"Stripe-Signature": "ok"})
    db.session.refresh(aoi)
    assert not aoi.is_premium
    assert not hikaru.is_premium


def test_webhook_bad_signature(app):
    res = app.test_client().post(
        "/webhooks/stripe", headers={"Stripe-Signature": "bad"}
    )
    assert res.status_code == 400


def test_portal(aoi, hikaru, login_as, fake_payment):
    a = login_as(aoi)
    buy(a, aoi, "solo", fake_payment)
    res = a.post("/billing/portal")
    assert res.headers["Location"] == f"https://billing.stripe.test/cus_{aoi.id}"


def test_billing_page_shows_plans(aoi, hikaru, login_as):
    page = login_as(aoi).get("/billing").get_data(as_text=True)
    assert "500円 / 月" in page
    assert "800円 / 月" in page
    assert "200円お得" in page
    assert "女神の鏡 追加10回" in page


# ---- 女神の鏡の追加購入 ----


def test_free_user_cannot_buy_mirror_pack(aoi, hikaru, login_as, fake_payment):
    login_as(aoi).post("/billing/checkout/mirrors")
    assert fake_payment.created == []
    page = login_as(aoi).get("/billing").get_data(as_text=True)
    assert "プランに入ると購入できます" in page


def test_buy_mirror_pack(aoi, hikaru, login_as, fake_payment):
    a = login_as(aoi)
    buy(a, aoi, "solo", fake_payment)
    purchase, _ = buy(a, aoi, "mirrors", fake_payment)
    assert purchase.amount == 100
    assert aoi.extra_mirrors == 10
    assert aoi.plan == "solo"  # 追加購入でプランは変わらない
    # 何度でも買える
    buy(a, aoi, "mirrors", fake_payment)
    assert aoi.extra_mirrors == 20
    assert fake_payment.created == ["solo", "mirrors", "mirrors"]


def test_partner_of_pair_plan_can_buy_mirror_pack(aoi, hikaru, login_as, fake_payment):
    buy(login_as(aoi), aoi, "pair", fake_payment)
    buy(login_as(hikaru), hikaru, "mirrors", fake_payment)
    assert hikaru.extra_mirrors == 10


def test_extra_mirrors_used_after_monthly(
    aoi, hikaru, login_as, fake_payment, fake_ai, premium
):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    hikaru.extra_mirrors = 2
    db.session.commit()
    use_mirrors(hikaru, 30)  # プランの月30回を使い切った
    assert plans.mirrors_left_this_month(hikaru) == 2

    speak(h, visit, "追加分で映してほしい")
    assert db.session.scalar(db.select(Plea)).mirror is not None
    db.session.refresh(hikaru)
    assert hikaru.extra_mirrors == 1


def test_extra_mirrors_not_used_while_monthly_left(
    aoi, hikaru, login_as, fake_payment, fake_ai, premium
):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    hikaru.extra_mirrors = 5
    db.session.commit()
    speak(h, visit, "まだ月の分がある")
    db.session.refresh(hikaru)
    assert hikaru.extra_mirrors == 5


def test_premium_limit_links_to_purchase(aoi, hikaru, login_as, fake_ai, premium):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    use_mirrors(hikaru, 30)
    speak(h, visit, "上限のあと")
    page = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "女神の鏡を追加で購入する" in page


def test_free_limit_links_only_to_plan(aoi, hikaru, login_as, fake_ai):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    use_mirrors(hikaru, 3)
    speak(h, visit, "上限のあと")
    page = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "プランに入ると続けて使えます" in page
    assert "女神の鏡を追加で購入する" not in page
