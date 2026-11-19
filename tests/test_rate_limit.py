import pytest

from sinden import create_app
from sinden.extensions import db


@pytest.fixture
def limited_app(fake_ai, fake_payment):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": True,
            "AI_SERVICE": fake_ai,
            "PAYMENT_SERVICE": fake_payment,
        }
    )
    with app.app_context():
        db.create_all()
        yield app


def test_login_blocked_after_5_tries(limited_app):
    client = limited_app.test_client()
    data = {"email": "nobody@example.com", "password": "wrong-password"}
    for _ in range(5):
        assert client.post("/login", data=data).status_code == 422
    res = client.post("/login", data=data)
    assert res.status_code == 429
    assert "少し時間をおいてください" in res.get_data(as_text=True)


def test_login_page_view_is_not_counted(limited_app):
    client = limited_app.test_client()
    for _ in range(10):
        assert client.get("/login").status_code == 200


def test_other_address_is_not_blocked(limited_app):
    data = {"email": "nobody@example.com", "password": "wrong-password"}
    a = limited_app.test_client()
    for _ in range(6):
        a.post("/login", data=data)
    b = limited_app.test_client()
    res = b.post("/login", data=data, environ_base={"REMOTE_ADDR": "10.0.0.2"})
    assert res.status_code == 422


def test_register_blocked_after_10(limited_app):
    client = limited_app.test_client()
    for i in range(10):
        client.post(
            "/register",
            data={
                "name": f"人{i}",
                "email": f"u{i}@example.com",
                "password": "password123",
                "password_confirm": "password123",
            },
        )
        client.post("/logout")
    res = client.post("/register", data={"name": "x", "email": "x@example.com"})
    assert res.status_code == 429
