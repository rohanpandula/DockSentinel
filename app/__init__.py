from __future__ import annotations

import atexit
import os

from dotenv import load_dotenv
from flask import Flask
from flask.json.provider import DefaultJSONProvider

from app.config import AppConfig
from app.extensions import db


def _ensure_sqlite_parent_dir(app: Flask, database_uri: str) -> None:
    if not database_uri.startswith("sqlite:///"):
        return

    raw_path = database_uri.removeprefix("sqlite:///")
    if raw_path in {"", ":memory:"}:
        return

    if raw_path.startswith("/"):
        resolved_path = raw_path
    else:
        resolved_path = os.path.join(app.instance_path, raw_path)

    parent = os.path.dirname(resolved_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _register_blueprints(app: Flask) -> None:
    from app.api.exclusions import bp as exclusions_bp
    from app.api.health import bp as health_bp
    from app.api.incidents import bp as incidents_bp
    from app.api.insights import bp as insights_bp
    from app.api.issues import bp as issues_bp
    from app.api.mutes import bp as mutes_bp
    from app.api.prompts import bp as prompts_bp
    from app.api.reports import bp as reports_bp
    from app.api.sentinel import bp as sentinel_bp
    from app.api.settings import bp as settings_bp
    from app.api.telegram import bp as telegram_bp
    from app.web.routes import bp as web_bp

    for bp in (health_bp, settings_bp, exclusions_bp, prompts_bp,
               sentinel_bp, insights_bp, reports_bp, telegram_bp, issues_bp,
               mutes_bp, incidents_bp):
        app.register_blueprint(bp)
    # Register web_bp with name="" so endpoints resolve without a "web." prefix
    # (preserves url_for("dashboard") etc. in templates — APP-03 guardrail).
    app.register_blueprint(web_bp, name="")


class ISOJSONProvider(DefaultJSONProvider):
    """Serialise datetimes as ISO-8601 (Flask's default emits RFC 1123 HTTP-dates)."""

    @staticmethod
    def default(o):
        import datetime as _dt
        if isinstance(o, (_dt.datetime, _dt.date)):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


def _fmt_dt(value, fmt: str = "%Y-%m-%d %H:%M:%S"):
    """Jinja filter: readable timestamps (no microseconds); passthrough for None/str."""
    if value is None or value == "":
        return "—"
    try:
        return value.strftime(fmt)
    except AttributeError:
        return str(value)


def create_app() -> Flask:
    load_dotenv()
    config = AppConfig.from_env()

    app = Flask(__name__)
    app.json = ISOJSONProvider(app)
    app.jinja_env.filters["dt"] = _fmt_dt
    app.config["SECRET_KEY"] = config.secret_key
    app.config["SQLALCHEMY_DATABASE_URI"] = config.database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TESTING"] = config.testing
    app.config["RUNTIME_LOCK_PATH"] = config.runtime_lock_path
    app.config["START_COORDINATOR"] = config.start_coordinator
    app.config["FLASK_PYDANTIC_VALIDATION_ERROR_RAISE"] = True

    _ensure_sqlite_parent_dir(app, app.config["SQLALCHEMY_DATABASE_URI"])
    db.init_app(app)

    with app.app_context():
        # Import models so SQLAlchemy's metadata knows about every table
        # before db.create_all() runs. Side-effect import only.
        from app import models  # noqa: F401
        if app.config.get("TESTING"):
            db.create_all()
        from app.bootstrap import seed_defaults
        from app.composition import build_container
        seed_defaults()
        app.extensions["services"] = build_container(app)

    from app.security import install_security
    install_security(app)
    _register_blueprints(app)
    from app.errors import register_error_handlers
    register_error_handlers(app)

    coordinator = app.extensions["services"].coordinator
    if app.config["START_COORDINATOR"] and not app.config["TESTING"]:
        coordinator.start()
        atexit.register(coordinator.stop)

    if os.environ.get("MDNS_ENABLED", "false").lower() == "true" and not app.config["TESTING"]:
        from app.services.mdns import MDNSPublisher
        hostname = os.environ.get("MDNS_HOSTNAME", "docksentinel")
        port = int(os.environ.get("MDNS_PORT", "80"))
        publisher = MDNSPublisher(hostname=hostname, port=port)
        publisher.start()
        atexit.register(publisher.stop)

    return app
