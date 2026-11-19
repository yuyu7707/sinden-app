from datetime import timedelta

from sinden.extensions import db
from sinden.models import MirrorUse, Plea, Visit, VisitStatus, now
from sinden.services.ai import AIError


def open_shrine(aoi, hikaru, login_as, theme="night"):
    """あおいが誘い、ひかるが応じ、ふたりとも掟に従うところまで進める"""
    a, h = login_as(aoi), login_as(hikaru)
    a.post("/shrine/invite", data={"theme": theme})
    visit = db.session.scalar(db.select(Visit))
    h.post(f"/shrine/{visit.id}/accept")
    a.post(f"/shrine/{visit.id}/agree")
    h.post(f"/shrine/{visit.id}/agree")
    db.session.refresh(visit)
    return visit, a, h


def speak(client, visit, body):
    """「女神に映す」→「自分の言葉で届ける」"""
    client.post(f"/shrine/{visit.id}/reflect", data={"body": body})
    return client.post(f"/shrine/{visit.id}/plea", data={"body": body})


def test_invite_accept_and_agree(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    assert visit.status == VisitStatus.PLEADING
    # 誘われた側から訴える
    assert visit.current_speaker_id == hikaru.id
    assert "あなたが訴える番です" in h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "いまは聴く番です" in a.get(f"/shrine/{visit.id}").get_data(as_text=True)


def test_番の数が画面に出て_届けるたびに変わる(aoi, hikaru, login_as):
    # 入力中の下書きは番ごとに分けて保存するため（前の番の文章が残らないように）
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    assert 'data-turn="0"' in h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    speak(h, visit, "帰りが遅くて不安だった")
    assert 'data-turn="1"' in a.get(f"/shrine/{visit.id}").get_data(as_text=True)


def test_JSとCSSのURLには更新時刻が付く(aoi, hikaru, login_as):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    text = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "/static/shrine.js?v=" in text
    assert "/static/sinden.css?v=" in text


def test_shrine_opens_only_when_partner_accepts(aoi, hikaru, login_as):
    a = login_as(aoi)
    a.post("/shrine/invite", data={"theme": "night"})
    visit = db.session.scalar(db.select(Visit))
    # 誘った本人は応じられない
    a.post(f"/shrine/{visit.id}/accept")
    db.session.refresh(visit)
    assert visit.status == VisitStatus.INVITED


def test_listener_cannot_plea(aoi, hikaru, login_as):
    visit, a, _h = open_shrine(aoi, hikaru, login_as)
    a.post(f"/shrine/{visit.id}/plea", data={"body": "割り込みたい"})
    assert db.session.scalar(db.select(db.func.count(Plea.id))) == 0
    db.session.refresh(visit)
    assert visit.current_speaker_id == hikaru.id


def test_plea_passes_turn_and_mirror_only_for_author(aoi, hikaru, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    speak(h, visit, "帰りが遅くて不安だった")
    db.session.refresh(visit)
    assert visit.current_speaker_id == aoi.id
    plea = db.session.scalar(db.select(Plea))
    assert plea.mirror == "鏡：帰りが遅くて不安だっ"
    assert fake_ai.calls == ["帰りが遅くて不安だった"]

    author_page = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    partner_page = a.get(f"/shrine/{visit.id}").get_data(as_text=True)
    # 生の言葉は相手にも届く。鏡は本人だけ
    assert "帰りが遅くて不安だった" in partner_page
    assert "鏡：" in author_page
    assert "鏡：" not in partner_page


def test_empty_plea_is_not_delivered_and_keeps_turn(aoi, hikaru, login_as):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    res = h.post(f"/shrine/{visit.id}/plea", data={"body": "  "}, follow_redirects=True)
    db.session.refresh(visit)
    # 何も書かずに押しても、番は替わらない
    assert visit.current_speaker_id == hikaru.id
    assert visit.pleas == []
    assert "届ける言葉を書いてください" in res.get_data(as_text=True)


def test_plea_too_long(aoi, hikaru, login_as, app):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/plea", data={"body": "あ" * 3001})
    db.session.refresh(visit)
    assert visit.pleas == []
    assert visit.current_speaker_id == hikaru.id


def use_mirrors(user, count):
    for _ in range(count):
        db.session.add(MirrorUse(user_id=user.id))
    db.session.commit()


def test_free_mirror_limit(aoi, hikaru, login_as, fake_ai):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    use_mirrors(hikaru, 3)
    speak(h, visit, "聞いてほしい")
    plea = db.session.scalar(db.select(Plea))
    assert plea.mirror is None
    assert "使い切りました" in plea.mirror_note
    assert fake_ai.calls == []


def test_free_mirror_limit_is_per_person(aoi, hikaru, login_as, fake_ai):
    # 相手が使い切っていても、自分の分は使える
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    use_mirrors(aoi, 3)
    speak(h, visit, "聞いてほしい")
    assert db.session.scalar(db.select(Plea)).mirror is not None


def test_premium_mirror_limit(aoi, hikaru, login_as, fake_ai, premium):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    use_mirrors(hikaru, 29)
    speak(h, visit, "29回使ったあと")
    assert db.session.scalar(db.select(Plea)).mirror is not None
    # 30回目まで使ったので、次は上限（番を戻してもう一度訴える）
    db.session.refresh(visit)
    visit.current_speaker_id = hikaru.id
    db.session.commit()
    speak(h, visit, "31回目")
    last = db.session.scalars(db.select(Plea).order_by(Plea.id.desc())).first()
    assert last.mirror is None
    assert "上限に達しました" in last.mirror_note


def test_ai_error_is_shown_as_note(aoi, hikaru, login_as, fake_ai):
    fake_ai.error = AIError("女神の鏡に接続できませんでした。")
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    speak(h, visit, "聞いてほしい")
    plea = db.session.scalar(db.select(Plea))
    assert plea.mirror_note == "女神の鏡に接続できませんでした。"
    db.session.refresh(visit)
    assert visit.current_speaker_id == aoi.id


def test_danger_words_show_help_lines(aoi, hikaru, login_as):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    speak(h, visit, "殴られるのが怖い")
    assert db.session.scalar(db.select(Plea)).danger
    page = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "#8008" in page


def test_other_pair_cannot_see_shrine(aoi, hikaru, login_as, other_pair_user):
    visit, _a, _h = open_shrine(aoi, hikaru, login_as)
    stranger = login_as(other_pair_user)
    assert stranger.get(f"/shrine/{visit.id}").status_code == 403
    assert stranger.get(f"/shrine/{visit.id}/state").status_code == 403
    res = stranger.post(f"/shrine/{visit.id}/plea", data={"body": "x"})
    assert res.status_code == 403


def test_state_shows_partner_presence(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.get(f"/shrine/{visit.id}/state")
    data = a.get(f"/shrine/{visit.id}/state").get_json()
    assert data["partner_present"] is True
    assert data["version"] == visit.version()


def test_turn_passes_when_speaker_is_away(aoi, hikaru, login_as):
    visit, a, _h = open_shrine(aoi, hikaru, login_as)
    visit.turn_started_at = now() - timedelta(seconds=300 + 61)
    db.session.commit()
    a.get(f"/shrine/{visit.id}/state")
    db.session.refresh(visit)
    assert visit.current_speaker_id == aoi.id


def test_leave_and_keep_record(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/plea", data={"body": "ごめんね"})
    a.post(f"/shrine/{visit.id}/leave")
    db.session.refresh(visit)
    assert visit.status == VisitStatus.PLEADING
    h.post(f"/shrine/{visit.id}/leave")
    db.session.refresh(visit)
    assert visit.status == VisitStatus.RECONCILED

    a.post(f"/shrine/{visit.id}/keep", data={"keep": "yes"})
    h.post(f"/shrine/{visit.id}/keep", data={"keep": "yes"})
    db.session.refresh(visit)
    assert visit.status == VisitStatus.CLOSED
    assert visit.kept
    assert "ごめんね" in a.get(f"/records/{visit.id}").get_data(as_text=True)


def test_leave_can_be_withdrawn(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    a.post(f"/shrine/{visit.id}/leave")
    a.post(f"/shrine/{visit.id}/leave", data={"stay": "1"})
    h.post(f"/shrine/{visit.id}/leave")
    db.session.refresh(visit)
    assert visit.status == VisitStatus.PLEADING


def test_one_no_deletes_pleas(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/plea", data={"body": "消してほしい話"})
    a.post(f"/shrine/{visit.id}/leave")
    h.post(f"/shrine/{visit.id}/leave")
    a.post(f"/shrine/{visit.id}/keep", data={"keep": "yes"})
    h.post(f"/shrine/{visit.id}/keep", data={"keep": "no"})
    db.session.refresh(visit)
    assert visit.status == VisitStatus.CLOSED
    assert not visit.kept
    assert db.session.scalar(db.select(db.func.count(Plea.id))) == 0
    assert a.get(f"/records/{visit.id}").status_code == 404


def test_morning_theme_requires_premium(aoi, hikaru, login_as):
    a = login_as(aoi)
    res = a.post("/shrine/invite", data={"theme": "morning"})
    assert res.headers["Location"].endswith("/billing")
    assert db.session.scalar(db.select(Visit)) is None


def test_morning_theme_with_premium(aoi, hikaru, login_as, premium):
    visit, a, _h = open_shrine(aoi, hikaru, login_as, theme="morning")
    assert visit.theme == "morning"
    assert "ローマの朝" in a.get(f"/shrine/{visit.id}").get_data(as_text=True)


def test_cancel_invitation(aoi, hikaru, login_as):
    a, h = login_as(aoi), login_as(hikaru)
    a.post("/shrine/invite", data={"theme": "night"})
    visit = db.session.scalar(db.select(Visit))
    h.post(f"/shrine/{visit.id}/cancel")
    db.session.refresh(visit)
    assert visit.status == VisitStatus.CANCELLED


def test_speaker_light_is_bright(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    # ひかるの番：ひかるの画面では自分が「話す」、あおいの画面では相手が「話す」
    speaker_page = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    listener_page = a.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert 'class="light on speaking" title="あなた"' in speaker_page
    assert 'class="light on listening" title="あなた"' in listener_page
    assert 'speaking" title="ひかる"' in listener_page


# ---- 女神に映す・ことばの灯 ----


def test_reflect_is_only_for_speaker(aoi, hikaru, login_as, fake_ai):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "わかってほしい"})
    db.session.refresh(visit)
    speaker_page = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    listener_page = a.get(f"/shrine/{visit.id}").get_data(as_text=True)
    # 鏡と灯は話し手にだけ見え、まだ相手には何も届かない
    assert "鏡：わかってほしい" in speaker_page
    assert "灯：わかってほしい" in speaker_page
    assert "わかってほしい" not in listener_page
    assert visit.pleas == []
    assert visit.current_speaker_id == hikaru.id
    # 聴く側は映せない
    a.post(f"/shrine/{visit.id}/reflect", data={"body": "割り込み"})
    assert fake_ai.calls == ["わかってほしい"]


def test_reflect_does_not_change_version(aoi, hikaru, login_as):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    before = visit.version()
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "わかってほしい"})
    db.session.refresh(visit)
    assert visit.version() == before  # 相手の画面は作り直されない


def test_reflect_only_once_per_turn(aoi, hikaru, login_as, fake_ai):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "一回目"})
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "二回目"})
    assert fake_ai.calls == ["一回目"]


