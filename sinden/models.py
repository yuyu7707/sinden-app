import secrets
from datetime import datetime
from typing import ClassVar

from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from sinden.extensions import db

# 招待コードに使う文字（0/O、1/I など見間違えやすい文字は除く）
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def now() -> datetime:
    return datetime.now()


def new_invite_code() -> str:
    return "".join(secrets.choice(CODE_CHARS) for _ in range(8))


class Pair(db.Model):
    """ふたり（夫婦・恋人）。関係が良いうちに作っておく"""

    __tablename__ = "pairs"

    id: Mapped[int] = mapped_column(primary_key=True)
    invite_code: Mapped[str] = mapped_column(String(12), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # 支払いなしでプラン扱いにする（動作確認・モニター用。flask set-premium で切り替える）
    comped: Mapped[bool] = mapped_column(Boolean, default=False)

    members: Mapped[list[User]] = relationship(back_populates="pair")

    @property
    def is_premium(self) -> bool:
        """ふたりで共有する機能（ローマの朝、記録の振り返り）を使えるか。
        どちらかがプラン（個人・ふたり）に入っていれば使える"""
        return self.comped or any(m.has_active_plan for m in self.members)

    @property
    def is_complete(self) -> bool:
        return len(self.members) >= 2

    def partner_of(self, user: User) -> User | None:
        for member in self.members:
            if member.id != user.id:
                return member
        return None


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    pair_id: Mapped[int | None] = mapped_column(ForeignKey("pairs.id"))
    # 祠の画面を開いている間、数秒ごとに更新する（相手の灯りに使う）
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # 月額プラン（支払った本人が持つ）。plan は "solo"（個人）か "pair"（ふたり）
    plan: Mapped[str | None] = mapped_column(String(10))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
    subscription_status: Mapped[str | None] = mapped_column(String(30))
    # 追加購入した女神の鏡の残り回数（毎月の回数を使い切ったあとに使う。期限なし）
    extra_mirrors: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    pair: Mapped[Pair | None] = relationship(back_populates="members")

    @property
    def has_active_plan(self) -> bool:
        """自分で支払ったプランが有効か"""
        return self.plan is not None and self.subscription_status in (
            "active",
            "trialing",
        )

    @property
    def has_subscription(self) -> bool:
        """解約・カード変更の対象になる契約があるか（支払い遅れも含む）"""
        return self.plan is not None and self.subscription_status in (
            "active",
            "trialing",
            "past_due",
        )

    @property
    def is_premium(self) -> bool:
        """本人だけが使う機能（女神の鏡、声、学び、手紙を書く）を使えるか"""
        if self.pair is not None and self.pair.comped:
            return True
        if self.has_active_plan:
            return True
        partner = self.partner
        return bool(
            partner is not None
            and partner.has_active_plan
            and partner.plan == PurchaseKind.PAIR
        )

    @property
    def plan_source(self) -> str | None:
        """画面に出す説明：どのプランで使えているか"""
        if self.pair is not None and self.pair.comped:
            return "特別プラン"
        if self.has_active_plan:
            return PurchaseKind.LABELS.get(self.plan)
        if self.is_premium:
            return f"{self.partner.name}さんのふたりプラン"
        return None

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def partner(self) -> User | None:
        return self.pair.partner_of(self) if self.pair else None


class VisitStatus:
    INVITED = "invited"  # 誘った。相手の返事待ち
    RULES = "rules"  # 祠に入った。掟の確認中
    PLEADING = "pleading"  # 一人ずつ訴えている
    RECONCILED = "reconciled"  # ふたりとも祠を出た。記録を残すか選ぶ
    CLOSED = "closed"  # 終わり
    CANCELLED = "cancelled"  # 誘いを取り消した／断った

    ACTIVE = (INVITED, RULES, PLEADING, RECONCILED)


class Theme:
    NIGHT = "night"
    MORNING = "morning"
    LABELS: ClassVar[dict[str, str]] = {NIGHT: "夜の祠", MORNING: "ローマの朝"}


class Visit(db.Model):
    """祠への1回の訪問（1回の喧嘩）"""

    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id"))
    inviter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    invitee_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default=VisitStatus.INVITED)
    theme: Mapped[str] = mapped_column(String(10), default=Theme.NIGHT)
    current_speaker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    turn_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    # ふたりそれぞれの意思表示（inviter_* / invitee_*）
    inviter_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    invitee_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    inviter_leave: Mapped[bool] = mapped_column(Boolean, default=False)
    invitee_leave: Mapped[bool] = mapped_column(Boolean, default=False)
    inviter_keep: Mapped[bool | None] = mapped_column(Boolean)
    invitee_keep: Mapped[bool | None] = mapped_column(Boolean)
    kept: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    # 話し手が「ことばを確かめる」を押したあとの下書き。話し手にだけ見せ、届けたら消す
    draft_text: Mapped[str | None] = mapped_column(Text)
    draft_mirror: Mapped[str | None] = mapped_column(Text)
    draft_lamp: Mapped[str | None] = mapped_column(Text)
    draft_note: Mapped[str | None] = mapped_column(String(200))
    draft_danger: Mapped[bool] = mapped_column(Boolean, default=False)

    pair: Mapped[Pair] = relationship()
    inviter: Mapped[User] = relationship(foreign_keys=[inviter_id])
    invitee: Mapped[User] = relationship(foreign_keys=[invitee_id])
    current_speaker: Mapped[User | None] = relationship(
        foreign_keys=[current_speaker_id]
    )
    pleas: Mapped[list[Plea]] = relationship(
        back_populates="visit", order_by="Plea.seq", cascade="all, delete-orphan"
    )

    def role(self, user: User) -> str | None:
        if user.id == self.inviter_id:
            return "inviter"
        if user.id == self.invitee_id:
            return "invitee"
        return None

    def is_member(self, user: User) -> bool:
        return self.role(user) is not None

    def partner(self, user: User) -> User:
        return self.invitee if user.id == self.inviter_id else self.inviter

    def flag(self, name: str, user: User):
        return getattr(self, f"{self.role(user)}_{name}")

    def set_flag(self, name: str, user: User, value) -> None:
        setattr(self, f"{self.role(user)}_{name}", value)

    def both(self, name: str) -> bool:
        return bool(getattr(self, f"inviter_{name}")) and bool(
            getattr(self, f"invitee_{name}")
        )

    @property
    def is_active(self) -> bool:
        return self.status in VisitStatus.ACTIVE

    @property
    def theme_label(self) -> str:
        return Theme.LABELS.get(self.theme, "")

    def remaining_seconds(self, turn_seconds: int) -> int:
        if self.turn_started_at is None:
            return turn_seconds
        passed = (now() - self.turn_started_at).total_seconds()
        return max(0, int(turn_seconds - passed))

    def version(self) -> str:
        """画面を作り直す必要があるかを、ブラウザが判断するための値"""
        return "-".join(
            str(v)
            for v in (
                self.status,
                self.current_speaker_id,
                len(self.pleas),
                self.inviter_agreed,
                self.invitee_agreed,
                self.inviter_leave,
                self.invitee_leave,
                self.inviter_keep,
                self.invitee_keep,
            )
        )


