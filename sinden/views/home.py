from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from sinden.extensions import db
from sinden.forms import InviteForm, JoinPairForm
from sinden.models import Letter, Pair, Visit, VisitStatus, new_invite_code
from sinden.services import plans
from sinden.services.safety import HELP_LINES

bp = Blueprint("home", __name__)


def active_visit(pair: Pair | None) -> Visit | None:
    if pair is None:
        return None
    return db.session.scalar(
        db.select(Visit)
        .where(Visit.pair_id == pair.id, Visit.status.in_(VisitStatus.ACTIVE))
        .order_by(Visit.id.desc())
    )


def home_version(user) -> str:
    """ホームの表示が変わる出来事（相手の参加・誘い・取り消し）から作る値"""
    pair = user.pair
    if pair is None:
        return "none"
    partner = user.partner
    visit = active_visit(pair)
    return ":".join(
        str(v)
        for v in (
            pair.id,
            partner.id if partner else "-",
            visit.id if visit else "-",
            visit.status if visit else "-",
        )
    )


@bp.route("/home/state")
@login_required
def state():
    return {"version": home_version(current_user)}


@bp.route("/")
def index():
    if not current_user.is_authenticated:
        return render_template("home/landing.html")
    pair = current_user.pair
    unread = 0
    if pair is not None:
        unread = db.session.scalar(
            db.select(db.func.count(Letter.id)).where(
                Letter.recipient_id == current_user.id, Letter.read_at.is_(None)
            )
        )
    return render_template(
        "home/index.html",
        pair=pair,
        partner=current_user.partner,
        visit=active_visit(pair),
        invite_form=InviteForm(),
        join_form=JoinPairForm(),
        unread=unread,
        home_version=home_version(current_user),
        mirrors_left=plans.mirrors_left_this_month(current_user) if pair else None,
    )


@bp.route("/pair/create", methods=["POST"])
@login_required
def create_pair():
    if current_user.pair is not None:
        flash("すでにペアがあります")
        return redirect(url_for("home.index"))
    pair = Pair(invite_code=new_invite_code())
    db.session.add(pair)
    current_user.pair = pair
    db.session.commit()
    flash("招待コードを作りました。相手に伝えてください")
    return redirect(url_for("home.index"))


@bp.route("/pair/join", methods=["POST"])
@login_required
def join_pair():
    form = JoinPairForm()
    if current_user.pair is not None:
        flash("すでにペアがあります")
        return redirect(url_for("home.index"))
    if form.validate_on_submit():
        code = form.code.data.strip().upper()
        pair = db.session.scalar(db.select(Pair).filter_by(invite_code=code))
        if pair is None or pair.is_complete:
            flash("その招待コードは使えません")
            return redirect(url_for("home.index"))
        current_user.pair = pair
        db.session.commit()
        flash("ふたりのペアができました")
        return redirect(url_for("home.index"))
    flash("招待コードを入力してください")
    return redirect(url_for("home.index"))


@bp.route("/help")
def help_lines():
    return render_template("home/help.html", lines=HELP_LINES)


@bp.route("/about")
def about():
    return render_template("home/about.html")
