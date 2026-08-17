"""Per-container alert mutes: repo, AlertService gate, API, web routes, Telegram."""
from __future__ import annotations

from datetime import timedelta

from app.extensions import db
from app.models import AnalysisEvent, ContainerMute, LocalIssue, Settings
from app.services.alerts import AlertService
from app.time_utils import utcnow_naive


class _Strategy:
    def __init__(self):
        self.sent = []

    def send(self, message, config, reply_markup=None):
        self.sent.append((message, reply_markup))
        return True, None, 1


class _EventRepo:
    def find_recent_alert_for_container(self, *a, **k):
        return None

    def count_recent_alerts(self, *a, **k):
        return 0


def _cfg():
    from app.config_objects import AlertConfig

    return AlertConfig(
        telegram_token="t", telegram_chat_id="c", cooldown_minutes=0,
        rate_limit_count=100, rate_limit_window_seconds=60,
    )


# ── repository ─────────────────────────────────────────────────


def test_mute_repo_upsert_active_expired_delete(app, container):
    with app.app_context():
        now = utcnow_naive()
        repo = container.mute_repo
        m = repo.upsert("web", now + timedelta(hours=1), "test")
        db.session.commit()
        assert repo.get_active("web", now).id == m.id
        assert [x.container_name for x in repo.list_active(now)] == ["web"]

        # upsert replaces rather than duplicating
        repo.upsert("web", None, "forever")
        db.session.commit()
        assert ContainerMute.query.filter_by(container_name="web").count() == 1
        assert repo.get_active("web", now + timedelta(days=400)) is not None

        # expired mutes are not active
        repo.upsert("db", now - timedelta(minutes=1), None)
        db.session.commit()
        assert repo.get_active("db", now) is None
        assert [x.container_name for x in repo.list_active(now)] == ["web"]

        assert repo.delete("web") is True
        assert repo.delete("web") is False
        db.session.commit()
        assert repo.get_active("web", now) is None


# ── AlertService gate ──────────────────────────────────────────


def test_alert_service_skips_muted_container(app, container):
    with app.app_context():
        strategy = _Strategy()
        svc = AlertService(strategy=strategy, event_repo=_EventRepo(), mute_repo=container.mute_repo)
        event = AnalysisEvent(id=1, container_id="c1", container_name="web", classification="critical", summary="s")

        sent, err, _ = svc.maybe_send(event, _cfg())
        assert sent is True and strategy.sent

        container.mute_repo.upsert("web", utcnow_naive() + timedelta(hours=24), "ui")
        db.session.commit()
        sent, err, _ = svc.maybe_send(event, _cfg())
        assert sent is False and err.startswith("muted until ")
        assert len(strategy.sent) == 1

        sent, err, _ = svc.send_plain("restart storm", _cfg(), container_name="web")
        assert sent is False and err.startswith("muted until ")
        # send_plain without a container is unaffected
        sent, _, _ = svc.send_plain("hello", _cfg())
        assert sent is True

        container.mute_repo.upsert("web", None, None)
        db.session.commit()
        _, err, _ = svc.maybe_send(event, _cfg())
        assert err == "muted until indefinitely"


def test_alert_service_without_mute_repo_still_sends():
    strategy = _Strategy()
    svc = AlertService(strategy=strategy, event_repo=_EventRepo())
    event = AnalysisEvent(id=7, container_id="c1", container_name="web", classification="critical")
    assert svc.maybe_send(event, _cfg())[0] is True


# ── keyboard + compact message ─────────────────────────────────


def test_keyboard_has_mute_button_after_existing_three():
    kb = AlertService._build_keyboard(9)["inline_keyboard"][0]
    assert [b["callback_data"] for b in kb] == ["reject:9", "approve:9", "discuss:9", "mute:9"]
    assert kb[3]["text"] == "🔕 Mute 24h"


def test_format_message_is_compact():
    event = AnalysisEvent(
        id=123, container_name="web", classification="critical", confidence=0.82,
        summary="OOM " * 5,
        root_cause_hypothesis="x" * 500,
        fix_suggestion="\n".join(f"step {i} " + "y" * 150 for i in range(6)),
        chunk_excerpt="\n".join(f"line{i} " + "z" * 200 for i in range(10)),
    )
    text = AlertService._format_message(event)
    lines = text.splitlines()
    assert len(lines) <= 13
    root = next(ln for ln in lines if ln.startswith("ROOT CAUSE"))
    assert len(root) <= len("ROOT CAUSE · ") + 240
    assert "FIX (model-generated — verify)" in text
    fix_block = text.split("FIX (model-generated — verify)\n")[1].split("LOG EXCERPT")[0]
    assert len(fix_block.strip().splitlines()) <= 3 and len(fix_block) <= 302
    excerpt = text.split("LOG EXCERPT\n")[1].splitlines()[:-1]
    assert len(excerpt) == 3 and all(len(ln) <= 120 for ln in excerpt)
    assert "line9 " in text and "line6 " not in text
    # The dashboard link deep-links the event so the UI opens it in the spotlight view.
    assert lines[-1] == "Confidence: 0.82 · Event ID: 123 · Dashboard: /insights?container=web&event=123"


# ── API ────────────────────────────────────────────────────────


