from flask import Flask
from config import Config
from app.extensions import db, migrate, login_manager, bcrypt, csrf


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)   # FIX 1: Flask-Migrate handles all schema changes
    login_manager.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)

    from app.auth.routes import auth_bp
    from app.worker.routes import worker_bp
    from app.supervisor.routes import supervisor_bp
    from app.api.routes import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(worker_bp, url_prefix="/worker")
    app.register_blueprint(supervisor_bp, url_prefix="/supervisor")
    app.register_blueprint(api_bp, url_prefix="/api")

    from app.utils import ist_today
    @app.context_processor
    def inject_today():
        return {"today": ist_today().isoformat()}

    # Server timestamps (submitted_at/edited_at/created_at) are stored as naive
    # UTC via datetime.utcnow(). This filter renders them in IST (UTC+5:30) so
    # the displayed time matches the operator's local clock.
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))

    @app.template_filter("ist")
    def _to_ist(dt, fmt="%d %b %Y %H:%M"):
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST).strftime(fmt)

    if "sqlite" in app.config["SQLALCHEMY_DATABASE_URI"]:
        import sqlite3
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(dbapi_conn, _):
            if isinstance(dbapi_conn, sqlite3.Connection):
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
                dbapi_conn.execute("PRAGMA busy_timeout=10000")

    with app.app_context():
        db.create_all()

    return app
