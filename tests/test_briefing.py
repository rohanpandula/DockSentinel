from __future__ import annotations

from app import create_app
from app.extensions import db
from app.models import AnalysisEvent
from app.services.llm_client import LLMResult
from app.time_utils import utcnow_naive


class DummyLLM:
    def chat_completion(self, **kwargs):
        return LLMResult(
            content=(
                "## Executive Summary\n- stable\n\n"
                "## Critical Incidents\n- none\n\n"
                "## Warnings and Trends\n- none\n\n"
                "## Container Restarts\n- none\n\n"
                "## Recommended Actions (Next 24h)\n- observe"
            ),
            model="demo",
            latency_ms=10,
            usage={},
        )


class FailingLLM:
    def chat_completion(self, **kwargs):
        raise RuntimeError("llm unavailable")


def _build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'briefing.db'}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    return create_app()


def test_generate_briefing(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    with app.app_context():
        db.session.add(
            AnalysisEvent(
                container_id="id1",
                container_name="web",
                status="analyzed",
                classification="warning",
                summary="high latency",
                created_at=utcnow_naive(),
            )
        )
        db.session.commit()

        briefing = app.extensions["services"].briefing
        briefing.llm_call_service._client = DummyLLM()
        report = briefing.generate_report()

        assert report.id is not None
        assert "Executive Summary" in report.markdown_content


def test_generate_briefing_fallback_on_llm_error(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    with app.app_context():
        briefing = app.extensions["services"].briefing
        briefing.llm_call_service._client = FailingLLM()
        report = briefing.generate_report()

        assert report.status == "llm_error"
        assert "Executive Summary" in report.markdown_content
