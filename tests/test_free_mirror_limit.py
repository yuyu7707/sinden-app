"""無料の女神の鏡は、1人 月1回（1回＝1人が自分の番で「ことばを確かめる」を1回押すこと）"""

from sinden.extensions import db
from sinden.services import plans
from tests.test_shrine import open_shrine

FREE_USED = "今月の無料の女神の鏡は使い切りました"


def test_free_limit_is_one_per_month(app, aoi, hikaru, login_as):
    visit, _a, _h = open_shrine(aoi, hikaru, login_as)
    assert app.config["MIRROR_FREE_PER_MONTH"] == 1
    assert plans.mirror_block_reason(visit, hikaru) is None

    plans.record_mirror_use(visit, hikaru)
    db.session.commit()

    assert plans.mirrors_left_this_month(hikaru) == 0
    assert FREE_USED in plans.mirror_block_reason(visit, hikaru)


def test_free_limit_is_counted_per_person(app, aoi, hikaru, login_as):
    """ふたりが1回ずつ話す1往復で、ふたりが1回ずつ使う。ひとりが使い切っても、相手は使える"""
    visit, _a, _h = open_shrine(aoi, hikaru, login_as)
    plans.record_mirror_use(visit, hikaru)
    db.session.commit()
    assert plans.mirror_block_reason(visit, aoi) is None


def test_sending_as_is_does_not_use_a_mirror(aoi, hikaru, login_as, fake_ai):
    """「このまま届ける」は AI を使わず、回数も減らない（無料が切れても、祠は止まらない）"""
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/plea", data={"body": "ことばを確かめずに届ける"})
    assert fake_ai.calls == []
    assert plans.mirrors_used_this_month(hikaru) == 0


def test_shrine_goes_on_after_free_mirror_is_used(aoi, hikaru, login_as, fake_ai):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    plans.record_mirror_use(visit, hikaru)
    db.session.commit()

    # 無料の鏡が切れていても、ことばを確かめずに届けられ、番は相手に移る
    h.post(f"/shrine/{visit.id}/plea", data={"body": "鏡なしで届ける"})
    db.session.refresh(visit)
    assert visit.current_speaker_id == aoi.id
    assert fake_ai.calls == []
