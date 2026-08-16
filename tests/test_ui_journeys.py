"""UI journey coverage for the redesign:

J1 glance (Now page rollups), J2 Telegram → event spotlight, J3 container
pipeline drill-down, J4 setup stepper + chat-id detection, J5 tuning impact,
J6 compare-verdicts scaffolding.
"""
from __future__ import annotations

from datetime import timedelta

from app import create_app
from app.web.pipeline_view import alert_outcome, build_funnel, explain_status, explain_suppression


def _build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'journeys.db'}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    return create_app()


def _seed(app):
    from app.extensions import db
    from app.models import AnalysisEvent, ContainerMute, LocalIssue, SentinelState, Settings
    from app.time_utils import utcnow_naive

    now = utcnow_naive()
    with app.app_context():
        state = SentinelState.singleton()
        state.enabled = True
        Settings.singleton().alert_min_classification = "critical"

        alerted = AnalysisEvent(
            container_id="web-1", container_name="web", status="analyzed", classification="critical",
            summary="web crashed", chunk_excerpt="boom", alert_sent=True, model="m1", confidence=0.9,
            matched_keywords="FATAL", created_at=now - timedelta(minutes=5),
        )
        held = AnalysisEvent(
            container_id="web-1", container_name="web", status="analyzed", classification="critical",
            summary="web crashed again", alert_sent=False,
            alert_error="duplicate alert suppressed by cooldown", created_at=now - timedelta(minutes=4),
        )
        low = AnalysisEvent(
            container_id="web-1", container_name="web", status="analyzed", classification="warning",
            summary="slow", alert_sent=False, created_at=now - timedelta(minutes=3),
        )
        skipped = AnalysisEvent(container_id="web-1", container_name="web", status="skipped",
                                classification="noise", created_at=now - timedelta(minutes=2))
        dedup = AnalysisEvent(container_id="web-1", container_name="web", status="dedup_skipped",
                              classification="noise", created_at=now - timedelta(minutes=1))
        db.session.add_all([alerted, held, low, skipped, dedup])
        db.session.add(ContainerMute(container_name="db", until=now + timedelta(hours=2), reason="ui"))
        db.session.flush()
        db.session.add(LocalIssue(event_id=alerted.id, container_name="web", title="web crashed",
                                  body="b", action="approve", status="open"))
        db.session.commit()
        return alerted.id


# ── J1: glance ────────────────────────────────────────────────────────────


