from __future__ import annotations

import atexit
import os
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, url_for

from app.config import AppConfig
from app.extensions import db
from app.models import (
    DEFAULT_PROMPTS,
    ExclusionRule,
    PromptTemplate,
    PromptKey,
    SchemaVersion,
    SentinelState,
    Settings,
)
from app.container import ServiceContainer
from app.repositories.analysis_events import AnalysisEventRepository
from app.repositories.exclusions import ExclusionRepository
from app.repositories.prompts import PromptRepository
from app.repositories.reports import ReportRepository
from app.repositories.settings import SettingsRepository
from app.services.briefing import BriefingService
from app.services.cli_backends import CLIBackendRunner
from app.services.coordinator import RuntimeCoordinator
from app.services.llm_call import LLMCallService
from app.services.llm_client import LLMClient
from app.services.sentinel import SentinelService
from app.services.telegram import TelegramNotifier
from app.services.verdict_parser import VerdictParser
from app.time_utils import utcnow_naive


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


def _seed_defaults() -> None:
    SchemaVersion.singleton()
    Settings.singleton()
    SentinelState.singleton()

    for pattern in ["docksentinel", "ollama", "portainer", "open-webui"]:
        if ExclusionRule.query.filter_by(container_pattern=pattern).first() is None:
            db.session.add(ExclusionRule(container_pattern=pattern, enabled=True))

    for key, content in DEFAULT_PROMPTS.items():
        existing = PromptTemplate.query.filter_by(key=key.value).first()
        if existing is None:
            db.session.add(
                PromptTemplate(
                    key=key.value,
                    content=content,
                    default_content=content,
                    version=1,
                    is_default=True,
                )
            )

    db.session.commit()



