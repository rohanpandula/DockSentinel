from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

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
    container = current_app.extensions["services"]

    container_name = request.args.get("container")
    classification = request.args.get("classification")
    start = _parse_dt(request.args.get("start"))
    end = _parse_dt(request.args.get("end"))
    limit = max(1, min(int(request.args.get("limit", 100)), 500))

    events = container.event_repo.get_filtered(
        container=container_name,
        classification=classification,
        start=start,
        end=end,
        limit=limit,
    )
    return jsonify({"items": [event.as_dict() for event in events]}), 200
