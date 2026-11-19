"""退会と、利用規約・プライバシーポリシーのページ"""

from sinden.extensions import db
from sinden.models import Letter, MirrorUse, Pair, Plea, Purchase, User, Visit
from tests.conftest import make_user
from tests.test_shrine import open_shrine, use_mirrors


def withdraw(client, password="password", confirm="y"):
    data = {"password": password}
    if confirm:
        data["confirm"] = confirm
    return client.post("/account/delete", data=data)


def test_withdraw_removes_own_and_shared_data(aoi, hikaru, login_as, premium):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/plea", data={"body": "ごめんね"})
    a.post("/letters/new", data={"title": "手紙", "body": "読んでね"})
    use_mirrors(aoi, 2)
    use_mirrors(hikaru, 3)
    db.session.add(Purchase(pair=aoi.pair, user=aoi, kind="mirrors", amount=100))
    db.session.commit()
    aoi_id, pair_id = aoi.id, aoi.pair_id

    res = withdraw(a)
    assert res.status_code == 302
    db.session.expire_all()

    assert db.session.get(User, aoi_id) is None
    # ふたりの祠・訴え・手紙は、相手の分も消える
    assert db.session.scalar(db.select(db.func.count(Visit.id))) == 0
    assert db.session.scalar(db.select(db.func.count(Plea.id))) == 0
    assert db.session.scalar(db.select(db.func.count(Letter.id))) == 0
    assert db.session.scalar(db.select(db.func.count(Purchase.id))) == 0
    # 相手のアカウントと、相手の鏡の回数は残る（退会で回数が戻らない）
    assert db.session.get(User, hikaru.id) is not None
    assert db.session.get(Pair, pair_id) is not None
    assert (
        db.session.scalar(
            db.select(db.func.count(MirrorUse.id)).filter_by(user_id=hikaru.id)
        )
        == 3
    )
    assert (
        db.session.scalar(
            db.select(db.func.count(MirrorUse.id)).filter_by(user_id=aoi_id)
        )
        == 0
    )
    # ログアウトしている（ホームではなくトップが出て、足元に退会のリンクがない）
    page = a.get("/").get_data(as_text=True)
    assert "退会しました" in page
    assert "/account/delete" not in page


def test_last_member_withdraw_removes_pair(app, login_as):
    alone = make_user("a@example.com", "あおい")
    client = login_as(alone)
    client.post("/pair/create")
    pair_id = db.session.get(User, alone.id).pair_id
    withdraw(client)
    db.session.expire_all()
    assert db.session.get(Pair, pair_id) is None


def test_partner_can_still_use_app(aoi, hikaru, login_as):
    withdraw(login_as(aoi))
    res = login_as(hikaru).get("/")
    assert res.status_code == 200


def test_withdraw_wrong_password(aoi, hikaru, login_as):
    res = withdraw(login_as(aoi), password="wrong-password")
    assert res.status_code == 422
    assert db.session.get(User, aoi.id) is not None


def test_withdraw_requires_confirm(aoi, hikaru, login_as):
    res = withdraw(login_as(aoi), confirm=None)
    assert res.status_code == 422
    assert db.session.get(User, aoi.id) is not None


def test_withdraw_requires_login(app):
    res = app.test_client().post("/account/delete", data={"password": "password"})
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_cannot_withdraw_with_subscription(aoi, hikaru, login_as):
    aoi.plan = "solo"
    aoi.subscription_status = "active"
    db.session.commit()
    res = withdraw(login_as(aoi))
    assert res.headers["Location"].endswith("/billing")
    assert db.session.get(User, aoi.id) is not None


def test_policy_pages(app):
    client = app.test_client()
    privacy = client.get("/privacy").get_data(as_text=True)
    assert "Claude API" in privacy
    assert "Stripe" in privacy
    assert "音声認識" in privacy
    assert "利用規約" in client.get("/terms").get_data(as_text=True)
    # 足元と登録画面からたどれる
    assert "/privacy" in client.get("/").get_data(as_text=True)
    assert "/terms" in client.get("/register").get_data(as_text=True)


def test_withdraw_page_names_partner(aoi, hikaru, login_as):
    page = login_as(aoi).get("/account/delete").get_data(as_text=True)
    assert "ひかるさんの分も含めて" in page
