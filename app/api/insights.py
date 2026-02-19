from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request

from app.models import AnalysisEvent

bp = Blueprint("insights_api", __name__, url_prefix="/api")


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


@bp.get("/insights")
def list_insights() -> tuple[dict, int]:
    query = AnalysisEvent.query

    container_name = request.args.get("container")
    if container_name:
        query = query.filter(AnalysisEvent.container_name == container_name)

    classification = request.args.get("classification")
    if classification:
        query = query.filter(AnalysisEvent.classification == classification)

    start = _parse_dt(request.args.get("start"))
    if start:
        query = query.filter(AnalysisEvent.created_at >= start)

    end = _parse_dt(request.args.get("end"))
    if end:
        query = query.filter(AnalysisEvent.created_at <= end)

    limit = max(1, min(int(request.args.get("limit", 100)), 500))
    events = query.order_by(AnalysisEvent.created_at.desc()).limit(limit).all()
    return jsonify({"items": [event.as_dict() for event in events]}), 200
