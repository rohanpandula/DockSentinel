from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_

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
        limit: int = 200,
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
        return query.order_by(AnalysisEvent.created_at.desc()).limit(limit).all()

    def get_distinct_container_names(self) -> list[str]:
        return [
            c[0]
            for c in db.session.query(AnalysisEvent.container_name).distinct().all()
            if c[0]
        ]
