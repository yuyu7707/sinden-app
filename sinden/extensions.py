from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
# ログイン・登録の回数制限。数はメモリに持つ（本番の worker ごとに数えるので、上限は最大で worker 数倍）
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
