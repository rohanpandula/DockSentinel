from __future__ import annotations

from app.extensions import db
from app.models.reports import DailyReport


class ReportRepository:
    def add(self, report: DailyReport) -> None:
        db.session.add(report)

    def list_all(self) -> list[DailyReport]:
        return DailyReport.query.order_by(DailyReport.created_at.desc()).all()

    def get(self, report_id: int) -> DailyReport | None:
        return db.session.get(DailyReport, report_id)

    def get_latest(self) -> DailyReport | None:
        return DailyReport.query.order_by(DailyReport.created_at.desc()).first()
