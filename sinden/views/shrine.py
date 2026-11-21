"""祠：誘う → 応じる → 掟に従う → 一人ずつ訴える → ふたりで祠を出る → 記録を選ぶ"""

from datetime import timedelta

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy.orm.attributes import flag_modified

from sinden.content import REACTIONS
from sinden.decorators import pair_required
from sinden.extensions import db
from sinden.forms import InviteForm, PleaForm
from sinden.models import Pair, Plea, Theme, Visit, VisitStatus, now
from sinden.services import plans
from sinden.services.ai import AIError
from sinden.services.safety import HELP_LINES, has_danger_words
from sinden.views.home import active_visit, expire_stale_invite

bp = Blueprint("shrine", __name__, url_prefix="/shrine")

# 話し手が画面を閉じてしまったとき、持ち時間を過ぎてこの秒数たったら番を渡す
AWAY_GRACE_SECONDS = 60
# 最後の更新からこの秒数以内なら「祠にいる（灯りがともる）」とみなす
PRESENCE_SECONDS = 10


def get_visit(visit_id: int) -> Visit:
    visit = db.session.get(Visit, visit_id)
    if visit is None:
        abort(404)
    if not visit.is_member(current_user):
        abort(403)
    return visit


def get_locked_visit(visit_id: int) -> Visit:
    """祠の状態を変える操作（応じる・取り消す・掟に従う・届ける・出る・残す・中断する）用。
    行をロックして、最新の内容を読み直す。
    ロックしないと、2人が同時に押したとき互いの選択が見えず、祠が先へ進まない。
    （鏡を作る reflect だけは、AI を待つあいだロックしないので、条件付きの UPDATE で守る）"""
    visit = get_visit(visit_id)
    db.session.refresh(visit, with_for_update=True)
    return visit


def back(visit: Visit):
    return redirect(url_for("shrine.show", visit_id=visit.id))


def pass_turn(visit: Visit) -> None:
    # 関連（current_speaker）は読み込みの状態で古い値が残ることがあるので、ID だけで切り替える
    visit.current_speaker_id = (
        visit.invitee_id
        if visit.current_speaker_id == visit.inviter_id
        else visit.inviter_id
    )
    visit.turn_started_at = now()
    clear_draft(visit)


DRAFT_FIELDS = (
    "draft_text",
    "draft_mirror",
    "draft_lamp",
    "draft_note",
    "draft_danger",
)


def close_without_record(visit: Visit) -> None:
    """記録を残さずに祠を終える。訴えと下書きを消す（中断と「残さない」で共通）"""
    visit.status = VisitStatus.CLOSED
    visit.kept = False
    visit.ended_at = now()
    visit.current_speaker_id = None
    visit.turn_started_at = None
    clear_draft(visit)
    visit.pleas.clear()


def clear_draft(visit: Visit) -> None:
    visit.draft_text = None
    visit.draft_mirror = None
    visit.draft_lamp = None
    visit.draft_note = None
    visit.draft_danger = False
    # 読んだときに空でも、そのあと別の処理（鏡づくり）が書いたかもしれないので、必ず書き込む
    for name in DRAFT_FIELDS:
        flag_modified(visit, name)


def expire_turn_if_away(visit: Visit) -> None:
    """話し手が持ち時間を大きく過ぎても訴えないときは、番を相手に渡す"""

    def expired() -> bool:
        if visit.status != VisitStatus.PLEADING or visit.turn_started_at is None:
            return False
        limit = current_app.config["TURN_SECONDS"] + AWAY_GRACE_SECONDS
        return now() - visit.turn_started_at > timedelta(seconds=limit)

    if expired():
        # ふたりの画面が同時に確かめても、番が2回替わらないよう、ロックして読み直す
        db.session.refresh(visit, with_for_update=True)
        if expired():
            pass_turn(visit)


def is_present(user) -> bool:
    return user.last_seen is not None and now() - user.last_seen < timedelta(
        seconds=PRESENCE_SECONDS
    )


