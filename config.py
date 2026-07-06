import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
_DEV_SECRET = "ihc-logbook-dev-secret-change-in-prod"


class Config:
    _secret = os.environ.get("SECRET_KEY") or _DEV_SECRET
    if os.environ.get("FLASK_DEBUG", "1") == "0" and _secret == _DEV_SECRET:
        raise RuntimeError(
            "SECRET_KEY is not set. Create a .env file with SECRET_KEY=<random string> "
            "before running in production."
        )
    SECRET_KEY = _secret

    # Render provides DATABASE_URL as postgres:// — SQLAlchemy needs postgresql://
    _db_url = os.environ.get("DATABASE_URL", "")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = (
        _db_url or "sqlite:///" + os.path.join(BASE_DIR, "instance", "logbook.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True

    # Render's free Postgres drops idle connections after a few minutes. Without
    # this, the first request after an idle period grabs a dead pooled connection
    # and returns a 500 (a reload then works). pool_pre_ping tests a connection
    # before use and transparently replaces dead ones; pool_recycle refreshes
    # connections before Postgres times them out (~5 min). Only applied for
    # Postgres — SQLite (local dev) doesn't need it.
    if _db_url:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": 280,
        }

    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
