from __future__ import annotations

import os

from flask import Flask

from app.container import ServiceContainer
from app.repositories.analysis_events import AnalysisEventRepository
from app.repositories.container_mutes import ContainerMuteRepository
from app.repositories.exclusions import ExclusionRepository
from app.repositories.prompts import PromptRepository
from app.repositories.reports import ReportRepository
from app.repositories.settings import SettingsRepository
from app.services.alerts import AlertService, TelegramAlertStrategy
from app.services.briefing import BriefingService
from app.services.cli_backends import CLIBackendRunner
from app.services.coordinator import RuntimeCoordinator
from app.services.llm_call import LLMCallService
from app.services.llm_client import LLMClient
from app.repositories.local_issues import LocalIssueRepository
from app.services.chunk_coalescer import ChunkCoalescer
from app.services.sentinel import SentinelService
from app.services.telegram_bot import TelegramBotService
from app.services.telegram import TelegramNotifier
from app.services.verdict_parser import VerdictParser


def build_container(app: Flask) -> ServiceContainer:
    # Dependency order: repos -> clients -> strategies -> services -> coordinator
    cli_backends_dir = os.getenv(
        "CLI_BACKENDS_DIR",
        os.path.join(os.path.dirname(__file__), "..", "llm-backends"),
    )
    cli_runner = CLIBackendRunner(
        backends_dir=os.path.abspath(cli_backends_dir),
        max_concurrent_calls=1,
    )
    llm_client = LLMClient(cli_runner=cli_runner)
    llm_call_service = LLMCallService(llm_client=llm_client)
    verdict_parser = VerdictParser()
    telegram_notifier = TelegramNotifier()

    event_repo = AnalysisEventRepository()
    settings_repo = SettingsRepository()
    prompt_repo = PromptRepository()
    report_repo = ReportRepository()
    exclusion_repo = ExclusionRepository()
    issue_repo = LocalIssueRepository()
    mute_repo = ContainerMuteRepository()

    alert_strategy = TelegramAlertStrategy(telegram_notifier)
    alert_service = AlertService(
        strategy=alert_strategy, event_repo=event_repo, issue_repo=issue_repo, mute_repo=mute_repo
    )

    sentinel_service = SentinelService(
        llm_call_service=llm_call_service,
        verdict_parser=verdict_parser,
        alert_service=alert_service,
        event_repo=event_repo,
        prompt_repo=prompt_repo,
        exclusion_repo=exclusion_repo,
    )
    coalescer = ChunkCoalescer(app=app, on_flush=sentinel_service.flush_coalesced)
    sentinel_service.coalescer = coalescer
    briefing_service = BriefingService(
        llm_call_service=llm_call_service,
        event_repo=event_repo,
        prompt_repo=prompt_repo,
        report_repo=report_repo,
    )
    telegram_bot = TelegramBotService(
        app=app,
        notifier=telegram_notifier,
        settings_repo=settings_repo,
        event_repo=event_repo,
        issue_repo=issue_repo,
        prompt_repo=prompt_repo,
        llm_call_service=llm_call_service,
        mute_repo=mute_repo,
    )
    coordinator = RuntimeCoordinator(
        app=app,
        sentinel_service=sentinel_service,
        briefing_service=briefing_service,
        telegram_bot=telegram_bot,
        telegram_notifier=telegram_notifier,
        event_repo=event_repo,
    )

    return ServiceContainer(
        llm_client=llm_client,
        llm_call=llm_call_service,
        verdict_parser=verdict_parser,
        telegram_notifier=telegram_notifier,
        alert_strategy=alert_strategy,
        alert_service=alert_service,
        sentinel=sentinel_service,
        briefing=briefing_service,
        coordinator=coordinator,
        event_repo=event_repo,
        settings_repo=settings_repo,
        prompt_repo=prompt_repo,
        issue_repo=issue_repo,
        telegram_bot=telegram_bot,
        report_repo=report_repo,
        exclusion_repo=exclusion_repo,
        mute_repo=mute_repo,
    )