@bp.route("/invite", methods=["POST"])
@pair_required
def invite():
    form = InviteForm()
    if not form.validate_on_submit():
        abort(400)
    # 2人が同時に誘っても祠が2つできないよう、ペアの行をロックしてから調べる
    db.session.scalar(
        db.select(Pair).filter_by(id=current_user.pair_id).with_for_update()
    )
    visit = active_visit(current_user.pair)
    if visit is not None:
        db.session.rollback()
        return back(visit)
    theme = Theme.for_time(now())
    visit = Visit(
        pair=current_user.pair,
        inviter=current_user,
        invitee=current_user.partner,
        theme=theme,
    )
    db.session.add(visit)
    db.session.commit()
    return back(visit)


@bp.route("/<int:visit_id>")
@pair_required
def show(visit_id):
    visit = get_visit(visit_id)
    if visit.status == VisitStatus.CANCELLED:
        flash("この誘いは取り消されました")
        return redirect(url_for("home.index"))
    if visit.status == VisitStatus.CLOSED:
        if visit.kept:
            return redirect(url_for("records.show", visit_id=visit.id))
        flash("祠を後にしました。今回の訴えは残していません")
        return redirect(url_for("home.index"))
    if expire_stale_invite(visit):
        flash("この誘いは、時間がたったので取り消されました")
        return redirect(url_for("home.index"))
    expire_turn_if_away(visit)
    current_user.last_seen = now()
    db.session.commit()

    partner = visit.partner(current_user)
    my_last = None
    for plea in visit.pleas:
        if plea.user_id == current_user.id:
            my_last = plea
    return render_template(
        f"shrine/{visit.status}.html",
        visit=visit,
        partner=partner,
        me_role=visit.role(current_user),
        is_speaker=visit.current_speaker_id == current_user.id,
        remaining=visit.remaining_seconds(current_app.config["TURN_SECONDS"]),
        turn_seconds=current_app.config["TURN_SECONDS"],
        max_chars=current_app.config["PLEA_MAX_CHARS"],
        partner_present=is_present(partner),
        my_last=my_last,
        form=PleaForm(),
        reactions=REACTIONS,
        help_lines=HELP_LINES,
        # 祠に入ったとき（掟の確認）だけ、近づいていく演出を見せる
        intro=visit.status == VisitStatus.RULES,
        # 話し手が「ことばを確かめる」を使えない理由（回数の上限など）。使えるなら None
        reflect_block=(
            plans.mirror_block_reason(visit, current_user)
            if visit.status == VisitStatus.PLEADING
            and visit.current_speaker_id == current_user.id
            and visit.draft_text is None
            else None
        ),
    )


@bp.route("/<int:visit_id>/state")
@pair_required
def state(visit_id):
    """数秒ごとにブラウザから呼ばれる。相手の灯りと、画面を作り直すかを返す"""
    visit = get_visit(visit_id)
    expire_turn_if_away(visit)
    current_user.last_seen = now()
    db.session.commit()
    partner = visit.partner(current_user)
    return jsonify(
        version=visit.version(),
        partner_present=is_present(partner),
        remaining=visit.remaining_seconds(current_app.config["TURN_SECONDS"]),
    )


@bp.route("/<int:visit_id>/accept", methods=["POST"])
@pair_required
def accept(visit_id):
    visit = get_locked_visit(visit_id)
    if expire_stale_invite(visit):
        flash(
            "この誘いは、時間がたったので取り消されました。もう一度誘ってもらってください"
        )
        return redirect(url_for("home.index"))
    if visit.status == VisitStatus.INVITED and visit.invitee_id == current_user.id:
        visit.status = VisitStatus.RULES
        db.session.commit()
    return back(visit)


@bp.route("/<int:visit_id>/cancel", methods=["POST"])
@pair_required
def cancel(visit_id):
    visit = get_locked_visit(visit_id)
    if visit.status == VisitStatus.INVITED:
        visit.status = VisitStatus.CANCELLED
        visit.ended_at = now()
        db.session.commit()
        flash("誘いを見送りました")
    return redirect(url_for("home.index"))


