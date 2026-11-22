from datetime import timedelta

from sinden.extensions import db
from sinden.models import Plea, now
from tests.test_shrine import open_shrine


def speaker_and_listener(visit, aoi, a, h):
    return (a, h) if visit.current_speaker_id == aoi.id else (h, a)


def test_strong_words_are_detected_but_danger_words_are_not_double_handled():
    from sinden.services.safety import has_strong_words

    assert has_strong_words("ふざけんな、いい加減にしろ")
    assert has_strong_words("はぁ？なにそれ")
    assert not has_strong_words("約束の時間に遅れて来たのが、悲しかった")
    # 危険の気配の言葉は、別の案内で扱う
    assert not has_strong_words("死ね")


def test_strong_words_show_flame_screen_and_do_not_deliver(
    aoi, hikaru, login_as, fake_ai
):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, listener = speaker_and_listener(visit, aoi, a, h)
    res = speaker.post(f"/shrine/{visit.id}/plea", data={"body": "ふざけんな！"})
    html = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "女神の灯が、揺れました" in html
    assert "このまま届ける" in html and "書き直す" in html
    # まだ届いていない。相手の画面にも出ない。AI も使わない
    assert db.session.scalar(db.select(db.func.count(Plea.id))) == 0
    assert "ふざけんな" not in listener.get(f"/shrine/{visit.id}").get_data(
        as_text=True
    )
    assert "ふざけんな" not in listener.get(f"/shrine/{visit.id}/state").get_data(
        as_text=True
    )
    assert fake_ai.calls == []


