from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from markupsafe import Markup

from pydantic import ValidationError

from app.extensions import db
from app.models import ExclusionRule, LocalIssue, PromptKey, SentinelState
from app.schemas.settings import ALLOWED_SETTINGS_FIELDS, MASK, SECRET_FIELDS, UpdateSettingsBody
from app.services.sentinel import classification_rank
from app.time_utils import utcnow_naive
from app.web.markdown_lite import render_markdown
from app.web.pipeline_view import (
    alert_outcome,
    build_funnel,
    explain_status,
    explain_suppression,
    tuning_impact,
    worst_classification,
)

bp = Blueprint("web", __name__, url_prefix="")

# Every value AnalysisEvent.status can take (see services/sentinel.py).
EVENT_STATUSES: tuple[str, ...] = (
    "analyzed",
    "skipped",
    "dedup_skipped",
    "analysis_cooldown",
    "rate_limited",
    "queued",
    "parse_error",
    "llm_error",
    "excluded",
    "container_event",
)

SKIPPED_STATUSES = {"skipped", "dedup_skipped", "analysis_cooldown", "rate_limited", "excluded", "queued"}


@bp.record_once
def _register_jinja_globals(state):
    # Globals (not context) so imported macros in _macros.html can use them too.
    state.app.jinja_env.globals["explain_status"] = explain_status
    state.app.jinja_env.globals["explain_suppression"] = explain_suppression


@bp.app_context_processor
def _inject_shell_state():
    """Every page shows the sentinel verdict pill in the nav (journey 1 from anywhere)."""
    try:
        state = SentinelState.singleton()
        degraded = state.enabled and (state.llm_failure_count > 0 or bool(state.last_error))
        shell = {"enabled": state.enabled, "degraded": degraded, "runtime": state.runtime_status}
    except Exception:  # pragma: no cover - only before tables exist
        shell = {"enabled": False, "degraded": False, "runtime": "unknown"}
    return {"shell_state": shell, "explain_status": explain_status, "explain_suppression": explain_suppression}


@bp.route("/", endpoint="index")
def index():
    return redirect(url_for("dashboard"))


def _setup_flags(state, settings) -> dict[str, bool]:
    telegram_ready = bool(settings and settings.telegram_token and settings.telegram_chat_id)
    # LLM counts as configured only once a Test LLM has succeeded — defaults alone don't tick it.
    llm_ready = state.llm_last_test_ok_at is not None
    return {
        "llm": llm_ready,
        "telegram": telegram_ready,
        "started": bool(state.enabled),
        "complete": llm_ready and telegram_ready and bool(state.enabled),
    }


def _fleet(events, settings, mutes, excluded_fn) -> list[dict]:
    """Per-container rollup for today's events (worst-first)."""
    rows: dict[str, dict] = {}
    for e in events:
        name = e.container_name or e.container_id or "?"
        row = rows.setdefault(
            name,
            {
                "name": name,
                "container_id": e.container_id,
                "worst": None,
                "events": 0,
                "analyzed": 0,
                "alerted": 0,
                "suppressed": 0,
                "errors": 0,
                "lifecycle": 0,
                "last_at": None,
                "last_summary": None,
            },
        )
        row["events"] += 1
        if e.status == "analyzed":
            row["analyzed"] += 1
            row["worst"] = worst_classification(row["worst"], e.classification)
            if e.alert_sent:
                row["alerted"] += 1
            elif e.alert_error:
                row["suppressed"] += 1
        elif e.status in {"llm_error", "parse_error"}:
            row["errors"] += 1
        elif e.status == "container_event":
            row["lifecycle"] += 1
            if e.alert_sent:
                row["alerted"] += 1
        if row["last_at"] is None or (e.created_at and e.created_at > row["last_at"]):
            row["last_at"] = e.created_at
            row["container_id"] = e.container_id or row["container_id"]
            if e.summary:
                row["last_summary"] = e.summary
    muted_names = {m.container_name for m in mutes}
    for row in rows.values():
        row["muted"] = row["name"] in muted_names
        row["excluded"] = excluded_fn(row["name"])
        row["rank"] = classification_rank(row["worst"])
        if row["errors"]:
            row["rank"] = max(row["rank"], 1)
    return sorted(rows.values(), key=lambda r: (-r["rank"], -r["alerted"], -r["events"], r["name"]))


