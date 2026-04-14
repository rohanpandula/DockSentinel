from flask import Blueprint, current_app, jsonify
from flask_pydantic import validate

from app.models import SentinelState
from app.schemas.insights import InsightItem
from app.schemas.sentinel import AnalyzeBody, AnalyzeResponse, SentinelStateSchema, SentinelStatusResponse, ToggleBody

bp = Blueprint("sentinel_api", __name__, url_prefix="/api")


@bp.get("/sentinel/status")
def get_status():
    state = SentinelState.singleton()
    coordinator = current_app.extensions["services"].coordinator
    return SentinelStatusResponse(
        state=SentinelStateSchema.model_validate(state),
        active_containers=coordinator.active_container_ids(),
    ).model_dump(), 200


@bp.post("/sentinel/toggle")
@validate(body=ToggleBody)
def toggle_sentinel(body: ToggleBody):
    enabled = body.enabled if body.enabled is not None else not SentinelState.singleton().enabled
    sentinel = current_app.extensions["services"].sentinel
    state = sentinel.set_enabled(bool(enabled))
    return {"state": SentinelStateSchema.model_validate(state).model_dump()}, 200


@bp.post("/sentinel/analyze-now")
@validate(body=AnalyzeBody)
def analyze_now(body: AnalyzeBody):
    sentinel = current_app.extensions["services"].sentinel
    try:
        event = sentinel.analyze_container_now(body.container.strip())
    except Exception as exc:  # pragma: no cover - requires docker runtime
        return jsonify({"error": str(exc)}), 500

    return AnalyzeResponse(event=InsightItem.model_validate(event)).model_dump(), 200
