from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any

from app.extensions import db
from app.models import AnalysisEvent, DailyReport, PromptKey, PromptTemplate, Settings
from app.time_utils import utcnow_naive


class BriefingService:
    def __init__(self, llm_client: Any) -> None:
        self.llm_client = llm_client

    def _settings(self) -> Settings:
        return Settings.singleton()

    def _prompt(self, key: PromptKey) -> PromptTemplate:
        prompt = PromptTemplate.query.filter_by(key=key.value).first()
        if prompt is None:
            raise RuntimeError(f"prompt not found for key {key.value}")
        return prompt

    def _call_llm(self, *, settings: Settings, messages: list[dict[str, str]], max_tokens: int):
        transport = (settings.llm_transport or "api").strip().lower()
        timeout_seconds = settings.llm_timeout_seconds
        retries = settings.llm_max_retries
        if transport == "cli":
            timeout_seconds = settings.cli_timeout_seconds
            retries = settings.cli_max_retries

        if hasattr(self.llm_client, "complete"):
            return self.llm_client.complete(
                transport=transport,
                cli_backend=settings.cli_backend,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                messages=messages,
                timeout_seconds=timeout_seconds,
                max_retries=retries,
                max_tokens=max_tokens,
                temperature=0.2,
            )

        return self.llm_client.chat_completion(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            messages=messages,
            timeout_seconds=timeout_seconds,
            max_retries=retries,
            max_tokens=max_tokens,
            temperature=0.2,
        )

    def _fallback_report(self, events: list[AnalysisEvent], period_start: datetime, period_end: datetime) -> str:
        classification_counts = Counter(e.classification or "unknown" for e in events)
        container_counts = Counter(e.container_name or "unknown" for e in events)

        top_containers = "\n".join(
            f"- {container}: {count} events" for container, count in container_counts.most_common(5)
        )
        if not top_containers:
            top_containers = "- No container events recorded"

        return (
            "## Executive Summary\n"
            f"- Period: {period_start.isoformat()} to {period_end.isoformat()}\n"
            f"- Total analyzed events: {len(events)}\n\n"
            "## Critical Incidents\n"
            f"- Critical: {classification_counts.get('critical', 0)}\n\n"
            "## Warnings and Trends\n"
            f"- Warning: {classification_counts.get('warning', 0)}\n"
            f"- Noise: {classification_counts.get('noise', 0)}\n\n"
            "## Container Restarts\n"
            "- Restart events are inferred from runtime logs in MVP.\n\n"
            "## Recommended Actions (Next 24h)\n"
            "- Review critical events first, then tune exclusions and prompt templates.\n\n"
            "### Top Containers by Event Volume\n"
            f"{top_containers}\n"
        )

    def generate_report(self) -> DailyReport:
        now = utcnow_naive()
        period_end = now
        period_start = now - timedelta(hours=24)

        events = (
            AnalysisEvent.query.filter(AnalysisEvent.created_at >= period_start)
            .order_by(AnalysisEvent.created_at.asc())
            .all()
        )

        settings = self._settings()
        nightly_system = self._prompt(PromptKey.NIGHTLY_SYSTEM)
        nightly_report = self._prompt(PromptKey.NIGHTLY_REPORT)

        evidence_lines = [
            f"- [{e.created_at.isoformat()}] container={e.container_name} classification={e.classification} summary={e.summary}"
            for e in events[:500]
        ]
        evidence = "\n".join(evidence_lines) if evidence_lines else "No events were recorded in this window."

        messages = [
            {"role": "system", "content": nightly_system.content},
            {
                "role": "user",
                "content": (
                    f"{nightly_report.content}\n\n"
                    f"Time window UTC: {period_start.isoformat()} to {period_end.isoformat()}\n\n"
                    f"Events:\n{evidence}"
                ),
            },
        ]

        markdown = ""
        status = "generated"
        model_name = settings.llm_model
        error_text: str | None = None

        try:
            response = self._call_llm(
                settings=settings,
                messages=messages,
                max_tokens=1200,
            )
            markdown = response.content
            model_name = response.model
        except Exception as exc:  # pragma: no cover - network dependent
            status = "llm_error"
            error_text = str(exc)
            markdown = self._fallback_report(events, period_start, period_end)

        report = DailyReport(
            period_start=period_start,
            period_end=period_end,
            status=status,
            markdown_content=markdown,
            model=model_name,
            prompt_version=nightly_report.version,
            error=error_text,
        )
        db.session.add(report)
        db.session.commit()
        return report
