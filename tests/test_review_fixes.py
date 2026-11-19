"""コードと設計書のレビューで見つかった点の修正を確かめる"""

from pathlib import Path

from sinden.extensions import db
from sinden.models import Plea, Visit, VisitStatus
from sinden.services import plans
from sinden.services.safety import has_danger_words
from tests.test_shrine import open_shrine


def reconcile(visit, a, h):
    h.post(f"/shrine/{visit.id}/plea", data={"body": "ごめんね"})
    a.post(f"/shrine/{visit.id}/leave")
    h.post(f"/shrine/{visit.id}/leave")
    db.session.refresh(visit)
    assert visit.status == VisitStatus.RECONCILED


# ---- 「残さない」は、相手の返事を待たずにすぐ終える ----


def test_one_no_closes_at_once_and_deletes_pleas(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    reconcile(visit, a, h)

    a.post(f"/shrine/{visit.id}/keep", data={"keep": "no"})  # ひかるはまだ選んでいない
    db.session.refresh(visit)
    assert visit.status == VisitStatus.CLOSED
    assert not visit.kept
    assert db.session.scalar(db.select(db.func.count(Plea.id))) == 0
    # 相手が開くと、ホームへ戻り、理由は伝わらない
    res = h.get(f"/shrine/{visit.id}", follow_redirects=True)
    assert "祠を後にしました" in res.get_data(as_text=True)


def test_one_yes_waits_for_partner(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    reconcile(visit, a, h)

    a.post(f"/shrine/{visit.id}/keep", data={"keep": "yes"})
    db.session.refresh(visit)
    assert visit.status == VisitStatus.RECONCILED
    assert db.session.scalar(db.select(db.func.count(Plea.id))) == 1
    # ひかるが「残さない」なら、そこで終わり。訴えは消える
    h.post(f"/shrine/{visit.id}/keep", data={"keep": "no"})
    db.session.refresh(visit)
    assert visit.status == VisitStatus.CLOSED
    assert not visit.kept
    assert db.session.scalar(db.select(db.func.count(Plea.id))) == 0


def test_keep_rejects_unknown_choice(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    reconcile(visit, a, h)
    assert a.post(f"/shrine/{visit.id}/keep", data={"keep": "maybe"}).status_code == 400


# ---- ふたりが同時に「掟に従う」を押す ----


def test_agree_sees_partner_choice_made_at_same_time(aoi, hikaru, login_as):
    a, h = login_as(aoi), login_as(hikaru)
    a.post("/shrine/invite", data={"theme": "night"})
    visit = db.session.scalar(db.select(Visit))
    h.post(f"/shrine/{visit.id}/accept")
    db.session.refresh(visit)
    assert visit.status == VisitStatus.RULES

    # あおいの「従う」が、ひかるの処理が読んだあとに DB へ入った状態を再現する
    db.session.execute(
        db.update(Visit)
        .where(Visit.id == visit.id)
        .values(inviter_agreed=True)
        .execution_options(synchronize_session=False)
    )
    assert visit.inviter_agreed is False  # 手元の visit は古いまま
    h.post(f"/shrine/{visit.id}/agree")
    db.session.refresh(visit)
    assert visit.status == VisitStatus.PLEADING


def test_agree_by_outsider_is_forbidden(aoi, hikaru, other_pair_user, login_as):
    visit, _a, _h = open_shrine(aoi, hikaru, login_as)
    assert (
        login_as(other_pair_user).post(f"/shrine/{visit.id}/agree").status_code == 403
    )


# ---- 持ち時間が0になっても、自動では届けない ----


def test_timer_does_not_auto_submit():
    js = Path("sinden/static/shrine.js").read_text()
    assert "requestSubmit" not in js


def test_speaker_page_has_time_up_notice_hidden(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert 'id="time-up"' in speaker
    assert "1分以内" in speaker
    # 聴く側には出さない
    assert 'id="time-up"' not in a.get(f"/shrine/{visit.id}").get_data(as_text=True)


# ---- 他人の記録 ----


def test_unfinished_visit_in_records_is_403_for_outsider(
    aoi, hikaru, other_pair_user, login_as
):
    visit, _a, _h = open_shrine(aoi, hikaru, login_as)
    # 残していない祠でも、他のペアには 404 でなく 403（記録の有無を教えない）
    assert login_as(other_pair_user).get(f"/records/{visit.id}").status_code == 403


def test_unkept_visit_is_404_for_member(aoi, hikaru, login_as):
    visit, a, _h = open_shrine(aoi, hikaru, login_as)
    assert a.get(f"/records/{visit.id}").status_code == 404


# ---- 自分を傷つける気配 ----


def test_self_harm_words_are_detected():
    assert has_danger_words("もう死にたい")
    assert has_danger_words("消えたい気分です")
    # 関係の話は、これだけでは反応しない
    assert not has_danger_words("この喧嘩を終わりにしたい")


def test_self_harm_shows_mind_lines_only_to_author(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/plea", data={"body": "もう死にたい"})
    mine = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "0120-061-338" in mine  # #いのちSOS
    assert "0120-279-338" in mine  # よりそいホットライン
    theirs = a.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "0120-061-338" not in theirs
    assert "死にたい" in theirs  # 訴えの本文は、これまでどおり相手に届く


def test_help_page_lists_both_groups(client_anon):
    html = client_anon.get("/help").get_data(as_text=True)
    assert "#8008" in html
    assert "チャット（12:00〜22:00）" in html
    assert "気持ちがつらいとき" in html
    assert "0120-061-338" in html


# ---- 鏡の追加購入のリンクを出す条件 ----


def test_offers_purchase_only_for_monthly_limit_of_plan():
    assert plans.offers_purchase(plans.MONTHLY_LIMIT_PREMIUM)
    assert not plans.offers_purchase(
        "女神の鏡が混み合っています。少し時間をおいてください。"
    )
    assert not plans.offers_purchase(
        "今月の無料の女神の鏡は使い切りました。プランに入ると続けて使えます。"
    )
    assert not plans.offers_purchase(None)


# ---- そのほか ----


def test_too_large_request_is_rejected(app):
    res = app.test_client().post("/login", data={"email": "a" * 2_000_000})
    assert res.status_code == 413


def test_login_and_terms_say_no_password_reset(client_anon):
    assert "再設定はできません" in client_anon.get("/login").get_data(as_text=True)
    assert "再設定はできません" in client_anon.get("/terms").get_data(as_text=True)