@bp.route("/<int:visit_id>/agree", methods=["POST"])
@pair_required
def agree(visit_id):
    # 2人が同時に押しても、互いの「従った」が見えるように、ロックして読み直す
    visit = get_locked_visit(visit_id)
    if visit.status == VisitStatus.RULES:
        visit.set_flag("agreed", current_user, True)
        if visit.both("agreed"):
            visit.status = VisitStatus.PLEADING
            # 誘われた側から訴える（誘った側は、先に一歩を踏み出したので）
            visit.current_speaker_id = visit.invitee_id
            visit.turn_started_at = now()
        db.session.commit()
    return back(visit)


def speaker_body_or_none(visit: Visit):
    """話し手の送ってきた訴えを確かめて返す。だめなら (None, 応答)"""
    if visit.status != VisitStatus.PLEADING:
        return None, back(visit)
    if visit.current_speaker_id != current_user.id:
        flash("いまは聴く番です")
        return None, back(visit)
    form = PleaForm()
    if not form.validate_on_submit():
        abort(400)
    body = (form.body.data or "").strip()
    if len(body) > current_app.config["PLEA_MAX_CHARS"]:
        flash(f"訴えは{current_app.config['PLEA_MAX_CHARS']:,}文字までです")
        return None, back(visit)
    return body, None


