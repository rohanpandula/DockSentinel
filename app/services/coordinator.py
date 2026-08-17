from __future__ import annotations

import fcntl
import logging
import os
import threading
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.models import SentinelState, Settings
from app.services.docker_watcher import DockerWatcher
from app.time_utils import utcnow_naive

LOGGER = logging.getLogger(__name__)
BRIEFING_TELEGRAM_MAX_CHARS = 3900


class RuntimeCoordinator:
    def __init__(
        self,
        app,
        sentinel_service,
        briefing_service,
        health_check_interval_seconds: int = 30,
        telegram_bot=None,
        telegram_notifier=None,
        event_repo=None,
        incident_service=None,
    ) -> None:
        self.app = app
        self.sentinel_service = sentinel_service
        self.briefing_service = briefing_service
        self.telegram_bot = telegram_bot
        self.telegram_notifier = telegram_notifier
        self.event_repo = event_repo
        self.incident_service = incident_service

        self._lock_fd = None
        self._scheduler: BackgroundScheduler | None = None
        self._watcher: DockerWatcher | None = None
        self._health_check_interval_seconds = health_check_interval_seconds
        self._health_stop_event = threading.Event()
        self._health_thread: threading.Thread | None = None
        self._started = False

    def _acquire_lock(self) -> bool:
        lock_path = self.app.config["RUNTIME_LOCK_PATH"]
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)

        self._lock_fd = open(lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd.seek(0)
            self._lock_fd.truncate(0)
            self._lock_fd.write(str(os.getpid()))
            self._lock_fd.flush()
            return True
        except BlockingIOError:
            self._lock_fd.close()
            self._lock_fd = None
            return False

    def _release_lock(self) -> None:
        if not self._lock_fd:
            return
        try:
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._lock_fd.close()
        self._lock_fd = None

    def _run_nightly_job(self) -> None:
        with self.app.app_context():
            report = self.briefing_service.generate_report()
            self._push_briefing_to_telegram(report)

    def _push_briefing_to_telegram(self, report) -> None:
        """Send the nightly briefing text to the configured chat (best effort)."""
        if report is None or self.telegram_notifier is None:
            return
        if getattr(report, "status", None) != "generated":
            return
        settings = Settings.singleton()
        token = (settings.telegram_token or "").strip()
        chat_id = (settings.telegram_chat_id or "").strip()
        if not token or not chat_id:
            return
        text = (report.markdown_content or "").strip()
        if not text:
            return
        header = "📋 DockSentinel nightly briefing\n\n"
        body = header + text
        if len(body) > BRIEFING_TELEGRAM_MAX_CHARS:
            body = body[: BRIEFING_TELEGRAM_MAX_CHARS - 1] + "…"
        try:
            ok, error, _ = self.telegram_notifier.send_message(token=token, chat_id=chat_id, text=body)
            if not ok:
                LOGGER.warning("nightly briefing telegram push failed: %s", error)
        except Exception:
            LOGGER.warning("nightly briefing telegram push raised", exc_info=True)

    def _run_prune_job(self) -> None:
        if self.event_repo is None:
            return
        with self.app.app_context():
            settings = Settings.singleton()
            days = max(1, int(getattr(settings, "event_retention_days", 14) or 14))
            cutoff = utcnow_naive() - timedelta(days=days)
            try:
                deleted = self.event_repo.prune(cutoff)
                LOGGER.info("pruned %d analysis events older than %d days", deleted, days)
            except Exception:
                LOGGER.warning("analysis event prune failed", exc_info=True)

    def _run_resolve_incidents_job(self) -> None:
        """Close incidents that have gone quiet (edit their message, post the
        resolve notice). Best effort: a failure here must never kill the
        scheduler thread."""
        if self.incident_service is None:
            return
        with self.app.app_context():
            try:
                resolved = self.incident_service.resolve_stale(utcnow_naive())
                if resolved:
                    LOGGER.info("auto-resolved %d stale incidents", len(resolved))
            except Exception:
                LOGGER.warning("incident auto-resolve failed", exc_info=True)

    def refresh_schedule(self) -> None:
        if self._scheduler is None:
            return

        settings = Settings.singleton()
        trigger = CronTrigger(hour=settings.nightly_hour, minute=settings.nightly_minute)
        self._scheduler.add_job(
            self._run_nightly_job,
            trigger=trigger,
            id="nightly_briefing",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._run_prune_job,
            trigger=CronTrigger(hour=3, minute=15),
            id="prune-events",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._run_resolve_incidents_job,
            trigger=IntervalTrigger(minutes=5),
            id="resolve-incidents",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def trigger_reconcile(self) -> None:
        if self._watcher is not None:
            self._watcher.force_reconcile()

    def active_container_ids(self) -> list[str]:
        if self._watcher is None:
            return []
        return self._watcher.active_container_ids()

    def _restart_watcher(self, dead_thread_name: str) -> bool:
        watcher = self._watcher
        if watcher is None:
            return False

        LOGGER.warning("docker watcher %s thread is not alive; restarting watcher", dead_thread_name)
        try:
            watcher.stop()
            watcher.start()
            watcher.force_reconcile()
            return True
        except Exception:
            LOGGER.warning("failed restarting docker watcher after %s thread failure", dead_thread_name, exc_info=True)
            return False

    def _check_watcher_health_once(self) -> bool:
        watcher = self._watcher
        if watcher is None:
            return False

        event_thread = getattr(watcher, "_event_thread", None)
        if event_thread is None or not event_thread.is_alive():
            return self._restart_watcher("event")

        reconcile_thread = getattr(watcher, "_reconcile_thread", None)
        if reconcile_thread is None or not reconcile_thread.is_alive():
            return self._restart_watcher("reconcile")

        return False

    def _flush_idle_buffers_once(self) -> None:
        try:
            with self.app.app_context():
                self.sentinel_service.flush_idle_buffers()
        except Exception:
            LOGGER.warning("idle buffer flush failed", exc_info=True)

    def _health_check_loop(self) -> None:
        while not self._health_stop_event.wait(self._health_check_interval_seconds):
            self._check_watcher_health_once()
            self._flush_idle_buffers_once()

    def _start_health_monitor(self) -> None:
        if self._health_thread is not None and self._health_thread.is_alive():
            return
        self._health_stop_event.clear()
        self._health_thread = threading.Thread(
            target=self._health_check_loop,
            name="coordinator-health-check",
            daemon=True,
        )
        self._health_thread.start()

    def start(self) -> bool:
        if self._started:
            return True

        if self.app.config.get("TESTING"):
            return False

        if self.app.debug and os.getenv("WERKZEUG_RUN_MAIN") != "true":
            return False

        if not self._acquire_lock():
            return False

        with self.app.app_context():
            settings = Settings.singleton()
            state = SentinelState.singleton()
            if state.enabled:
                state.runtime_status = "running"
                state.started_at = utcnow_naive()
            else:
                state.runtime_status = "stopped"
            state.last_error = None
            # Dashboard labels this 'since last restart' — make that true.
            state.llm_failure_count = 0

            def _line_callback(container_id: str, container_name: str, line: str, flush_only: bool) -> None:
                with self.app.app_context():
                    self.sentinel_service.handle_log_line(container_id, container_name, line, flush_only)

            def _is_excluded(container_name: str) -> bool:
                with self.app.app_context():
                    return self.sentinel_service.is_excluded_container(container_name)

            def _container_event(container_id: str, container_name: str, status: str, attrs: dict) -> None:
                with self.app.app_context():
                    self.sentinel_service.handle_container_event(container_id, container_name, status, attrs)

            self._watcher = DockerWatcher(
                line_callback=_line_callback,
                is_excluded_callback=_is_excluded,
                reconcile_interval_seconds=60,
                container_event_callback=_container_event,
            )

            try:
                self._watcher.start()
            except Exception as exc:  # pragma: no cover - requires docker runtime
                state.runtime_status = "degraded"
                state.last_error = f"docker watcher failed to start: {exc}"

            self._scheduler = BackgroundScheduler()
            self._scheduler.start()
            self.refresh_schedule()
            self._start_health_monitor()

            if self.telegram_bot is not None:
                self.telegram_bot.start()

            db_state = SentinelState.singleton()
            db_state.last_error = state.last_error
            db_state.runtime_status = state.runtime_status

            from app.extensions import db

            db.session.commit()

        self._started = True
        return True

    def stop(self) -> None:
        self._health_stop_event.set()
        if self._health_thread is not None:
            self._health_thread.join(timeout=1)
            self._health_thread = None

        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None

        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

        if self.telegram_bot is not None:
            self.telegram_bot.stop()

        self._release_lock()
        self._started = False
