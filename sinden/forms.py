from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    EmailField,
    PasswordField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Regexp

EMAIL = Regexp(
    r"^[^@\s]+@[^@\s]+\.[^@\s]+$", message="メールアドレスの形式で入力してください"
)


class RegisterForm(FlaskForm):
    name = StringField(
        "呼び名（相手に表示されます）",
        validators=[DataRequired(message="呼び名を入力してください"), Length(max=50)],
    )
    email = EmailField(
        "メールアドレス", validators=[DataRequired(), EMAIL, Length(max=255)]
    )
    password = PasswordField(
        "パスワード（8文字以上）",
        validators=[
            DataRequired(),
            Length(min=8, message="8文字以上にしてください"),
        ],
    )


class LoginForm(FlaskForm):
    email = EmailField("メールアドレス", validators=[DataRequired(), EMAIL])
    password = PasswordField("パスワード", validators=[DataRequired()])


class WithdrawForm(FlaskForm):
    password = PasswordField("いまのパスワード", validators=[DataRequired()])
    confirm = BooleanField(
        "祠の記録と手紙が、ふたりとも見られなくなることを理解しました",
        validators=[DataRequired(message="確認の印を付けてください")],
    )


class JoinPairForm(FlaskForm):
    code = StringField(
        "相手から届いた招待コード",
        validators=[
            DataRequired(message="招待コードを入力してください"),
            Length(max=12),
        ],
    )


class InviteForm(FlaskForm):
    """誘うだけのフォーム（CSRF のため）。祠の版は誘った時刻で決まる"""


class PleaForm(FlaskForm):
    # 文字数の上限はビューで config の値と比べる
    body = TextAreaField("訴え")


class LetterForm(FlaskForm):
    title = StringField(
        "題名",
        validators=[
            DataRequired(message="題名を入力してください"),
            Length(max=100, message="100文字以内で入力してください"),
        ],
    )
    body = TextAreaField(
        "本文",
        validators=[
            DataRequired(message="本文を入力してください"),
            Length(max=5000, message="5,000文字以内で入力してください"),
        ],
    )