@bp.route("/<int:visit_id>/reflect", methods=["POST"])
@pair_required
def reflect(visit_id):
    """「ことばを確かめる」：まだ相手には届けない。鏡と、ことばの灯を、話し手にだけ見せる"""
    visit = get_visit(visit_id)
    body, error = speaker_body_or_none(visit)
    if error:
        return error
    if not body:
        flash("訴えを書くか、声で話してから確かめてください")
        return back(visit)
    # 1回の番で映せるのは1回まで（AI の回数を守るため）。
    # 二重に押されても AI を2回呼ばないよう、「自分の番で、下書きがまだない」ときだけ下書きを置けた方が進む
    turn_started_at = visit.turn_started_at
    this_turn = (
        Visit.id == visit.id,
        Visit.status == VisitStatus.PLEADING,
        Visit.current_speaker_id == current_user.id,
        Visit.turn_started_at == turn_started_at,
    )
    claimed = db.session.execute(
        db.update(Visit)
        .where(*this_turn, Visit.draft_text.is_(None))
        .values(draft_text=body)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.session.rollback()
        return back(visit)
    db.session.commit()

    # AI を待つあいだ（最長1分ほど）は、行をロックしない
    draft = {
        "draft_mirror": None,
        "draft_lamp": None,
        "draft_danger": has_danger_words(body),
        "draft_note": plans.mirror_block_reason(visit, current_user),
    }
    if draft["draft_note"] is None:
        try:
            result = current_app.extensions["ai"].reflect(body)
            draft["draft_mirror"] = result.mirror
            draft["draft_danger"] = draft["draft_danger"] or result.danger
            # 危険の気配があるときは、ことばの灯を出さない
            draft["draft_lamp"] = (
                None if draft["draft_danger"] else (result.lamp or None)
            )
            # AI を呼んだので、結果を使えなくても回数は数える
            plans.record_mirror_use(visit, current_user)
        except AIError as e:
            draft["draft_note"] = str(e)
    # 待つあいだに番が替わっていたら（「このまま届ける」や持ち時間切れ）、結果は捨てる。
    # 条件なしで書くと、話し手の鏡・灯・危険の判定が、相手の番の下書きに入ってしまう
    db.session.execute(
        db.update(Visit)
        .where(*this_turn, Visit.draft_text == body)
        .values(**draft)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return back(visit)


@bp.route("/<int:visit_id>/plea", methods=["POST"])
@pair_required
def plea(visit_id):
    """相手に届ける。source=lamp なら、ことばの灯の言い方を届ける"""
    # 行をロックして最新を読む。二度押しの2回目は、番が替わったあとに読むので届かない
    visit = get_locked_visit(visit_id)
    body, error = speaker_body_or_none(visit)
    if error:
        db.session.rollback()
        return error

    # 鏡・灯は、この番の下書きがあるときだけ使う
    has_draft = visit.draft_text is not None
    use_lamp = has_draft and request.form.get("source") == "lamp" and visit.draft_lamp
    if use_lamp:
        # 灯の文章はフォームから受け取らず、サーバーに保存した案を使う
        body = visit.draft_lamp
        source = "lamp"
    elif not body:
        # 何も書かずに押したときに、黙って番が移らないようにする
        db.session.rollback()
        flash("届ける言葉を書いてください")
        return back(visit)
    elif has_draft:
        source = "own" if body == visit.draft_text else "edited"
    else:
        source = "own"

    db.session.add(
        Plea(
            visit=visit,
            user=current_user,
            seq=len(visit.pleas) + 1,
            body=body,
            mirror=visit.draft_mirror if has_draft else None,
            mirror_note=visit.draft_note if has_draft else None,
            danger=(has_draft and visit.draft_danger) or has_danger_words(body),
            source=source,
        )
    )
    pass_turn(visit)
    db.session.commit()
    return back(visit)


@bp.route("/<int:visit_id>/react", methods=["POST"])
@pair_required
def react(visit_id):
    """言葉にならないときの、決まったリアクション。AI は使わず、鏡の回数にも数えない"""
    visit = get_locked_visit(visit_id)
    if visit.status != VisitStatus.PLEADING:
        db.session.rollback()
        return back(visit)
    if visit.current_speaker_id != current_user.id:
        db.session.rollback()
        flash("いまは聴く番です")
        return back(visit)
    form = PleaForm()
    if not form.validate_on_submit():
        abort(400)
    # ことばは、フォームから受け取らず、サーバーの決まりから選ぶ
    phrase = REACTIONS.get(request.form.get("key", ""))
    if phrase is None:
        abort(400)
    db.session.add(
        Plea(
            visit=visit,
            user=current_user,
            seq=len(visit.pleas) + 1,
            body=phrase,
            source="reaction",
        )
    )
    pass_turn(visit)
    db.session.commit()
    return back(visit)


@bp.route("/<int:visit_id>/leave", methods=["POST"])
@pair_required
def leave(visit_id):
    visit = get_locked_visit(visit_id)
    if visit.status == VisitStatus.PLEADING:
        visit.set_flag("leave", current_user, request.form.get("stay") != "1")
        if visit.both("leave"):
            visit.status = VisitStatus.RECONCILED
            visit.current_speaker_id = None
            visit.turn_started_at = None
            clear_draft(visit)
        db.session.commit()
    return back(visit)


@bp.route("/<int:visit_id>/keep", methods=["POST"])
@pair_required
def keep(visit_id):
    visit = get_locked_visit(visit_id)
    if visit.status != VisitStatus.RECONCILED:
        return back(visit)
    choice = request.form.get("keep")
    if choice not in ("yes", "no"):
        abort(400)
    if choice == "no":
        # 「残さない」は、相手の返事を待たずに、その場で訴えを消して終える
        visit.set_flag("keep", current_user, False)
        close_without_record(visit)
    else:
        visit.set_flag("keep", current_user, True)
        if visit.both("keep"):
            visit.status = VisitStatus.CLOSED
            visit.ended_at = now()
            visit.kept = True
    db.session.commit()
    return back(visit)


@bp.route("/<int:visit_id>/stop", methods=["POST"])
@pair_required
def stop(visit_id):
    """祠を中断する。ひとりで終えられる（相手の同意はいらない）。訴えは残さない

    危険を感じたときに、相手に理由を伝えずに祠を終えられるようにするため。
    相手には「祠を後にしました。今回の訴えは残していません」とだけ出る（show の closed）。
    """
    visit = get_locked_visit(visit_id)
    if visit.status not in (VisitStatus.RULES, VisitStatus.PLEADING):
        db.session.rollback()
        return back(visit)
    close_without_record(visit)
    db.session.commit()
    flash("祠を中断しました。今回の訴えは残していません")
    return redirect(url_for("home.index"))