def test_confirm_delivers_once(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    speaker.post(
        f"/shrine/{visit.id}/plea", data={"body": "ふざけんな！", "confirm": "1"}
    )
    plea = db.session.scalar(db.select(Plea))
    assert plea.body == "ふざけんな！"
    assert plea.source == "own"


def test_rewrite_keeps_text_and_delivers_nothing(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    res = speaker.post(
        f"/shrine/{visit.id}/plea", data={"body": "ふざけんな！", "rewrite": "1"}
    )
    html = res.get_data(as_text=True)
    assert "ふざけんな！" in html and "plea-body" in html
    assert db.session.scalar(db.select(db.func.count(Plea.id))) == 0


def test_normal_words_are_delivered_without_confirmation(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    speaker.post(f"/shrine/{visit.id}/plea", data={"body": "遅くて不安だった"})
    assert db.session.scalar(db.select(db.func.count(Plea.id))) == 1


def test_strong_screen_is_escaped(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    res = speaker.post(
        f"/shrine/{visit.id}/plea", data={"body": "ふざけんな<script>alert(1)</script>"}
    )
    html = res.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html


def test_extend_once_adds_one_turn_and_keeps_draft(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, listener = speaker_and_listener(visit, aoi, a, h)
    before = visit.turn_started_at
    speaker.post(f"/shrine/{visit.id}/extend")
    db.session.refresh(visit)
    assert visit.turn_extended
    assert visit.turn_started_at == before + timedelta(seconds=300)
    assert visit.remaining_seconds(300) > 300
    # 2回目は延ばせない
    speaker.post(f"/shrine/{visit.id}/extend")
    db.session.refresh(visit)
    assert visit.turn_started_at == before + timedelta(seconds=300)
    # 聴く側に、目立つ枠で知らせる
    page = listener.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "5分延長しました" in page
    assert "ことばを探しています" in page
    assert "waiting-note" in page


def test_extend_is_only_for_speaker(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    _, listener = speaker_and_listener(visit, aoi, a, h)
    before = visit.turn_started_at
    listener.post(f"/shrine/{visit.id}/extend")
    db.session.refresh(visit)
    assert not visit.turn_extended
    assert visit.turn_started_at == before


def test_extension_resets_when_turn_passes(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    speaker.post(f"/shrine/{visit.id}/extend")
    speaker.post(f"/shrine/{visit.id}/plea", data={"body": "遅くて不安だった"})
    db.session.refresh(visit)
    assert not visit.turn_extended


def test_extension_does_not_save_an_expired_turn(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    first = visit.current_speaker_id
    visit.turn_started_at = now() - timedelta(seconds=400)
    db.session.commit()
    speaker.post(f"/shrine/{visit.id}/extend")
    db.session.refresh(visit)
    assert visit.current_speaker_id != first
    assert not visit.turn_extended


def test_away_notice_is_shown(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    html = speaker.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "席を外しているようです" in html or "隣で聴いています" in html


def test_flame_screen_explains_its_meaning(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    html = speaker.post(
        f"/shrine/{visit.id}/plea", data={"body": "ふざけんな"}
    ).get_data(as_text=True)
    assert "気づいたしるし" in html
    assert "よい・悪いを決めるものではありません" in html


def test_reflect_button_and_waiting_notice_are_present(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    html = speaker.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "data-reflect" in html
    # 押したらすぐに出る、鏡の映像（鏡の中に「映しています…」）
    assert "data-mirror-waiting" in html and "mirror-stage" in html
    assert "映しています" in html
    assert speaker.get("/static/mirror.js").status_code == 200


def test_mirror_card_is_shown_after_reflect(aoi, hikaru, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    speaker.post(f"/shrine/{visit.id}/reflect", data={"body": "遅くて不安だった"})
    html = speaker.get(f"/shrine/{visit.id}").get_data(as_text=True)
    # 文字は、鏡の中（ガラスの面）に出る
    assert "mirror-glass" in html and "mirror-text" in html


def test_lamp_text_is_inside_the_book_and_keeps_text(aoi, hikaru, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    speaker.post(f"/shrine/{visit.id}/reflect", data={"body": "遅くて不安だった"})
    html = speaker.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "lamp-stage" in html and "lamp-pagetext" in html and "lamp-line" in html
    assert "灯：遅くて不安だった" in html


def test_reflect_button_is_the_main_call_to_action(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    html = speaker.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert 'class="reflect-cta"' in html
    assert "「女神の鏡」と、「ことばの灯」で確かめる" in html


def test_mirror_and_lamp_animations_keep_the_text(aoi, hikaru, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    speaker.post(f"/shrine/{visit.id}/reflect", data={"body": "遅くて不安だった"})
    html = speaker.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "mirror-fog" in html
    assert html.count("art-page") >= 5
    # 飾りがあっても、本文は消えない
    assert "鏡：遅くて不安だっ" in html and "灯：遅くて不安だった" in html


def test_mirror_and_lamp_illustrations_are_shown(aoi, hikaru, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, _ = speaker_and_listener(visit, aoi, a, h)
    speaker.post(f"/shrine/{visit.id}/reflect", data={"body": "遅くて不安だった"})
    html = speaker.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert 'class="art-mirror"' in html
    assert 'class="art-lamp"' in html
    assert "fit-box" in html


def test_delivered_words_are_shown_as_chat_bubbles_for_both(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, listener = speaker_and_listener(visit, aoi, a, h)
    speaker.post(f"/shrine/{visit.id}/plea", data={"body": "遅くて不安だった"})
    mine = speaker.get(f"/shrine/{visit.id}").get_data(as_text=True)
    theirs = listener.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert 'class="pleas bubbles"' in mine and 'class="pleas bubbles"' in theirs
    # 書いた本人には「あなた」、相手には名前で、同じ言葉が見える
    assert "遅くて不安だった" in mine and "遅くて不安だった" in theirs
    assert 'class="bubble-name">あなた' in mine
    assert 'class="bubble-name">あなた' not in theirs


def test_bubbles_do_not_leak_mirror_or_lamp(aoi, hikaru, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speaker, listener = speaker_and_listener(visit, aoi, a, h)
    speaker.post(f"/shrine/{visit.id}/reflect", data={"body": "遅くて不安だった"})
    speaker.post(f"/shrine/{visit.id}/plea", data={"body": "遅くて不安だった"})
    theirs = listener.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "鏡：" not in theirs and "灯：" not in theirs


def test_newest_bubble_is_on_top(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    first, second = speaker_and_listener(visit, aoi, a, h)
    first.post(f"/shrine/{visit.id}/plea", data={"body": "ひとつ目の言葉"})
    second.post(f"/shrine/{visit.id}/plea", data={"body": "ふたつ目の言葉"})
    for client in (first, second):
        html = client.get(f"/shrine/{visit.id}").get_data(as_text=True)
        # 新しい言葉（ふたつ目）が、先に出る
        assert html.index("ふたつ目の言葉") < html.index("ひとつ目の言葉")
