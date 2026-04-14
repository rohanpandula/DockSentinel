from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from flask import Flask

from app.config_objects import LLMConfig
from app.extensions import db
from app.models import (
    AnalysisEvent,
    LocalIssue,
    LocalIssueAction,
    LocalIssueStatus,
    PromptKey,
)
from app.repositories.analysis_events import AnalysisEventRepository
from app.repositories.local_issues import LocalIssueRepository
from app.repositories.prompts import PromptRepository
from app.repositories.settings import SettingsRepository
from app.services.llm_call import LLMCallService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


class TelegramBotService:
    """Long-polling loop that handles inline-keyboard callbacks and
    follow-up discussion messages from the Telegram chat.

    Flow:
      - Alert arrives in chat with [Reject] [Approve] [Discuss] buttons.
      - Tap → Telegram emits a `callback_query` we receive here.
      - Reject: LocalIssue recorded with status=rejected, keyboard stripped.
      - Approve: LocalIssue recorded with status=open, keyboard stripped,
        reply posted with the issue number.
      - Discuss: LocalIssue recorded with status=discussing, bot sends a
        prompt "Reply with your question". The user's reply (matched by
        `reply_to_message_id`) is routed to the LLM with the event context,
        and the answer is posted back in-thread.
    """

    def __init__(
        self,
        app: Flask,
        notifier: TelegramNotifier,
        settings_repo: SettingsRepository,
        event_repo: AnalysisEventRepository,
        issue_repo: LocalIssueRepository,
        prompt_repo: PromptRepository,
        llm_call_service: LLMCallService,
    ) -> None:
        self._app = app
        self.notifier = notifier
        self.settings_repo = settings_repo
        self.event_repo = event_repo
        self.issue_repo = issue_repo
        self.prompt_repo = prompt_repo
        self.llm_call_service = llm_call_service
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._offset = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="telegram-bot", daemon=True)
        self._thread.start()
        logger.info("telegram bot polling started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                with self._app.app_context():
                    token = self._token()
                if not token:
                    self._stop.wait(10)
                    continue
                updates = self.notifier.get_updates(token, offset=self._offset, timeout=25)
                for update in updates:
                    update_id = int(update.get("update_id", 0))
                    self._offset = max(self._offset, update_id + 1)
                    try:
                        with self._app.app_context():
                            self._dispatch(update, token)
                    except Exception:
                        logger.exception("telegram bot update dispatch failed")
            except Exception:
                logger.exception("telegram bot polling error")
                self._stop.wait(5)

    def _token(self) -> str:
        settings = self.settings_repo.get()
        return (settings.telegram_token or "").strip()

    def _dispatch(self, update: dict[str, Any], token: str) -> None:
        if "callback_query" in update:
            self._handle_callback(update["callback_query"], token)
        elif "message" in update:
            self._handle_message(update["message"], token)

    # ── Callback: Reject / Approve / Discuss ────────────────────
    def _handle_callback(self, cq: dict[str, Any], token: str) -> None:
        cq_id = cq.get("id", "")
        data = cq.get("data", "")
        message = cq.get("message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        message_id = message.get("message_id")

        if ":" not in data:
            self.notifier.answer_callback_query(token, cq_id, "Invalid action")
            return
        action, _, raw_event_id = data.partition(":")
        try:
            event_id = int(raw_event_id)
        except ValueError:
            self.notifier.answer_callback_query(token, cq_id, "Invalid event id")
            return

        event = self.event_repo.get(event_id) if hasattr(self.event_repo, "get") else db.session.get(AnalysisEvent, event_id)
        if event is None:
            self.notifier.answer_callback_query(token, cq_id, "Event not found")
            return

        if action == "reject":
            issue = self._create_issue(event, LocalIssueAction.REJECT, LocalIssueStatus.REJECTED, chat_id, message_id)
            db.session.commit()
            self.notifier.edit_message_reply_markup(token, chat_id, message_id, reply_markup={"inline_keyboard": []})
            self.notifier.answer_callback_query(token, cq_id, "Rejected")
            self.notifier.send_message(
                token, chat_id,
                f"✕ REJECTED · Issue #{issue.id} recorded.",
                reply_to_message_id=message_id,
            )
        elif action == "approve":
            issue = self._create_issue(event, LocalIssueAction.APPROVE, LocalIssueStatus.OPEN, chat_id, message_id)
            db.session.commit()
            self.notifier.edit_message_reply_markup(token, chat_id, message_id, reply_markup={"inline_keyboard": []})
            self.notifier.answer_callback_query(token, cq_id, f"Issue #{issue.id} created")
            self.notifier.send_message(
                token, chat_id,
                f"✓ APPROVED · Issue #{issue.id} open locally.\nQuery it at /issues.",
                reply_to_message_id=message_id,
            )
        elif action == "discuss":
            issue = self._create_issue(event, LocalIssueAction.DISCUSS, LocalIssueStatus.DISCUSSING, chat_id, message_id)
            db.session.commit()
            self.notifier.edit_message_reply_markup(token, chat_id, message_id, reply_markup={"inline_keyboard": []})
            ok, _, reply_id = self.notifier.send_message(
                token, chat_id,
                f"💬 DISCUSSING · Issue #{issue.id}\nReply to THIS message with your question about this alert.",
                reply_to_message_id=message_id,
            )
            if ok and reply_id is not None:
                issue.telegram_message_id = reply_id
                db.session.commit()
            self.notifier.answer_callback_query(token, cq_id, "Ask a follow-up")
        else:
            self.notifier.answer_callback_query(token, cq_id, "Unknown action")

    # ── Text message: discussion follow-up ──────────────────────
    def _handle_message(self, msg: dict[str, Any], token: str) -> None:
        text = (msg.get("text") or "").strip()
        if not text:
            return
        chat_id = str(msg.get("chat", {}).get("id", ""))
        reply_to = msg.get("reply_to_message") or {}
        reply_to_id = reply_to.get("message_id")

        issue: Optional[LocalIssue] = None
        if reply_to_id:
            issue = self.issue_repo.get_by_telegram_message(int(reply_to_id))
        if issue is None:
            issue = self.issue_repo.get_latest_discussing_for_chat(chat_id)
        if issue is None or issue.status != LocalIssueStatus.DISCUSSING.value:
            return  # unrelated message

        issue.append_discussion("user", text)
        db.session.commit()

        answer = self._ask_llm(issue, text)
        issue.append_discussion("assistant", answer)
        db.session.commit()

        ok, _, reply_id = self.notifier.send_message(
            token, chat_id, answer,
            reply_to_message_id=msg.get("message_id"),
        )
        if ok and reply_id is not None:
            issue.telegram_message_id = reply_id
            db.session.commit()

    # ── Helpers ─────────────────────────────────────────────────
    def _create_issue(
        self,
        event: AnalysisEvent,
        action: LocalIssueAction,
        status: LocalIssueStatus,
        chat_id: str,
        message_id: Optional[int],
    ) -> LocalIssue:
        title = (event.summary or f"{event.container_name}: critical alert").strip()[:500]
        body_parts: list[str] = [
            f"# {title}",
            "",
            f"**Container:** {event.container_name}",
            f"**Classification:** {event.classification or 'critical'}",
            f"**Status:** {event.status or 'analyzed'}",
            "",
            "## Root cause hypothesis",
            event.root_cause_hypothesis or "—",
            "",
            "## Suggested fix",
            event.fix_suggestion or "—",
        ]
        if event.chunk_excerpt:
            body_parts += ["", "## Log excerpt", "```", event.chunk_excerpt[:2000], "```"]
        issue = LocalIssue(
            event_id=event.id,
            container_name=event.container_name or "",
            title=title,
            body="\n".join(body_parts),
            status=status.value,
            action=action.value,
            confidence=event.confidence,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
        )
        self.issue_repo.add(issue)
        return issue

    def _ask_llm(self, issue: LocalIssue, user_message: str) -> str:
        settings = self.settings_repo.get()
        try:
            system_prompt = self.prompt_repo.get(PromptKey.SENTINEL_SYSTEM).content
        except Exception:
            system_prompt = "You are an SRE assistant helping triage Docker container issues."

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "system",
                "content": (
                    "You are continuing a live discussion with an operator about a specific "
                    "container alert. Stay focused, give concrete actions, answer only what "
                    "is asked. Keep replies under 1200 characters."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Issue context:\n{issue.body}\n\n"
                    f"Prior discussion:\n{issue.discussion or '(none)'}\n\n"
                    f"Operator asks:\n{user_message}"
                ),
            },
        ]
        try:
            result = self.llm_call_service.call(
                config=LLMConfig.from_settings(settings),
                messages=messages,
                max_tokens=settings.reserved_output_tokens,
            )
            return (result.content or "").strip() or "(empty response)"
        except Exception as exc:  # pragma: no cover - network dependent
            return f"[LLM error: {exc}]"
