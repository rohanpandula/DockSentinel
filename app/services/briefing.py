from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.config_objects import LLMConfig
from app.extensions import db
from app.models import AnalysisEvent, DailyReport, LocalIssue, PromptKey, PromptTemplate, Settings
from app.services.llm_call import LLMCallService
from app.time_utils import utcnow_naive

if TYPE_CHECKING:
    from app.repositories.analysis_events import AnalysisEventRepository
    from app.repositories.prompts import PromptRepository
    from app.repositories.reports import ReportRepository


class BriefingService:
    def __init__(
        self,
        llm_call_service: LLMCallService,
        event_repo: "AnalysisEventRepository",
        prompt_repo: "PromptRepository",
        report_repo: "ReportRepository",
    ) -> None:
        self.llm_call_service = llm_call_service
        self.event_repo = event_repo
        self.prompt_repo = prompt_repo
        self.report_repo = report_repo

    def _settings(self) -> Settings:
        return Settings.singleton()

    def _prompt(self, key: PromptKey) -> PromptTemplate:
        prompt = self.prompt_repo.get_by_key(key)
        if prompt is None:
            raise RuntimeError(f"prompt not found for key {key.value}")
        return prompt

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

    @staticmethod
    def _evidence(events: list[AnalysisEvent]) -> str:
        """Prompt context: LLM-analysed events (worst first), pipeline counts, open issues.

        Rows that never reached the LLM (skipped/dedup/rate-limited/queued/excluded)
        are summarised as counts rather than listed, so the model isn't asked to
        reason over hundreds of "noise" placeholders.
        """
        analyzed = [e for e in events if e.status == "analyzed"]
        severity = {"critical": 0, "warning": 1, "noise": 2}
        analyzed.sort(key=lambda e: (severity.get(e.classification or "", 3), e.created_at))
        status_counts = Counter(e.status or "unknown" for e in events)
        class_counts = Counter(e.classification or "unknown" for e in analyzed)

        lines = [
            "Pipeline totals for the window:",
            f"- chunks seen: {len(events)}; analysed by LLM: {len(analyzed)} "
            f"(critical={class_counts.get('critical', 0)}, warning={class_counts.get('warning', 0)}, "
            f"noise={class_counts.get('noise', 0)})",
            "- not analysed: "
            + ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()) if k != "analyzed"),
            "",
        ]

        listed = [e for e in analyzed if e.classification in ("critical", "warning")][:300]
        noise_left = 500 - len(listed)
        listed += [e for e in analyzed if e.classification == "noise"][: max(noise_left, 0)]
        if listed:
            lines.append("Analysed events (critical and warning first):")
            for e in listed:
                lines.append(
                    f"- [{e.created_at.isoformat()}] container={e.container_name} "
                    f"classification={e.classification} alert_sent={bool(e.alert_sent)} summary={e.summary}"
                )
        else:
            lines.append("No events were analysed by the LLM in this window.")

        try:
            open_issues = (
                db.session.query(LocalIssue)
                .filter(LocalIssue.status.in_(["open", "discussing"]))
                .order_by(LocalIssue.created_at.desc())
                .limit(50)
                .all()
            )
        except Exception:  # pragma: no cover - table missing on very old DBs
            open_issues = []
        lines.append("")
        if open_issues:
            lines.append("Open issues awaiting operator action:")
            for issue in open_issues:
                lines.append(
                    f"- #{issue.id} [{issue.status}] container={issue.container_name} "
                    f"opened={issue.created_at.isoformat()} title={issue.title}"
                )
        else:
            lines.append("Open issues awaiting operator action: none")
        return "\n".join(lines)

    def generate_report(self) -> DailyReport:
        now = utcnow_naive()
        period_end = now
        period_start = now - timedelta(hours=24)

        events = self.event_repo.get_for_window(period_start)

        settings = self._settings()
        nightly_system = self._prompt(PromptKey.NIGHTLY_SYSTEM)
        nightly_report = self._prompt(PromptKey.NIGHTLY_REPORT)

        evidence = self._evidence(events)

        messages = [
            {"role": "system", "content": nightly_system.content},
            {
                "role": "user",
                "content": (
                    f"{nightly_report.content}\n\n"
                    f"Time window UTC: {period_start.isoformat()} to {period_end.isoformat()}\n\n"
                    f"{evidence}"
                ),
            },
        ]

        markdown = ""
        status = "generated"
        model_name = settings.llm_model
        error_text: str | None = None

        try:
            response = self.llm_call_service.call(
                config=LLMConfig.from_settings(settings),
                messages=messages,
                max_tokens=1200,
                temperature=0.2,
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
        self.report_repo.add(report)
        db.session.commit()
        return report
