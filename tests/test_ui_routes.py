from __future__ import annotations

from app import create_app


def _build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ui.db'}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    return create_app()


def test_ui_routes_smoke(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    client = app.test_client()

    routes = [
        "/",
        "/dashboard",
        "/settings",
        "/exclusions",
        "/insights",
        "/reports",
        "/prompts",
    ]

    for route in routes:
        response = client.get(route)
        assert response.status_code in {200, 302}, f"unexpected status for {route}: {response.status_code}"


def _seed(app):
    from app.extensions import db
    from app.models import AnalysisEvent, DailyReport, LocalIssue
    from app.time_utils import utcnow_naive

    with app.app_context():
        analyzed = AnalysisEvent(
            container_id="c1", container_name="web", status="analyzed", classification="critical",
            summary="web crashed", chunk_excerpt="line1\nline2", alert_sent=False,
            alert_error="duplicate alert suppressed by cooldown",
        )
        skipped = AnalysisEvent(container_id="c2", container_name="db", status="skipped", classification="noise")
        llm_err = AnalysisEvent(container_id="c3", container_name="cache", status="llm_error", llm_error="boom")
        db.session.add_all([analyzed, skipped, llm_err])
        db.session.flush()
        db.session.add(LocalIssue(event_id=analyzed.id, container_name="web", title="web crashed",
                                  body="b", action="approve", status="open"))
        now = utcnow_naive()
        db.session.add(DailyReport(period_start=now, period_end=now, status="llm_error", error="timeout",
                                   markdown_content="## Executive Summary\n\n- **bad** <b>x</b>"))
        db.session.add(DailyReport(period_start=now, period_end=now, status="generated",
                                   markdown_content="## OK\n\nfine"))
        db.session.commit()
        return analyzed.id


def test_insights_status_filter_sticky_alert_error_and_issue_link(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    event_id = _seed(app)
    client = app.test_client()

    html = client.get("/insights?status=llm_error&container=cache").get_data(as_text=True)
    assert 'value="llm_error" selected' in html
    assert 'value="cache"' in html
    assert "boom" in html
    assert "web crashed" not in html

    html = client.get("/insights?status=analyzed").get_data(as_text=True)
    assert "duplicate alert suppressed by cooldown" in html
    assert f"issue #" in html
    assert "/issues?id=" in html
    assert "cache" not in html or "llm_error" not in html.split("disclosure__summary")[1]

    # unknown status is ignored, not a 500
    assert client.get("/insights?status=nope").status_code == 200


def test_reports_render_markdown_and_error_badge(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    client = app.test_client()
    html = client.get("/reports").get_data(as_text=True)
    assert "llm error" in html
    assert "badge--critical" in html
    assert 'class="badge badge--ok">generated' in html

    from app.models import DailyReport
    with app.app_context():
        bad = DailyReport.query.filter_by(status="llm_error").first()
        bad_id = bad.id
    html = client.get(f"/reports?id={bad_id}").get_data(as_text=True)
    assert "<h2>Executive Summary</h2>" in html
    assert "<strong>bad</strong>" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>x</b>" not in html
    assert "LLM call failed" in html


def test_dashboard_stopped_banner_and_split_counts(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    client = app.test_client()
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Sentinel is stopped" in html
    assert "Skipped (prefilter)" in html
    assert "Noise (LLM)" in html

    from app.models import SentinelState
    with app.app_context():
        from app.extensions import db
        SentinelState.singleton().enabled = True
        db.session.commit()
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Sentinel is stopped" not in html


def test_alert_message_has_excerpt_and_dashboard_hint():
    from app.models import AnalysisEvent
    from app.services.alerts import AlertService

    lines = [f"l{i} " + "x" * 200 for i in range(7)] + ["", "  "]
    event = AnalysisEvent(
        id=42, container_name="my app", status="analyzed", classification="critical",
        summary="s", chunk_excerpt="\n".join(lines), confidence=0.9,
    )
    text = AlertService._format_message(event)
    assert "LOG EXCERPT" in text
    body = text.split("LOG EXCERPT")[1]
    assert "l4 " in body and "l3 " not in body  # last 3 non-empty lines
    for ln in body.splitlines():
        assert len(ln) <= 160
    assert "Dashboard: /insights?container=my%20app" in text
    assert "Event ID: 42" in text


def test_seed_defaults_refreshes_default_prompt(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    from app.bootstrap import seed_defaults
    from app.extensions import db
    from app.models import DEFAULT_PROMPTS, PromptKey, PromptTemplate

    with app.app_context():
        default_row = db.session.get(PromptTemplate, PromptKey.SENTINEL_ANALYSIS.value)
        custom_row = db.session.get(PromptTemplate, PromptKey.NIGHTLY_REPORT.value)
        default_row.content = default_row.default_content = "old default"
        custom_row.content = "my custom"
        custom_row.default_content = "old default"
        custom_row.is_default = False
        db.session.commit()

        seed_defaults()

        default_row = db.session.get(PromptTemplate, PromptKey.SENTINEL_ANALYSIS.value)
        custom_row = db.session.get(PromptTemplate, PromptKey.NIGHTLY_REPORT.value)
        assert default_row.content == DEFAULT_PROMPTS[PromptKey.SENTINEL_ANALYSIS]
        assert default_row.is_default is True
        assert custom_row.content == "my custom"
        assert custom_row.default_content == DEFAULT_PROMPTS[PromptKey.NIGHTLY_REPORT]