def test_now_page_shows_verdict_attention_and_fleet(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    html = app.test_client().get("/dashboard").get_data(as_text=True)

    assert "need" in html and "attention" in html          # verdict strip
    assert "Needs attention" in html
    assert "duplicate alert suppressed by cooldown" in html  # why it did not reach the phone
    assert "Fleet today" in html
    assert "/containers/web" in html                       # fleet tile links to the drill-down
    # a warning under the threshold is by-design, not "attention"
    assert "below threshold" not in html.split("Fleet today")[0]


def test_now_page_all_clear_when_nothing_pending(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    html = app.test_client().get("/dashboard").get_data(as_text=True)
    assert "Nothing pending" in html
    assert "Sentinel is stopped" in html


# ── J2: Telegram alert → spotlight ────────────────────────────────────────


def test_event_spotlight_has_context_and_actions(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    event_id = _seed(app)
    html = app.test_client().get(f"/insights?container=web&event={event_id}").get_data(as_text=True)

    assert "web crashed" in html
    assert "Alert outcome" in html and "Sent to Telegram" in html
    assert "Log excerpt" in html and "boom" in html
    assert "recent history" in html                 # container history strip
    assert "Analyze again" in html
    assert "Mute 24h" in html
    assert f"/issues?id=" in html                   # issue raised from this event
    assert "/containers/web" in html


def test_spotlight_for_missing_event_is_not_a_500(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    resp = app.test_client().get("/insights?event=999999")
    assert resp.status_code == 200
    assert "Event not found" in resp.get_data(as_text=True)


def test_alert_message_deep_links_the_event():
    from app.models import AnalysisEvent
    from app.services.alerts import AlertService

    text = AlertService._format_message(
        AnalysisEvent(id=7, container_name="web", status="analyzed", classification="critical", summary="s")
    )
    assert "Dashboard: /insights?container=web&event=7" in text


def test_outcome_filter_narrows_the_event_list(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    client = app.test_client()

    held = client.get("/insights?outcome=suppressed").get_data(as_text=True)
    assert "web crashed again" in held
    assert "skipped · prefilter" not in held

    never = client.get("/insights?outcome=never").get_data(as_text=True)
    assert "skipped" in never


# ── J3: container drill-down ──────────────────────────────────────────────


def test_container_page_funnel_explains_every_drop(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    html = app.test_client().get("/containers/web").get_data(as_text=True)

    assert "Why did I (not) get alerted?" in html
    assert "log chunks seen" in html
    assert "matched a keyword" in html
    assert "alerted on Telegram" in html
    assert "Keyword list" in html and "Dedup window" in html      # knob links
    assert "alert cooldown" in html                               # suppression histogram
    assert "Knobs in effect" in html
    assert "Timeline" in html


def test_container_page_for_unknown_container_is_empty_not_broken(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    resp = app.test_client().get("/containers/does-not-exist")
    assert resp.status_code == 200
    assert "No log chunks in this window" in resp.get_data(as_text=True)


def test_container_page_window_filter_is_validated(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    client = app.test_client()
    assert client.get("/containers/web?hours=72").status_code == 200
    assert client.get("/containers/web?hours=99999").status_code == 200  # falls back to 24


def test_funnel_math_matches_event_statuses(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    with app.app_context():
        from app.models import AnalysisEvent, Settings

        events = AnalysisEvent.query.filter_by(container_name="web").all()
        funnel = build_funnel(events, Settings.singleton())

    assert funnel.total_chunks == 5
    assert funnel.alerted == 1
    stages = {s.key: s for s in funnel.stages}
    assert stages["seen"].count == 5 and stages["seen"].dropped == 1        # prefilter
    assert stages["keyword"].dropped == 1                                   # dedup
    assert stages["analyzed"].dropped == 1                                  # warning below threshold
    assert stages["eligible"].dropped == 1                                  # cooldown suppression
    assert funnel.suppressions[0][0] == "alert cooldown"


# ── J4: setup ─────────────────────────────────────────────────────────────


def test_setup_stepper_shows_until_complete(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    html = app.test_client().get("/dashboard").get_data(as_text=True)
    assert "Get set up" in html
    assert "0 / 3 done" in html
    assert "Detect chat id" in html


def test_setup_hidden_once_configured_but_reopenable(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    from app.extensions import db
    from app.models import SentinelState, Settings
    from app.time_utils import utcnow_naive

    with app.app_context():
        state = SentinelState.singleton()
        state.enabled = True
        state.llm_last_test_ok_at = utcnow_naive()
        settings = Settings.singleton()
        settings.telegram_token = "123:abc"
        settings.telegram_chat_id = "42"
        db.session.commit()

    client = app.test_client()
    assert "Get set up" not in client.get("/dashboard").get_data(as_text=True)
    assert "Get set up" in client.get("/dashboard?setup=1").get_data(as_text=True)


def test_detect_chat_requires_token_then_reports_last_seen(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    client = app.test_client()

    resp = client.get("/api/telegram/detect-chat")
    assert resp.status_code == 400
    assert "token" in resp.get_json()["error"]

    from app.extensions import db
    from app.models import Settings

    with app.app_context():
        Settings.singleton().telegram_token = "123:abc"
        db.session.commit()

    assert client.get("/api/telegram/detect-chat").status_code == 404  # nothing seen yet

    services = app.extensions["services"]
    services.telegram_bot.last_seen_chat = {"chat_id": "99", "type": "private", "title": "op", "seen_at": "x"}
    body = client.get("/api/telegram/detect-chat").get_json()
    assert body == {"ok": True, "chat_id": "99", "type": "private", "title": "op", "seen_at": "x"}


def test_bot_records_last_seen_chat_even_when_unauthorised(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    bot = app.extensions["services"].telegram_bot
    with app.app_context():
        bot._dispatch({"message": {"chat": {"id": 555, "type": "private", "title": "me"}, "text": "/start"}}, "tok")
    assert bot.last_seen_chat["chat_id"] == "555"


# ── J5: tuning feedback ───────────────────────────────────────────────────


def test_settings_shows_what_each_knob_did(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    html = app.test_client().get("/settings").get_data(as_text=True)

    assert "at a glance" in html
    assert "dropped by keyword prefilter" in html
    assert "duplicates skipped" in html
    assert "alerts held back" in html
    assert "Mutes &amp; exclusions" in html
    assert "Re-run setup" in html


def test_reports_page_has_weekly_review_strip(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    html = app.test_client().get("/reports").get_data(as_text=True)
    assert "Last 7 days" in html
    assert "alerts sent" in html
    assert "Triage open issues" in html


# ── J6: model tinkering ───────────────────────────────────────────────────


def test_issue_detail_has_compare_board_and_source_event(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    _seed(app)
    with app.app_context():
        from app.models import LocalIssue

        issue_id = LocalIssue.query.first().id
    html = app.test_client().get(f"/issues?id={issue_id}").get_data(as_text=True)

    assert "compare verdicts" in html
    assert "data-tryllm-runs" in html
    assert "data-tryllm-compare" in html
    assert "source event" in html


def test_prompt_studio_shows_default_alongside_editor(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    html = app.test_client().get("/prompts").get_data(as_text=True)
    assert "Side by side" in html
    assert "data-prompt-default" in html
    assert "Triage · task" in html


# ── pipeline_view unit coverage ───────────────────────────────────────────


def test_explain_status_and_suppression_are_plain_english():
    assert "keyword" in explain_status("skipped")["why"].lower()
    assert explain_status("dedup_skipped")["anchor"] == "limits"
    assert explain_suppression("muted until 2026-01-01")["label"] == "muted"
    assert explain_suppression("confidence 0.4 below alert_min_confidence 0.5")["label"] == "confidence gate"
    assert explain_suppression(None) is None
    assert explain_suppression("something new")["label"] == "not delivered"


def test_alert_outcome_covers_sent_suppressed_below_and_never(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        from app.models import AnalysisEvent, Settings

        settings = Settings.singleton()
        settings.alert_min_classification = "critical"

        sent = AnalysisEvent(status="analyzed", classification="critical", alert_sent=True)
        supp = AnalysisEvent(status="analyzed", classification="critical", alert_sent=False,
                             alert_error="global rate limit exceeded")
        below = AnalysisEvent(status="analyzed", classification="warning", alert_sent=False)
        never = AnalysisEvent(status="skipped", classification="noise", alert_sent=False)

        assert alert_outcome(sent, settings)["kind"] == "sent"
        assert alert_outcome(supp, settings)["kind"] == "suppressed"
        assert alert_outcome(supp, settings)["anchor"] == "limits"
        assert alert_outcome(below, settings)["kind"] == "below"
        assert alert_outcome(never, settings)["kind"] == "never"


def test_every_event_status_has_an_explanation():
    from app.web.routes import EVENT_STATUSES

    for status in EVENT_STATUSES:
        assert explain_status(status)["why"], status
