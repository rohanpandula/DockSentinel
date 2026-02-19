from __future__ import annotations

from flask import Blueprint, jsonify

from app.models import SentinelState

bp = Blueprint("health_api", __name__, url_prefix="/api")


@bp.get("/health")
def health() -> tuple[str, int] | tuple[dict, int]:
    state = SentinelState.singleton()
    return jsonify(
        {
            "status": "ok",
            "runtime": state.as_dict(),
        }
    ), 200
