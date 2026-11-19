"""設計書レビュー（11/19）で決めた仕様：安全の案内、祠の中断、プライバシーの境界、日時、文言"""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sinden.extensions import db
from sinden.models import Plea, Visit, VisitStatus, now
from tests.test_shrine import open_shrine

DANGER_BOX = "和解よりもあなたの安全が大切です"
DANGER_WORDS = "殴られるのが怖い"


# ---- 1. 安全の案内 ----


def test_danger_without_ai_is_shown_only_to_writer(aoi, hikaru, login_as, fake_ai):
    """「このまま届ける」（AI を使わない）でも、言葉の確認で本人に案内が出る。相手には出ない"""
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/plea", data={"body": DANGER_WORDS})
    assert fake_ai.calls == []
    assert db.session.scalar(db.select(Plea)).danger

    mine = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert DANGER_BOX in mine
    assert "祠を中断する（ひとりで終えられます）" in mine
    assert "完全ではありません" in mine

    theirs = a.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert DANGER_BOX not in theirs
    assert DANGER_WORDS in theirs  # 届けた本文は相手にも届く


def test_ai_danger_draft_is_shown_only_to_writer(aoi, hikaru, login_as, fake_ai):
    fake_ai.danger = True
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "なんとなく不安"})

    mine = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert DANGER_BOX in mine
    assert "ことばの灯の言い方で届ける" not in mine

    theirs = a.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert DANGER_BOX not in theirs
    # 危険の気配があっても、送信と番の交代はふだんどおり
    h.post(f"/shrine/{visit.id}/plea", data={"body": "なんとなく不安"})
    db.session.refresh(visit)
    assert visit.current_speaker_id == aoi.id


def test_help_page_says_detection_is_not_perfect(app):
    page = app.test_client().get("/help").get_data(as_text=True)
    assert "完全ではありません" in page


# ---- 1. 祠を中断する ----


def test_listener_can_stop_alone(aoi, hikaru, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    fake_ai.danger = False
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "下書き"})
    h.post(f"/shrine/{visit.id}/plea", data={"body": "届けた言葉"})
    # 聴く側（いまは ひかる）でも、ひとりで中断できる
    res = h.post(f"/shrine/{visit.id}/stop")
    assert res.headers["Location"] == "/"
    db.session.refresh(visit)
    assert visit.status == VisitStatus.CLOSED
    assert not visit.kept
    assert visit.current_speaker_id is None
    assert visit.draft_text is None
    assert db.session.scalar(db.select(db.func.count(Plea.id))) == 0
    # 相手には理由を伝えず、ふつうの終わりの言葉だけ
    page = a.get(f"/shrine/{visit.id}", follow_redirects=True).get_data(as_text=True)
    assert "祠を後にしました" in page
    assert "中断" not in page


def test_stop_during_rules(aoi, hikaru, login_as):
    a, h = login_as(aoi), login_as(hikaru)
    a.post("/shrine/invite", data={"theme": "night"})
    visit = db.session.scalar(db.select(Visit))
    h.post(f"/shrine/{visit.id}/accept")
    assert "祠を中断する" in a.get(f"/shrine/{visit.id}").get_data(as_text=True)
    a.post(f"/shrine/{visit.id}/stop")
    db.session.refresh(visit)
    assert visit.status == VisitStatus.CLOSED


def test_stop_is_ignored_after_reconciled(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    a.post(f"/shrine/{visit.id}/leave")
    h.post(f"/shrine/{visit.id}/leave")
    a.post(f"/shrine/{visit.id}/stop")
    db.session.refresh(visit)
    assert visit.status == VisitStatus.RECONCILED


def test_other_pair_cannot_stop(aoi, hikaru, other_pair_user, login_as):
    visit, _a, _h = open_shrine(aoi, hikaru, login_as)
    assert login_as(other_pair_user).post(f"/shrine/{visit.id}/stop").status_code == 403
    db.session.refresh(visit)
    assert visit.status == VisitStatus.PLEADING


# ---- 3. プライバシーの境界 ----


def test_state_json_has_no_private_data(aoi, hikaru, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "まだ届けていない下書き"})
    for client in (a, h):
        data = client.get(f"/shrine/{visit.id}/state").get_json()
        assert set(data) == {"version", "partner_present", "remaining"}
        assert "下書き" not in str(data)


def test_state_is_forbidden_for_other_pair(aoi, hikaru, other_pair_user, login_as):
    visit, _a, _h = open_shrine(aoi, hikaru, login_as)
    res = login_as(other_pair_user).get(f"/shrine/{visit.id}/state")
    assert res.status_code == 403


def test_listener_html_has_no_draft_mirror_or_lamp(aoi, hikaru, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "ひみつの下書き"})
    mine = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "ひみつの下書き" in mine
    assert "鏡：ひみつの下書き" in mine
    assert "灯：ひみつの下書き" in mine

    theirs = a.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "ひみつの下書き" not in theirs


def test_records_show_only_own_mirror(aoi, hikaru, other_pair_user, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "ひかるの訴え"})
    h.post(f"/shrine/{visit.id}/plea", data={"body": "ひかるの訴え"})
    a.post(f"/shrine/{visit.id}/leave")
    h.post(f"/shrine/{visit.id}/leave")
    a.post(f"/shrine/{visit.id}/keep", data={"keep": "yes"})
    h.post(f"/shrine/{visit.id}/keep", data={"keep": "yes"})

    assert "鏡：ひかるの訴え" in h.get(f"/records/{visit.id}").get_data(as_text=True)
    theirs = a.get(f"/records/{visit.id}").get_data(as_text=True)
    assert "ひかるの訴え" in theirs  # 本文は見える
    assert "鏡：ひかるの訴え" not in theirs  # 鏡は見えない
    assert login_as(other_pair_user).get(f"/records/{visit.id}").status_code == 403


def test_partner_state_is_404_after_withdraw(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    a.post("/account/delete", data={"password": "password", "confirm": "y"})
    # 相手がいなくなったのでホームへ転送される（shrine.js はこれを見てホームへ移る）
    res = h.get(f"/shrine/{visit.id}/state")
    assert res.status_code == 302
    assert res.headers["Location"] == "/"


def test_draft_storage_key_includes_user(aoi, hikaru, login_as):
    visit, a, _h = open_shrine(aoi, hikaru, login_as)
    page = a.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert f'data-user="{aoi.id}"' in page
    assert "data-logout" in page


# ---- 4. 日時 ----


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset が使えない OS")
def test_now_is_japan_time_even_if_server_is_utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        expected = datetime.now(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)
        assert abs((now() - expected).total_seconds()) < 5
        assert abs((now() - datetime.now()).total_seconds()) > 8 * 3600
    finally:
        monkeypatch.undo()
        time.tzset()


# ---- 6. 文言 ----


def test_reconciled_says_couples_choice(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    a.post(f"/shrine/{visit.id}/leave")
    h.post(f"/shrine/{visit.id}/leave")
    page = a.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "ふたりの選択：和解" in page
    assert "判決" not in page


def test_no_verdict_word_on_story_pages(app):
    client = app.test_client()
    for url in ("/", "/about"):
        page = client.get(url).get_data(as_text=True)
        assert "判決" not in page
        assert "ふたりが選んだのは、いつも「和解」でした" in page
