from flask import Blueprint, abort, render_template
from flask_login import current_user

from sinden.content import ARTICLES, find_article

bp = Blueprint("learn", __name__, url_prefix="/learn")

ROMAN = [
    "I",
    "II",
    "III",
    "IV",
    "V",
    "VI",
    "VII",
    "VIII",
    "IX",
    "X",
    "XI",
    "XII",
    "XIII",
    "XIV",
    "XV",
]


@bp.app_template_filter("roman")
def roman(number: int) -> str:
    """1 → I。学びの記事の番号を、ローマの書庫らしくローマ数字で見せる"""
    return ROMAN[number - 1] if 1 <= number <= len(ROMAN) else str(number)


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
        "learn/show.html",
        article=article,
        number=ARTICLES.index(article) + 1,
        readable=can_read(article),
    )