@bp.route("/dashboard", endpoint="dashboard")
def dashboard():
    container = current_app.extensions["services"]
    state = SentinelState.singleton()  # per D-07, SentinelState keeps singleton
    settings = container.settings_repo.get()
    now = utcnow_naive()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_events = container.event_repo.get_today(today_start)

    # "noise" = the LLM looked and said noise; "skipped" = never reached the LLM
    # (prefilter / dedup / rate limit / coalesce queue / exclusion).
    counts = {"critical": 0, "warning": 0, "noise": 0, "skipped": 0, "errors": 0, "alerted": 0}
    attention: list[dict] = []
    for event in today_events:
        if event.status == "analyzed":
            if event.classification in counts:
                counts[event.classification] += 1
            if event.alert_sent:
                counts["alerted"] += 1
            elif event.classification in {"critical", "warning"}:
                outcome = alert_outcome(event, settings)
                # Warnings under the chosen threshold are by design, not "attention".
                if outcome["kind"] != "below" or event.classification == "critical":
                    attention.append({"event": event, "outcome": outcome})
        elif event.status in {"parse_error", "llm_error"}:
            counts["errors"] += 1
        elif event.status in SKIPPED_STATUSES:
            counts["skipped"] += 1
        elif event.status == "container_event" and event.alert_sent:
            counts["alerted"] += 1
        # container_event rows (die/oom/restart) are lifecycle signals, not chunks — not counted here.
    attention = sorted(attention, key=lambda a: (-classification_rank(a["event"].classification), -(a["event"].created_at or now).timestamp()))[:8]

    mutes = container.mute_repo.list_active(now)
    fleet = _fleet(today_events, settings, mutes, container.sentinel.is_excluded_container)
    active_ids = set(container.coordinator.active_container_ids())
    for row in fleet:
        row["attached"] = bool(row.get("container_id") and row["container_id"] in active_ids)

    issue_counts = container.issue_repo.count_by_status()
    open_issues = issue_counts.get("open", 0) + issue_counts.get("discussing", 0)
    setup = _setup_flags(state, settings)
    degraded = state.enabled and (state.llm_failure_count > 0 or bool(state.last_error))

    # One-line verdict for the glance path.
    if not state.enabled:
        verdict = ("stopped", "Sentinel is stopped", "No containers are being watched and no alerts will fire.")
    elif degraded:
        verdict = ("degraded", "Sentinel is degraded", state.last_error or f"LLM failed {state.llm_failure_count}× since start.")
    elif attention or counts["critical"]:
        n = len(attention)
        verdict = (
            "attention",
            f"{n} thing{'s' if n != 1 else ''} need{'s' if n == 1 else ''} attention" if n else f"{counts['critical']} critical today",
            "Critical or warning verdicts today that were not delivered to your phone.",
        )
    else:
        verdict = ("ok", "All quiet", f"{len(active_ids)} containers watched · {counts['alerted']} alert{'s' if counts['alerted'] != 1 else ''} today.")

    events = container.event_repo.get_recent(limit=12)
    latest_report = container.report_repo.get_latest()

    return render_template(
        "dashboard.html",
        state=state,
        counts=counts,
        events=events,
        latest_report=latest_report,
        active_containers=list(active_ids),
        known_containers=_list_running_containers(),
        analyze_error=request.args.get("analyze_error"),
        settings=settings,
        mutes=mutes,
        attention=attention,
        fleet=fleet,
        open_issues=open_issues,
        setup=setup,
        show_setup=(not setup["complete"]) or request.args.get("setup") == "1",
        verdict=verdict,
        degraded=degraded,
        last_seen_chat=getattr(getattr(container, "telegram_bot", None), "last_seen_chat", None),
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


def _tuning_stats(container, days: int = 7) -> dict:
    since = utcnow_naive() - timedelta(days=days)
    events = container.event_repo.get_for_window(since)
    impact = tuning_impact(events)
    per_container: Counter[str] = Counter()
    for e in events:
        if e.status in {"skipped", "dedup_skipped", "rate_limited", "analysis_cooldown"} and e.container_name:
            per_container[e.container_name] += 1
    return {
        "days": days,
        "impact": impact,
        "total": len(events),
        "noisiest": per_container.most_common(5),
    }


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
            return render_template("settings.html", settings=settings, errors=errors, tuning=_tuning_stats(container),
                                   mutes=container.mute_repo.list_active(utcnow_naive()),
                                   exclusions=container.exclusion_repo.list_all()), 400
        for key, value in body.model_dump(exclude_unset=True).items():
            if key in SECRET_FIELDS and (value is None or value.strip() in {"", MASK}):
                continue
            setattr(settings, key, value)
        container.settings_repo.save()
        container.coordinator.refresh_schedule()
        return redirect(url_for("settings_page", saved=1))
    return render_template(
        "settings.html",
        settings=settings,
        tuning=_tuning_stats(container),
        mutes=container.mute_repo.list_active(utcnow_naive()),
        exclusions=container.exclusion_repo.list_all(),
        saved=request.args.get("saved") == "1",
        state=SentinelState.singleton(),
    )


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
        nxt = request.form.get("next")
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(url_for("exclusions_page"))

    exclusions = container.exclusion_repo.list_all()
    # Which known containers does each rule currently match? (7-day event history)
    names = container.event_repo.get_distinct_container_names()
    matches = {
        rule.id: sorted(n for n in names if rule.container_pattern.lower() in n.lower())
        for rule in exclusions
    }
    return render_template("exclusions.html", exclusions=exclusions, matches=matches, known=sorted(names))


@bp.route("/exclusions/delete/<int:rule_id>", methods=["POST"], endpoint="exclusions_delete")
def exclusions_delete(rule_id: int):
    container = current_app.extensions["services"]
    rule = container.exclusion_repo.get(rule_id)
    if rule is not None:
        container.exclusion_repo.delete(rule)
        db.session.commit()
        container.coordinator.trigger_reconcile()
    return redirect(url_for("exclusions_page"))


def _issue_map(event_ids: list[int]) -> dict[int, int]:
    issue_by_event: dict[int, int] = {}
    if event_ids:
        rows = (
            db.session.query(LocalIssue.event_id, LocalIssue.id)
            .filter(LocalIssue.event_id.in_(event_ids))
            .order_by(LocalIssue.created_at.asc())
            .all()
        )
        for event_id, issue_id in rows:
            issue_by_event.setdefault(event_id, issue_id)
    return issue_by_event


@bp.route("/insights", endpoint="insights_page")
def insights_page():
    svc = current_app.extensions["services"]
    settings = svc.settings_repo.get()
    container_filter = request.args.get("container") or None
    classification = request.args.get("classification") or None
    status = request.args.get("status") or None
    if status not in EVENT_STATUSES:
        status = None
    outcome = request.args.get("outcome") or None  # alerted | suppressed | never
    if outcome not in {"alerted", "suppressed", "never"}:
        outcome = None
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
    if status:
        # Filter in Python: keeps the repository signature untouched and the
        # page caps at 200 rows anyway.
        events = [e for e in events if e.status == status]
    if outcome == "alerted":
        events = [e for e in events if e.alert_sent]
    elif outcome == "suppressed":
        events = [e for e in events if not e.alert_sent and e.alert_error]
    elif outcome == "never":
        events = [e for e in events if e.status in SKIPPED_STATUSES]
    containers = svc.event_repo.get_distinct_container_names()

    # Map event id -> issue id so rows can link to the issue raised from them.
    event_ids = [e.id for e in events if e.id is not None]
    issue_by_event = _issue_map(event_ids)

    now = utcnow_naive()
    muted_until = {m.container_name: m.until_label() for m in svc.mute_repo.list_active(now)}

    # Journey 2: a Telegram alert deep-links ?event=<id> → spotlight card with full context.
    spotlight = None
    spotlight_id = request.args.get("event", type=int)
    if spotlight_id:
        ev = svc.event_repo.get(spotlight_id)
        if ev is not None:
            history = [
                h for h in svc.event_repo.get_filtered(container=ev.container_name, limit=9)
                if h.id != ev.id
            ][:8] if ev.container_name else []
            issue_id = _issue_map([ev.id]).get(ev.id)
            spotlight = {
                "event": ev,
                "outcome": alert_outcome(ev, settings),
                "status": explain_status(ev.status),
                "history": history,
                "issue_id": issue_id,
                "mute": svc.mute_repo.get_active(ev.container_name, now) if ev.container_name else None,
            }

    return render_template(
        "insights.html",
        events=events,
        containers=containers,
        muted_until=muted_until,
        statuses=EVENT_STATUSES,
        issue_by_event=issue_by_event,
        settings=settings,
        spotlight=spotlight,
        spotlight_missing=bool(spotlight_id and spotlight is None),
        alert_outcome=alert_outcome,
        filters={
            "container": container_filter or "",
            "classification": classification or "",
            "status": status or "",
            "outcome": outcome or "",
            "start": start_str or "",
            "end": end_str or "",
        },
    )


@bp.route("/containers/<path:name>", endpoint="container_page")
def container_page(name: str):
    """Journey 3 — per-container drill-down: what happened to this container's
    logs at every pipeline stage, and why nothing (or something) alerted."""
    svc = current_app.extensions["services"]
    settings = svc.settings_repo.get()
    name = name.strip()
    now = utcnow_naive()
    hours = request.args.get("hours", type=int) or 24
    if hours not in (6, 24, 72, 168):
        hours = 24
    since = now - timedelta(hours=hours)

    events = svc.event_repo.get_filtered(container=name, start=since, limit=500)
    funnel = build_funnel(events, settings)
    timeline = events[:60]
    for_issue = _issue_map([e.id for e in timeline if e.id is not None])

    issues = [i for i in svc.issue_repo.list_all(limit=200) if i.container_name == name][:20]
    mute = svc.mute_repo.get_active(name, now)
    matching_rules = [r for r in svc.exclusion_repo.list_all() if r.enabled and r.container_pattern.lower() in name.lower()]

    last = events[0] if events else None
    active_ids = set(svc.coordinator.active_container_ids())
    attached = bool(last and last.container_id and last.container_id in active_ids)
    known = last is not None or name in _list_running_containers()

    last_verdict = next((e for e in events if e.status == "analyzed"), None)
    last_alert = next((e for e in events if e.alert_sent), None)

    return render_template(
        "container.html",
        name=name,
        hours=hours,
        events=timeline,
        funnel=funnel,
        issues=issues,
        mute=mute,
        matching_rules=matching_rules,
        attached=attached,
        known=known,
        last_verdict=last_verdict,
        last_alert=last_alert,
        settings=settings,
        issue_by_event=for_issue,
        alert_outcome=alert_outcome,
        total_events=len(events),
    )


@bp.route("/reports", endpoint="reports_page")
def reports_page():
    container = current_app.extensions["services"]
    reports = container.report_repo.list_all()
    selected_id = request.args.get("id", type=int)
    selected = container.report_repo.get(selected_id) if selected_id else (reports[0] if reports else None)
    # render_markdown escapes all source text before adding tags, so it is safe to mark.
    report_html = Markup(render_markdown(selected.markdown_content)) if selected else Markup("")

    # Weekly review strip: what happened in the last 7 days.
    now = utcnow_naive()
    week = container.event_repo.get_for_window(now - timedelta(days=7))
    week_stats = {"alerts": 0, "critical": 0, "warning": 0, "chunks": 0, "suppressed": 0}
    noisiest: Counter[str] = Counter()
    for e in week:
        if e.status == "container_event":
            if e.alert_sent:
                week_stats["alerts"] += 1
            continue
        week_stats["chunks"] += 1
        if e.status == "analyzed":
            if e.classification in ("critical", "warning"):
                week_stats[e.classification] += 1
            if e.alert_sent:
                week_stats["alerts"] += 1
            elif e.alert_error:
                week_stats["suppressed"] += 1
        if e.container_name and e.status in SKIPPED_STATUSES:
            noisiest[e.container_name] += 1
    issue_counts = container.issue_repo.count_by_status()
    return render_template(
        "reports.html",
        reports=reports,
        selected_report=selected,
        report_html=report_html,
        week=week_stats,
        noisiest=noisiest.most_common(5),
        issue_counts=issue_counts,
        settings=container.settings_repo.get(),
    )


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
    latest_issue = next(iter(container.issue_repo.list_all(limit=1)), None)
    return render_template(
        "prompt_studio.html",
        prompts=prompts,
        selected_prompt=prompt,
        latest_issue=latest_issue,
        settings=container.settings_repo.get(),
    )


@bp.route("/issues", endpoint="issues_page")
def issues_page():
    svc = current_app.extensions["services"]
    status = request.args.get("status") or None
    issues = svc.issue_repo.list_all(limit=200, status=status)
    counts = svc.issue_repo.count_by_status()
    selected_id = request.args.get("id", type=int)
    selected = svc.issue_repo.get(selected_id) if selected_id else None

    analyzed_by = None
    selected_event = None
    if selected is not None:
        analyzed_by = selected.llm_model
        if selected.event_id:
            selected_event = svc.event_repo.get(selected.event_id)
            if not analyzed_by and selected_event is not None:
                analyzed_by = selected_event.model

    selected_mute = None
    if selected is not None and selected.container_name:
        selected_mute = svc.mute_repo.get_active(selected.container_name, utcnow_naive())

    return render_template(
        "issues.html",
        selected_mute=selected_mute,
        selected_body_html=Markup(render_markdown(selected.body)) if selected and selected.body else Markup(""),
        issues=issues,
        counts=counts,
        selected=selected,
        selected_event=selected_event,
        analyzed_by=analyzed_by,
        active_status=status,
        settings=svc.settings_repo.get(),
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
    return _redirect_back()


@bp.route("/sentinel/analyze", methods=["POST"], endpoint="sentinel_analyze_from_ui")
def sentinel_analyze_from_ui():
    sentinel = current_app.extensions["services"].sentinel
    container = request.form.get("container", "").strip()
    nxt = request.form.get("next")
    if not container:
        return redirect(url_for("dashboard", analyze_error="no container selected"))
    try:
        event = sentinel.analyze_container_now(container)
    except Exception as exc:
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            sep = "&" if "?" in nxt else "?"
            return redirect(f"{nxt}{sep}analyze_error={str(exc)[:300]}")
        return redirect(url_for("dashboard", analyze_error=str(exc)[:300]))
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    if event is not None and getattr(event, "id", None):
        return redirect(url_for("insights_page", container=container, event=event.id))
    return redirect(url_for("dashboard"))


def _redirect_back(default_endpoint: str = "dashboard"):
    nxt = request.form.get("next") or request.referrer
    # Only follow same-site relative paths.
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    if nxt and request.host_url and nxt.startswith(request.host_url):
        return redirect(nxt)
    return redirect(url_for(default_endpoint))


@bp.route("/mutes/<path:container_name>", methods=["POST"], endpoint="mute_container")
def mute_container(container_name: str):
    svc = current_app.extensions["services"]
    name = container_name.strip()
    hours = request.args.get("hours", request.form.get("hours", "24"))
    try:
        hours_int = int(hours) if hours not in (None, "", "0", "null") else None
    except ValueError:
        hours_int = 24
    if hours_int is not None and not (1 <= hours_int <= 8760):
        hours_int = 24
    if name:
        until = utcnow_naive() + timedelta(hours=hours_int) if hours_int is not None else None
        svc.mute_repo.upsert(name, until, request.form.get("reason") or "ui")
        db.session.commit()
    return _redirect_back()


@bp.route("/mutes/<path:container_name>/delete", methods=["POST"], endpoint="unmute_container")
def unmute_container(container_name: str):
    svc = current_app.extensions["services"]
    if svc.mute_repo.delete(container_name.strip()):
        db.session.commit()
    return _redirect_back()