def test_send_with_lamp(aoi, hikaru, login_as):
    visit, a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "いつも遅い！"})
    # フォームの本文は使わず、サーバーに保存した灯を届ける
    h.post(f"/shrine/{visit.id}/plea", data={"body": "書き換えた文", "source": "lamp"})
    plea = db.session.scalar(db.select(Plea))
    assert plea.body == "灯：いつも遅い！"
    assert plea.source == "lamp"
    assert plea.mirror == "鏡：いつも遅い！"
    db.session.refresh(visit)
    assert visit.draft_text is None
    assert "灯：いつも遅い！" in a.get(f"/shrine/{visit.id}").get_data(as_text=True)


def test_send_edited_words(aoi, hikaru, login_as):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "いつも遅い！"})
    h.post(f"/shrine/{visit.id}/plea", data={"body": "遅いと心配になる"})
    plea = db.session.scalar(db.select(Plea))
    assert plea.body == "遅いと心配になる"
    assert plea.source == "edited"


def test_send_without_reflect_uses_no_ai(aoi, hikaru, login_as, fake_ai):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/plea", data={"body": "このまま届ける"})
    plea = db.session.scalar(db.select(Plea))
    assert plea.source == "own"
    assert plea.mirror is None
    assert fake_ai.calls == []


def test_no_lamp_when_danger(aoi, hikaru, login_as, fake_ai):
    fake_ai.danger = True
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "怖い"})
    db.session.refresh(visit)
    assert visit.draft_lamp is None
    page = h.get(f"/shrine/{visit.id}").get_data(as_text=True)
    assert "#8008" in page
    assert "ことばの灯の言い方で届ける" not in page
    # 灯がないので、source=lamp を送っても自分の言葉が届く
    h.post(f"/shrine/{visit.id}/plea", data={"body": "怖い", "source": "lamp"})
    assert db.session.scalar(db.select(Plea)).body == "怖い"


def test_no_lamp_when_danger_words(aoi, hikaru, login_as):
    visit, _a, h = open_shrine(aoi, hikaru, login_as)
    h.post(f"/shrine/{visit.id}/reflect", data={"body": "殴られるのが怖い"})
    db.session.refresh(visit)
    assert visit.draft_danger
    assert visit.draft_lamp is None
