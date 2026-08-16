from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, delete

from app.extensions import db
from app.models.events import AnalysisEvent


class AnalysisEventRepository:
    def add(self, event: AnalysisEvent) -> None:
        db.session.add(event)

    def get(self, event_id: int) -> AnalysisEvent | None:
        return db.session.get(AnalysisEvent, event_id)

    def find_duplicate_chunk(self, chunk_hash: str, since: datetime) -> AnalysisEvent | None:
        return AnalysisEvent.query.filter(
            and_(
                AnalysisEvent.chunk_hash == chunk_hash,
                AnalysisEvent.status.notin_(["skipped"]),
                AnalysisEvent.created_at >= since,
            )
        ).first()

    def count_recent_by_container(self, container_id: str, since: datetime) -> int:
        return AnalysisEvent.query.filter(
            and_(
                AnalysisEvent.container_id == container_id,
                AnalysisEvent.status.in_(["analyzed", "parse_error", "llm_error"]),
                AnalysisEvent.created_at >= since,
            )
        ).count()

    def find_alert_duplicate(self, chunk_hash: str, since: datetime) -> AnalysisEvent | None:
        return (
            AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.chunk_hash == chunk_hash,
                    AnalysisEvent.alert_sent.is_(True),
                    AnalysisEvent.created_at >= since,
                )
            )
            .order_by(AnalysisEvent.created_at.desc())
            .first()
        )

    def find_recent_alert_for_container(
        self, container_id: str, classification: str | None, since: datetime
    ) -> AnalysisEvent | None:
        """Most recent *sent* alert for this container with the same classification."""
        return (
            AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.container_id == container_id,
                    AnalysisEvent.classification == classification,
                    AnalysisEvent.alert_sent.is_(True),
                    AnalysisEvent.created_at >= since,
                )
            )
            .order_by(AnalysisEvent.created_at.desc())
            .first()
        )

    def count_recent_alerts(self, since: datetime) -> int:
        return AnalysisEvent.query.filter(
            and_(AnalysisEvent.alert_sent.is_(True), AnalysisEvent.created_at >= since)
        ).count()

    def find_recent_excluded(self, container_id: str, since: datetime) -> AnalysisEvent | None:
        return (
            AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.container_id == container_id,
                    AnalysisEvent.status == "excluded",
                    AnalysisEvent.created_at >= since,
                )
            )
            .order_by(AnalysisEvent.created_at.desc())
            .first()
        )

    def count_container_events(self, container_name: str, statuses: list[str], since: datetime) -> int:
        """Count container lifecycle events (status="container_event") for one
        container NAME whose docker status (die/oom/...) is in `statuses`.
        Keyed by name (not id): a container recreated by compose/`--rm` gets a
        new id every time but keeps its name, and that is still one crash loop."""
        return AnalysisEvent.query.filter(
            and_(
                AnalysisEvent.container_name == container_name,
                AnalysisEvent.status == "container_event",
                AnalysisEvent.matched_keywords.in_(statuses),
                AnalysisEvent.created_at >= since,
            )
        ).count()

    def find_recent_storm_alert(self, container_name: str, since: datetime) -> AnalysisEvent | None:
        return (
            AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.container_name == container_name,
                    AnalysisEvent.status == "container_event",
                    AnalysisEvent.alert_sent.is_(True),
                    AnalysisEvent.created_at >= since,
                )
            )
            .order_by(AnalysisEvent.created_at.desc())
            .first()
        )

    def find_last_analyzed(self, container_id: str, since: datetime) -> AnalysisEvent | None:
        """Most recent LLM-analyzed event for this container id inside the window
        (used by the analysis-level cooldown)."""
        return (
            AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.container_id == container_id,
                    AnalysisEvent.status == "analyzed",
                    AnalysisEvent.created_at >= since,
                )
            )
            .order_by(AnalysisEvent.created_at.desc(), AnalysisEvent.id.desc())
            .first()
        )

    def count_warnings(self, container_name: str, since: datetime) -> int:
        """Warning verdicts (analyzed or inherited via analysis_cooldown) for one
        container NAME inside the window (persistent-warning escalation)."""
        return AnalysisEvent.query.filter(
            and_(
                AnalysisEvent.container_name == container_name,
                AnalysisEvent.status.in_(["analyzed", "analysis_cooldown"]),
                AnalysisEvent.classification == "warning",
                AnalysisEvent.created_at >= since,
            )
        ).count()

    def find_recent_alert_for_name(self, container_name: str, since: datetime) -> AnalysisEvent | None:
        """Most recent *sent* alert of any kind for this container NAME."""
        return (
            AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.container_name == container_name,
                    AnalysisEvent.alert_sent.is_(True),
                    AnalysisEvent.created_at >= since,
                )
            )
            .order_by(AnalysisEvent.created_at.desc())
            .first()
        )

    def get_for_window(self, since: datetime) -> list[AnalysisEvent]:
        return (
            AnalysisEvent.query.filter(AnalysisEvent.created_at >= since)
            .order_by(AnalysisEvent.created_at.asc())
            .all()
        )

    def get_recent(self, limit: int) -> list[AnalysisEvent]:
        return AnalysisEvent.query.order_by(AnalysisEvent.created_at.desc()).limit(limit).all()

    def get_today(self, today_start: datetime) -> list[AnalysisEvent]:
        return AnalysisEvent.query.filter(AnalysisEvent.created_at >= today_start).all()

    def get_filtered(
        self,
        container: str | None = None,
        classification: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
        sort: str = "-created_at",
    ) -> list[AnalysisEvent]:
        query = AnalysisEvent.query
        if container:
            query = query.filter(AnalysisEvent.container_name == container)
        if classification:
            query = query.filter(AnalysisEvent.classification == classification)
        if start:
            query = query.filter(AnalysisEvent.created_at >= start)
        if end:
            query = query.filter(AnalysisEvent.created_at <= end)
        order_col = (
            AnalysisEvent.created_at.desc()
            if sort.startswith("-")
            else AnalysisEvent.created_at.asc()
        )
        return query.order_by(order_col).limit(limit).offset(offset).all()

    PRUNABLE_STATUSES = frozenset(
        {"skipped", "dedup_skipped", "analysis_cooldown", "rate_limited", "queued", "excluded"}
    )

    def prune(self, older_than: datetime, statuses=None) -> int:
        """Delete low-value rows older than ``older_than``. Never touches analyzed/parse_error/llm_error."""
        wanted = set(statuses) if statuses is not None else set(self.PRUNABLE_STATUSES)
        wanted &= self.PRUNABLE_STATUSES
        if not wanted:
            return 0
        stmt = delete(AnalysisEvent).where(
            and_(AnalysisEvent.status.in_(sorted(wanted)), AnalysisEvent.created_at < older_than)
        )
        result = db.session.execute(stmt)
        db.session.commit()
        return int(result.rowcount or 0)

    def get_distinct_container_names(self) -> list[str]:
        return [
            c[0]
            for c in db.session.query(AnalysisEvent.container_name).distinct().all()
            if c[0]
        ]
