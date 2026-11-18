import click

from sinden.extensions import db
from sinden.models import (
    Letter,
    MirrorUse,
    Pair,
    Plea,
    Purchase,
    User,
    Visit,
    new_invite_code,
)


def init_app(app):
    @app.cli.command("seed")
    @click.confirmation_option(prompt="全てのデータを消して入れ直します。よいですか？")
    def seed():
        """開発用の初期データ（ペア1組と、ペアのいない1人）。本番では実行しない"""
        for model in (Plea, Visit, MirrorUse, Letter, Purchase):
            db.session.execute(db.delete(model))
        db.session.execute(db.update(User).values(pair_id=None))
        db.session.execute(db.delete(User))
        db.session.execute(db.delete(Pair))

        pair = Pair(invite_code=new_invite_code())
        db.session.add(pair)
        for email, name, p in (
            ("a@example.com", "あおい", pair),
            ("b@example.com", "ひかる", pair),
            ("c@example.com", "ひとり", None),
        ):
            user = User(name=name, email=email, pair=p)
            user.set_password("password")
            db.session.add(user)
        db.session.commit()
        click.echo("初期データを入れました（パスワードはすべて password）")

    @app.cli.command("set-premium")
    @click.argument("email")
    @click.option("--off", is_flag=True, help="特別プランを外す")
    def set_premium(email, off):
        """動作確認・モニター用：ペアを特別プラン（ふたりとも全機能）にする。Stripe を通さない"""
        user = db.session.scalar(db.select(User).filter_by(email=email.lower()))
        if user is None or user.pair is None:
            raise click.ClickException("そのユーザーか、ペアが見つかりません")
        user.pair.comped = not off
        db.session.commit()
        click.echo(f"{email} のペアを{'無料' if off else '特別プラン'}にしました")
