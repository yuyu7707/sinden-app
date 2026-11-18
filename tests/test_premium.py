from sinden.extensions import db
from sinden.models import Letter, Visit, VisitStatus, now


def test_writing_letter_requires_premium(aoi, hikaru, login_as):
    a = login_as(aoi)
    assert a.get("/letters/").status_code == 200  # 一覧（読む）は無料
    res = a.get("/letters/new")
    assert res.headers["Location"].endswith("/billing")


def test_free_user_can_read_letter(aoi, hikaru, login_as):
    # 個人プランのあおいが書き、無料のひかるが読む
    aoi.plan = "solo"
    aoi.subscription_status = "active"
    db.session.commit()
    login_as(aoi).post("/letters/new", data={"title": "t", "body": "読んでね"})
    letter = db.session.scalar(db.select(Letter))
    page = login_as(hikaru).get(f"/letters/{letter.id}").get_data(as_text=True)
    assert "読んでね" in page


def test_send_and_read_letter(aoi, hikaru, login_as, premium):
    login_as(aoi).post(
        "/letters/new", data={"title": "ごめんね", "body": "昨日は言いすぎた"}
    )
    letter = db.session.scalar(db.select(Letter))
    assert letter.recipient_id == hikaru.id
    assert letter.read_at is None

    page = login_as(hikaru).get(f"/letters/{letter.id}").get_data(as_text=True)
    assert "昨日は言いすぎた" in page
    assert "PDF に保存" in page
    db.session.refresh(letter)
    assert letter.read_at is not None


def test_other_pair_cannot_read_letter(aoi, hikaru, login_as, premium, other_pair_user):
    login_as(aoi).post("/letters/new", data={"title": "t", "body": "b"})
    letter = db.session.scalar(db.select(Letter))
    other_pair_user.pair.comped = True
    db.session.commit()
    assert login_as(other_pair_user).get(f"/letters/{letter.id}").status_code == 403


def test_letter_is_escaped(aoi, hikaru, login_as, premium):
    login_as(aoi).post(
        "/letters/new", data={"title": "t", "body": "<script>alert(1)</script>"}
    )
    letter = db.session.scalar(db.select(Letter))
    page = login_as(hikaru).get(f"/letters/{letter.id}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page


def test_learn_free_and_locked(app, aoi, hikaru, login_as):
    client = app.test_client()
    free = client.get("/learn/assertion").get_data(as_text=True)
    assert "アサーティブ" in free
    locked = client.get("/learn/desc").get_data(as_text=True)
    assert "続きは、プラン" in locked
    assert "例：家事の分担" not in locked


def test_learn_premium_reads_all(aoi, hikaru, login_as, premium):
    page = login_as(aoi).get("/learn/desc").get_data(as_text=True)
    assert "例：家事の分担" in page


def make_kept_visit(aoi, hikaru, index):
    visit = Visit(
        pair_id=aoi.pair_id,
        inviter=aoi,
        invitee=hikaru,
        status=VisitStatus.CLOSED,
        kept=True,
        ended_at=now().replace(microsecond=index),
    )
    db.session.add(visit)
    db.session.commit()
    return visit


def test_records_free_limit(aoi, hikaru, login_as):
    visits = [make_kept_visit(aoi, hikaru, i) for i in range(5)]
    a = login_as(aoi)
    page = a.get("/records/").get_data(as_text=True)
    assert "これより前の記録が 2 件" in page
    # いちばん古い記録は、無料では開けない
    assert a.get(f"/records/{visits[0].id}").headers["Location"].endswith("/billing")
    assert a.get(f"/records/{visits[4].id}").status_code == 200


def test_records_premium_all(aoi, hikaru, login_as, premium):
    visits = [make_kept_visit(aoi, hikaru, i) for i in range(5)]
    assert login_as(aoi).get(f"/records/{visits[0].id}").status_code == 200
