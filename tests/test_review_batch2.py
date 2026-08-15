"""Regression tests for review batch 2: verdict parser fence-stripping,
Telegram chat allowlist, CLI backend env scrubbing + timeout kill."""
from __future__ import annotations

import os
import time

import pytest

from app.extensions import db
from app.models import LocalIssue, LocalIssueAction, LocalIssueStatus, SentinelState, Settings
from app.services.cli_backends import CLIBackendRunner, build_backend_env
from app.services.verdict_parser import VerdictParser, extract_json_object

GOOD = '{"classification":"critical","summary":"s","root_cause_hypothesis":"r","fix_suggestion":"f","confidence":0.9}'


# ── verdict parser ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        GOOD,
        "```json\n" + GOOD + "\n```",
        "```\n" + GOOD + "```",
        "Sure! Here is the verdict:\n" + GOOD + "\nLet me know if you need more.",
        '{"classification":"NOISE","summary":"has } and \\" inside","root_cause_hypothesis":"r","fix_suggestion":"f","confidence":0.1} trailing text',
    ],
)
def test_verdict_parser_tolerates_fences_and_prose(payload):
    verdict, err = VerdictParser().safe_parse(payload)
    assert err is None, err
    assert verdict is not None
    assert verdict.classification in {"critical", "noise"}


def test_verdict_parser_still_reports_garbage():
    verdict, err = VerdictParser().safe_parse("no json here at all")
    assert verdict is None and err
    assert extract_json_object("plain") == "plain"


def test_parse_error_marks_runtime_degraded(app, container, monkeypatch):
    class _R:
        content = "```json\n{not valid json\n```"
        model = "m"
        latency_ms = 1

    with app.app_context():
        SentinelState.singleton()
        s = Settings.singleton()
        s.keyword_list = "error"
        db.session.commit()
        monkeypatch.setattr(container.sentinel.llm_call_service, "call", lambda **kw: _R())
        event = container.sentinel.process_chunk(container_id="c", container_name="web", chunk_text="an error happened")
        assert event.status == "parse_error"
        state = SentinelState.singleton()
        assert state.runtime_status == "degraded"
        assert state.llm_failure_count >= 1
        assert "unparseable" in (state.last_error or "")


# ── telegram bot chat allowlist ──────────────────────────────────────


