import pytest
from flask import g

from sinden import create_app
from sinden.extensions import db
from sinden.models import Pair, User, new_invite_code
from sinden.services.ai import AIError, Reflection
from sinden.services.payment import WebhookError

# 本物の外部サービス（Claude API、Stripe）は、テストでは呼ばない


class FakeAI:
    def __init__(self):
        self.calls = []
        self.error = None
        self.danger = False

    def reflect(self, text):
        if self.error:
            raise self.error
        self.calls.append(text)
        return Reflection(
            mirror=f"鏡：{text[:10]}",
            danger=self.danger,
            lamp="" if self.danger else f"灯：{text}",
        )


class FakePayment:
    def __init__(self):
        self.created = []
        self.sessions = {}
        self.event = None

    def create_checkout_session(self, purchase):
        session_id = f"cs_test_{purchase.id}"
        self.created.append(purchase.kind)
        return session_id, f"https://checkout.stripe.test/{session_id}"

    def retrieve_session(self, session_id):
        return self.sessions[session_id]

    def create_portal_url(self, customer_id):
        return f"https://billing.stripe.test/{customer_id}"

    def parse_webhook(self, payload, signature):
        if signature != "ok":
            raise WebhookError("bad")
        return self.event


@pytest.fixture
def fake_ai():
    return FakeAI()


@pytest.fixture
def fake_payment():
    return FakePayment()


@pytest.fixture
def app(fake_ai, fake_payment):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "AI_SERVICE": fake_ai,
            "PAYMENT_SERVICE": fake_payment,
        }
    )

    # テストでは app_context を開いたままリクエストを送るため、g が使い回される。
    # 2人分のブラウザ（client）を交互に使うので、ログイン中のユーザーの記憶を毎回消す
    @app.before_request
    def reset_login_cache():
        g.pop("_login_user", None)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


def make_user(email, name, pair=None):
    user = User(name=name, email=email, pair=pair)
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def pair(app):
    p = Pair(invite_code=new_invite_code())
    db.session.add(p)
    db.session.commit()
    return p


@pytest.fixture
def aoi(pair):
    return make_user("a@example.com", "あおい", pair)


@pytest.fixture
def hikaru(pair):
    return make_user("b@example.com", "ひかる", pair)


@pytest.fixture
def other_pair_user(app):
    other = Pair(invite_code=new_invite_code())
    db.session.add(other)
    db.session.commit()
    user = make_user("x@example.com", "べつの人", other)
    make_user("y@example.com", "べつの相手", other)
    return user


@pytest.fixture
def login_as(app):
    """ユーザーごとに別のブラウザ（client）を用意してログインする"""

    def do_login(user):
        client = app.test_client()
        client.post("/login", data={"email": user.email, "password": "password"})
        return client

    return do_login


@pytest.fixture
def premium(pair):
    pair.comped = True
    db.session.commit()
    return pair


__all__ = ["AIError"]
