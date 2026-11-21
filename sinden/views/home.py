from flask import Blueprint, flash, jsonify, redirect, render_template, url_for
from flask_login import current_user, login_required

from sinden.extensions import db
from sinden.forms import InviteForm, JoinPairForm
from sinden.models import Letter, Pair, User, Visit, VisitStatus, new_invite_code
from sinden.services import plans
from sinden.services.safety import HELP_LINES

bp = Blueprint("home", __name__)


@bp.route("/manifest.webmanifest")
def manifest():
    """ホーム画面に追加するための情報（PWA）。Service Worker は使わない（古い画面が残らないように）"""
    res = jsonify(
        {
            "name": "Placaの祠",
            "short_name": "Placaの祠",
            "description": "関係を続けたいふたりのための、ひとりずつ話せる場所",
            "lang": "ja",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#12162e",
            "theme_color": "#12162e",
            "icons": [
                {
                    "src": url_for("static", filename="icons/icon-192.png"),
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": url_for("static", filename="icons/icon-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
        }
    )
    res.headers["Content-Type"] = "application/manifest+json"
    return res


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
        # 2人が同時に同じコードで入って3人にならないよう、ペアの行をロックしてから数える。
        # 人数もロック付きで読む（MySQL では、ロックなしだと古い内容が見えることがある）
        pair = db.session.scalar(
            db.select(Pair).filter_by(invite_code=code).with_for_update()
        )
        members = (
            db.session.scalars(
                db.select(User.id).filter_by(pair_id=pair.id).with_for_update()
            ).all()
            if pair is not None
            else []
        )
        if pair is None or len(members) >= 2:
            db.session.rollback()
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


@bp.route("/privacy")
def privacy():
    return render_template("home/privacy.html")


@bp.route("/terms")
def terms():
    return render_template("home/terms.html")


@bp.route("/about")
def about():
    return render_template("home/about.html")