def _register_api_blueprints(app: Flask) -> None:
    from app.api.exclusions import bp as exclusions_bp
    from app.api.health import bp as health_bp
    from app.api.insights import bp as insights_bp
    from app.api.prompts import bp as prompts_bp
    from app.api.reports import bp as reports_bp
    from app.api.sentinel import bp as sentinel_bp
    from app.api.settings import bp as settings_bp
    from app.api.telegram import bp as telegram_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(exclusions_bp)
    app.register_blueprint(prompts_bp)
    app.register_blueprint(sentinel_bp)
    app.register_blueprint(insights_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(telegram_bp)


def _register_web_routes(app: Flask) -> None:
    @app.get("/")
    def index():
        return redirect(url_for("dashboard"))

    @app.get("/dashboard")
    def dashboard():
        container = app.extensions["services"]
        state = SentinelState.singleton()  # per D-07, SentinelState keeps singleton
        today_start = utcnow_naive().replace(hour=0, minute=0, second=0, microsecond=0)
        today_events = container.event_repo.get_today(today_start)

        counts = {"critical": 0, "warning": 0, "noise": 0}
        for event in today_events:
            if event.classification in counts:
                counts[event.classification] += 1

        events = container.event_repo.get_recent(limit=10)
        latest_report = container.report_repo.get_latest()

        return render_template(
            "dashboard.html",
            state=state,
            counts=counts,
            events=events,
            latest_report=latest_report,
            active_containers=container.coordinator.active_container_ids(),
        )

    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        container = app.extensions["services"]
        settings = container.settings_repo.get()
        if request.method == "POST":
            for key, value in request.form.items():
                if hasattr(settings, key):
                    cast_value = value
                    if key in {
                        "nightly_hour",
                        "nightly_minute",
                        "max_input_chars",
                        "max_input_tokens",
                        "reserved_output_tokens",
                        "alert_cooldown_minutes",
                        "alert_rate_limit_count",
                        "alert_rate_limit_window_seconds",
                        "llm_timeout_seconds",
                        "llm_max_retries",
                        "cli_timeout_seconds",
                        "cli_max_retries",
                        "dedup_window_seconds",
                        "container_rate_limit_count",
                        "container_rate_limit_window_seconds",
                        "keyword_flush_delay_lines",
                    }:
                        cast_value = int(value)
                    setattr(settings, key, cast_value)
            container.settings_repo.save()
            container.coordinator.refresh_schedule()
            return redirect(url_for("settings_page"))
        return render_template("settings.html", settings=settings)

    @app.route("/exclusions", methods=["GET", "POST"])
    def exclusions_page():
        container = app.extensions["services"]
        if request.method == "POST":
            pattern = request.form.get("container_pattern", "").strip()
            if pattern and container.exclusion_repo.find_by_pattern(pattern) is None:
                container.exclusion_repo.add(
                    ExclusionRule(container_pattern=pattern, enabled=True)
                )
                db.session.commit()
                container.coordinator.trigger_reconcile()
            return redirect(url_for("exclusions_page"))

        exclusions = container.exclusion_repo.list_all()
        return render_template("exclusions.html", exclusions=exclusions)

    @app.get("/exclusions/delete/<int:rule_id>")
    def exclusions_delete(rule_id: int):
        container = app.extensions["services"]
        rule = container.exclusion_repo.get(rule_id)
        if rule is not None:
            container.exclusion_repo.delete(rule)
            db.session.commit()
            container.coordinator.trigger_reconcile()
        return redirect(url_for("exclusions_page"))

    @app.get("/insights")
    def insights_page():
        svc = app.extensions["services"]
        container_filter = request.args.get("container")
        classification = request.args.get("classification")
        start_str = request.args.get("start")
        end_str = request.args.get("end")

        start = None
        end = None
        if start_str:
            try:
                start = datetime.fromisoformat(start_str)
            except ValueError:
                pass
        if end_str:
            try:
                end = datetime.fromisoformat(end_str)
            except ValueError:
                pass

        events = svc.event_repo.get_filtered(
            container=container_filter,
            classification=classification,
            start=start,
            end=end,
            limit=200,
        )
        containers = svc.event_repo.get_distinct_container_names()
        return render_template("insights.html", events=events, containers=containers)

    @app.get("/reports")
    def reports_page():
        container = app.extensions["services"]
        reports = container.report_repo.list_all()
        selected_id = request.args.get("id", type=int)
        selected = container.report_repo.get(selected_id) if selected_id else (reports[0] if reports else None)
        return render_template("reports.html", reports=reports, selected_report=selected)

    @app.post("/reports/generate")
    def reports_generate():
        app.extensions["services"].briefing.generate_report()
        return redirect(url_for("reports_page"))

    @app.route("/prompts", methods=["GET", "POST"])
    def prompt_studio_page():
        container = app.extensions["services"]
        selected_key = request.args.get("key", PromptKey.SENTINEL_ANALYSIS.value)
        prompt = container.prompt_repo.get_by_key(selected_key)

        if request.method == "POST":
            action = request.form.get("action")
            key = request.form.get("key", selected_key)
            prompt = container.prompt_repo.get_by_key(key)
            if prompt is not None:
                if action == "save":
                    content = request.form.get("content", "").strip()
                    if content:
                        prompt.content = content
                        prompt.version += 1
                        prompt.is_default = content == prompt.default_content
                elif action == "reset":
                    prompt.content = prompt.default_content
                    prompt.version += 1
                    prompt.is_default = True
                db.session.commit()
            return redirect(url_for("prompt_studio_page", key=key))

        prompts = container.prompt_repo.list_all()
        return render_template("prompt_studio.html", prompts=prompts, selected_prompt=prompt)

    @app.post("/sentinel/toggle")
    def sentinel_toggle_from_ui():
        sentinel = app.extensions["services"].sentinel
        desired = request.form.get("enabled") == "true"
        sentinel.set_enabled(desired)
        return redirect(url_for("dashboard"))

    @app.post("/sentinel/analyze")
    def sentinel_analyze_from_ui():
        sentinel = app.extensions["services"].sentinel
        container = request.form.get("container", "").strip()
        if container:
            try:
                sentinel.analyze_container_now(container)
            except Exception:
                pass
        return redirect(url_for("dashboard"))


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

    _ensure_sqlite_parent_dir(app, app.config["SQLALCHEMY_DATABASE_URI"])
    db.init_app(app)

    with app.app_context():
        if app.config.get("TESTING"):
            db.create_all()
        _seed_defaults()

    cli_backends_dir = os.getenv("CLI_BACKENDS_DIR", os.path.join(os.path.dirname(__file__), "..", "llm-backends"))
    cli_runner = CLIBackendRunner(backends_dir=os.path.abspath(cli_backends_dir), max_concurrent_calls=1)
    llm_client = LLMClient(cli_runner=cli_runner)
    llm_call_service = LLMCallService(llm_client=llm_client)
    verdict_parser = VerdictParser()
    telegram_notifier = TelegramNotifier()
    event_repo = AnalysisEventRepository()
    settings_repo = SettingsRepository()
    prompt_repo = PromptRepository()
    report_repo = ReportRepository()
    exclusion_repo = ExclusionRepository()
    sentinel_service = SentinelService(
        llm_call_service=llm_call_service,
        verdict_parser=verdict_parser,
        telegram_notifier=telegram_notifier,
        event_repo=event_repo,
        prompt_repo=prompt_repo,
        exclusion_repo=exclusion_repo,
    )
    briefing_service = BriefingService(
        llm_call_service=llm_call_service,
        event_repo=event_repo,
        prompt_repo=prompt_repo,
        report_repo=report_repo,
    )
    coordinator = RuntimeCoordinator(app=app, sentinel_service=sentinel_service, briefing_service=briefing_service)

    app.extensions["services"] = ServiceContainer(
        llm_client=llm_client,
        llm_call=llm_call_service,
        verdict_parser=verdict_parser,
        telegram_notifier=telegram_notifier,
        sentinel=sentinel_service,
        briefing=briefing_service,
        coordinator=coordinator,
        event_repo=event_repo,
        settings_repo=settings_repo,
        prompt_repo=prompt_repo,
        report_repo=report_repo,
        exclusion_repo=exclusion_repo,
    )

    _register_api_blueprints(app)
    _register_web_routes(app)

    if app.config["START_COORDINATOR"] and not app.config["TESTING"]:
        coordinator.start()
        atexit.register(coordinator.stop)

    return app
