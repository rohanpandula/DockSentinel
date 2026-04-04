from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.models import SentinelState

bp = Blueprint("sentinel_api", __name__, url_prefix="/api")


@bp.get("/sentinel/status")
def get_status() -> tuple[dict, int]:
    state = SentinelState.singleton()
    coordinator = current_app.extensions["services"].coordinator
    return jsonify({"state": state.as_dict(), "active_containers": coordinator.active_container_ids()}), 200


@bp.post("/sentinel/toggle")
def toggle_sentinel() -> tuple[dict, int]:
    payload = request.get_json(silent=True) or {}
    enabled = payload.get("enabled")
    if enabled is None:
        enabled = not SentinelState.singleton().enabled

    sentinel = current_app.extensions["services"].sentinel
    state = sentinel.set_enabled(bool(enabled))
    return jsonify({"state": state.as_dict()}), 200


@bp.post("/sentinel/analyze-now")
def analyze_now() -> tuple[dict, int]:
    payload = request.get_json(silent=True) or {}
    container = (payload.get("container") or "").strip()
    if not container:
        return jsonify({"error": "container is required"}), 400

    sentinel = current_app.extensions["services"].sentinel
    try:
        event = sentinel.analyze_container_now(container)
    except Exception as exc:  # pragma: no cover - requires docker runtime
        return jsonify({"error": str(exc)}), 500

    return jsonify(event.as_dict()), 200