def test_mutes_api_crud(client):
    r = client.get("/api/mutes")
    assert r.status_code == 200 and r.get_json() == {"items": []}

    r = client.put("/api/mutes/web", json={"hours": 24, "reason": "noisy"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["container_name"] == "web" and body["until"] is not None and body["reason"] == "noisy"

    r = client.put("/api/mutes/db", json={"hours": None})
    assert r.status_code == 200 and r.get_json()["until"] is None

    r = client.put("/api/mutes/db", json={"hours": 0})
    assert r.status_code == 400
    r = client.put("/api/mutes/db", json={"hours": 9000})
    assert r.status_code == 400

    names = [m["container_name"] for m in client.get("/api/mutes").get_json()["items"]]
    assert names == ["db", "web"]

    assert client.delete("/api/mutes/web").get_json() == {"deleted": True}
    assert client.delete("/api/mutes/web").status_code == 404
    names = [m["container_name"] for m in client.get("/api/mutes").get_json()["items"]]
    assert names == ["db"]


# ── web routes / templates ─────────────────────────────────────


def test_web_mute_routes_and_badges(app, client):
    with app.app_context():
        ev = AnalysisEvent(container_id="c1", container_name="web", status="analyzed",
                           classification="critical", summary="boom")
        db.session.add(ev)
        db.session.flush()
        db.session.add(LocalIssue(event_id=ev.id, container_name="web", title="t", body="b",
                                  action="approve", status="open"))
        db.session.commit()
        issue_id = LocalIssue.query.first().id

    html = client.get("/insights").get_data(as_text=True)
    assert "Mute container 24h" in html and "muted until" not in html

    r = client.post("/mutes/web?hours=24", data={"next": "/insights"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/insights")

    html = client.get("/insights").get_data(as_text=True)
    assert "muted until" in html and "Unmute web" in html
    html = client.get(f"/issues?id={issue_id}").get_data(as_text=True)
    assert "muted until" in html and ">Unmute<" in html
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Muted containers" in html and "web" in html and ">Unmute<" in html

    r = client.post("/mutes/web/delete", data={"next": "/dashboard"})
    assert r.status_code == 302
    html = client.get("/dashboard").get_data(as_text=True)
    assert "No containers are muted" in html
    html = client.get(f"/issues?id={issue_id}").get_data(as_text=True)
    assert "Mute container 24h" in html

    # open redirect is refused
    r = client.post("/mutes/web", data={"next": "https://evil.example/"})
    assert r.headers["Location"].endswith("/dashboard")


# ── Telegram bot ───────────────────────────────────────────────


class _Notifier:
    def __init__(self):
        self.sent = []
        self.answered = []
        self.markups = []

    def send_message(self, token, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return True, None, 555

    def answer_callback_query(self, token, cq_id, text):
        self.answered.append(text)

    def edit_message_reply_markup(self, token, chat_id, message_id, reply_markup=None):
        self.markups.append(reply_markup)


def _bot(app, container, notifier):
    from app.services.telegram_bot import TelegramBotService

    return TelegramBotService(
        app=app, notifier=notifier, settings_repo=container.settings_repo,
        event_repo=container.event_repo, issue_repo=container.issue_repo,
        prompt_repo=container.prompt_repo, llm_call_service=container.llm_call,
        mute_repo=container.mute_repo,
    )


def test_bot_mute_callback_and_commands(app, container):
    notifier = _Notifier()
    with app.app_context():
        s = Settings.singleton()
        s.telegram_chat_id = "1000"
        ev = AnalysisEvent(container_id="c1", container_name="web", status="analyzed", classification="critical")
        db.session.add(ev)
        db.session.commit()
        bot = _bot(app, container, notifier)

        cb = {"callback_query": {"id": "cq", "data": f"mute:{ev.id}",
                                 "message": {"chat": {"id": 1000}, "message_id": 1}}}
        bot._dispatch(cb, "tok")
        assert notifier.answered == ["Muted web for 24h"]
        assert notifier.markups == [{"inline_keyboard": []}]
        assert notifier.sent[-1][1].startswith("🔕 MUTED · web · until ")
        mute = container.mute_repo.get_active("web", utcnow_naive())
        assert mute is not None and mute.reason == "telegram"
        assert timedelta(hours=23) < mute.until - utcnow_naive() <= timedelta(hours=24)

        bot._dispatch({"message": {"text": "/mutes", "chat": {"id": 1000}, "message_id": 2}}, "tok")
        assert "web" in notifier.sent[-1][1] and "Muted containers" in notifier.sent[-1][1]

        bot._dispatch({"message": {"text": "/unmute web", "chat": {"id": 1000}, "message_id": 3}}, "tok")
        assert notifier.sent[-1][1] == "🔔 UNMUTED · web"
        assert container.mute_repo.get_active("web", utcnow_naive()) is None

        bot._dispatch({"message": {"text": "/unmute web", "chat": {"id": 1000}, "message_id": 4}}, "tok")
        assert notifier.sent[-1][1] == "web is not muted."
        bot._dispatch({"message": {"text": "/mutes", "chat": {"id": 1000}, "message_id": 5}}, "tok")
        assert notifier.sent[-1][1] == "🔔 No containers are muted."

        # stranger chats are still ignored
        n = len(notifier.sent)
        bot._dispatch({"message": {"text": "/mutes", "chat": {"id": 2000}, "message_id": 6}}, "tok")
        assert len(notifier.sent) == n
