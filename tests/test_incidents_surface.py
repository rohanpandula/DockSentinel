"""Surface tests for the incident layer: JSON API, /incidents page, nav badge
and the Telegram /incidents + /resolve commands.

Rows are seeded straight through db.session so these tests do not depend on the
incident engine (track-g) having landed.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.extensions import db
from app.models import Incident
from app.time_utils import utcnow_naive


def _mk(session, **kwargs) -> Incident:
    now = utcnow_naive()
    defaults = dict(
        signature="web:oom",
        container_name="web",
        classification="critical",
        title="web keeps OOMing",
        status="open",
        first_seen_at=now - timedelta(minutes=42),
        last_seen_at=now,
        occurrence_count=7,
        telegram_chat_id="123",
        telegram_message_id=555,
        notify_count=3,
    )
    defaults.update(kwargs)
    incident = Incident(**defaults)
    session.add(incident)
    session.commit()
    return incident


@pytest.fixture
def seeded(app):
    with app.app_context():
        now = utcnow_naive()
        open_one = _mk(db.session)
        resolved = _mk(
            db.session,
            signature="db:disk",
            container_name="db",
            classification="warning",
            title="db disk pressure",
            status="resolved",
            first_seen_at=now - timedelta(hours=3),
            last_seen_at=now - timedelta(hours=1),
            resolved_at=now - timedelta(minutes=30),
            occurrence_count=2,
            telegram_message_id=None,
            notify_count=1,
        )
        yield {"open_id": open_one.id, "resolved_id": resolved.id}


# ── API ────────────────────────────────────────────────────────────────
def test_api_list_all_and_filtered(client, seeded):
    body = client.get("/api/incidents").get_json()
    assert [i["id"] for i in body["items"]] == [seeded["open_id"], seeded["resolved_id"]]

    open_only = client.get("/api/incidents?status=open").get_json()["items"]
    assert len(open_only) == 1 and open_only[0]["status"] == "open"

    resolved_only = client.get("/api/incidents?status=resolved").get_json()["items"]
    assert len(resolved_only) == 1 and resolved_only[0]["container_name"] == "db"

    assert len(client.get("/api/incidents?limit=1").get_json()["items"]) == 1


def test_api_list_validation(client, seeded):
    bad_status = client.get("/api/incidents?status=nope")
    assert bad_status.status_code == 400
    assert bad_status.get_json() == {"error": "invalid status"}

    for bad in ("0", "501", "abc", "-3"):
        resp = client.get(f"/api/incidents?limit={bad}")
        assert resp.status_code == 400, bad
        assert resp.get_json()["error"] == "invalid limit"


def test_api_get_detail_and_404(client, seeded):
    body = client.get(f"/api/incidents/{seeded['open_id']}").get_json()
    assert body["occurrence_count"] == 7
    assert body["telegram_message_id"] == 555
    assert body["notify_count"] == 3
    # 42 minutes between first_seen_at and last_seen_at
    assert 2500 <= body["duration_seconds"] <= 2540

    missing = client.get("/api/incidents/99999")
    assert missing.status_code == 404
    assert missing.get_json() == {"error": "not found"}


def test_api_resolve_then_409(client, seeded, app):
    resp = client.post(f"/api/incidents/{seeded['open_id']}/resolve")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None

    again = client.post(f"/api/incidents/{seeded['open_id']}/resolve")
    assert again.status_code == 409
    assert again.get_json() == {"error": "already resolved"}

    assert client.post("/api/incidents/99999/resolve").status_code == 404

    with app.app_context():
        assert db.session.get(Incident, seeded["open_id"]).status == "resolved"


# ── Web UI ─────────────────────────────────────────────────────────────
def test_incidents_page_lists_open_and_resolved(client, seeded):
    html = client.get("/incidents").get_data(as_text=True)
    assert "Open incidents" in html
    assert "web keeps OOMing" in html
    assert "Recently resolved" in html
    assert "db disk pressure" in html
    assert "×7" in html
    assert "Pick an incident" in html  # no detail selected yet


def test_incidents_page_detail_shows_timeline_and_actions(client, seeded):
    html = client.get(f"/incidents?id={seeded['open_id']}").get_data(as_text=True)
    assert f"#{seeded['open_id']} · web keeps OOMing" in html
    assert "Occurrences" in html and "Notifications" in html
    assert "first seen" in html and "last seen" in html
    assert "Resolve" in html
    assert "Mute container 24h" in html
    assert "/containers/web" in html  # drill-down link
    assert "container=web" in html    # filtered events link

    resolved_html = client.get(f"/incidents?id={seeded['resolved_id']}").get_data(as_text=True)
    assert "Resolved " in resolved_html


def test_incidents_page_resolve_action(client, seeded, app):
    resp = client.post(f"/incidents/{seeded['open_id']}/resolve")
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Incident, seeded["open_id"]).status == "resolved"


def test_nav_badge_shows_open_count_only_when_nonzero(client, app, seeded):
    html = client.get("/dashboard").get_data(as_text=True)
    assert 'class="nav__badge"' in html
    assert "Incidents" in html
    assert "1 open" in html  # badge title
    # dashboard block for open incidents
    assert "data-open-incidents" in html

    client.post(f"/api/incidents/{seeded['open_id']}/resolve")
    html = client.get("/dashboard").get_data(as_text=True)
    assert 'class="nav__badge"' not in html
    assert "data-open-incidents" not in html
    assert "Incidents" in html  # nav entry still present


def test_dashboard_keeps_recent_events_block(client, seeded):
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Recent events" in html
    assert "Skipped (prefilter)" in html


# ── Telegram ───────────────────────────────────────────────────────────
class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.answers: list[str] = []
        self.markup_edits: list = []

    def send_message(self, token, chat_id, text, reply_to_message_id=None, reply_markup=None):
        self.sent.append((chat_id, text))
        return True, None, 900 + len(self.sent)

    def answer_callback_query(self, token, callback_query_id, text=""):
        self.answers.append(text)

    def edit_message_reply_markup(self, token, chat_id, message_id, reply_markup=None):
        self.markup_edits.append((chat_id, message_id))


def _bot(app, notifier):
    from app.services.telegram_bot import TelegramBotService

    return TelegramBotService(
        app=app,
        notifier=notifier,
        settings_repo=app.extensions["services"].settings_repo,
        event_repo=app.extensions["services"].event_repo,
        issue_repo=app.extensions["services"].issue_repo,
        prompt_repo=app.extensions["services"].prompt_repo,
        llm_call_service=app.extensions["services"].llm_call,
        mute_repo=app.extensions["services"].mute_repo,
    )


def test_telegram_incidents_command(app, seeded):
    notifier = FakeNotifier()
    bot = _bot(app, notifier)
    with app.app_context():
        assert bot._handle_command("/incidents", "123", "tok", 1) is True
    chat, text = notifier.sent[-1]
    assert chat == "123"
    assert text.startswith("🔥 Open incidents:")
    assert f"#{seeded['open_id']} · web · ×7 · 42m · web keeps OOMing" in text
    # resolved incidents are not listed
    assert "db disk pressure" not in text


def test_telegram_incidents_command_when_empty(app):
    notifier = FakeNotifier()
    bot = _bot(app, notifier)
    with app.app_context():
        bot._handle_command("/incidents@docksentinel_bot", "123", "tok", 1)
    assert notifier.sent[-1][1] == "No open incidents"


def test_telegram_resolve_command(app, seeded):
    notifier = FakeNotifier()
    bot = _bot(app, notifier)
    with app.app_context():
        bot._handle_command(f"/resolve {seeded['open_id']}", "123", "tok", 1)
        assert "RESOLVED" in notifier.sent[-1][1]
        assert db.session.get(Incident, seeded["open_id"]).status == "resolved"

        bot._handle_command(f"/resolve {seeded['open_id']}", "123", "tok", 1)
        assert "already resolved" in notifier.sent[-1][1]

        bot._handle_command("/resolve 99999", "123", "tok", 1)
        assert "not found" in notifier.sent[-1][1]

        bot._handle_command("/resolve", "123", "tok", 1)
        assert notifier.sent[-1][1] == "Usage: /resolve <incident_id>"


def test_telegram_mutes_command_still_works(app):
    notifier = FakeNotifier()
    bot = _bot(app, notifier)
    with app.app_context():
        bot._handle_command("/mutes", "123", "tok", 1)
        assert "No containers are muted" in notifier.sent[-1][1]
        bot.mute_repo.upsert("web", utcnow_naive() + timedelta(hours=1), "test")
        db.session.commit()
        bot._handle_command("/mutes", "123", "tok", 1)
        assert "web" in notifier.sent[-1][1]
        bot._handle_command("/unmute web", "123", "tok", 1)
        assert "UNMUTED" in notifier.sent[-1][1]


def test_telegram_resolve_callback(app, seeded):
    notifier = FakeNotifier()
    bot = _bot(app, notifier)
    cq = {
        "id": "cq1",
        "data": f"resolve:{seeded['open_id']}",
        "message": {"chat": {"id": "123"}, "message_id": 77},
    }
    with app.app_context():
        bot._handle_callback(cq, "tok")
        assert db.session.get(Incident, seeded["open_id"]).status == "resolved"
        assert notifier.markup_edits == [("123", 77)]
        assert "resolved" in notifier.answers[-1]

        bot._handle_callback(cq, "tok")
        assert notifier.answers[-1] == "Already resolved"