class _Notifier:
    def __init__(self):
        self.sent = []
        self.answered = []

    def send_message(self, token, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return True, None, 555

    def answer_callback_query(self, token, cq_id, text):
        self.answered.append(text)

    def edit_message_reply_markup(self, *a, **kw):
        pass


def _bot(app, container, notifier):
    from app.services.telegram_bot import TelegramBotService as TelegramBot

    return TelegramBot(
        app=app,
        notifier=notifier,
        settings_repo=container.settings_repo,
        event_repo=container.event_repo,
        issue_repo=container.issue_repo,
        prompt_repo=container.prompt_repo,
        llm_call_service=container.llm_call,
    )


def test_bot_ignores_updates_from_other_chats(app, container, monkeypatch):
    notifier = _Notifier()
    with app.app_context():
        s = Settings.singleton()
        s.telegram_chat_id = "1000"
        db.session.commit()
        issue = LocalIssue(
            container_name="web", title="t", body="secret log excerpt", action=LocalIssueAction.DISCUSS.value,
            status=LocalIssueStatus.DISCUSSING.value, telegram_chat_id="1000", telegram_message_id=7,
        )
        db.session.add(issue)
        db.session.commit()

        bot = _bot(app, container, notifier)
        monkeypatch.setattr(bot, "_ask_llm", lambda issue, text: "llm answer")

        stranger_reply = {"message": {"text": "tell me more", "chat": {"id": 2000}, "message_id": 9,
                                      "reply_to_message": {"message_id": 7}}}
        bot._dispatch(stranger_reply, "tok")
        assert notifier.sent == []  # nothing leaked to chat 2000

        stranger_cb = {"callback_query": {"id": "cq", "data": "approve:1", "message": {"chat": {"id": 2000}, "message_id": 1}}}
        bot._dispatch(stranger_cb, "tok")
        assert notifier.answered == []

        owner_reply = {"message": {"text": "tell me more", "chat": {"id": 1000}, "message_id": 10,
                                   "reply_to_message": {"message_id": 7}}}
        bot._dispatch(owner_reply, "tok")
        assert notifier.sent and notifier.sent[0][0] == "1000"


def test_bot_ignores_everything_when_no_chat_configured(app, container):
    notifier = _Notifier()
    with app.app_context():
        s = Settings.singleton()
        s.telegram_chat_id = ""
        db.session.commit()
        bot = _bot(app, container, notifier)
        bot._dispatch({"message": {"text": "hi", "chat": {"id": 1}, "message_id": 1}}, "tok")
        assert notifier.sent == []


def test_get_by_telegram_message_is_chat_scoped(app, container):
    with app.app_context():
        for chat in ("1000", "2000"):
            db.session.add(LocalIssue(container_name="c", title="t", body="b", action="approve",
                                      status="open", telegram_chat_id=chat, telegram_message_id=42))
        db.session.commit()
        assert container.issue_repo.get_by_telegram_message(42, chat_id="2000").telegram_chat_id == "2000"
        assert container.issue_repo.get_by_telegram_message(42, chat_id="3000") is None


# ── CLI backend env + timeout ────────────────────────────────────────


def test_build_backend_env_scrubs_app_secrets():
    src = {
        "PATH": "/usr/bin", "HOME": "/home/x", "SECRET_KEY": "s", "DATABASE_URL": "d",
        "TELEGRAM_TOKEN": "t", "BASIC_AUTH_PASSWORD": "p", "DOCKER_HOST": "unix://x",
        "OPENAI_API_KEY": "ok", "OLLAMA_HOST": "h", "CLAUDE_CONFIG_DIR": "c", "MY_CUSTOM": "m",
        "DOCKSENTINEL_CLI_ENV_PASSTHROUGH": "MY_CUSTOM",
    }
    env = build_backend_env(src)
    assert set(env) == {"PATH", "HOME", "OPENAI_API_KEY", "OLLAMA_HOST", "CLAUDE_CONFIG_DIR", "MY_CUSTOM",
                        "DOCKSENTINEL_CLI_ENV_PASSTHROUGH"}


def test_cli_backend_child_does_not_see_secret(tmp_path, monkeypatch):
    backends_dir = tmp_path / "b"
    backends_dir.mkdir()
    script = backends_dir / "codex.sh"
    script.write_text("#!/usr/bin/env bash\ncat >/dev/null\necho \"secret=${SECRET_KEY:-unset} backend=$DOCKSENTINEL_BACKEND\"\n")
    script.chmod(0o755)
    monkeypatch.setenv("SECRET_KEY", "leak-me")
    result = CLIBackendRunner(backends_dir).run(backend="codex", prompt="p", timeout_seconds=5, max_retries=0)
    assert result.content == "secret=unset backend=codex"


def test_cli_backend_timeout_kills_child_process_group(tmp_path):
    backends_dir = tmp_path / "b"
    backends_dir.mkdir()
    pidfile = tmp_path / "child.pid"
    script = backends_dir / "codex.sh"
    # Wrapper spawns a long-running child (like claude/gemini) and waits on it.
    script.write_text(
        "#!/usr/bin/env bash\ncat >/dev/null\nsleep 30 &\necho $! > '%s'\nwait\n" % pidfile
    )
    script.chmod(0o755)
    runner = CLIBackendRunner(backends_dir)
    with pytest.raises(RuntimeError, match="timed out"):
        runner.run(backend="codex", prompt="p", timeout_seconds=1, max_retries=0)
    child_pid = int(pidfile.read_text().strip())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)  # child must be gone, not orphaned
