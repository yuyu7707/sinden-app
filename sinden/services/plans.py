"""無料と有料の違いを決めるところ。数はすべて config から取る。

- 本人だけの機能（女神の鏡・声・学び・手紙を書く）：User.is_premium
- ふたりで共有する機能（ローマの朝・記録の振り返り）：Pair.is_premium
"""

from datetime import datetime

from flask import current_app

from sinden.extensions import db
from sinden.models import MirrorUse, User, Visit, now

# プランの人が今月の回数を使い切ったときの理由。この文のときだけ、購入のリンクを出す
MONTHLY_LIMIT_PREMIUM = (
    "今月の女神の鏡の上限に達しました。追加で購入すると続けて使えます。"
)


def offers_purchase(note: str | None) -> bool:
    """この理由の下に、鏡の追加購入のリンクを出すか（文章の一部を探さず、ここで決める）"""
    return note == MONTHLY_LIMIT_PREMIUM


def month_start(at: datetime | None = None) -> datetime:
    at = at or now()
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def mirror_limit(user: User) -> int:
    key = "MIRROR_PREMIUM_PER_MONTH" if user.is_premium else "MIRROR_FREE_PER_MONTH"
    return current_app.config[key]


def mirrors_used_this_month(user: User) -> int:
    return db.session.scalar(
        db.select(db.func.count(MirrorUse.id)).where(
            MirrorUse.user_id == user.id, MirrorUse.created_at >= month_start()
        )
    )


def mirrors_used_in_visit(visit: Visit, user: User) -> int:
    return db.session.scalar(
        db.select(db.func.count(MirrorUse.id)).where(
            MirrorUse.visit_id == visit.id, MirrorUse.user_id == user.id
        )
    )


def monthly_left(user: User) -> int:
    """今月の回数（プラン・無料）の残り。追加購入分は含まない"""
    return max(0, mirror_limit(user) - mirrors_used_this_month(user))


def mirrors_left_this_month(user: User) -> int:
    """今月あと何回、女神の鏡を使えるか（追加購入分を含む）"""
    return monthly_left(user) + user.extra_mirrors


def mirror_block_reason(visit: Visit, user: User) -> str | None:
    """鏡を使えない理由。使えるなら None"""
    if mirrors_used_in_visit(visit, user) >= current_app.config["MIRROR_PER_VISIT"]:
        return "今回の祠では、女神の鏡の上限に達しました。"
    if mirrors_left_this_month(user) <= 0:
        if user.is_premium:
            return MONTHLY_LIMIT_PREMIUM
        return "今月の無料の女神の鏡は使い切りました。プランに入ると続けて使えます。"
    return None


def record_mirror_use(visit: Visit, user: User) -> None:
    """鏡を1回使ったことを記録する。今月の回数を使い切っていれば、追加購入分から1回減らす"""
    if monthly_left(user) <= 0:
        # 減算は DB の中で計算し、0 より下にはしない（同時に使われても数がずれない）
        db.session.execute(
            db.update(User)
            .where(User.id == user.id, User.extra_mirrors > 0)
            .values(extra_mirrors=User.extra_mirrors - 1)
        )
    db.session.add(MirrorUse(user_id=user.id, visit_id=visit.id))
