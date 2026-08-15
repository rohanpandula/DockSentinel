from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from pydantic import ValidationError

from app.extensions import db
from app.models import ExclusionRule, PromptKey, SentinelState
from app.schemas.settings import ALLOWED_SETTINGS_FIELDS, MASK, SECRET_FIELDS, UpdateSettingsBody
from app.time_utils import utcnow_naive

bp = Blueprint("web", __name__, url_prefix="")


@bp.route("/", endpoint="index")
def index():
    return redirect(url_for("dashboard"))


@bp.route("/dashboard", endpoint="dashboard")
def dashboard():
    container = current_app.extensions["services"]
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
        known_containers=_list_running_containers(),
    )


def _list_running_containers() -> list[str]:
    try:
        import docker

        client = docker.from_env()
        names = sorted({c.name for c in client.containers.list() if c.name})
        try:
            client.close()
        except Exception:
            pass
        return names
    except Exception:
        return []


@bp.route("/settings", methods=["GET", "POST"], endpoint="settings_page")
def settings_page():
    container = current_app.extensions["services"]
    settings = container.settings_repo.get()
    if request.method == "POST":
        # Same allowlist + validation as PUT /api/settings; blank/masked secret
        # fields mean "keep current value". Unknown/blank fields are ignored.
        raw = {
            key: value
            for key, value in request.form.items()
            if key in ALLOWED_SETTINGS_FIELDS and value.strip() != ""
        }
        try:
            body = UpdateSettingsBody.model_validate(raw)
        except ValidationError as exc:
            errors = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
            return render_template("settings.html", settings=settings, errors=errors), 400
        for key, value in body.model_dump(exclude_unset=True).items():
            if key in SECRET_FIELDS and (value is None or value.strip() in {"", MASK}):
                continue
            setattr(settings, key, value)
        container.settings_repo.save()
        container.coordinator.refresh_schedule()
        return redirect(url_for("settings_page"))
    return render_template("settings.html", settings=settings)


@bp.route("/exclusions", methods=["GET", "POST"], endpoint="exclusions_page")
def exclusions_page():
    container = current_app.extensions["services"]
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


@bp.route("/exclusions/delete/<int:rule_id>", methods=["POST"], endpoint="exclusions_delete")
def exclusions_delete(rule_id: int):
    container = current_app.extensions["services"]
    rule = container.exclusion_repo.get(rule_id)
    if rule is not None:
        container.exclusion_repo.delete(rule)
        db.session.commit()
        container.coordinator.trigger_reconcile()
    return redirect(url_for("exclusions_page"))


@bp.route("/insights", endpoint="insights_page")
def insights_page():
    svc = current_app.extensions["services"]
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


@bp.route("/reports", endpoint="reports_page")
def reports_page():
    container = current_app.extensions["services"]
    reports = container.report_repo.list_all()
    selected_id = request.args.get("id", type=int)
    selected = container.report_repo.get(selected_id) if selected_id else (reports[0] if reports else None)
    return render_template("reports.html", reports=reports, selected_report=selected)


@bp.route("/reports/generate", methods=["POST"], endpoint="reports_generate")
def reports_generate():
    current_app.extensions["services"].briefing.generate_report()
    return redirect(url_for("reports_page"))


@bp.route("/prompts", methods=["GET", "POST"], endpoint="prompt_studio_page")
def prompt_studio_page():
    container = current_app.extensions["services"]
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


@bp.route("/issues", endpoint="issues_page")
def issues_page():
    svc = current_app.extensions["services"]
    status = request.args.get("status") or None
    issues = svc.issue_repo.list_all(limit=200, status=status)
    counts = svc.issue_repo.count_by_status()
    selected_id = request.args.get("id", type=int)
    selected = svc.issue_repo.get(selected_id) if selected_id else None

    analyzed_by = None
    if selected is not None:
        analyzed_by = selected.llm_model
        if not analyzed_by and selected.event_id:
            event = svc.event_repo.get(selected.event_id)
            if event is not None:
                analyzed_by = event.model

    return render_template(
        "issues.html",
        issues=issues,
        counts=counts,
        selected=selected,
        analyzed_by=analyzed_by,
        active_status=status,
    )


@bp.route("/issues/<int:issue_id>/status", methods=["POST"], endpoint="issues_set_status")
def issues_set_status(issue_id: int):
    svc = current_app.extensions["services"]
    issue = svc.issue_repo.get(issue_id)
    if issue is not None:
        new_status = request.form.get("status", "").strip()
        valid = {"open", "discussing", "rejected", "closed"}
        if new_status in valid:
            issue.status = new_status
            db.session.commit()
    return redirect(url_for("issues_page", id=issue_id))


@bp.route("/sentinel/toggle", methods=["POST"], endpoint="sentinel_toggle_from_ui")
def sentinel_toggle_from_ui():
    sentinel = current_app.extensions["services"].sentinel
    desired = request.form.get("enabled") == "true"
    sentinel.set_enabled(desired)
    return redirect(url_for("dashboard"))


@bp.route("/sentinel/analyze", methods=["POST"], endpoint="sentinel_analyze_from_ui")
def sentinel_analyze_from_ui():
    sentinel = current_app.extensions["services"].sentinel
    container = request.form.get("container", "").strip()
    if container:
        try:
            sentinel.analyze_container_now(container)
        except Exception:
            pass
    return redirect(url_for("dashboard"))
