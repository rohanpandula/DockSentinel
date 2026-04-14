from flask import Blueprint, current_app, jsonify
from flask_pydantic import validate

from app.schemas.reports import (
    ReportDetailResponse,
    ReportItem,
    ReportListResponse,
    ReportsQuery,
)

bp = Blueprint("reports_api", __name__, url_prefix="/api")


@bp.get("/reports")
@validate(query=ReportsQuery)
def list_reports(query: ReportsQuery):
    services = current_app.extensions["services"]
    reports = services.report_repo.list_all(limit=query.limit, offset=query.offset)
    return ReportListResponse(
        items=[ReportItem.model_validate(r) for r in reports],
        offset=query.offset,
        limit=query.limit,
    )


@bp.get("/reports/<int:report_id>")
def get_report(report_id: int):
    services = current_app.extensions["services"]
    report = services.report_repo.get(report_id)
    if report is None:
        return jsonify({"error": "report not found"}), 404
    return ReportDetailResponse.model_validate(report).model_dump(), 200


@bp.post("/reports/generate")
def generate_report():
    services = current_app.extensions["services"]
    report = services.briefing.generate_report()
    return ReportDetailResponse.model_validate(report).model_dump(), 201
