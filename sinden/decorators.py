from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user, login_required


def pair_required(view):
    """ログインしていて、ペアがそろっていれば通す。そろっていなければホームへ"""

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.pair is None or not current_user.pair.is_complete:
            flash("先にふたりのペアを作ってください")
            return redirect(url_for("home.index"))
        return view(*args, **kwargs)

    return wrapped


def premium_required(view):
    """ペアが有料プランなら通す。違えばプランの画面へ"""

    @wraps(view)
    @pair_required
    def wrapped(*args, **kwargs):
        if not current_user.is_premium:
            flash("この機能はプランで使えます")
            return redirect(url_for("billing.index"))
        return view(*args, **kwargs)

    return wrapped
