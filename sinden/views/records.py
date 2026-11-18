from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)
from flask_login import current_user

from sinden.decorators import pair_required
from sinden.extensions import db
from sinden.models import Visit, VisitStatus

bp = Blueprint("records", __name__, url_prefix="/records")


def kept_visits(pair_id: int) -> list[Visit]:
    return list(
        db.session.scalars(
            db.select(Visit)
            .where(
                Visit.pair_id == pair_id,
                Visit.status == VisitStatus.CLOSED,
                Visit.kept.is_(True),
            )
            .order_by(Visit.ended_at.desc(), Visit.id.desc())
        )
    )


@bp.route("/")
@pair_required
def index():
    visits = kept_visits(current_user.pair_id)
    limit = None if current_user.pair.is_premium else current_app.config["RECORDS_FREE"]
    shown = visits if limit is None else visits[:limit]
    return render_template(
        "records/index.html",
        visits=shown,
        hidden=len(visits) - len(shown),
    )


@bp.route("/<int:visit_id>")
@pair_required
def show(visit_id):
    visit = db.session.get(Visit, visit_id)
    if visit is None or not visit.kept:
        abort(404)
    if not visit.is_member(current_user):
        abort(403)
    if not current_user.pair.is_premium:
        free_ids = [
            v.id
            for v in kept_visits(current_user.pair_id)[
                : current_app.config["RECORDS_FREE"]
            ]
        ]
        if visit.id not in free_ids:
            flash("古い記録の振り返りは、どちらかがプランに入ると見られます")
            return redirect(url_for("billing.index"))
    return render_template("records/show.html", visit=visit)
