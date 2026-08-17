from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.repositories.analysis_events import AnalysisEventRepository
    from app.repositories.exclusions import ExclusionRepository
    from app.repositories.prompts import PromptRepository
    from app.repositories.reports import ReportRepository
    from app.repositories.settings import SettingsRepository
    from app.services.alerts import AlertService, AlertStrategy

_KEY_MAP: dict[str, str] = {
    "telegram": "telegram_notifier",
}


@dataclass
class ServiceContainer:
    llm_client: Any
    llm_call: Any
    verdict_parser: Any
    telegram_notifier: Any
    alert_strategy: AlertStrategy
    alert_service: AlertService
    sentinel: Any
    briefing: Any
    coordinator: Any
    event_repo: AnalysisEventRepository
    settings_repo: SettingsRepository
    prompt_repo: PromptRepository
    report_repo: ReportRepository
    exclusion_repo: ExclusionRepository
    issue_repo: Any = None
    telegram_bot: Any = None
    mute_repo: Any = None
    incident_repo: Any = None
    incident_service: Any = None

    def __getitem__(self, key: str) -> Any:
        """Backwards-compatibility shim for string-key access during migration."""
        mapped = _KEY_MAP.get(key, key)
        return getattr(self, mapped)

    def __setitem__(self, key: str, value: Any) -> None:
        """Backwards-compatibility shim for test injection during migration."""
        mapped = _KEY_MAP.get(key, key)
        setattr(self, mapped, value)