class Plea(db.Model):
    """1回の訴え。本文は相手にも届く。鏡（mirror）は書いた本人だけが見られる"""

    __tablename__ = "pleas"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    seq: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    mirror: Mapped[str | None] = mapped_column(Text)
    # 鏡を作れなかったときの理由（本人にだけ短く表示する）
    mirror_note: Mapped[str | None] = mapped_column(String(200))
    danger: Mapped[bool] = mapped_column(Boolean, default=False)
    # 届けた言葉の選び方：own（自分の言葉のまま）/ edited（映したあと自分で直した）/ lamp（ことばの灯の言い方）
    source: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    visit: Mapped[Visit] = relationship(back_populates="pleas")
    user: Mapped[User] = relationship()


class MirrorUse(db.Model):
    """女神の鏡を使った記録（1人ずつ、月の回数を数える。訴えを消しても残す）"""

    __tablename__ = "mirror_uses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    visit_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PurchaseKind:
    """申し込みの種類。

    個人・ふたりは月額プラン（個人は入った本人だけ、ふたりは2人とも使える）。
    鏡の追加は1回払いで、毎月の回数を使い切ったあとに使う。
    """

    SOLO = "solo"
    PAIR = "pair"
    MIRRORS = "mirrors"
    PLANS = (SOLO, PAIR)
    LABELS: ClassVar[dict[str, str]] = {
        SOLO: "個人プラン",
        PAIR: "ふたりプラン",
        MIRRORS: "女神の鏡 追加",
    }
    PRICE_KEYS: ClassVar[dict[str, str]] = {
        SOLO: "PRICE_SOLO",
        PAIR: "PRICE_PAIR",
        MIRRORS: "PRICE_MIRROR_PACK",
    }


class Purchase(db.Model):
    """支払いの申し込み。Stripe の決済ページを開くたびに1行作る"""

    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)

    pair: Mapped[Pair] = relationship()
    user: Mapped[User] = relationship()

    @property
    def label(self) -> str:
        return PurchaseKind.LABELS.get(self.kind, "")


class Letter(db.Model):
    """相手に届ける手紙（有料）"""

    __tablename__ = "letters"

    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)

    sender: Mapped[User] = relationship(foreign_keys=[sender_id])
    recipient: Mapped[User] = relationship(foreign_keys=[recipient_id])
