from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from app.extensions import db
from app.models import DailyReport

bp = Blueprint("reports_api", __name__, url_prefix="/api")


@bp.get("/reports")
def list_reports() -> tuple[dict, int]:
    reports = DailyReport.query.order_by(DailyReport.created_at.desc()).all()
    return jsonify({"items": [report.as_dict() for report in reports]}), 200


@bp.get("/reports/<int:report_id>")
def get_report(report_id: int) -> tuple[dict, int]:
    report = db.session.get(DailyReport, report_id)
    if report is None:
        return jsonify({"error": "report not found"}), 404
    return jsonify(report.as_dict()), 200


@bp.post("/reports/generate")
def generate_report() -> tuple[dict, int]:
    briefing = current_app.extensions["services"]["briefing"]
    report = briefing.generate_report()
    return jsonify(report.as_dict()), 201
