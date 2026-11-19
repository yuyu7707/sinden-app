from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from sinden.extensions import db, limiter, login_manager
from sinden.forms import LoginForm, RegisterForm, WithdrawForm
from sinden.models import Letter, MirrorUse, Plea, Purchase, User, Visit

bp = Blueprint("auth", __name__)

# 照合の時間をそろえるための、どのパスワードとも合わない値
DUMMY_HASH = generate_password_hash("placa-no-hokora-dummy")


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


def safe_next(target: str | None) -> str | None:
    """ログイン後の戻り先。外部サイトへ飛ばされないように、自サイトのパスだけを許す

    ブラウザは "\\" を "/" と読み、タブや改行を読み飛ばすので、
    "/\\evil.example" や "/\\t/evil.example" も外部サイトになる。これらも拒否する。
    """
    if not target or not target.startswith("/"):
        return None
    if "\\" in target or any(ord(c) < 0x20 or ord(c) == 0x7F for c in target):
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    return target


@bp.route("/register", methods=["GET", "POST"])
# アカウントの大量作成を防ぐ（発表会場など、同じ回線から何人か登録しても足りる数）
@limiter.limit("10 per hour", methods=["POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if db.session.scalar(db.select(User).filter_by(email=email)):
            form.email.errors.append("このメールアドレスは登録済みです")
            return render_template("auth/register.html", form=form), 422
        user = User(name=form.name.data.strip(), email=email)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("登録しました。次に、ふたりのペアを作りましょう")
        return redirect(url_for("home.index"))
    status = 422 if form.is_submitted() else 200
    return render_template("auth/register.html", form=form), status


@bp.route("/login", methods=["GET", "POST"])
# パスワードの総当たりを防ぐ
@limiter.limit("5 per minute;30 per hour", methods=["POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            db.select(User).filter_by(email=form.email.data.strip().lower())
        )
        if user is None:
            # 登録されていないメールでも同じだけ時間をかけ、応答の速さで見分けられないようにする
            check_password_hash(DUMMY_HASH, form.password.data)
        if user is None or not user.check_password(form.password.data):
            flash("メールアドレスかパスワードが違います")
            return render_template("auth/login.html", form=form), 422
        login_user(user)
        return redirect(safe_next(request.args.get("next")) or url_for("home.index"))
    status = 422 if form.is_submitted() else 200
    return render_template("auth/login.html", form=form), status


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("ログアウトしました")
    return redirect(url_for("home.index"))


def delete_account(user: User) -> None:
    """退会：本人のアカウントと、本人に関わるデータを消す（commit は呼ぶ側で）

    - ふたりの祠（訴え・鏡・記録）と、ふたりの間の手紙は、相手の分も消す。
      記録は「ふたりとも残す」ときだけ残すものなので、片方が去れば残す同意がなくなる
    - 相手のアカウントと、相手の鏡の利用回数は残す
    """
    pair = user.pair
    if pair is not None:
        visit_ids = db.select(Visit.id).where(Visit.pair_id == pair.id)
        db.session.execute(db.delete(Plea).where(Plea.visit_id.in_(visit_ids)))
        db.session.execute(db.delete(Visit).where(Visit.pair_id == pair.id))
        db.session.execute(db.delete(Letter).where(Letter.pair_id == pair.id))
    db.session.execute(db.delete(MirrorUse).where(MirrorUse.user_id == user.id))
    db.session.execute(db.delete(Purchase).where(Purchase.user_id == user.id))
    user.pair = None
    db.session.flush()
    if pair is not None and not db.session.scalar(
        db.select(User.id).where(User.pair_id == pair.id).limit(1)
    ):
        db.session.execute(db.delete(Purchase).where(Purchase.pair_id == pair.id))
        db.session.delete(pair)
    db.session.delete(user)


@bp.route("/account/delete", methods=["GET", "POST"])
@login_required
def withdraw():
    if current_user.has_subscription:
        flash("プランに入っている間は退会できません。先にプランを解約してください")
        return redirect(url_for("billing.index"))
    form = WithdrawForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.password.data):
            form.password.errors.append("パスワードが違います")
            return render_template("auth/withdraw.html", form=form), 422
        user = db.session.get(User, current_user.id)
        logout_user()
        delete_account(user)
        db.session.commit()
        flash("退会しました。これまで祠を使っていただき、ありがとうございました")
        return redirect(url_for("home.index"))
    status = 422 if form.is_submitted() else 200
    return render_template("auth/withdraw.html", form=form), status


@bp.app_context_processor
def inject_user():
    return {"current_user": current_user}
