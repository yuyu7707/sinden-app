from flask import Blueprint, abort, render_template
from flask_login import current_user

from sinden.content import ARTICLES, find_article

bp = Blueprint("learn", __name__, url_prefix="/learn")


def can_read(article: dict) -> bool:
    return article["free"] or (
        current_user.is_authenticated and current_user.is_premium
    )


@bp.route("/")
def index():
    return render_template("learn/index.html", articles=ARTICLES, can_read=can_read)


@bp.route("/<slug>")
def show(slug):
    article = find_article(slug)
    if article is None:
        abort(404)
    return render_template(
        "learn/show.html", article=article, readable=can_read(article)
    )
