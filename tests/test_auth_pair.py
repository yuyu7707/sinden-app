from sinden.extensions import db
from sinden.models import User
from tests.conftest import make_user


def test_landing_page(app):
    res = app.test_client().get("/")
    assert res.status_code == 200
    assert "喧嘩を、<br>終わりにしないための祠。" in res.get_data(as_text=True)


def test_register_and_create_pair(app):
    client = app.test_client()
    res = client.post(
        "/register",
        data={"name": "あおい", "email": "A@Example.com", "password": "password1"},
    )
    assert res.status_code == 302
    user = db.session.scalar(db.select(User).filter_by(email="a@example.com"))
    assert user is not None

    client.post("/pair/create")
    db.session.refresh(user)
    assert user.pair is not None
    assert user.pair.invite_code in client.get("/").get_data(as_text=True)


def test_register_short_password(app):
    res = app.test_client().post(
        "/register", data={"name": "a", "email": "a@example.com", "password": "short"}
    )
    assert res.status_code == 422


def test_login_wrong_password(app):
    make_user("a@example.com", "あおい")
    res = app.test_client().post(
        "/login", data={"email": "a@example.com", "password": "wrong"}
    )
    assert res.status_code == 422


def test_join_pair_with_code(app, login_as):
    inviter = make_user("a@example.com", "あおい")
    joiner = make_user("b@example.com", "ひかる")
    login_as(inviter).post("/pair/create")
    db.session.refresh(inviter)
    code = inviter.pair.invite_code

    login_as(joiner).post("/pair/join", data={"code": code.lower()})
    db.session.refresh(joiner)
    assert joiner.pair_id == inviter.pair_id
    assert joiner.partner.id == inviter.id


def test_join_pair_wrong_code(app, login_as):
    joiner = make_user("b@example.com", "ひかる")
    login_as(joiner).post("/pair/join", data={"code": "NOPE1234"})
    db.session.refresh(joiner)
    assert joiner.pair is None


def test_cannot_join_full_pair(aoi, hikaru, login_as):
    third = make_user("c@example.com", "さんにんめ")
    login_as(third).post("/pair/join", data={"code": aoi.pair.invite_code})
    db.session.refresh(third)
    assert third.pair is None


def test_shrine_requires_pair(app, login_as):
    solo = make_user("c@example.com", "ひとり")
    res = login_as(solo).post("/shrine/invite", data={"theme": "night"})
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/")


def test_ホームの状態は相手の参加と誘いで変わる(pair, aoi, login_as):
    a = login_as(aoi)
    v1 = a.get("/home/state").get_json()["version"]
    assert f'data-version="{v1}"' in a.get("/").get_data(as_text=True)

    hikaru = make_user("b@example.com", "ひかる", pair)
    v2 = a.get("/home/state").get_json()["version"]
    assert v2 != v1

    login_as(hikaru).post("/shrine/invite", data={"theme": "night"})
    assert a.get("/home/state").get_json()["version"] != v2


def test_祠の由来はログインしてもしなくても開ける(aoi, login_as, app):
    for client in (app.test_client(), login_as(aoi)):
        text = client.get("/about").get_data(as_text=True)
        assert "女神に訴えるのは" in text
        assert "顔のない女神" in text
    assert "ホームへ戻る" in text  # ログインしているとき


def test_ホームの状態はログインが必要(app):
    res = app.test_client().get("/home/state")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_ペアがなければホームは自動で確かめない(app, login_as):
    solo = make_user("c@example.com", "ひとり")
    client = login_as(solo)
    assert client.get("/home/state").get_json()["version"] == "none"
    assert "home.js" not in client.get("/").get_data(as_text=True)
