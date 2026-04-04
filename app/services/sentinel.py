from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

import docker
from sqlalchemy import and_

from app.extensions import db
from app.models import AnalysisEvent, PromptKey, PromptTemplate, SentinelState, Settings
from app.services.llm_call import LLMCallService
from app.services.log_buffer import LogBuffer
from app.services.prefilter import Prefilter
from app.time_utils import utcnow_naive


class SentinelService:
    def __init__(self, llm_call_service: LLMCallService, verdict_parser: Any, telegram_notifier: Any) -> None:
        self.llm_call_service = llm_call_service
        self.verdict_parser = verdict_parser
        self.telegram_notifier = telegram_notifier
        self.log_buffer = LogBuffer(16000, 4000, 600)

    def _settings(self) -> Settings:
        return Settings.singleton()

    def _state(self) -> SentinelState:
        return SentinelState.singleton()

    def _prefilter(self) -> Prefilter:
        settings = self._settings()
        keywords = [k.strip() for k in settings.keyword_list.split(",") if k.strip()]
        return Prefilter(keywords)

    def _sync_buffer_limits(self) -> None:
        settings = self._settings()
        self.log_buffer.set_limits(
            max_input_chars=settings.max_input_chars,
            max_input_tokens=settings.max_input_tokens,
            reserved_output_tokens=settings.reserved_output_tokens,
            token_strategy=settings.token_estimation_strategy,
            model_name=settings.llm_model,
            keyword_flush_delay_lines=settings.keyword_flush_delay_lines,
        )

    def is_enabled(self) -> bool:
        return self._state().enabled

    def set_enabled(self, enabled: bool) -> SentinelState:
        state = self._state()
        state.enabled = enabled
        state.runtime_status = "running" if enabled else "stopped"
        state.started_at = utcnow_naive() if enabled else None
        db.session.commit()
        return state

    def mark_runtime_degraded(self, error_message: str) -> None:
        state = self._state()
        state.runtime_status = "degraded"
        state.last_error = error_message
        db.session.commit()

    def mark_runtime_running(self) -> None:
        state = self._state()
        if state.enabled:
            state.runtime_status = "running"
            state.last_error = None
            db.session.commit()

    def is_excluded_container(self, container_name: str) -> bool:
        from app.models import ExclusionRule

        for row in ExclusionRule.query.filter_by(enabled=True).all():
            if row.container_pattern.lower() in container_name.lower():
                return True
        return False

    def _prompt(self, key: PromptKey) -> PromptTemplate:
        template = PromptTemplate.query.filter_by(key=key.value).first()
        if template is None:
            raise RuntimeError(f"prompt not found for key {key.value}")
        return template

    def _record_llm_failure(self, message: str) -> None:
        state = self._state()
        state.llm_failure_count += 1
        state.llm_last_failure_at = utcnow_naive()
        state.last_error = message
        state.runtime_status = "degraded"
        db.session.commit()

    def _event_base(
        self,
        *,
        container_id: str,
        container_name: str,
        chunk_text: str,
        matched_keywords: list[str],
        input_chars: int,
        estimated_input_tokens: int,
    ) -> AnalysisEvent:
        return AnalysisEvent(
            container_id=container_id,
            container_name=container_name,
            matched_keywords=",".join(matched_keywords) if matched_keywords else None,
            chunk_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
            chunk_excerpt=chunk_text[:1200],
            input_chars=input_chars,
            estimated_input_tokens=estimated_input_tokens,
        )

    def _record_excluded_event(self, container_id: str, container_name: str) -> None:
        cutoff = utcnow_naive() - timedelta(minutes=5)
        already_recorded = (
            AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.container_id == container_id,
                    AnalysisEvent.status == "excluded",
                    AnalysisEvent.created_at >= cutoff,
                )
            )
            .order_by(AnalysisEvent.created_at.desc())
            .first()
        )
        if already_recorded:
            return

        db.session.add(
            AnalysisEvent(
                container_id=container_id,
                container_name=container_name,
                status="excluded",
                classification=None,
            )
        )
        db.session.commit()

    def handle_log_line(self, container_id: str, container_name: str, line: str, flush_only: bool = False) -> None:
        if not self.is_enabled():
            return
        if self.is_excluded_container(container_name):
            self._record_excluded_event(container_id=container_id, container_name=container_name)
            return

        self._sync_buffer_limits()
        if flush_only:
            chunk = self.log_buffer.flush_container(container_id)
            if chunk:
                self.process_chunk(container_id=container_id, container_name=container_name, chunk_text=chunk.text)
            return

        matches = self._prefilter().match(line)
        chunks = self.log_buffer.add_line(container_id=container_id, line=line, keyword_hit=bool(matches))
        for chunk in chunks:
            self.process_chunk(container_id=container_id, container_name=container_name, chunk_text=chunk.text)

    def process_chunk(self, *, container_id: str, container_name: str, chunk_text: str) -> AnalysisEvent:
        settings = self._settings()
        prefilter = self._prefilter()
        matched_keywords = prefilter.match(chunk_text)

        input_chars = len(chunk_text)
        estimated_input_tokens = self.log_buffer.estimate_tokens(chunk_text)
        event = self._event_base(
            container_id=container_id,
            container_name=container_name,
            chunk_text=chunk_text,
            matched_keywords=matched_keywords,
            input_chars=input_chars,
            estimated_input_tokens=estimated_input_tokens,
        )

        if not matched_keywords:
            event.status = "skipped"
            event.classification = "noise"
            db.session.add(event)
            db.session.commit()
            return event

        # --- Chunk dedup: skip if the same content was already analyzed recently ---
        dedup_window = settings.dedup_window_seconds
        if dedup_window > 0:
            cutoff = utcnow_naive() - timedelta(seconds=dedup_window)
            already_analyzed = AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.chunk_hash == event.chunk_hash,
                    AnalysisEvent.status.notin_(["skipped"]),
                    AnalysisEvent.created_at >= cutoff,
                )
            ).first()
            if already_analyzed:
                event.status = "dedup_skipped"
                event.classification = "noise"
                db.session.add(event)
                db.session.commit()
                return event

        # --- Per-container rate limiting ---
        container_limit = settings.container_rate_limit_count
        container_window = settings.container_rate_limit_window_seconds
        if container_limit > 0 and container_window > 0:
            window_start = utcnow_naive() - timedelta(seconds=container_window)
            recent_calls = AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.container_id == container_id,
                    AnalysisEvent.status.in_(["analyzed", "parse_error", "llm_error"]),
                    AnalysisEvent.created_at >= window_start,
                )
            ).count()
            if recent_calls >= container_limit:
                event.status = "rate_limited"
                event.classification = "noise"
                db.session.add(event)
                db.session.commit()
                return event

        sentinel_system = self._prompt(PromptKey.SENTINEL_SYSTEM)
        sentinel_analysis = self._prompt(PromptKey.SENTINEL_ANALYSIS)
        guard = self._prompt(PromptKey.JSON_OUTPUT_GUARD)

        messages = [
            {"role": "system", "content": sentinel_system.content},
            {"role": "system", "content": guard.content},
            {
                "role": "user",
                "content": f"{sentinel_analysis.content}\n\nContainer: {container_name}\n\nLogs:\n{chunk_text}",
            },
        ]

        try:
            llm_result = self.llm_call_service.call(
                messages=messages,
                max_tokens=settings.reserved_output_tokens,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                transport=(settings.llm_transport or "api").strip().lower(),
                cli_backend=settings.cli_backend,
                timeout_seconds=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
                cli_timeout_seconds=settings.cli_timeout_seconds,
                cli_max_retries=settings.cli_max_retries,
            )
        except Exception as exc:  # pragma: no cover - network dependent
            event.status = "llm_error"
            event.llm_error = str(exc)
            db.session.add(event)
            db.session.commit()
            self._record_llm_failure(str(exc))
            return event

        verdict, parse_error = self.verdict_parser.safe_parse(llm_result.content)
        event.model = llm_result.model
        event.latency_ms = llm_result.latency_ms
        event.prompt_version = sentinel_analysis.version

        if verdict is None:
            event.status = "parse_error"
            event.parse_error = parse_error
            db.session.add(event)
            db.session.commit()
            return event

        event.status = "analyzed"
        event.classification = verdict.classification
        event.summary = verdict.summary
        event.root_cause_hypothesis = verdict.root_cause_hypothesis
        event.fix_suggestion = verdict.fix_suggestion
        event.confidence = verdict.confidence

        if verdict.classification == "critical":
            sent, alert_error = self._send_alert_if_allowed(event)
            event.alert_sent = sent
            event.alert_error = alert_error

        db.session.add(event)
        db.session.commit()
        self.mark_runtime_running()
        return event

    def _send_alert_if_allowed(self, event: AnalysisEvent) -> tuple[bool, str | None]:
        settings = self._settings()

        cooldown_since = utcnow_naive() - timedelta(minutes=settings.alert_cooldown_minutes)
        duplicate = (
            AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.chunk_hash == event.chunk_hash,
                    AnalysisEvent.alert_sent.is_(True),
                    AnalysisEvent.created_at >= cooldown_since,
                )
            )
            .order_by(AnalysisEvent.created_at.desc())
            .first()
        )
        if duplicate:
            return False, "duplicate alert suppressed by cooldown"

        window_since = utcnow_naive() - timedelta(seconds=settings.alert_rate_limit_window_seconds)
        recent_alerts = AnalysisEvent.query.filter(
            and_(AnalysisEvent.alert_sent.is_(True), AnalysisEvent.created_at >= window_since)
        ).count()

        if recent_alerts >= settings.alert_rate_limit_count:
            return False, "global rate limit exceeded"

        message = (
            f"DockSentinel Critical Alert\n"
            f"Container: {event.container_name}\n"
            f"Summary: {event.summary or 'N/A'}\n"
            f"Fix: {event.fix_suggestion or 'N/A'}"
        )
        return self.telegram_notifier.send_message(
            token=settings.telegram_token or "",
            chat_id=settings.telegram_chat_id or "",
            text=message,
        )

    def analyze_container_now(self, container_name_or_id: str) -> AnalysisEvent:
        settings = self._settings()
        client = docker.from_env()
        container = client.containers.get(container_name_or_id)
        raw = container.logs(tail=200, stdout=True, stderr=True)
        chunk_text = raw.decode("utf-8", errors="replace")

        if not chunk_text.strip():
            chunk_text = "No logs available from selected container."

        # Use a bounded payload for immediate analysis.
        if len(chunk_text) > settings.max_input_chars:
            chunk_text = chunk_text[-settings.max_input_chars :]

        return self.process_chunk(
            container_id=container.id,
            container_name=container.name,
            chunk_text=chunk_text,
        )
