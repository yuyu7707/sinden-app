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

from sinden.decorators import pair_required
from sinden.extensions import db
from sinden.forms import InviteForm, PleaForm
from sinden.models import Plea, Theme, Visit, VisitStatus, now
from sinden.services import plans
from sinden.services.ai import AIError
from sinden.services.safety import HELP_LINES, has_danger_words
from sinden.views.home import active_visit

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
    """ふたりが同時に押す操作（終える・残す）用。行をロックして、最新の内容を読み直す。
    ロックしないと、2人が同時に押したとき互いの選択が見えず、祠が先へ進まない"""
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


def clear_draft(visit: Visit) -> None:
    visit.draft_text = None
    visit.draft_mirror = None
    visit.draft_lamp = None
    visit.draft_note = None
    visit.draft_danger = False


def expire_turn_if_away(visit: Visit) -> None:
    """話し手が持ち時間を大きく過ぎても訴えないときは、番を相手に渡す"""
    if visit.status != VisitStatus.PLEADING or visit.turn_started_at is None:
        return
    limit = current_app.config["TURN_SECONDS"] + AWAY_GRACE_SECONDS
    if now() - visit.turn_started_at > timedelta(seconds=limit):
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
    visit = active_visit(current_user.pair)
    if visit is not None:
        return back(visit)
    theme = form.theme.data
    if theme == Theme.MORNING and not current_user.pair.is_premium:
        flash("ローマの朝の祠は、どちらかがプランに入ると選べます")
        return redirect(url_for("billing.index"))
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
    visit = get_visit(visit_id)
    if visit.status == VisitStatus.INVITED and visit.invitee_id == current_user.id:
        visit.status = VisitStatus.RULES
        db.session.commit()
    return back(visit)


@bp.route("/<int:visit_id>/cancel", methods=["POST"])
@pair_required
def cancel(visit_id):
    visit = get_visit(visit_id)
    if visit.status == VisitStatus.INVITED:
        visit.status = VisitStatus.CANCELLED
        visit.ended_at = now()
        db.session.commit()
        flash("誘いを見送りました")
    return redirect(url_for("home.index"))


@bp.route("/<int:visit_id>/agree", methods=["POST"])
@pair_required
def agree(visit_id):
    visit = get_visit(visit_id)
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
    # 二重に押されても AI を2回呼ばないよう、「下書きがまだない」ときだけ下書きを置けた方が進む
    claimed = db.session.execute(
        db.update(Visit)
        .where(Visit.id == visit.id, Visit.draft_text.is_(None))
        .values(draft_text=body)
    )
    if claimed.rowcount != 1:
        db.session.rollback()
        return back(visit)
    db.session.commit()

    visit.draft_mirror = None
    visit.draft_lamp = None
    visit.draft_danger = has_danger_words(body)
    visit.draft_note = plans.mirror_block_reason(visit, current_user)
    if visit.draft_note is None:
        try:
            result = current_app.extensions["ai"].reflect(body)
            visit.draft_mirror = result.mirror
            visit.draft_danger = visit.draft_danger or result.danger
            # 危険の気配があるときは、ことばの灯を出さない
            visit.draft_lamp = None if visit.draft_danger else (result.lamp or None)
            plans.record_mirror_use(visit, current_user)
        except AIError as e:
            visit.draft_note = str(e)
    db.session.commit()
    return back(visit)


@bp.route("/<int:visit_id>/plea", methods=["POST"])
@pair_required
def plea(visit_id):
    """相手に届ける。source=lamp なら、ことばの灯の言い方を届ける"""
    visit = get_visit(visit_id)
    body, error = speaker_body_or_none(visit)
    if error:
        return error

    use_lamp = request.form.get("source") == "lamp" and visit.draft_lamp
    if use_lamp:
        # 灯の文章はフォームから受け取らず、サーバーに保存した案を使う
        body = visit.draft_lamp
        source = "lamp"
    elif visit.draft_text is not None:
        source = "own" if body == visit.draft_text else "edited"
    else:
        source = "own"

    if body:
        db.session.add(
            Plea(
                visit=visit,
                user=current_user,
                seq=len(visit.pleas) + 1,
                body=body,
                mirror=visit.draft_mirror,
                mirror_note=visit.draft_note,
                danger=visit.draft_danger or has_danger_words(body),
                source=source,
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
    visit.set_flag("keep", current_user, choice == "yes")
    if visit.inviter_keep is not None and visit.invitee_keep is not None:
        visit.status = VisitStatus.CLOSED
        visit.ended_at = now()
        visit.kept = visit.both("keep")
        if not visit.kept:
            # どちらかが「残さない」なら、訴えはすべて消す
            visit.pleas.clear()
    db.session.commit()
    return back(visit)
