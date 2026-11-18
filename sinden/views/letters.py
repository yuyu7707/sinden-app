from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user

from sinden.decorators import pair_required, premium_required
from sinden.extensions import db
from sinden.forms import LetterForm
from sinden.models import Letter, now

bp = Blueprint("letters", __name__, url_prefix="/letters")


@bp.route("/")
@pair_required
def index():
    received = db.session.scalars(
        db.select(Letter)
        .where(Letter.recipient_id == current_user.id)
        .order_by(Letter.id.desc())
    )
    sent = db.session.scalars(
        db.select(Letter)
        .where(Letter.sender_id == current_user.id)
        .order_by(Letter.id.desc())
    )
    return render_template(
        "letters/index.html", received=list(received), sent=list(sent)
    )


@bp.route("/new", methods=["GET", "POST"])
@premium_required
def new():
    form = LetterForm()
    if form.validate_on_submit():
        letter = Letter(
            pair_id=current_user.pair_id,
            sender=current_user,
            recipient=current_user.partner,
            title=form.title.data.strip(),
            body=form.body.data.strip(),
        )
        db.session.add(letter)
        db.session.commit()
        flash(f"{current_user.partner.name}さんに手紙を届けました")
        return redirect(url_for("letters.show", letter_id=letter.id))
    status = 422 if form.is_submitted() else 200
    return render_template("letters/new.html", form=form), status


@bp.route("/<int:letter_id>")
@pair_required
def show(letter_id):
    letter = db.session.get(Letter, letter_id)
    if letter is None:
        abort(404)
    if current_user.id not in (letter.sender_id, letter.recipient_id):
        abort(403)
    if letter.recipient_id == current_user.id and letter.read_at is None:
        letter.read_at = now()
        db.session.commit()
    return render_template("letters/show.html", letter=letter)
