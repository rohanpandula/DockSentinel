from __future__ import annotations

import atexit
import os

from dotenv import load_dotenv
from flask import Flask

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
    from app.api.insights import bp as insights_bp
    from app.api.prompts import bp as prompts_bp
    from app.api.reports import bp as reports_bp
    from app.api.sentinel import bp as sentinel_bp
    from app.api.settings import bp as settings_bp
    from app.api.telegram import bp as telegram_bp
    from app.web.routes import bp as web_bp

    for bp in (health_bp, settings_bp, exclusions_bp, prompts_bp,
               sentinel_bp, insights_bp, reports_bp, telegram_bp):
        app.register_blueprint(bp)
    # Register web_bp with name="" so endpoints resolve without a "web." prefix
    # (preserves url_for("dashboard") etc. in templates — APP-03 guardrail).
    app.register_blueprint(web_bp, name="")


def create_app() -> Flask:
    load_dotenv()
    config = AppConfig.from_env()

    app = Flask(__name__)
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

    _register_blueprints(app)
    from app.errors import register_error_handlers
    register_error_handlers(app)

    coordinator = app.extensions["services"].coordinator
    if app.config["START_COORDINATOR"] and not app.config["TESTING"]:
        coordinator.start()
        atexit.register(coordinator.stop)

    return app
